# GUI 重构方案：pywebview → HTTP + SSE

> **版本**: v2.0 (基于 Codex Review 更新)
> **日期**: 2024-12-18

## 背景

### 问题
1. **WSL2 兼容性**：pywebview 在 WSL2 下需要 WSLg 或 X Server，配置复杂
2. **跨平台限制**：pywebview 依赖平台特定的 WebView 组件
3. **调试困难**：pywebview 窗口无法使用浏览器 DevTools
4. **单客户端限制**：当前架构只支持一个 GUI 窗口

### 目标
1. 保持现有功能不变
2. 支持 WSL2 等无 GUI 环境
3. 支持多客户端并行访问（GUI + 浏览器）
4. pywebview 不可用时自动降级为纯 Web 模式
5. 最小化代码改动

## 架构设计

### 现有架构

```
┌─────────────────────────────────────────────────────────────┐
│                    现有架构                                  │
│                                                             │
│  主进程 (MCP Server)                                        │
│      │                                                      │
│      └── GUIManager                                         │
│              │                                              │
│              └── multiprocessing.Process (子进程)           │
│                      │                                      │
│                      └── LiveViewer                         │
│                              ├── pywebview 窗口             │
│                              ├── _poll_queue_loop 线程      │
│                              ├── mp.Queue 事件队列          │
│                              └── evaluate_js("addEvent()") │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 新架构

```
┌─────────────────────────────────────────────────────────────┐
│                    新架构                                    │
│                                                             │
│  主进程 (MCP Server)                                        │
│      │                                                      │
│      └── GUIManager                                         │
│              │                                              │
│              └── multiprocessing.Process (子进程)           │
│                      │                                      │
│                      └── LiveViewer                         │
│                              │                              │
│                              ├── GUIServer (HTTP + SSE)     │
│                              │       ├── GET /  → HTML      │
│                              │       ├── GET /sse → 事件流  │
│                              │       └── clients[] 连接池   │
│                              │                              │
│                              ├── _poll_queue_loop 线程      │
│                              │       └── server.broadcast() │
│                              │                              │
│                              └── 客户端连接                  │
│                                   ├── pywebview (可选)      │
│                                   ├── Chrome 浏览器         │
│                                   └── 其他浏览器            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## 核心改动

### 1. 新增 GUIServer 类

**文件**: `src/cli_agent_mcp/shared/gui/server.py` (新建)

