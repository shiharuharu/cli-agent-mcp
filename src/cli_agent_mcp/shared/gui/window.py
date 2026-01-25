"""pywebview 窗口管理。

cli-agent-mcp shared/gui v0.2.0
同步日期: 2025-12-18

提供 pywebview 窗口和 Queue 通信机制，支持 HTTP + SSE 降级。

Example:
    # 基本用法（单端模式）
    viewer = LiveViewer(title="GeminiMCP")
    viewer.start()
    viewer.push_event(unified_event_dict)

    # 多端模式
    viewer = LiveViewer(title="CLI Agent", multi_source_mode=True)
    viewer.start()
"""

from __future__ import annotations

import logging
import os
import queue
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from .renderer import EventRenderer, RenderConfig
from .server import GUIServer, ServerConfig
from .template import generate_html

logger = logging.getLogger(__name__)

__all__ = [
    "LiveViewer",
    "ViewerConfig",
]


@dataclass
class ViewerConfig:
    """查看器配置。

    Attributes:
        title: 窗口标题
        width: 窗口宽度
        height: 窗口高度
        multi_source_mode: 是否为多端模式
        queue_max_size: 事件队列最大大小
        poll_interval_ms: 队列轮询间隔（毫秒）
    """
    title: str = "CLI Agent Live Output"
    width: int = 1000
    height: int = 650
    multi_source_mode: bool = False
    queue_max_size: int = 5000
    poll_interval_ms: int = 50


