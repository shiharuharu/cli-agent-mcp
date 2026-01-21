"""内置 HTTP + SSE 服务器

cli-agent-mcp shared/gui v0.2.0
同步日期: 2025-12-18

提供 HTTP 静态页面和 SSE 事件流，支持多客户端并行访问。
"""

from __future__ import annotations

import http.server
import json
import logging
import mimetypes
import queue
import secrets
import socketserver
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

__all__ = [
    "GUIServer",
    "ServerConfig",
]


@dataclass
class ServerConfig:
    """服务器配置"""
    host: str = "127.0.0.1"
    port: int = 0  # 0 = 随机端口
    grace_period: float = 10.0  # 宽限期（秒）
    max_clients: int = 10  # 最大客户端数


class ReusableTCPServer(socketserver.ThreadingTCPServer):
    """支持端口复用的 TCP 服务器"""
    allow_reuse_address = True


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
        self._file_tokens: dict[str, str] = {}  # token -> file_path

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

        self._server = ReusableTCPServer(
            (self.config.host, self.config.port), handler
        )
        self._server.daemon_threads = True  # SSE 线程不阻塞进程退出
        self._server.block_on_close = False  # stop() 不等待线程结束

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
            for client_q in self._clients[:]:
                try:
                    client_q.put_nowait(event)
                except queue.Full:
                    logger.debug("Client queue full, dropping event")

    @property
    def client_count(self) -> int:
        """当前连接的客户端数量"""
        with self._lock:
            return len(self._clients)

    def register_file(self, file_path: str) -> str:
        """注册文件并返回访问 URL"""
        token = secrets.token_urlsafe(16)
        self._file_tokens[token] = file_path
        return f"/file/{token}"

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
                elif self.path.startswith('/file/'):
                    self._serve_file()
                else:
                    self.send_error(404)

            def _serve_file(self):
                token = self.path[6:]  # 去掉 "/file/" 前缀
                file_path = server._file_tokens.get(token)
                if not file_path or not Path(file_path).exists():
                    self.send_error(404)
                    return
                content = Path(file_path).read_bytes()
                mime_type = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'
                self.send_response(200)
                self.send_header('Content-Type', mime_type)
                self.send_header('Content-Length', len(content))
                self.send_header('Cache-Control', 'max-age=3600')
                self.end_headers()
                self.wfile.write(content)

            def _serve_html(self):
                content = server.html.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', len(content))
                self.end_headers()
                self.wfile.write(content)

            def _serve_sse(self):
                client_q: queue.Queue = queue.Queue(maxsize=500)

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
                            self.wfile.write(b": ping\n\n")
                            self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError, TimeoutError):
                    pass
                finally:
                    server._client_disconnected(client_q)

            def log_message(self, format, *args):
                pass

        return Handler