```python
"""内置 HTTP + SSE 服务器"""

import http.server
import json
import logging
import queue
import socketserver
import threading
import time
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class ServerConfig:
    """服务器配置"""
    host: str = "127.0.0.1"
    port: int = 0  # 0 = 随机端口
    grace_period: float = 2.0  # 宽限期（秒）
    max_clients: int = 10  # 最大客户端数


class GUIServer:
    """HTTP 服务器，提供静态 HTML 和 SSE 事件流"""

    def __init__(self, html: str, config: ServerConfig | None = None):
        self.html = html
        self.config = config or ServerConfig()
        self._clients: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._shutdown_callback: Callable[[], None] | None = None
        self._server: socketserver.TCPServer | None = None
        self._actual_port: int = 0

    @property
    def port(self) -> int:
        """实际绑定的端口"""
        return self._actual_port

    @property
    def url(self) -> str:
        """服务器 URL"""
        return f"http://{self.config.host}:{self._actual_port}"

    def on_all_disconnected(self, callback: Callable[[], None]):
        """注册所有客户端断开时的回调"""
        self._shutdown_callback = callback

    def start(self) -> int:
        """启动服务器，返回实际端口"""
        handler = self._create_handler()

        # 直接绑定，让系统分配端口（避免竞态）
        self._server = socketserver.ThreadingTCPServer(
            (self.config.host, self.config.port), handler
        )
        self._server.allow_reuse_address = True

        # 从 server 获取实际端口
        self._actual_port = self._server.server_address[1]

        thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="gui_http_server"
        )
        thread.start()

        logger.info(f"GUI server started at {self.url}")
        return self._actual_port

    def stop(self):
        """停止服务器"""
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            logger.debug("GUI server stopped")

    def broadcast(self, event: dict):
        """广播事件到所有 SSE 客户端"""
        with self._lock:
            for client_q in self._clients[:]:  # 复制列表避免并发修改
                try:
                    client_q.put_nowait(event)
                except queue.Full:
                    logger.debug("Client queue full, dropping event")

    @property
    def client_count(self) -> int:
        """当前连接的客户端数量"""
        with self._lock:
            return len(self._clients)

    def _client_connected(self, client_q: queue.Queue) -> bool:
        """客户端连接，返回是否允许"""
        with self._lock:
            if len(self._clients) >= self.config.max_clients:
                logger.warning(f"Max clients ({self.config.max_clients}) reached")
                return False
            self._clients.append(client_q)
            logger.debug(f"Client connected, total: {len(self._clients)}")
            return True

    def _client_disconnected(self, client_q: queue.Queue):
        """客户端断开"""
        with self._lock:
            if client_q in self._clients:
                self._clients.remove(client_q)
            remaining = len(self._clients)
            logger.debug(f"Client disconnected, remaining: {remaining}")

        if remaining == 0:
            # 启动宽限期检查
            threading.Thread(
                target=self._check_shutdown_after_grace,
                daemon=True,
                name="gui_grace_check"
            ).start()

    def _check_shutdown_after_grace(self):
        """宽限期后检查是否需要退出"""
        time.sleep(self.config.grace_period)
        with self._lock:
            if not self._clients and self._shutdown_callback:
                logger.info("All clients disconnected after grace period")
                self._shutdown_callback()

    def _create_handler(self):
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def do_GET(self):
                if self.path == '/':
                    self._serve_html()
                elif self.path == '/sse':
                    self._serve_sse()
                else:
                    self.send_error(404)

            def _serve_html(self):
                content = server.html.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', len(content))
                self.end_headers()
                self.wfile.write(content)

            def _serve_sse(self):
                client_q: queue.Queue = queue.Queue(maxsize=500)

                # 检查是否允许连接
                if not server._client_connected(client_q):
                    self.send_error(503, "Too many clients")
                    return

                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Connection', 'keep-alive')
                self.send_header('X-Accel-Buffering', 'no')
                self.end_headers()

                try:
                    while True:
                        try:
                            event = client_q.get(timeout=25)
                            data = json.dumps(event, ensure_ascii=False)
                            self.wfile.write(f"data: {data}\n\n".encode('utf-8'))
                            self.wfile.flush()
                        except queue.Empty:
                            # 心跳保活
                            self.wfile.write(b": ping\n\n")
                            self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError, TimeoutError):
                    pass  # 客户端断开
                finally:
                    server._client_disconnected(client_q)

            def log_message(self, format, *args):
                pass  # 静默日志

        return Handler
```

### 2. 修改 template.py

**文件**: `src/cli_agent_mcp/shared/gui/template.py`

添加 SSE 客户端代码和 `updateStatus` 函数：

```javascript
// 添加到 <script> 标签末尾

// ========== updateStatus 函数 ==========
function updateStatus(status) {
    const statusBar = document.getElementById('status-bar');
    if (!statusBar) return;

    let parts = [];
    if (status.model) parts.push(`Model: ${status.model}`);
    if (status.session) parts.push(`Session: ${status.session.slice(0, 8)}...`);
    if (status.tokens) parts.push(`Tokens: ${status.tokens}`);
    if (status.duration) parts.push(`Duration: ${status.duration.toFixed(1)}s`);
    if (status.tools) parts.push(`Tools: ${status.tools}`);
    if (status.streaming) parts.push('⏳ Streaming...');

    statusBar.textContent = parts.join(' | ') || 'Ready';
}

// ========== SSE 客户端 ==========
(function() {
    let evtSource = null;
    let reconnectAttempts = 0;
    const maxReconnectAttempts = 10;

    function connect() {
        evtSource = new EventSource('/sse');

        evtSource.onopen = function() {
            console.log('SSE connected');
            reconnectAttempts = 0;
        };

        evtSource.onmessage = function(e) {
            try {
                const data = JSON.parse(e.data);
                if (data.type === 'event') {
                    addEvent(data.html, data.session, data.source, data.task_note);
                } else if (data.type === 'status') {
                    updateStatus(data.status);
                }
            } catch (err) {
                console.error('SSE parse error:', err);
            }
        };

        evtSource.onerror = function() {
            console.log('SSE connection lost');
            evtSource.close();

            if (reconnectAttempts < maxReconnectAttempts) {
                reconnectAttempts++;
                const delay = Math.min(1000 * reconnectAttempts, 10000);
                console.log(`Reconnecting in ${delay}ms (attempt ${reconnectAttempts})`);
                setTimeout(connect, delay);
            }
        };
    }

    connect();

    // 页面关闭时清理
    window.addEventListener('beforeunload', function() {
        if (evtSource) evtSource.close();
    });
})();
```