class LiveViewer:
    """实时事件查看器。

    使用 pywebview 显示统一事件流，支持：
    - 单端模式（不显示来源标签）
    - 多端模式（显示来源标签，侧边栏按来源分组）
    - Queue 通信（线程安全的事件推送）
    - 状态栏统计（尽力而为）

    Example:
        viewer = LiveViewer(multi_source_mode=True)
        viewer.start()

        # 从其他线程推送事件
        viewer.push_event(event_dict)

        # 或使用便捷方法
        viewer.push_raw(raw_cli_output, source="gemini")
    """

    def __init__(
        self,
        config: ViewerConfig | None = None,
        *,
        title: str | None = None,
        multi_source_mode: bool | None = None,
    ) -> None:
        """初始化查看器。

        Args:
            config: 完整配置对象
            title: 窗口标题（覆盖 config）
            multi_source_mode: 是否多端模式（覆盖 config）
        """
        self.config = config or ViewerConfig()
        if title is not None:
            self.config.title = title
        if multi_source_mode is not None:
            self.config.multi_source_mode = multi_source_mode

        # 渲染器（file_url_resolver 在 server 启动后设置）
        self._renderer = EventRenderer(
            RenderConfig(multi_source_mode=self.config.multi_source_mode),
            file_url_resolver=None,
        )

        # 事件队列
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(
            maxsize=self.config.queue_max_size
        )

        # 窗口引用
        self._window = None
        self._started = threading.Event()
        self._closed = threading.Event()
        self._poll_thread: threading.Thread | None = None

        # HTTP 服务器
        self._server: GUIServer | None = None
        self._url: str | None = None
        self._url_callback: Callable[[str], None] | None = None  # URL 回调
        self._webview_available: bool = False

        # 统计
        self._stats = {
            "model": None,
            "session": None,
            "tokens": 0,
            "duration": 0.0,
            "tools": 0,
        }

    @property
    def url(self) -> str | None:
        """获取 GUI URL"""
        return self._url

    @property
    def is_webview_mode(self) -> bool:
        """是否使用 pywebview 模式"""
        return self._webview_available and self._window is not None

    def start(self, blocking: bool = True) -> None:
        """启动查看器。

        Args:
            blocking: 是否阻塞当前线程
        """
        if blocking:
            self._run()
        else:
            thread = threading.Thread(target=self._run, daemon=True)
            thread.start()
            # 等待窗口准备好
            self._started.wait(timeout=10)

    def _check_gui_available(self) -> bool:
        """检查 GUI 环境是否可用（Linux/WSL2 特殊处理）"""
        if sys.platform == "linux":
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
        server_config = ServerConfig(
            host=os.environ.get("CAM_GUI_HOST", "127.0.0.1"),
            port=int(os.environ.get("CAM_GUI_PORT", "0")),
        )
        self._server = GUIServer(html, server_config)
        try:
            self._server.start()
        except OSError as e:
            if server_config.port:
                logger.warning(
                    f"Failed to bind GUI server on port {server_config.port} ({e}), falling back to random port"
                )
                server_config.port = 0
                self._server = GUIServer(html, server_config)
                self._server.start()
            else:
                raise
        self._url = self._server.url

        # 设置 file_url_resolver
        self._renderer._file_url_resolver = self._server.register_file

        # HTTP server 启动后立即回调 URL
        if self._url_callback:
            try:
                self._url_callback(self._url)
            except Exception:
                pass

        # 注册断开回调
        self._server.on_all_disconnected(self._on_all_clients_disconnected)

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
                url=self._url,
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
                try:
                    self._queue.put_nowait(None)  # 非阻塞，避免死锁
                except queue.Full:
                    pass
                # 停止 HTTP 服务器
                if self._server:
                    self._server.stop()

            self._window.events.loaded += on_loaded
            self._window.events.closed += on_closed

            webview.start()

        except ImportError:
            logger.warning(f"pywebview not installed, use browser: {self._url}")
            self._start_web_only_mode()

        except Exception as e:
            logger.warning(f"pywebview failed ({e}), falling back to browser: {self._url}")
            self._start_web_only_mode()

    def _start_web_only_mode(self):
        """启动纯 Web 模式"""
        self._webview_available = False
        self._started.set()

        # 自动打开浏览器
        import webbrowser
        if self._url:
            webbrowser.open(self._url)

        self._poll_thread = threading.Thread(
            target=self._poll_queue_loop, daemon=True
        )
        self._poll_thread.start()

        self._closed.wait()

    def _on_all_clients_disconnected(self):
        """所有客户端断开时的回调"""
        logger.info("All clients disconnected")
        # 断开可能由休眠/网络切换/页面刷新导致；无论模式都不自杀，等待重连。
        if self._window is not None:
            logger.info("Pywebview mode: waiting for client reconnection")
        else:
            logger.info("Browser mode: waiting for client reconnection")
        return

    def _poll_queue_loop(self) -> None:
        """后台轮询线程主循环 - 不再依赖 self._window"""
        poll_interval = self.config.poll_interval_ms / 1000

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

    def _render_event(self, event: dict[str, Any]) -> None:
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

            self._update_stats(event)

        except Exception as e:
            logger.warning(f"Render error: {e}")

    def _extract_session_id(self, event: dict[str, Any]) -> str:
        """提取 session ID。"""
        if event.get("session_id"):
            return event["session_id"]
        metadata = event.get("metadata", {})
        return metadata.get("session_id", "") or metadata.get("thread_id", "")

    def _update_stats(self, event: dict[str, Any]) -> None:
        """更新状态栏 - 通过 SSE 广播"""
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

        # Debug info from metadata (banana, image, parallel)
        metadata = event.get("metadata", {})
        debug = metadata.get("debug", {})
        if debug:
            if debug.get("model"):
                self._stats["model"] = debug["model"]
                updated = True
            if debug.get("duration_sec"):
                self._stats["duration"] = debug["duration_sec"]
                updated = True
            if debug.get("image_count"):
                self._stats["tools"] = debug["image_count"]
                updated = True
            if debug.get("total_tasks"):
                self._stats["tools"] = debug["total_tasks"]
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

    def push_event(self, event: dict[str, Any]) -> bool:
        """推送统一事件到显示队列。

        Args:
            event: 统一事件字典（UnifiedEvent.model_dump()）

        Returns:
            是否成功入队（队列满时返回 False）
        """
        try:
            self._queue.put_nowait(event)
            return True
        except queue.Full:
            return False

    def push_events(self, events: list[dict[str, Any]]) -> int:
        """批量推送事件。

        Args:
            events: 事件列表

        Returns:
            成功入队的数量
        """
        count = 0
        for event in events:
            if self.push_event(event):
                count += 1
        return count

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

    @property
    def is_running(self) -> bool:
        """查看器是否正在运行。"""
        return self._started.is_set() and not self._closed.is_set()

    def wait_closed(self, timeout: float | None = None) -> bool:
        """等待窗口关闭。

        Args:
            timeout: 超时时间（秒）

        Returns:
            是否已关闭
        """
        return self._closed.wait(timeout=timeout)
