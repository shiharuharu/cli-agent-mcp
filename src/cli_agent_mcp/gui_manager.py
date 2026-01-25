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
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse

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

    # 心跳（Windows 兜底：用于检测主进程异常退出）
    heartbeat_interval: float = 2.0
    heartbeat_timeout: float = 10.0

    # 回调
    on_restart: Callable[[], None] | None = None  # 重启时的回调（用于重发 LOG_DEBUG 通知）


def _gui_process_entry(
    event_queue: mp.Queue,
    shutdown_event: mp.Event,
    startup_complete: mp.Event,
    heartbeat_queue: mp.Queue | None,  # Windows 兜底心跳；None 表示禁用
    url_queue: mp.Queue,  # 用于传回 GUI URL
    config_dict: dict,
) -> None:
    """GUI 子进程入口。

    职责：
    1. 创建并运行 GUI 窗口
    2. 监听 shutdown_event
    3. 检测主进程是否退出（macOS/Linux: PPID；Windows: 心跳兜底）
    """
    try:
        from cli_agent_mcp.shared.gui import LiveViewer, ViewerConfig
    except ImportError:
        logger.error("Failed to import GUI module")
        return

    title = config_dict.get("title", "CLI Agent MCP")
    detail_mode = config_dict.get("detail_mode", False)
    heartbeat_timeout = config_dict.get("heartbeat_timeout", 10.0)
    keep_on_exit = bool(config_dict.get("keep_on_exit", False))
    watch_parent = not keep_on_exit
    initial_ppid = os.getppid()

    preferred_port = config_dict.get("port")
    if preferred_port:
        os.environ["CAM_GUI_PORT"] = str(preferred_port)

    # 创建 viewer
    viewer = LiveViewer(ViewerConfig(title=title, multi_source_mode=True))

    # URL 回调：HTTP server 启动后立即回传（不等 loaded 事件）
    def send_url_callback(url: str):
        try:
            url_queue.put_nowait(url)
            logger.info(f"GUI URL: {url}")
        except Exception:
            pass

    viewer._url_callback = send_url_callback

    # 状态
    should_exit = threading.Event()

    # Windows 心跳兜底（避免 PID 复用/PPID 语义差异）
    use_heartbeat_watchdog = watch_parent and sys.platform == "win32" and heartbeat_queue is not None
    last_heartbeat = time.monotonic()

    def update_heartbeat() -> None:
        nonlocal last_heartbeat
        last_heartbeat = time.monotonic()

    def check_heartbeat_timeout() -> bool:
        return (time.monotonic() - last_heartbeat) > heartbeat_timeout

    def parent_exited_posix() -> bool:
        """POSIX: 通过 PPID 变化 + kill(0) 判定父进程是否退出。"""
        if os.getppid() != initial_ppid:
            return True
        try:
            os.kill(initial_ppid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            # 没权限但进程存在：视为仍存活
            return False
        return False

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

            # keep_on_exit=True 时禁用父进程退出监控（GUI 常驻）
            if watch_parent:
                # macOS/Linux：优先用 PPID 判定父进程是否退出
                if os.name == "posix":
                    if parent_exited_posix():
                        logger.warning(
                            "Parent process appears to have exited "
                            f"(initial_ppid={initial_ppid}, current_ppid={os.getppid()})"
                        )
                        should_exit.set()
                        viewer.close()
                        return
                else:
                    # 非 POSIX：尽力而为（Windows 下通常依赖心跳兜底）
                    if os.getppid() != initial_ppid:
                        logger.warning(
                            "Parent process appears to have changed "
                            f"(initial_ppid={initial_ppid}, current_ppid={os.getppid()})"
                        )
                        should_exit.set()
                        viewer.close()
                        return

            # Windows：保留心跳兜底
            if use_heartbeat_watchdog:
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
        self._stable_port: int | None = None  # best-effort port reuse across GUI restarts

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
                self._heartbeat_queue = (
                    mp.Queue(maxsize=10)
                    if (sys.platform == "win32" and not self.config.keep_on_exit)
                    else None
                )
                self._url_queue = mp.Queue(maxsize=1)
                self._shutdown_event = mp.Event()
                self._startup_complete = mp.Event()

                # 启动 GUI 进程
                if not self._spawn_gui():
                    logger.warning("Failed to start GUI")
                    return

                # 启动心跳线程（仅 Windows 兜底）
                if self._heartbeat_queue is not None:
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
            env_port = 0
            try:
                env_port = int(os.environ.get("CAM_GUI_PORT") or "0")
            except ValueError:
                env_port = 0

            config_dict = {
                "title": self.config.title,
                "detail_mode": self.config.detail_mode,
                "heartbeat_timeout": self.config.heartbeat_timeout,
                "keep_on_exit": self.config.keep_on_exit,
            }
            if env_port <= 0 and self._stable_port:
                config_dict["port"] = self._stable_port

            # heartbeat_queue 仅用于 Windows 兜底；keep_on_exit 时为 None
            heartbeat_queue = self._heartbeat_queue

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

            if self._url and env_port <= 0:
                try:
                    parsed = urlparse(self._url)
                    if parsed.port:
                        self._stable_port = parsed.port
                except Exception:
                    pass

            watchdog = "none" if self.config.keep_on_exit else ("heartbeat" if sys.platform == "win32" else "ppid")
            logger.info(
                f"GUI process started (PID: {self._process.pid}, URL: {self._url}, watchdog={watchdog})"
            )
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
        self._heartbeat_queue = (
            mp.Queue(maxsize=10)
            if (sys.platform == "win32" and not self.config.keep_on_exit)
            else None
        )
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
