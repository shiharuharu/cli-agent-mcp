"""GUI 进程管理器（重构版）。

设计目标：
1. 单例保证 - 单个 MCP 进程只启动一个 GUI
2. 手滑恢复 - 用户关闭窗口后自动重开
3. LOG_DEBUG - 重启后重发日志路径通知
4. KEEP_GUI - 主进程退出时可选保留 GUI

架构：
- daemon=False: 子进程不随主进程自动死亡，便于 KEEP_GUI 支持
- atexit: 正常退出时优雅清理
- Event: 简化的进程间信号通信
- 启动保护期: 防止竞态导致的双实例
"""

from __future__ import annotations

import atexit
import logging
import multiprocessing as mp
import os
import queue
import signal
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

__all__ = ["GUIManager", "GUIConfig"]

logger = logging.getLogger(__name__)


@dataclass
class GUIConfig:
    """GUI 配置。"""

    title: str = "CLI Agent MCP"
    detail_mode: bool = False
    keep_on_exit: bool = False  # 主进程退出时是否保留 GUI

    # 重启相关
    restart_delay: float = 0.5  # 重启前延迟
    startup_grace_period: float = 3.0  # 启动保护期（秒）- 此期间内不允许重启
    max_restart_attempts: int = 5  # 最大连续重启次数
    restart_window: float = 60.0  # 重启计数窗口（秒）
    initial_delay: float = 3.0  # 首次启动延迟（秒）- 规避调度器问题

    # 心跳（仅用于检测主进程被 SIGKILL）
    heartbeat_interval: float = 2.0
    heartbeat_timeout: float = 10.0

    # 回调
    on_restart: Callable[[], None] | None = None  # 重启时的回调（用于重发 LOG_DEBUG 通知）


def _gui_process_entry(
    event_queue: mp.Queue,
    shutdown_event: mp.Event,
    startup_complete: mp.Event,
    heartbeat_queue: mp.Queue | None,  # None 表示禁用心跳检测 (KEEP_GUI=true)
    url_queue: mp.Queue,  # 用于传回 GUI URL
    config_dict: dict,
) -> None:
    """GUI 子进程入口。

    职责：
    1. 创建并运行 GUI 窗口
    2. 监听 shutdown_event
    3. 如果启用心跳，检测主进程异常退出
    """
    import sys
    from pathlib import Path

    # 添加 shared 路径
    shared_path = Path(__file__).parent / "shared"
    if shared_path.exists() and str(shared_path) not in sys.path:
        sys.path.insert(0, str(shared_path))

    try:
        from gui import LiveViewer, ViewerConfig
    except ImportError:
        logger.error("Failed to import GUI module")
        return

    title = config_dict.get("title", "CLI Agent MCP")
    detail_mode = config_dict.get("detail_mode", False)
    heartbeat_timeout = config_dict.get("heartbeat_timeout", 10.0)
    heartbeat_enabled = heartbeat_queue is not None

    # 创建 viewer
    viewer = LiveViewer(ViewerConfig(title=title, multi_source_mode=True))

    # 启动后传回 URL（在 viewer.start() 之前设置回调）
    def send_url_on_start():
        if viewer.url:
            try:
                url_queue.put_nowait(viewer.url)
                logger.info(f"GUI URL: {viewer.url}")
            except Exception:
                pass

    # 注册启动回调
    original_started_set = viewer._started.set
    def started_set_with_url():
        original_started_set()
        send_url_on_start()
    viewer._started.set = started_set_with_url

    # 状态
    should_exit = threading.Event()
    last_heartbeat = time.time()
    heartbeat_lock = threading.Lock()

    def update_heartbeat():
        nonlocal last_heartbeat
        with heartbeat_lock:
            last_heartbeat = time.time()

    def check_heartbeat_timeout() -> bool:
        with heartbeat_lock:
            return (time.time() - last_heartbeat) > heartbeat_timeout

    # 事件轮询线程
    def poll_events():
        while not should_exit.is_set() and not viewer._closed.is_set():
            try:
                event = event_queue.get(timeout=0.1)
                if event is None:  # 停止信号
                    should_exit.set()
                    viewer.close()
                    return
                if detail_mode:
                    event["_detail_mode"] = True
                viewer.push_event(event)
            except queue.Empty:
                continue
            except Exception as e:
                logger.debug(f"Poll error: {e}")

    # 监控线程：检查 shutdown_event 和心跳
    def monitor():
        while not should_exit.is_set() and not viewer._closed.is_set():
            # 检查 shutdown_event（优雅关闭信号）
            if shutdown_event.is_set():
                logger.debug("Shutdown event received")
                should_exit.set()
                viewer.close()
                return

            # 检查心跳（仅当启用时）
            if heartbeat_enabled:
                try:
                    heartbeat_queue.get(timeout=0.5)
                    update_heartbeat()
                except queue.Empty:
                    if check_heartbeat_timeout():
                        logger.warning("Heartbeat timeout, main process may have died")
                        should_exit.set()
                        viewer.close()
                        return
            else:
                # 心跳禁用时，只检查 shutdown_event
                time.sleep(0.5)

    # 启动工作线程
    poll_thread = threading.Thread(target=poll_events, daemon=True)
    monitor_thread = threading.Thread(target=monitor, daemon=True)
    poll_thread.start()
    monitor_thread.start()

    # 通知主进程启动完成
    startup_complete.set()

    # 运行 GUI（阻塞）
    viewer.start(blocking=True)

    # GUI 关闭，设置退出标志
    should_exit.set()
    logger.debug("GUI process exiting")