### 3. 修改 window.py

**文件**: `src/cli_agent_mcp/shared/gui/window.py`

```python
# 主要改动点

import os
import sys

class LiveViewer:
    def __init__(self, ...):
        # ... 现有代码 ...
        self._server: GUIServer | None = None
        self._url: str | None = None
        self._webview_available: bool = False

    @property
    def url(self) -> str | None:
        """获取 GUI URL"""
        return self._url

    @property
    def is_webview_mode(self) -> bool:
        """是否使用 pywebview 模式"""
        return self._webview_available and self._window is not None

    def _check_gui_available(self) -> bool:
        """检查 GUI 环境是否可用（Linux/WSL2 特殊处理）"""
        if sys.platform == "linux":
            # 检查 DISPLAY 或 WAYLAND_DISPLAY
            if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
                logger.info("No DISPLAY/WAYLAND_DISPLAY, GUI not available")
                return False
        return True

    def _run(self) -> None:
        """运行主循环"""
        html = generate_html(
            multi_source_mode=self.config.multi_source_mode,
            title=self.config.title,
        )

        # 启动 HTTP 服务器
        from .server import GUIServer, ServerConfig
        server_config = ServerConfig(
            host=os.environ.get("CAM_GUI_HOST", "127.0.0.1"),
            port=int(os.environ.get("CAM_GUI_PORT", "0")),
        )
        self._server = GUIServer(html, server_config)
        self._server.start()
        self._url = self._server.url

        # 注册断开回调
        self._server.on_all_disconnected(self._on_all_clients_disconnected)

        # 打印 URL
        logger.info(f"GUI available at: {self._url}")

        # 检查 GUI 环境
        if not self._check_gui_available():
            self._start_web_only_mode()
            return

        # 尝试启动 pywebview
        try:
            import webview
            self._window = webview.create_window(
                self.config.title,
                url=self._url,  # 改为加载 HTTP URL
                width=self.config.width,
                height=self.config.height,
                min_size=(600, 400),
            )

            def on_loaded():
                self._started.set()
                self._webview_available = True
                self._poll_thread = threading.Thread(
                    target=self._poll_queue_loop, daemon=True
                )
                self._poll_thread.start()

            def on_closed():
                self._closed.set()
                self._queue.put(None)

            self._window.events.loaded += on_loaded
            self._window.events.closed += on_closed

            webview.start()

        except ImportError:
            logger.warning(f"pywebview not installed, use browser: {self._url}")
            self._start_web_only_mode()

        except Exception as e:
            # 捕获所有运行时异常（如 GTK/Qt 不可用）
            logger.warning(f"pywebview failed ({e}), falling back to browser: {self._url}")
            self._start_web_only_mode()

    def _start_web_only_mode(self):
        """启动纯 Web 模式"""
        self._webview_available = False
        self._started.set()

        # 启动轮询线程
        self._poll_thread = threading.Thread(
            target=self._poll_queue_loop, daemon=True
        )
        self._poll_thread.start()

        # 等待关闭信号
        self._closed.wait()

    def _poll_queue_loop(self) -> None:
        """后台轮询线程 - 不再依赖 self._window"""
        poll_interval = self.config.poll_interval_ms / 1000

        # 修改条件：只依赖 _closed 和 _server
        while not self._closed.is_set() and self._server is not None:
            try:
                events_processed = 0
                while events_processed < 100:
                    try:
                        event = self._queue.get_nowait()
                        if event is None:
                            return
                        self._render_event(event)
                        events_processed += 1
                    except queue.Empty:
                        break
            except Exception as e:
                logger.debug(f"Poll loop error: {e}")

            time.sleep(poll_interval)

    def _render_event(self, event: dict) -> None:
        """渲染事件 - 通过 SSE 广播"""
        if self._server is None:
            return

        try:
            html = self._renderer.render(event)
            session_id = self._extract_session_id(event)
            source = event.get("source", "unknown")
            task_note = event.get("metadata", {}).get("task_note", "") or event.get("task_note", "")

            # 通过 SSE 广播
            self._server.broadcast({
                'type': 'event',
                'html': html,
                'session': session_id,
                'source': source,
                'task_note': task_note,
            })

            # 更新状态
            self._update_stats(event)

        except Exception as e:
            logger.warning(f"Render error: {e}")

    def _update_stats(self, event: dict) -> None:
        """更新状态栏 - 通过 SSE 广播"""
        # 不再依赖 self._window
        updated = False

        # Model
        if event.get("model"):
            self._stats["model"] = event["model"]
            updated = True

        # Session
        session_id = self._extract_session_id(event)
        if session_id:
            self._stats["session"] = session_id
            updated = True

        # Stats from lifecycle events
        stats = event.get("stats", {})
        if stats:
            if stats.get("total_tokens"):
                self._stats["tokens"] = stats["total_tokens"]
                updated = True
            elif stats.get("input_tokens") or stats.get("output_tokens"):
                self._stats["tokens"] = (
                    stats.get("input_tokens", 0) + stats.get("output_tokens", 0)
                )
                updated = True

            if stats.get("duration_ms"):
                self._stats["duration"] = stats["duration_ms"] / 1000
                updated = True

            if stats.get("tool_calls"):
                self._stats["tools"] = stats["tool_calls"]
                updated = True

        # Tool count from operations
        if event.get("category") == "operation" and event.get("status") == "running":
            self._stats["tools"] = self._stats.get("tools", 0) + 1
            updated = True

        # Streaming indicator
        is_streaming = event.get("is_delta", False) or event.get("status") == "running"

        if updated and self._server:
            status_data = {
                "model": self._stats.get("model"),
                "session": self._stats.get("session"),
                "tokens": self._stats.get("tokens", 0),
                "duration": self._stats.get("duration", 0.0),
                "tools": self._stats.get("tools", 0),
                "streaming": is_streaming,
            }
            self._server.broadcast({
                'type': 'status',
                'status': status_data,
            })

    def _on_all_clients_disconnected(self):
        """所有客户端断开时的回调"""
        logger.info("All clients disconnected")
        self._closed.set()

    def close(self) -> None:
        """关闭查看器窗口"""
        self._closed.set()

        # 关闭 pywebview 窗口
        if self._window:
            try:
                self._window.destroy()
            except Exception:
                pass

        # 停止 HTTP 服务器
        if self._server:
            self._server.stop()
```

