"""RequestRegistry 模块测试。

测试请求注册表的基本功能：
- 请求登记和注销
- 批量取消
- 活动状态查询
"""

from __future__ import annotations

import asyncio
from unittest import mock

import pytest

from cli_agent_mcp.orchestrator import RequestRegistry, RequestInfo


class TestRequestRegistry:
    """RequestRegistry 基本功能测试。"""

    def test_generate_request_id(self):
        """生成唯一请求 ID。"""
        id1 = RequestRegistry.generate_request_id()
        id2 = RequestRegistry.generate_request_id()
        assert id1 != id2
        assert len(id1) == 36  # UUID4 格式

    def test_register_and_unregister(self):
        """登记和注销请求。"""
        registry = RequestRegistry()
        task = mock.MagicMock(spec=asyncio.Task)
        task.done.return_value = False

        # 登记
        registry.register("req-1", "codex", task, "test task")
        assert "req-1" in registry
        assert registry.total_count == 1

        # 注销
        result = registry.unregister("req-1")
        assert result is True
        assert "req-1" not in registry
        assert registry.total_count == 0

    def test_register_duplicate_raises_error(self):
        """登记重复请求 ID 时抛出错误。"""
        registry = RequestRegistry()
        task = mock.MagicMock(spec=asyncio.Task)
        task.done.return_value = False

        registry.register("req-1", "codex", task)

        with pytest.raises(ValueError, match="already registered"):
            registry.register("req-1", "gemini", task)

    def test_unregister_nonexistent_returns_false(self):
        """注销不存在的请求返回 False。"""
        registry = RequestRegistry()
        result = registry.unregister("nonexistent")
        assert result is False

    def test_get_request_info(self):
        """获取请求信息。"""
        registry = RequestRegistry()
        task = mock.MagicMock(spec=asyncio.Task)
        task.done.return_value = False

        registry.register("req-1", "codex", task, "test task")

        info = registry.get("req-1")
        assert info is not None
        assert info.request_id == "req-1"
        assert info.cli_type == "codex"
        assert info.task_note == "test task"

        # 不存在的请求
        assert registry.get("nonexistent") is None


class TestRequestRegistryCancellation:
    """RequestRegistry 取消功能测试。"""

    def test_cancel_single_request(self):
        """取消单个请求。"""
        registry = RequestRegistry()
        task = mock.MagicMock(spec=asyncio.Task)
        task.done.return_value = False

        registry.register("req-1", "codex", task)
        result = registry.cancel("req-1")

        assert result is True
        task.cancel.assert_called_once()

    def test_cancel_nonexistent_request(self):
        """取消不存在的请求返回 False。"""
        registry = RequestRegistry()
        result = registry.cancel("nonexistent")
        assert result is False

    def test_cancel_completed_request(self):
        """取消已完成的请求返回 False。"""
        registry = RequestRegistry()
        task = mock.MagicMock(spec=asyncio.Task)
        task.done.return_value = True  # 已完成

        registry.register("req-1", "codex", task)
        result = registry.cancel("req-1")

        assert result is False
        task.cancel.assert_not_called()

    def test_cancel_all(self):
        """取消所有活动请求。"""
        registry = RequestRegistry()

        # 创建多个任务
        task1 = mock.MagicMock(spec=asyncio.Task)
        task1.done.return_value = False

        task2 = mock.MagicMock(spec=asyncio.Task)
        task2.done.return_value = False

        task3 = mock.MagicMock(spec=asyncio.Task)
        task3.done.return_value = True  # 已完成

        registry.register("req-1", "codex", task1)
        registry.register("req-2", "gemini", task2)
        registry.register("req-3", "claude", task3)

        cancelled = registry.cancel_all()

        assert cancelled == 2  # 只取消 2 个活动请求
        task1.cancel.assert_called_once()
        task2.cancel.assert_called_once()
        task3.cancel.assert_not_called()