class GUIManager:
    """GUI 进程管理器。

    Example:
        manager = GUIManager(GUIConfig(title="My App"))
        manager.start()
        manager.push_event({"category": "message", ...})
        # 程序退出时自动清理（或调用 stop()）
    """

    # 类级别的实例追踪（用于 atexit 清理）
    _instances: list["GUIManager"] = []
    _atexit_registered = False

    def __init__(self, config: GUIConfig | None = None) -> None:
        self.config = config or GUIConfig()

        # 进程和队列
        self._process: mp.Process | None = None
        self._event_queue: mp.Queue | None = None
        self._heartbeat_queue: mp.Queue | None = None
        self._url_queue: mp.Queue | None = None
        self._shutdown_event: mp.Event | None = None
        self._startup_complete: mp.Event | None = None

        # GUI URL
        self._url: str | None = None

        # 状态
        self._running = False
        self._should_restart = True
        self._restart_count = 0
        self._last_restart_time = 0.0
        self._startup_time = 0.0  # 启动保护期计算用

        # 线程
        self._heartbeat_thread: threading.Thread | None = None
        self._monitor_thread: threading.Thread | None = None

        # 锁
        self._lock = threading.Lock()

        # 注册 atexit（只注册一次）
        self._register_atexit()
        GUIManager._instances.append(self)

    @classmethod
    def _register_atexit(cls) -> None:
        """注册全局 atexit 清理函数。"""
        if not cls._atexit_registered:
            atexit.register(cls._cleanup_all)
            cls._atexit_registered = True

    @classmethod
    def _cleanup_all(cls) -> None:
        """清理所有实例（atexit 回调）。"""
        for instance in cls._instances:
            try:
                instance.stop()
            except Exception as e:
                logger.debug(f"Cleanup error: {e}")

    def start(self) -> bool:
        """启动 GUI（异步，不阻塞 MCP 服务器）。

        Returns:
            是否成功启动（立即返回 True，GUI 在后台延迟启动）
        """
        with self._lock:
            if self._running:
                return True

            self._running = True
            self._should_restart = True
            self._restart_count = 0
            self._startup_time = time.time()

            # 在后台线程中延迟启动 GUI（不阻塞 MCP 服务器）
            def delayed_start():
                if self.config.initial_delay > 0:
                    logger.info(f"GUI will start in {self.config.initial_delay}s...")
                    time.sleep(self.config.initial_delay)

                if not self._running:
                    return  # 可能在延迟期间被 stop()

                # 创建 IPC 资源
                self._event_queue = mp.Queue(maxsize=5000)
                self._heartbeat_queue = mp.Queue(maxsize=10)
                self._url_queue = mp.Queue(maxsize=1)
                self._shutdown_event = mp.Event()
                self._startup_complete = mp.Event()

                # 启动 GUI 进程
                if not self._spawn_gui():
                    logger.warning("Failed to start GUI")
                    return

                # 启动心跳线程
                self._heartbeat_thread = threading.Thread(
                    target=self._heartbeat_loop, daemon=True, name="gui_heartbeat"
                )
                self._heartbeat_thread.start()

                # 启动监控线程
                self._monitor_thread = threading.Thread(
                    target=self._monitor_loop, daemon=True, name="gui_monitor"
                )
                self._monitor_thread.start()

                logger.info("GUI Manager started")

                # GUI 启动完成后调用回调（首次启动也需要）
                if self.config.on_restart:
                    try:
                        self.config.on_restart()
                    except Exception as e:
                        logger.debug(f"Startup callback error: {e}")

            # 启动后台线程
            threading.Thread(target=delayed_start, daemon=True, name="gui_delayed_start").start()

            return True

    def _spawn_gui(self) -> bool:
        """创建并启动 GUI 子进程。"""
        try:
            config_dict = {
                "title": self.config.title,
                "detail_mode": self.config.detail_mode,
                "heartbeat_timeout": self.config.heartbeat_timeout,
            }

            # KEEP_GUI=true 时禁用心跳检测，GUI 不会因心跳超时而关闭
            heartbeat_queue = None if self.config.keep_on_exit else self._heartbeat_queue

            # daemon=True: 默认随主进程退出（避免进程驻留）
            # daemon=False: keep_on_exit 时保留 GUI
            self._process = mp.Process(
                target=_gui_process_entry,
                args=(
                    self._event_queue,
                    self._shutdown_event,
                    self._startup_complete,
                    heartbeat_queue,
                    self._url_queue,
                    config_dict,
                ),
                daemon=not self.config.keep_on_exit,
                name="gui_process",
            )
            self._process.start()

            # 等待启动完成
            if not self._startup_complete.wait(timeout=10):
                logger.error("GUI startup timeout")
                self._terminate_process()
                return False

            # 获取 GUI URL
            try:
                self._url = self._url_queue.get(timeout=2)
                logger.debug(f"GUI URL received: {self._url}")
            except queue.Empty:
                logger.warning("Failed to get GUI URL")

            logger.info(f"GUI process started (PID: {self._process.pid}, URL: {self._url}, heartbeat={'disabled' if self.config.keep_on_exit else 'enabled'})")
            return True

        except Exception as e:
            logger.exception(f"Failed to spawn GUI: {e}")
            return False

    def _heartbeat_loop(self) -> None:
        """心跳发送循环。"""
        while self._running:
            if self._heartbeat_queue is None:
                break
            try:
                self._heartbeat_queue.put_nowait(time.time())
            except queue.Full:
                pass  # GUI 没在消费，可能已关闭
            except Exception:
                break
            time.sleep(self.config.heartbeat_interval)

    def _monitor_loop(self) -> None:
        """监控 GUI 进程状态，处理重启。"""
        # 等待启动保护期结束
        grace_remaining = self.config.startup_grace_period - (time.time() - self._startup_time)
        if grace_remaining > 0:
            logger.debug(f"Waiting {grace_remaining:.1f}s startup grace period")
            time.sleep(grace_remaining)

        while self._running:
            try:
                # 检查进程是否存活
                if self._process and not self._process.is_alive():
                    exit_code = self._process.exitcode
                    logger.info(f"GUI process exited (code: {exit_code})")

                    if self._should_restart and self._running:
                        self._handle_restart()
                    else:
                        break

                time.sleep(0.5)

            except Exception as e:
                logger.debug(f"Monitor error: {e}")
                time.sleep(1)

    def _handle_restart(self) -> None:
        """处理 GUI 重启。"""
        current_time = time.time()

        # 重置重启计数（如果超过窗口时间）
        if current_time - self._last_restart_time > self.config.restart_window:
            self._restart_count = 0

        self._restart_count += 1
        self._last_restart_time = current_time

        # 检查重启次数限制
        if self._restart_count > self.config.max_restart_attempts:
            logger.error(f"Max restart attempts ({self.config.max_restart_attempts}) reached")
            self._should_restart = False
            return

        logger.info(f"Restarting GUI ({self._restart_count}/{self.config.max_restart_attempts})...")

        # 延迟重启
        time.sleep(self.config.restart_delay)

        # 清理旧进程
        self._terminate_process()

        # 重建 IPC 资源（旧的可能已损坏）
        self._event_queue = mp.Queue(maxsize=5000)
        self._heartbeat_queue = mp.Queue(maxsize=10)
        self._url_queue = mp.Queue(maxsize=1)
        self._shutdown_event = mp.Event()
        self._startup_complete = mp.Event()

        # 启动新进程
        if self._spawn_gui():
            # 重启成功，调用回调（用于重发 LOG_DEBUG 通知等）
            if self.config.on_restart:
                try:
                    self.config.on_restart()
                except Exception as e:
                    logger.debug(f"Restart callback error: {e}")

    def _terminate_process(self) -> None:
        """终止 GUI 进程。"""
        if self._process is None:
            return

        try:
            if self._process.is_alive():
                # 先尝试优雅关闭
                if self._shutdown_event:
                    self._shutdown_event.set()
                if self._event_queue:
                    try:
                        self._event_queue.put_nowait(None)
                    except Exception:
                        pass

                # 等待优雅退出
                self._process.join(timeout=2)

                # 如果还没退出，强制终止
                if self._process.is_alive():
                    logger.debug("Force terminating GUI process")
                    self._process.terminate()
                    self._process.join(timeout=1)

                    if self._process.is_alive():
                        self._process.kill()
                        self._process.join(timeout=1)
        except Exception as e:
            logger.debug(f"Terminate error: {e}")
        finally:
            self._process = None

    def stop(self) -> None:
        """停止 GUI 管理器。"""
        with self._lock:
            if not self._running:
                return

            self._should_restart = False
            self._running = False

            # 如果配置了保留 GUI，不终止进程
            if self.config.keep_on_exit:
                logger.info("GUI Manager stopped (GUI window kept alive)")
                # 清空心跳队列，GUI 会因心跳超时自行关闭（如果需要）
                return

            # 终止进程
            self._terminate_process()
            logger.info("GUI Manager stopped")

    def push_event(self, event: dict[str, Any]) -> bool:
        """推送事件到 GUI。"""
        if not self._running or self._event_queue is None:
            return False
        try:
            self._event_queue.put_nowait(event)
            return True
        except queue.Full:
            logger.warning("GUI event queue full")
            return False
        except Exception:
            return False

    @property
    def is_running(self) -> bool:
        """GUI 是否正在运行。"""
        return (
            self._running
            and self._process is not None
            and self._process.is_alive()
        )

    @property
    def url(self) -> str | None:
        """获取 GUI URL。"""
        return self._url
