"""SignalManager 模块测试。

测试信号管理器的基本功能：
- 信号处理策略
- 配置支持
- 双击退出
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest import mock

import pytest

from cli_agent_mcp.config import SigintMode
from cli_agent_mcp.orchestrator import RequestRegistry
from cli_agent_mcp.signal_manager import SignalManager


class TestSigintMode:
    """SigintMode 枚举测试。"""

    def test_from_string_valid(self):
        """有效字符串解析。"""
        assert SigintMode.from_string("cancel") == SigintMode.CANCEL
        assert SigintMode.from_string("exit") == SigintMode.EXIT
        assert SigintMode.from_string("cancel_then_exit") == SigintMode.CANCEL_THEN_EXIT

    def test_from_string_case_insensitive(self):
        """大小写不敏感。"""
        assert SigintMode.from_string("CANCEL") == SigintMode.CANCEL
        assert SigintMode.from_string("Exit") == SigintMode.EXIT
        assert SigintMode.from_string("Cancel_Then_Exit") == SigintMode.CANCEL_THEN_EXIT

    def test_from_string_invalid(self):
        """无效字符串返回默认值 CANCEL。"""
        assert SigintMode.from_string("invalid") == SigintMode.CANCEL
        assert SigintMode.from_string("") == SigintMode.CANCEL


class TestSignalManagerInit:
    """SignalManager 初始化测试。"""

    def test_init_with_defaults(self):
        """使用默认配置初始化。"""
        registry = RequestRegistry()

        with mock.patch.dict(os.environ, {}, clear=False):
            # 确保没有相关环境变量
            os.environ.pop("CAM_SIGINT_MODE", None)
            os.environ.pop("CAM_SIGINT_DOUBLE_TAP_WINDOW", None)

            # 重新加载配置
            from cli_agent_mcp.config import reload_config
            reload_config()

            manager = SignalManager(registry)

            assert manager.registry is registry
            assert manager.sigint_mode == SigintMode.CANCEL
            assert manager.double_tap_window == 1.0

    def test_init_with_custom_values(self):
        """使用自定义值初始化。"""
        registry = RequestRegistry()
        manager = SignalManager(
            registry,
            sigint_mode=SigintMode.EXIT,
            double_tap_window=2.0,
        )

        assert manager.sigint_mode == SigintMode.EXIT
        assert manager.double_tap_window == 2.0


class TestSignalManagerSigintCancel:
    """SignalManager SIGINT CANCEL 模式测试。"""

    def test_sigint_with_active_requests_cancels_all(self):
        """有活动请求时 SIGINT 取消所有请求。"""
        registry = RequestRegistry()
        task = mock.MagicMock(spec=asyncio.Task)
        task.done.return_value = False
        registry.register("req-1", "codex", task)

        manager = SignalManager(
            registry,
            sigint_mode=SigintMode.CANCEL,
        )

        # 模拟 SIGINT
        manager._handle_sigint()

        # 验证请求被取消
        task.cancel.assert_called_once()

        # 验证没有请求关闭
        assert manager.is_shutdown_requested is False

    def test_sigint_without_active_requests_shuts_down(self):
        """没有活动请求时 SIGINT 请求关闭。"""
        registry = RequestRegistry()

        manager = SignalManager(
            registry,
            sigint_mode=SigintMode.CANCEL,
        )
        manager._shutdown_event = asyncio.Event()
        manager._loop = mock.MagicMock()

        # 模拟 SIGINT
        manager._handle_sigint()

        # 验证请求关闭
        assert manager.is_shutdown_requested is True


class TestSignalManagerSigintExit:
    """SignalManager SIGINT EXIT 模式测试。"""

    def test_sigint_always_shuts_down(self):
        """EXIT 模式下 SIGINT 始终请求关闭。"""
        registry = RequestRegistry()
        task = mock.MagicMock(spec=asyncio.Task)
        task.done.return_value = False
        registry.register("req-1", "codex", task)

        manager = SignalManager(
            registry,
            sigint_mode=SigintMode.EXIT,
        )
        manager._shutdown_event = asyncio.Event()
        manager._loop = mock.MagicMock()

        # 模拟 SIGINT
        manager._handle_sigint()

        # 验证请求关闭（即使有活动请求）
        assert manager.is_shutdown_requested is True

        # 验证请求没有被取消
        task.cancel.assert_not_called()


class TestSignalManagerSigintCancelThenExit:
    """SignalManager SIGINT CANCEL_THEN_EXIT 模式测试。"""

    def test_sigint_first_cancels_second_exits(self):
        """CANCEL_THEN_EXIT 模式：第一次取消，第二次退出。"""
        registry = RequestRegistry()
        task = mock.MagicMock(spec=asyncio.Task)
        task.done.return_value = False
        registry.register("req-1", "codex", task)

        manager = SignalManager(
            registry,
            sigint_mode=SigintMode.CANCEL_THEN_EXIT,
            double_tap_window=1.0,
        )
        manager._shutdown_event = asyncio.Event()
        manager._loop = mock.MagicMock()

        # 第一次 SIGINT
        manager._handle_sigint()

        # 验证请求被取消
        task.cancel.assert_called_once()

        # 验证标记为已请求关闭但没有触发实际关闭
        assert manager._shutdown_requested is True

    def test_sigint_without_active_requests_shuts_down(self):
        """CANCEL_THEN_EXIT 模式：没有活动请求时直接关闭。"""
        registry = RequestRegistry()

        manager = SignalManager(
            registry,
            sigint_mode=SigintMode.CANCEL_THEN_EXIT,
        )
        manager._shutdown_event = asyncio.Event()
        manager._loop = mock.MagicMock()

        # 模拟 SIGINT
        manager._handle_sigint()

        # 验证请求关闭
        assert manager.is_shutdown_requested is True


class TestSignalManagerDoubleTap:
    """SignalManager 双击退出测试。"""

    def test_double_tap_forces_exit(self):
        """双击 SIGINT 设置强制退出标志。

        注意：新实现不再直接调用 sys.exit(130)，而是设置 is_force_exit 标志，
        让主循环在清理完成后再退出。这确保子进程被正确清理。
        """
        registry = RequestRegistry()

        manager = SignalManager(
            registry,
            sigint_mode=SigintMode.CANCEL_THEN_EXIT,
            double_tap_window=1.0,
        )
        manager._shutdown_event = asyncio.Event()
        manager._loop = mock.MagicMock()

        # 设置状态：已请求关闭
        manager._shutdown_requested = True

        # 第一次 SIGINT
        manager._handle_sigint()

        # 第二次 SIGINT（在窗口内）- 应该设置强制退出标志
        manager._handle_sigint()

        # 验证强制退出标志被设置
        assert manager.is_force_exit is True
        # 验证 shutdown event 被触发
        manager._loop.call_soon_threadsafe.assert_called()


class TestSignalManagerSigterm:
    """SignalManager SIGTERM 测试。"""

    def test_sigterm_cancels_all_and_shuts_down(self):
        """SIGTERM 取消所有请求并关闭。"""
        registry = RequestRegistry()
        task = mock.MagicMock(spec=asyncio.Task)
        task.done.return_value = False
        registry.register("req-1", "codex", task)

        manager = SignalManager(registry)
        manager._shutdown_event = asyncio.Event()
        manager._loop = mock.MagicMock()

        # 模拟 SIGTERM
        manager._handle_sigterm()

        # 验证请求被取消
        task.cancel.assert_called_once()

        # 验证请求关闭
        assert manager.is_shutdown_requested is True


class TestSignalManagerCallbacks:
    """SignalManager 回调测试。"""

    def test_on_shutdown_callback(self):
        """关闭时调用回调。"""
        registry = RequestRegistry()
        callback = mock.MagicMock()

        manager = SignalManager(
            registry,
            sigint_mode=SigintMode.EXIT,
            on_shutdown=callback,
        )
        manager._shutdown_event = asyncio.Event()
        manager._loop = mock.MagicMock()

        # 模拟 SIGINT（EXIT 模式直接关闭）
        manager._handle_sigint()

        # 验证回调被调用
        callback.assert_called_once()


class TestSignalManagerGracefulShutdown:
    """SignalManager 程序化关闭测试。"""

    def test_request_graceful_shutdown(self):
        """程序化请求优雅退出。"""
        registry = RequestRegistry()
        task = mock.MagicMock(spec=asyncio.Task)
        task.done.return_value = False
        registry.register("req-1", "codex", task)

        manager = SignalManager(registry)
        manager._shutdown_event = asyncio.Event()
        manager._loop = mock.MagicMock()

        # 程序化请求关闭
        manager.request_graceful_shutdown()

        # 验证请求被取消
        task.cancel.assert_called_once()

        # 验证请求关闭
        assert manager.is_shutdown_requested is True


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal handling")
class TestSignalManagerStartStop:
    """SignalManager 启动/停止测试（仅 POSIX）。"""

    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        """启动和停止信号管理器。"""
        registry = RequestRegistry()
        manager = SignalManager(registry)

        # 启动
        await manager.start()
        assert manager._running is True
        assert manager._loop is not None

        # 停止
        await manager.stop()
        assert manager._running is False


class TestConfigParsing:
    """配置解析测试。"""

    def test_parse_sigint_mode_from_env(self):
        """从环境变量解析 SIGINT 模式。"""
        from cli_agent_mcp.config import load_config

        with mock.patch.dict(os.environ, {"CAM_SIGINT_MODE": "exit"}):
            config = load_config()
            assert config.sigint_mode == SigintMode.EXIT

        with mock.patch.dict(os.environ, {"CAM_SIGINT_MODE": "cancel_then_exit"}):
            config = load_config()
            assert config.sigint_mode == SigintMode.CANCEL_THEN_EXIT

    def test_parse_double_tap_window_from_env(self):
        """从环境变量解析双击窗口时间。"""
        from cli_agent_mcp.config import load_config

        with mock.patch.dict(os.environ, {"CAM_SIGINT_DOUBLE_TAP_WINDOW": "2.5"}):
            config = load_config()
            assert config.sigint_double_tap_window == 2.5

    def test_parse_double_tap_window_clamped(self):
        """双击窗口时间被限制在范围内。"""
        from cli_agent_mcp.config import load_config

        # 太小
        with mock.patch.dict(os.environ, {"CAM_SIGINT_DOUBLE_TAP_WINDOW": "0.01"}):
            config = load_config()
            assert config.sigint_double_tap_window == 0.1

        # 太大
        with mock.patch.dict(os.environ, {"CAM_SIGINT_DOUBLE_TAP_WINDOW": "100"}):
            config = load_config()
            assert config.sigint_double_tap_window == 10.0

    def test_parse_double_tap_window_invalid(self):
        """无效值返回默认值。"""
        from cli_agent_mcp.config import load_config

        with mock.patch.dict(os.environ, {"CAM_SIGINT_DOUBLE_TAP_WINDOW": "invalid"}):
            config = load_config()
            assert config.sigint_double_tap_window == 1.0