class TestRequestRegistryStatus:
    """RequestRegistry 状态查询测试。"""

    def test_has_active_requests(self):
        """检查是否有活动请求。"""
        registry = RequestRegistry()
        assert registry.has_active_requests() is False

        task = mock.MagicMock(spec=asyncio.Task)
        task.done.return_value = False

        registry.register("req-1", "codex", task)
        assert registry.has_active_requests() is True

        task.done.return_value = True
        assert registry.has_active_requests() is False

    def test_active_count(self):
        """获取活动请求数量。"""
        registry = RequestRegistry()
        assert registry.active_count == 0

        task1 = mock.MagicMock(spec=asyncio.Task)
        task1.done.return_value = False

        task2 = mock.MagicMock(spec=asyncio.Task)
        task2.done.return_value = True

        registry.register("req-1", "codex", task1)
        registry.register("req-2", "gemini", task2)

        assert registry.active_count == 1
        assert registry.total_count == 2

    def test_list_active(self):
        """列出活动请求。"""
        registry = RequestRegistry()

        task1 = mock.MagicMock(spec=asyncio.Task)
        task1.done.return_value = False

        task2 = mock.MagicMock(spec=asyncio.Task)
        task2.done.return_value = True

        registry.register("req-1", "codex", task1)
        registry.register("req-2", "gemini", task2)

        active = registry.list_active()
        assert len(active) == 1
        assert active[0].request_id == "req-1"


class TestRequestRegistryCallbacks:
    """RequestRegistry 回调功能测试。"""

    def test_on_empty_callback(self):
        """注册表变空时调用回调。"""
        registry = RequestRegistry()
        callback = mock.MagicMock()

        registry.add_on_empty_callback(callback)

        task = mock.MagicMock(spec=asyncio.Task)
        task.done.return_value = False

        registry.register("req-1", "codex", task)
        callback.assert_not_called()

        registry.unregister("req-1")
        callback.assert_called_once()

    def test_on_empty_callback_only_when_empty(self):
        """只有在完全清空时才调用回调。"""
        registry = RequestRegistry()
        callback = mock.MagicMock()

        registry.add_on_empty_callback(callback)

        task1 = mock.MagicMock(spec=asyncio.Task)
        task1.done.return_value = False
        task2 = mock.MagicMock(spec=asyncio.Task)
        task2.done.return_value = False

        registry.register("req-1", "codex", task1)
        registry.register("req-2", "gemini", task2)

        registry.unregister("req-1")
        callback.assert_not_called()  # 还有一个请求

        registry.unregister("req-2")
        callback.assert_called_once()  # 现在完全清空

    def test_remove_on_empty_callback(self):
        """移除回调。"""
        registry = RequestRegistry()
        callback = mock.MagicMock()

        registry.add_on_empty_callback(callback)
        registry.remove_on_empty_callback(callback)

        task = mock.MagicMock(spec=asyncio.Task)
        task.done.return_value = False

        registry.register("req-1", "codex", task)
        registry.unregister("req-1")

        callback.assert_not_called()


class TestRequestRegistryCleanup:
    """RequestRegistry 清理功能测试。"""

    def test_cleanup_done(self):
        """清理已完成的请求。"""
        registry = RequestRegistry()

        task1 = mock.MagicMock(spec=asyncio.Task)
        task1.done.return_value = False

        task2 = mock.MagicMock(spec=asyncio.Task)
        task2.done.return_value = True

        task3 = mock.MagicMock(spec=asyncio.Task)
        task3.done.return_value = True

        registry.register("req-1", "codex", task1)
        registry.register("req-2", "gemini", task2)
        registry.register("req-3", "claude", task3)

        cleaned = registry.cleanup_done()

        assert cleaned == 2
        assert registry.total_count == 1
        assert "req-1" in registry
        assert "req-2" not in registry
        assert "req-3" not in registry


class TestRequestInfo:
    """RequestInfo 测试。"""

    def test_repr_running(self):
        """运行中的请求字符串表示。"""
        task = mock.MagicMock(spec=asyncio.Task)
        task.done.return_value = False

        info = RequestInfo(
            request_id="12345678-1234-1234-1234-123456789012",
            cli_type="codex",
            task=task,
            task_note="test",
        )

        repr_str = repr(info)
        assert "12345678" in repr_str
        assert "codex" in repr_str
        assert "running" in repr_str

    def test_repr_done(self):
        """已完成的请求字符串表示。"""
        task = mock.MagicMock(spec=asyncio.Task)
        task.done.return_value = True

        info = RequestInfo(
            request_id="12345678-1234-1234-1234-123456789012",
            cli_type="gemini",
            task=task,
        )

        repr_str = repr(info)
        assert "done" in repr_str
