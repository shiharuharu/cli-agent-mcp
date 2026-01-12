"""CLI Agent MCP 应用入口。

包含服务器生命周期管理和主入口点。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
import time

from .config import get_config
from .gui_manager import GUIConfig, GUIManager
from .orchestrator import RequestRegistry
from .signal_manager import SignalManager
from .server import create_server

__all__ = ["run_server", "main"]

logger = logging.getLogger(__name__)


async def run_server() -> None:
    """运行 MCP Server。

    启动 MCP 服务器，并集成信号管理器以支持：
    - SIGINT: 取消活动请求（而不是直接退出）
    - SIGTERM: 优雅退出

    使用并发任务架构：
    - server_task: 运行 MCP server
    - shutdown_watcher: 监听 shutdown 事件并取消 server_task
    """
    config = get_config()
    logger.info(f"Starting CLI Agent MCP Server (FastMCP): {config}")

    # 创建请求注册表和信号管理器
    registry = RequestRegistry()
    gui_manager = None
    signal_manager = None
    server_task: asyncio.Task | None = None
    shutdown_watcher: asyncio.Task | None = None

    # 启动 GUI（如果启用）
    if config.gui_enabled:
        # 创建日志通知推送函数（用于首次启动和重启时）
        def push_log_debug_notice():
            if gui_manager:
                # 推送 GUI URL
                if gui_manager.url:
                    logger.debug(f"GUI URL: {gui_manager.url}")
                    gui_manager.push_event({
                        "category": "system",
                        "source": "server",
                        "message": f"GUI URL: {gui_manager.url}",
                        "severity": "info",
                        "content_type": "text",
                        "timestamp": time.time(),
                        "raw": {"type": "system", "subtype": "gui_url", "url": gui_manager.url},
                    })
                # 推送日志路径
                if config.log_debug and config.log_file:
                    gui_manager.push_event({
                        "category": "system",
                        "source": "server",
                        "message": f"Debug log: {config.log_file}",
                        "severity": "info",
                        "content_type": "text",
                        "timestamp": time.time(),
                        "raw": {"type": "system", "subtype": "log_path", "path": config.log_file},
                    })

        gui_manager = GUIManager(
            GUIConfig(
                title="CLI Agent MCP",
                detail_mode=config.gui_detail,
                keep_on_exit=config.gui_keep,
                on_restart=push_log_debug_notice,  # GUI 启动/重启时自动调用
            )
        )
        if gui_manager.start():
            logger.info("GUI starting in background...")
            # 注意：日志通知由 on_restart 回调在 GUI 真正启动后自动发送
        else:
            logger.warning("Failed to start GUI, continuing without it")
            gui_manager = None

    # 创建关闭回调
    def on_shutdown():
        """信号管理器触发的关闭回调。"""
        logger.info("Shutdown callback triggered")
        if gui_manager:
            gui_manager.stop()
        # 关闭 stdin 以中断 stdio_server 的阻塞读取
        # 这是让进程能够正常退出的关键
        try:
            sys.stdin.close()
            logger.debug("stdin closed to unblock stdio_server")
        except Exception as e:
            logger.debug(f"Error closing stdin: {e}")

    # 创建信号管理器
    signal_manager = SignalManager(
        registry=registry,
        on_shutdown=on_shutdown,
    )

    # 创建 FastMCP server
    mcp = create_server(gui_manager, registry)

    # 定义 server 运行协程
    async def _run_server_impl():
        """运行 FastMCP server 的内部实现。"""
        logger.debug("Starting FastMCP server with stdio transport")
        await mcp.run_stdio_async()
        logger.debug("FastMCP server completed normally")

    # 定义 shutdown 监听协程
    async def _watch_shutdown():
        """监听 shutdown 事件并取消 server task。"""
        await signal_manager.wait_for_shutdown()
        logger.info("Shutdown signal received, cancelling server task...")
        if server_task and not server_task.done():
            server_task.cancel()

    try:
        # 启动信号管理器
        await signal_manager.start()
        logger.info(
            f"Signal manager started (mode={signal_manager.sigint_mode.value}, "
            f"double_tap_window={signal_manager.double_tap_window}s)"
        )

        # 创建并发任务
        server_task = asyncio.create_task(_run_server_impl(), name="mcp-server")
        shutdown_watcher = asyncio.create_task(_watch_shutdown(), name="shutdown-watcher")

        # 等待 server 任务完成（正常退出或被取消）
        try:
            await server_task
        except asyncio.CancelledError:
            logger.info("Server task cancelled by shutdown signal")

    except asyncio.CancelledError:
        logger.info("run_server: asyncio.CancelledError caught")
        raise

    except BaseException as e:
        logger.error(
            f"run_server: BaseException caught: type={type(e).__name__}, "
            f"msg={e}"
        )
        raise

    finally:
        logger.info("run_server: entering finally block")

        # 清理 shutdown watcher
        if shutdown_watcher and not shutdown_watcher.done():
            shutdown_watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await shutdown_watcher

        # 停止信号管理器
        if signal_manager:
            await signal_manager.stop()

        # 停止 GUI
        if gui_manager:
            gui_manager.stop()

        logger.info("run_server: cleanup completed")

        # 检查是否需要强制退出（双击 SIGINT）
        if signal_manager and signal_manager.is_force_exit:
            logger.warning("Force exit requested, terminating with exit code 130")
            sys.exit(130)  # 128 + SIGINT(2) = 130


def main() -> None:
    """主入口点。"""
    config = get_config()

    # 配置日志输出
    log_handlers: list[logging.Handler] = []

    if config.log_debug and config.log_file:
        # LOG_DEBUG 模式：输出到临时文件
        file_handler = logging.FileHandler(config.log_file, encoding="utf-8")

        # 自定义格式化器：尝试将对象 JSON 序列化
        class JsonSerializingFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                # 尝试序列化 args 中的对象
                if record.args:
                    import json
                    new_args = []
                    for arg in record.args:
                        try:
                            if hasattr(arg, "model_dump"):
                                # Pydantic 模型
                                new_args.append(json.dumps(arg.model_dump(), ensure_ascii=False))
                            elif hasattr(arg, "__dict__") and not isinstance(arg, (str, int, float, bool, type(None))):
                                # 普通对象
                                new_args.append(json.dumps(vars(arg), ensure_ascii=False, default=str))
                            elif isinstance(arg, dict):
                                new_args.append(json.dumps(arg, ensure_ascii=False, default=str))
                            else:
                                new_args.append(arg)
                        except Exception:
                            new_args.append(arg)
                    record.args = tuple(new_args)
                return super().format(record)

        file_handler.setFormatter(JsonSerializingFormatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
        log_handlers.append(file_handler)
        log_level = logging.DEBUG
    else:
        # 默认模式：输出到 stderr
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        log_handlers.append(stderr_handler)
        log_level = logging.INFO

    # 配置 root logger（第三方库）为 WARNING，减少噪音
    logging.basicConfig(
        level=logging.WARNING,
        handlers=log_handlers,
    )
    # 只对 cli_agent_mcp 命名空间启用详细日志
    logging.getLogger("cli_agent_mcp").setLevel(log_level)

    asyncio.run(run_server())


if __name__ == "__main__":
    main()
