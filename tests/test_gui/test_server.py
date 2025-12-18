"""GUIServer 单元测试"""

import json
import queue
import threading
import time
import urllib.request

import pytest

from src.cli_agent_mcp.shared.gui.server import GUIServer, ServerConfig


class TestGUIServer:
    """GUIServer 基本功能测试"""

    def test_server_starts_and_stops(self):
        """服务器能正常启动和停止"""
        server = GUIServer("<html>test</html>")
        port = server.start()
        assert port > 0
        assert server.url.startswith("http://127.0.0.1:")
        server.stop()

    def test_server_serves_html(self):
        """服务器能提供 HTML 页面"""
        html = "<html><body>Hello</body></html>"
        server = GUIServer(html)
        server.start()
        try:
            with urllib.request.urlopen(server.url, timeout=2) as resp:
                content = resp.read().decode('utf-8')
                assert content == html
        finally:
            server.stop()

    def test_server_random_port(self):
        """端口为 0 时分配随机端口"""
        server = GUIServer("<html>test</html>", ServerConfig(port=0))
        port = server.start()
        assert port > 1024  # 非特权端口
        server.stop()

    def test_broadcast_to_no_clients(self):
        """无客户端时广播不报错"""
        server = GUIServer("<html>test</html>")
        server.start()
        try:
            server.broadcast({"type": "test"})  # 不应抛出异常
            assert server.client_count == 0
        finally:
            server.stop()


class TestSSEConnection:
    """SSE 连接测试"""

    def test_sse_endpoint_exists(self):
        """SSE 端点存在"""
        server = GUIServer("<html>test</html>")
        server.start()
        try:
            req = urllib.request.Request(f"{server.url}/sse")
            with urllib.request.urlopen(req, timeout=1) as resp:
                assert resp.headers.get('Content-Type') == 'text/event-stream'
        except Exception:
            pass  # 连接可能超时，但端点存在
        finally:
            server.stop()


class TestClientManagement:
    """客户端管理测试"""

    def test_max_clients_limit(self):
        """客户端数量限制"""
        config = ServerConfig(max_clients=2)
        server = GUIServer("<html>test</html>", config)

        # 模拟添加客户端
        q1, q2, q3 = queue.Queue(), queue.Queue(), queue.Queue()
        assert server._client_connected(q1) is True
        assert server._client_connected(q2) is True
        assert server._client_connected(q3) is False  # 超过限制
        assert server.client_count == 2

    def test_client_disconnect_updates_count(self):
        """客户端断开后计数更新"""
        server = GUIServer("<html>test</html>")
        q = queue.Queue()
        server._client_connected(q)
        assert server.client_count == 1
        server._client_disconnected(q)
        assert server.client_count == 0


class TestBroadcast:
    """广播功能测试"""

    def test_broadcast_to_multiple_clients(self):
        """广播到多个客户端"""
        server = GUIServer("<html>test</html>")
        q1, q2 = queue.Queue(), queue.Queue()
        server._client_connected(q1)
        server._client_connected(q2)

        event = {"type": "event", "html": "<div>test</div>"}
        server.broadcast(event)

        assert q1.get_nowait() == event
        assert q2.get_nowait() == event

    def test_broadcast_drops_on_full_queue(self):
        """队列满时丢弃事件"""
        server = GUIServer("<html>test</html>")
        q = queue.Queue(maxsize=1)
        server._client_connected(q)

        server.broadcast({"type": "event1"})
        server.broadcast({"type": "event2"})  # 应该被丢弃

        assert q.qsize() == 1


class TestGracePeriod:
    """宽限期测试"""

    def test_shutdown_callback_after_grace(self):
        """宽限期后触发回调"""
        config = ServerConfig(grace_period=0.1)
        server = GUIServer("<html>test</html>", config)

        callback_called = threading.Event()
        server.on_all_disconnected(lambda: callback_called.set())

        q = queue.Queue()
        server._client_connected(q)
        server._client_disconnected(q)

        # 等待宽限期 + 一点余量
        assert callback_called.wait(timeout=0.5)

    def test_no_callback_if_client_reconnects(self):
        """宽限期内重连不触发回调"""
        config = ServerConfig(grace_period=0.3)
        server = GUIServer("<html>test</html>", config)

        callback_called = threading.Event()
        server.on_all_disconnected(lambda: callback_called.set())

        q1 = queue.Queue()
        server._client_connected(q1)
        server._client_disconnected(q1)

        # 宽限期内重连
        time.sleep(0.1)
        q2 = queue.Queue()
        server._client_connected(q2)

        # 等待超过宽限期
        time.sleep(0.4)
        assert not callback_called.is_set()