## 配置变更

### 现有环境变量（保持不变）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CAM_GUI` | `true` | 启用 GUI 仪表盘 |
| `CAM_GUI_DETAIL` | `false` | GUI 详细模式 |
| `CAM_KEEP_UI` | `false` | 退出时保留 GUI |

> **注意**: 环境变量是 `CAM_KEEP_UI`，不是 `CAM_GUI_KEEP`

### 新增环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CAM_GUI_PORT` | `0` (随机) | 指定 GUI 服务端口 |
| `CAM_GUI_HOST` | `127.0.0.1` | 绑定地址 |

> **安全警告**: 设置 `CAM_GUI_HOST=0.0.0.0` 会允许远程访问，可能泄露敏感信息（prompt、文件路径等）。仅在受信任网络环境中使用，或通过 `ssh -L` 做端口转发。

## 重要说明

### SSE 断开检测 vs 心跳机制

这是两个**不同的机制**，解决不同的问题：

| 机制 | 作用 | 位置 |
|------|------|------|
| **SSE 断开检测** | 检测 GUI 客户端（浏览器/pywebview）是否存在 | GUIServer |
| **心跳机制** | 检测主进程是否还活着 | GUIManager |

SSE 断开检测**不会替代**心跳机制。两者并存：
- 心跳：主进程 → GUI 子进程（检测主进程是否被 SIGKILL）
- SSE：GUI 子进程 → 浏览器（检测是否还有客户端连接）

