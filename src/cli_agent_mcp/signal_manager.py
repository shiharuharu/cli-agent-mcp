"""信号管理模块。

实现信号隔离策略，将 OS 信号转换为请求级别的操作：
- SIGINT: 取消活动请求（而不是直接退出进程）
- SIGTERM: 优雅退出（取消所有请求 + 清理 + 退出）

支持的配置：
- CAM_SIGINT_MODE: cancel | exit | cancel_then_exit
- CAM_SIGINT_DOUBLE_TAP_WINDOW: 双击退出窗口时间

这是解决"取消请求导致整个进程退出"问题的核心模块。
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time
from typing import Callable, Optional

from .config import SigintMode, get_config
from .orchestrator import RequestRegistry

__all__ = ["SignalManager", "SigintMode"]

logger = logging.getLogger(__name__)


class SignalManager:
    """信号管理器。

    管理 SIGINT 和 SIGTERM 信号的处理，实现信号隔离策略：
    - 将 SIGINT 转换为"取消活动请求"操作
    - 将 SIGTERM 转换为"优雅退出"操作

    Example:
        ```python
        registry = RequestRegistry()
        signal_manager = SignalManager(registry)

        async def main():
            await signal_manager.start()
            try:
                # 运行服务器...
                await server.run()
            finally:
                await signal_manager.stop()

        asyncio.run(main())
        ```

    Attributes:
        registry: 请求注册表
        sigint_mode: SIGINT 处理模式
        double_tap_window: 双击退出窗口时间（秒）
    """

    def __init__(
        self,
        registry: RequestRegistry,
        sigint_mode: Optional[SigintMode] = None,
        double_tap_window: Optional[float] = None,
        on_shutdown: Optional[Callable[[], None]] = None,
    ) -> None:
        """初始化信号管理器。

        Args:
            registry: 请求注册表
            sigint_mode: SIGINT 处理模式（默认从配置读取）
            double_tap_window: 双击退出窗口时间（默认从配置读取）
            on_shutdown: 关闭时的回调函数
        """
        self.registry = registry

        # 从配置读取默认值
        config = get_config()
        self.sigint_mode = sigint_mode if sigint_mode is not None else config.sigint_mode
        self.double_tap_window = (
            double_tap_window if double_tap_window is not None else config.sigint_double_tap_window
        )
        self._on_shutdown = on_shutdown

        # 内部状态
        self._last_sigint_time: float = 0.0
        self._shutdown_requested: bool = False
        self._force_exit: bool = False  # 双击 SIGINT 触发的强制退出标志
        self._shutdown_event: Optional[asyncio.Event] = None
        self._original_sigint_handler: Optional[signal.Handlers] = None
        self._original_sigterm_handler: Optional[signal.Handlers] = None
        self._running: bool = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def is_shutdown_requested(self) -> bool:
        """是否已请求关闭。"""
        return self._shutdown_requested

    @property
    def is_force_exit(self) -> bool:
        """是否请求强制退出（双击 SIGINT）。"""
        return self._force_exit

    async def start(self) -> None:
        """启动信号监听。

        设置 SIGINT 和 SIGTERM 的处理器。
        必须在 asyncio 事件循环中调用。
        """
        if self._running:
            logger.warning("SignalManager already running")
            return

        self._loop = asyncio.get_running_loop()
        self._shutdown_event = asyncio.Event()
        self._running = True

        # 在 POSIX 系统上设置信号处理器
        if sys.platform != "win32":
            # 保存原始处理器
            self._original_sigint_handler = signal.getsignal(signal.SIGINT)
            self._original_sigterm_handler = signal.getsignal(signal.SIGTERM)

            # 设置新处理器（使用 loop.add_signal_handler）
            self._loop.add_signal_handler(
                signal.SIGINT,
                self._handle_sigint,
            )
            self._loop.add_signal_handler(
                signal.SIGTERM,
                self._handle_sigterm,
            )
            logger.debug(
                f"Signal handlers installed (mode={self.sigint_mode.value}, "
                f"double_tap_window={self.double_tap_window}s)"
            )
        else:
            # Windows: 使用 signal.signal() 设置处理器
            self._original_sigint_handler = signal.signal(
                signal.SIGINT,
                lambda sig, frame: self._handle_sigint(),
            )
            logger.debug(
                f"SIGINT handler installed on Windows (mode={self.sigint_mode.value})"
            )

    async def stop(self) -> None:
        """停止信号监听。

        恢复原始信号处理器。
        """
        if not self._running:
            return

        self._running = False

        # 恢复原始处理器
        if sys.platform != "win32" and self._loop:
            try:
                self._loop.remove_signal_handler(signal.SIGINT)
                self._loop.remove_signal_handler(signal.SIGTERM)
            except Exception as e:
                logger.debug(f"Error removing signal handlers: {e}")
        elif sys.platform == "win32" and self._original_sigint_handler is not None:
            try:
                signal.signal(signal.SIGINT, self._original_sigint_handler)
            except Exception as e:
                logger.debug(f"Error restoring SIGINT handler: {e}")

        logger.debug("Signal handlers removed")

    async def wait_for_shutdown(self) -> None:
        """等待关闭信号。

        在收到 SIGTERM 或满足退出条件的 SIGINT 后返回。
        """
        if self._shutdown_event:
            await self._shutdown_event.wait()

    def _handle_sigint(self) -> None:
        """处理 SIGINT 信号。

        根据配置的模式和当前状态决定行为：
        - 如果有活动请求：取消请求
        - 如果没有活动请求或模式为 EXIT：请求关闭
        - 如果在双击窗口内再次收到 SIGINT：强制退出
        """
        current_time = time.time()
        time_since_last = current_time - self._last_sigint_time
        self._last_sigint_time = current_time

        # 检查双击退出
        if time_since_last < self.double_tap_window and self._shutdown_requested:
            logger.warning("Double SIGINT detected, forcing shutdown")
            self._force_shutdown()
            return

        # 根据模式处理
        if self.sigint_mode == SigintMode.EXIT:
            # 直接退出模式
            logger.info("SIGINT received (mode=exit), requesting shutdown")
            self._request_shutdown()

        elif self.sigint_mode == SigintMode.CANCEL:
            # 取消模式：有活动请求则取消，否则退出
            if self.registry.has_active_requests():
                count = self.registry.cancel_all()
                logger.info(
                    f"SIGINT received (mode=cancel), cancelled {count} request(s)"
                )
            else:
                logger.info(
                    "SIGINT received (mode=cancel), no active requests, requesting shutdown"
                )
                self._request_shutdown()

        elif self.sigint_mode == SigintMode.CANCEL_THEN_EXIT:
            # 先取消后退出模式
            if self.registry.has_active_requests():
                count = self.registry.cancel_all()
                logger.info(
                    f"SIGINT received (mode=cancel_then_exit), cancelled {count} request(s). "
                    f"Press Ctrl+C again within {self.double_tap_window}s to exit."
                )
                # 标记为已请求关闭，但不触发实际关闭
                self._shutdown_requested = True
            else:
                logger.info(
                    "SIGINT received (mode=cancel_then_exit), no active requests, requesting shutdown"
                )
                self._request_shutdown()

    def _handle_sigterm(self) -> None:
        """处理 SIGTERM 信号。

        始终进入优雅退出流程：取消所有请求并请求关闭。
        """
        logger.info("SIGTERM received, initiating graceful shutdown")

        # 取消所有活动请求
        if self.registry.has_active_requests():
            count = self.registry.cancel_all()
            logger.info(f"Cancelled {count} active request(s) for shutdown")

        self._request_shutdown()

    def _request_shutdown(self) -> None:
        """请求关闭。"""
        self._shutdown_requested = True

        # 调用关闭回调
        if self._on_shutdown:
            try:
                self._on_shutdown()
            except Exception as e:
                logger.warning(f"Error in shutdown callback: {e}")

        # 设置关闭事件
        if self._shutdown_event and self._loop:
            self._loop.call_soon_threadsafe(self._shutdown_event.set)

    def _force_shutdown(self) -> None:
        """强制退出。

        设置 force_exit 标志并触发 shutdown event。
        实际的进程退出由 run_server() 在清理完成后执行。
        """
        logger.warning("Forcing immediate shutdown")
        self._force_exit = True
        self._shutdown_requested = True

        # 取消所有活动请求
        if self.registry.has_active_requests():
            count = self.registry.cancel_all()
            logger.info(f"Force shutdown: cancelled {count} request(s)")

        # 调用关闭回调
        if self._on_shutdown:
            try:
                self._on_shutdown()
            except Exception as e:
                logger.warning(f"Error in shutdown callback: {e}")

        # 设置 shutdown event（让主循环有机会清理后退出）
        if self._shutdown_event and self._loop:
            self._loop.call_soon_threadsafe(self._shutdown_event.set)

    def request_graceful_shutdown(self) -> None:
        """程序化请求优雅退出。

        可以从代码中调用以触发关闭流程。
        """
        logger.info("Programmatic shutdown requested")

        # 取消所有活动请求
        if self.registry.has_active_requests():
            count = self.registry.cancel_all()
            logger.info(f"Cancelled {count} active request(s)")

        self._request_shutdown()