### pywebview 降级逻辑

降级触发条件（任一满足即降级）：
1. `import webview` 失败（ImportError）
2. Linux 环境下无 `DISPLAY` 或 `WAYLAND_DISPLAY`
3. `webview.create_window()` 或 `webview.start()` 抛出任何异常

降级后行为：
- 打印 URL 到日志
- 启动纯 Web 模式
- 用户需手动在浏览器打开 URL

## 兼容性

### 向后兼容

- 现有环境变量保持不变
- pywebview 可用时行为与之前一致（只是从 `html=` 改为 `url=`）
- 事件格式和渲染逻辑不变
- KEEP_UI 语义不变

### 新增能力

- pywebview 不可用时自动降级为纯 Web 模式
- 支持多客户端并行访问（最多 10 个）
- 支持远程访问（配置 `CAM_GUI_HOST=0.0.0.0`）
- 提供 `LiveViewer.url` 属性获取 GUI 地址

## 测试计划

### 单元测试

1. `GUIServer` 启动和停止
2. SSE 连接和断开检测
3. 多客户端广播
4. 宽限期逻辑
5. 客户端数量限制
6. **pywebview 不可用时的降级路径**

### 集成测试

1. pywebview 可用时的正常流程
2. pywebview 不可用时的降级流程
3. GUI + 浏览器并行访问
4. KEEP_UI 模式下的退出逻辑
5. **Linux 无 DISPLAY 时的行为**

### 手动测试

1. Windows 原生环境
2. WSL2 环境（无 pywebview）
3. macOS 环境
4. Linux 环境（GTK/QT）

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| SSE 连接不稳定 | 事件丢失 | 心跳保活 + 自动重连（指数退避） |
| 端口冲突 | 启动失败 | 使用随机端口（从 TCPServer 获取） |
| 多客户端性能 | 广播延迟 | 限制最大客户端数（10） |
| 浏览器兼容性 | SSE 不支持 | 现代浏览器都支持 |
| 远程访问安全 | 信息泄露 | 默认只绑定 127.0.0.1 |

## 实施步骤

1. **Phase 1**: 新增 `GUIServer` 类（不影响现有功能）
2. **Phase 2**: 修改 `template.py` 添加 `updateStatus` 和 SSE 客户端代码
3. **Phase 3**: 修改 `LiveViewer` 使用 HTTP URL + 降级逻辑
4. **Phase 4**: 更新 `close()` 方法，添加清理逻辑
5. **Phase 5**: 测试和文档更新

## Codex Review 结果

### 确认的优点

- ✅ SSE 单向推送完全符合场景需求
- ✅ 多客户端广播设计合理（每客户端独立 Queue）
- ✅ 宽限期逻辑无竞态问题
- ✅ 事件格式和渲染逻辑保持兼容
- ✅ KEEP_UI 语义不受影响

### 已修复的问题

- ✅ 环境变量名：`CAM_GUI_KEEP` → `CAM_KEEP_UI`
- ✅ `_poll_queue_loop` 条件不再依赖 `self._window`
- ✅ pywebview 降级覆盖所有异常（不只是 ImportError）
- ✅ 端口分配改为从 TCPServer 直接获取（避免竞态）
- ✅ 添加 `updateStatus` 函数实现
- ✅ `close()` 方法补充 `_server.stop()`
- ✅ 添加 host 参数支持
- ✅ 添加客户端数量限制
- ✅ 澄清 SSE 断开检测 vs 心跳机制的区别

## 参考

- [Server-Sent Events (SSE) - MDN](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events)
- [pywebview 文档](https://pywebview.flowrl.com/)
- [Python http.server](https://docs.python.org/3/library/http.server.html)
