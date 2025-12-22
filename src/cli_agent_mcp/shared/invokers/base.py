"""CLI 调用器抽象基类。

cli-agent-mcp shared/mcp v0.1.0
同步日期: 2025-12-17

提供 CLI 子进程管理、输出流解析、事件回调等基础功能。

重构说明（请求上下文隔离）：
- ExecutionContext: 持有 per-request 的执行态
- CLIInvoker: 每次 execute() 创建新的上下文，确保请求间状态隔离

新增功能（致命错误检测）：
- _FATAL_ERROR_PATTERNS: 致命错误模式列表，子类可扩展
- _check_stderr_line_for_fatal_error(): stderr 实时错误检测
- 检测到致命错误时自动终止进程，避免死锁
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable

from .types import (
    CLIType,
    CommonParams,
    DebugInfo,
    ExecutionResult,
    GUIMetadata,
)

if TYPE_CHECKING:
    from ..parsers import UnifiedEvent

__all__ = [
    "CLIInvoker",
    "EventCallback",
    "ExecutionContext",
]

# 类型别名：事件回调函数
EventCallback = Callable[["UnifiedEvent"], None]

logger = logging.getLogger(__name__)


@dataclass
class ExecutionContext:
    """执行上下文 - 持有 per-request 的执行态。

    每次请求创建新的 ExecutionContext，确保请求间状态隔离。
    这是解决并发/取消时状态互相污染问题的核心。

    Attributes:
        process: 当前子进程引用
        session_id: 从事件流中提取的会话 ID
        collected_messages: 收集的原始消息
        agent_messages: 过程中的 assistant 消息（不含 reasoning）
        final_answer: 最终答案（最后一条 agent_message）
        exit_error: 非零退出码的错误信息
        captured_errors: 捕获的非 JSON 错误信息
        debug_info: 调试统计信息
    """
    # 进程引用
    process: asyncio.subprocess.Process | None = None

    # 会话状态
    session_id: str = ""

    # 消息收集
    collected_messages: list[dict[str, Any]] = field(default_factory=list)
    agent_messages: list[str] = field(default_factory=list)
    final_answer: str = ""

    # 错误状态
    exit_error: str | None = None
    captured_errors: list[str] = field(default_factory=list)

    # 调试信息
    debug_info: DebugInfo = field(default_factory=DebugInfo)


class CLIInvoker(ABC):
    """CLI 调用器抽象基类。

    子类需要实现：
    - cli_type: CLI 类型属性
    - build_command(): 构建 CLI 命令行
    - parse_line(): 解析单行输出（可选，默认使用 parsers 模块）

    使用示例:
        invoker = CodexInvoker()
        result = await invoker.execute(params)

        # 或者使用事件流
        async for event in invoker.stream(params):
            gui.push_event(event)

    重构说明（请求上下文隔离）：
    - 执行态字段已迁移到 ExecutionContext
    - 每次 execute() 创建新的上下文，确保请求间状态隔离
    - event_callback 和 parser 是配置，可以保留在 invoker 上
    """

    # 非 JSON 行中的错误模式（用于提取有用信息）
    _ERROR_PATTERNS = [
        # Gemini API 重试错误
        (r"Attempt \d+ failed with status (\d+)\. .* ApiError: (.+)", "api_error"),
        # 工具执行错误
        (r"Error executing tool (\w+): (.+)", "tool_error"),
        # 通用错误堆栈起始
        (r"ApiError: (.+)", "api_error"),
        # OpenCode/Bun 错误 (TypeScript runtime errors)
        (r"(\w+Error): (.+)", "runtime_error"),
        # Node.js/Bun 抛出的错误
        (r"^\s*throw\s+", "throw_error"),
        # 堆栈跟踪起始
        (r"^\s+at\s+.+\(.+:\d+:\d+\)", "stack_trace"),
        # OpenCode 特有：数字 | 开头的源码行
        (r"^\d+\s*\|", "source_line"),
        # OpenCode 特有：^ 指示错误位置
        (r"^\s+\^", "error_pointer"),
    ]

    # 致命错误模式 - 匹配到这些模式时立即终止进程
    # 这些错误表明 CLI 进入了无法恢复的状态（如无限重试循环）
    # 子类可以通过覆盖此属性来添加 CLI 特有的致命错误模式
    _FATAL_ERROR_PATTERNS: list[str] = [
        # Gemini: 无效的会话 ID（会触发无限重试循环）
        r"Error resuming session: Invalid session identifier",
        # Gemini: 会话相关错误
        r"Error resuming session:",
        # 通用：致命错误标识
        r"FATAL(?:\s+ERROR)?:",
        # 权限/认证错误（通常无法恢复）
        r"(?:Authentication|Authorization)\s+(?:failed|error)",
        # API key 错误
        r"(?:Invalid|Missing)\s+API\s*[Kk]ey",
        # 配置错误
        r"(?:Configuration|Config)\s+error",
    ]

    # 致命错误重复阈值 - 同一错误出现超过此次数时终止
    # 用于检测 CLI 进入重试死循环的情况
    _FATAL_ERROR_REPEAT_THRESHOLD: int = 3

    def __init__(
        self,
        event_callback: EventCallback | None = None,
        parser: Any | None = None,
    ) -> None:
        """初始化调用器。

        Args:
            event_callback: 事件回调函数，用于 GUI 推送
            parser: 自定义解析器实例（可选）
        """
        # 配置（可复用）
        self._event_callback = event_callback
        self._parser = parser

        # 当前执行上下文（per-request，每次 execute 创建新的）
        self._ctx: ExecutionContext | None = None

    # =========================================================================
    # 兼容性属性（向后兼容，访问当前上下文的字段）
    # =========================================================================

    @property
    def _process(self) -> asyncio.subprocess.Process | None:
        """兼容性属性：当前进程。"""
        return self._ctx.process if self._ctx else None

    @_process.setter
    def _process(self, value: asyncio.subprocess.Process | None) -> None:
        if self._ctx:
            self._ctx.process = value

    @property
    def _session_id(self) -> str:
        """兼容性属性：session_id。"""
        return self._ctx.session_id if self._ctx else ""

    @_session_id.setter
    def _session_id(self, value: str) -> None:
        if self._ctx:
            self._ctx.session_id = value

    @property
    def _collected_messages(self) -> list[dict[str, Any]]:
        """兼容性属性：collected_messages。"""
        return self._ctx.collected_messages if self._ctx else []

    @property
    def _agent_messages(self) -> list[str]:
        """兼容性属性：agent_messages。"""
        return self._ctx.agent_messages if self._ctx else []

    @property
    def _final_answer(self) -> str:
        """兼容性属性：final_answer。"""
        return self._ctx.final_answer if self._ctx else ""

    @_final_answer.setter
    def _final_answer(self, value: str) -> None:
        if self._ctx:
            self._ctx.final_answer = value

    @property
    def _exit_error(self) -> str | None:
        """兼容性属性：exit_error。"""
        return self._ctx.exit_error if self._ctx else None

    @_exit_error.setter
    def _exit_error(self, value: str | None) -> None:
        if self._ctx:
            self._ctx.exit_error = value

    @property
    def _captured_errors(self) -> list[str]:
        """兼容性属性：captured_errors。"""
        return self._ctx.captured_errors if self._ctx else []

    @property
    def _debug_info(self) -> DebugInfo:
        """兼容性属性：debug_info。"""
        return self._ctx.debug_info if self._ctx else DebugInfo()

    @_debug_info.setter
    def _debug_info(self, value: DebugInfo) -> None:
        if self._ctx:
            self._ctx.debug_info = value

    @property
    @abstractmethod
    def cli_type(self) -> CLIType:
        """返回 CLI 类型。"""
        ...

    @property
    def cli_name(self) -> str:
        """返回 CLI 名称字符串。"""
        return self.cli_type.value

    @property
    def uses_stdin_prompt(self) -> bool:
        """是否通过 stdin 传递 prompt。

        默认 True（codex/claude 使用 stdin），子类可重写。
        Gemini 0.20+ 使用位置参数，返回 False。
        """
        return True

    @abstractmethod
    def build_command(self, params: CommonParams) -> list[str]:
        """构建 CLI 命令行参数。

        Args:
            params: 调用参数

        Returns:
            命令行参数列表
        """
        ...

    def validate_params(self, params: CommonParams) -> None:
        """验证参数合法性。

        Args:
            params: 调用参数

        Raises:
            ValueError: 参数不合法时抛出
        """
        if not params.prompt:
            raise ValueError("prompt is required")
        if not params.workspace:
            raise ValueError("workspace is required")
        workspace = Path(params.workspace)
        if not workspace.exists():
            raise ValueError(f"workspace does not exist: {workspace}")
        if not workspace.is_dir():
            raise ValueError(f"workspace is not a directory: {workspace}")

    def _get_parser(self) -> Any:
        """获取解析器实例。

        延迟导入以避免循环依赖。
        """
        if self._parser is None:
            from ..parsers import create_parser

            self._parser = create_parser(self.cli_name)
        return self._parser

    async def execute(self, params: CommonParams) -> ExecutionResult:
        """执行 CLI 命令并返回结果。

        这是主要的执行入口，内部调用 stream() 收集所有事件。

        重要：每次调用都会创建新的 ExecutionContext，确保请求间状态隔离。

        Args:
            params: 调用参数

        Returns:
            执行结果
        """
        start_time = time.time()

        # 核心变更：每次执行创建新的上下文，确保请求间状态隔离
        self._ctx = ExecutionContext()

        try:
            self.validate_params(params)
        except ValueError as e:
            self._ctx = None  # 清理上下文
            return ExecutionResult(
                success=False,
                error=str(e),
                gui_metadata=GUIMetadata(
                    task_note=params.task_note,
                    task_tags=params.task_tags,
                    source=self.cli_name,
                    start_time=start_time,
                    end_time=time.time(),
                ),
            )

        cmd = self.build_command(params)
        logger.info(f"Executing: {' '.join(cmd)}")

        try:
            # 收集所有事件
            async for event in self._run_process(cmd, params):
                # 回调通知
                if self._event_callback:
                    self._event_callback(event)
                # 收集消息
                self._process_event(event, params)

            end_time = time.time()
            self._ctx.debug_info.duration_sec = end_time - start_time

            # 检查是否有退出错误（非零退出码）
            success = self._ctx.exit_error is None

            result = ExecutionResult(
                success=success,
                session_id=self._ctx.session_id,
                agent_messages=self._ctx.final_answer,  # 最终答案（最后一条）
                thought_steps=self._ctx.agent_messages,  # 中间消息（除最后一条外）
                error=self._ctx.exit_error,  # 退出错误信息
                all_messages=self._ctx.collected_messages if params.verbose_output else None,
                gui_metadata=GUIMetadata(
                    task_note=params.task_note,
                    task_tags=params.task_tags,
                    source=self.cli_name,
                    start_time=start_time,
                    end_time=end_time,
                ),
                debug_info=self._ctx.debug_info,
            )
            return result

        except asyncio.CancelledError as e:
            logger.warning(
                f"{self.cli_name} execution cancelled "
                f"(type={type(e).__name__}, process_alive={self._process is not None and self._process.returncode is None})"
            )
            end_time = time.time()
            if self._ctx:
                self._ctx.debug_info.duration_sec = end_time - start_time

            # 向 GUI 发送取消事件
            if self._event_callback:
                self._send_cancel_event(params)

            # Re-raise 让取消异常传播到 MCP 框架
            # 框架会正确处理取消响应
            logger.debug(f"{self.cli_name} re-raising CancelledError")
            raise

        except BaseException as e:
            # 捕获所有异常以便记录
            logger.error(
                f"{self.cli_name} BaseException: type={type(e).__name__}, "
                f"msg={e}, is_Exception={isinstance(e, Exception)}"
            )
            if not isinstance(e, Exception):
                # SystemExit, KeyboardInterrupt 等，直接 re-raise
                raise

            end_time = time.time()
            debug_info = self._ctx.debug_info if self._ctx else DebugInfo()
            debug_info.duration_sec = end_time - start_time

            # 向 GUI 发送错误事件
            if self._event_callback:
                self._send_error_event(
                    f"Execution failed: {e}",
                    error_type="startup_failed",
                )

            return ExecutionResult(
                success=False,
                error=str(e),
                gui_metadata=GUIMetadata(
                    task_note=params.task_note,
                    task_tags=params.task_tags,
                    source=self.cli_name,
                    start_time=start_time,
                    end_time=end_time,
                ),
                debug_info=debug_info,
            )
        finally:
            # 清理上下文引用，释放内存（防止 invoker 复用时滞留大缓冲区）
            logger.debug(f"{self.cli_name} execute() finally block")
            self._ctx = None

    async def stream(
        self, params: CommonParams
    ) -> AsyncIterator["UnifiedEvent"]:
        """流式执行 CLI 命令，逐个产出事件。

        适用于需要实时处理事件的场景。

        重要：每次调用都会创建新的 ExecutionContext，确保请求间状态隔离。

        Args:
            params: 调用参数

        Yields:
            解析后的统一事件
        """
        # 核心变更：每次执行创建新的上下文
        self._ctx = ExecutionContext()

        self.validate_params(params)
        cmd = self.build_command(params)
        logger.info(f"Streaming: {' '.join(cmd)}")

        async for event in self._run_process(cmd, params):
            yield event

    async def _run_process(
        self, cmd: list[str], params: CommonParams
    ) -> AsyncIterator["UnifiedEvent"]:
        """运行子进程并解析输出流。

        Args:
            cmd: 命令行参数列表
            params: 调用参数

        Yields:
            解析后的统一事件
        """
        from ..parsers import UnifiedEvent

        # DEBUG: 记录完整的子进程调用信息
        logger.debug(
            f"[SUBPROCESS] Preparing to execute:\n"
            f"  Command: {' '.join(cmd)}\n"
            f"  Workspace: {params.workspace}\n"
            f"  Prompt length: {len(params.prompt)} chars"
        )

        # 构建平台特定的子进程参数，实现进程组隔离
        # 这是防止 SIGINT 同时打到父/子进程的关键
        subprocess_kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            # Windows: 创建新的进程组
            subprocess_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            # POSIX: 创建新的会话（等同于 setsid）
            subprocess_kwargs["start_new_session"] = True

        # stdin 处理策略：
        # - uses_stdin_prompt=True (codex/claude): 使用 PIPE 传递 prompt
        # - uses_stdin_prompt=False (gemini): 使用 DEVNULL 隔离
        #
        # 重要：必须使用 DEVNULL 而不是 None！
        # 当 stdin=None 时，子进程会继承父进程的 stdin（MCP 的 JSON-RPC 通道）
        # 子进程退出时可能关闭这个继承的 stdin，导致 MCP server 异常退出
        stdin_mode = (
            asyncio.subprocess.PIPE
            if self.uses_stdin_prompt
            else asyncio.subprocess.DEVNULL
        )

        # 注意：asyncio.create_subprocess_exec 在 POSIX 系统上默认 close_fds=True
        # 这确保子进程不会继承父进程的文件描述符（网络连接、日志文件等）

        # 获取环境变量覆盖（子类可通过 get_env() 提供）
        env = self.get_env(params) if hasattr(self, 'get_env') else None

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=stdin_mode,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=params.workspace,
            env=env,
            **subprocess_kwargs,
        )

        # DEBUG: 记录进程启动信息
        logger.debug(
            f"[SUBPROCESS] Started: pid={self._process.pid}, "
            f"stdin_mode={'PIPE' if self.uses_stdin_prompt else 'DEVNULL'}"
        )

        # 通过 stdin 发送 prompt（仅当 uses_stdin_prompt=True）
        if self.uses_stdin_prompt and self._process.stdin:
            self._process.stdin.write(params.prompt.encode("utf-8"))
            await self._process.stdin.drain()
            self._process.stdin.close()
            await self._process.stdin.wait_closed()

        # 子进程启动后，推送系统信息
        if self._event_callback:
            self._send_process_started_event()

        parser = self._get_parser()

        # stderr 缓冲区配置
        # 使用环形缓冲策略：超出上限时丢弃最旧的数据
        # 4MB 足够保留大多数错误信息，同时防止内存溢出
        STDERR_MAX_SIZE = 4 * 1024 * 1024  # 4MB
        stderr_chunks: list[bytes] = []
        stderr_total_size = 0

        # DEBUG: 收集 stdout 原始输出用于调试
        stdout_lines_raw: list[str] = []

        # 致命错误检测状态
        fatal_error_event = asyncio.Event()
        fatal_error_message: list[str] = []  # 使用列表以便在闭包中修改
        stderr_error_counts: dict[str, int] = {}  # 用于检测重复错误

        async def drain_stderr() -> None:
            """并发读取 stderr，检测致命错误并使用环形缓冲防止内存溢出。

            致命错误检测策略：
            1. 模式匹配：检测 _FATAL_ERROR_PATTERNS 中的模式
            2. 重复检测：同一错误重复超过阈值次数时触发
            """
            nonlocal stderr_total_size
            if not (self._process and self._process.stderr):
                return

            # 编译致命错误正则表达式
            fatal_patterns = [re.compile(p, re.IGNORECASE) for p in self._FATAL_ERROR_PATTERNS]

            # 行缓冲：用于从字节流中提取完整行
            line_buffer = b""

            while True:
                chunk = await self._process.stderr.read(4096)
                if not chunk:
                    # 处理最后剩余的数据
                    if line_buffer:
                        line = line_buffer.decode("utf-8", errors="replace")
                        self._check_stderr_line_for_fatal_error(
                            line, fatal_patterns, stderr_error_counts,
                            fatal_error_event, fatal_error_message
                        )
                    break

                # 存储原始数据
                stderr_chunks.append(chunk)
                stderr_total_size += len(chunk)

                # 超出上限时，丢弃最旧的数据
                while stderr_total_size > STDERR_MAX_SIZE and stderr_chunks:
                    removed = stderr_chunks.pop(0)
                    stderr_total_size -= len(removed)

                # 逐行检测致命错误
                line_buffer += chunk
                while b"\n" in line_buffer:
                    line_bytes, line_buffer = line_buffer.split(b"\n", 1)
                    line = line_bytes.decode("utf-8", errors="replace")

                    # 检测致命错误
                    if self._check_stderr_line_for_fatal_error(
                        line, fatal_patterns, stderr_error_counts,
                        fatal_error_event, fatal_error_message
                    ):
                        # 已检测到致命错误，继续读取以避免管道阻塞
                        # 但不再做额外检测
                        pass

        stderr_task = asyncio.create_task(drain_stderr())

        # 消息累积状态（用于合并连续的 delta 消息）
        pending_event: UnifiedEvent | None = None
        pending_text: str = ""

        def flush_pending() -> UnifiedEvent | None:
            """刷新累积的消息，返回合并后的事件。"""
            nonlocal pending_event, pending_text
            if pending_event is None or not pending_text:
                pending_event = None
                pending_text = ""
                return None
            # 创建合并后的事件
            merged = pending_event
            merged.raw = {**merged.raw, "content": pending_text, "_merged": True}
            if hasattr(merged, "text"):
                merged.text = pending_text
            if hasattr(merged, "is_delta"):
                merged.is_delta = False
            result = merged
            pending_event = None
            pending_text = ""
            return result

        try:
            if self._process.stdout:
                # 使用手动循环替代 async for，以便能够检查 fatal_error_event
                # async for line in stdout 会阻塞直到有数据，无法响应 fatal_error_event
                while True:
                    # 检查是否检测到致命错误（来自 stderr）
                    if fatal_error_event.is_set():
                        logger.warning(
                            f"[FATAL ERROR] Breaking stdout loop due to fatal error in stderr"
                        )
                        break

                    # 使用 wait() 同时等待 stdout 读取和致命错误事件
                    # 这样即使 stdout 没有输出，也能响应 stderr 中的致命错误
                    read_task = asyncio.create_task(self._process.stdout.readline())
                    fatal_wait_task = asyncio.create_task(fatal_error_event.wait())

                    done, pending = await asyncio.wait(
                        [read_task, fatal_wait_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    # 取消未完成的任务
                    for task in pending:
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass

                    # 检查是否因为致命错误而完成
                    if fatal_wait_task in done:
                        logger.warning(
                            f"[FATAL ERROR] Exiting stdout loop due to fatal error event"
                        )
                        break

                    # 获取读取结果
                    if read_task in done:
                        try:
                            line = read_task.result()
                        except Exception:
                            continue

                        # EOF - stdout 关闭
                        if not line:
                            break

                        try:
                            decoded = line.decode("utf-8", errors="replace").strip()
                        except Exception:
                            continue

                        # DEBUG: 记录原始 stdout 行
                        stdout_lines_raw.append(decoded)

                        if not decoded:
                            continue

                        # 尝试解析 JSON
                        try:
                            data = json.loads(decoded)
                        except json.JSONDecodeError:
                            # 非 JSON 行：尝试提取错误信息
                            error_info = self._extract_error_from_line(decoded)
                            if error_info:
                                error_type, error_msg = error_info
                                self._captured_errors.append(error_msg)
                                # 实时发送错误到 GUI
                                if self._event_callback:
                                    self._send_error_event(
                                        error_msg,
                                        error_type=error_type,
                                        severity="warning",  # API 重试等是警告级别
                                    )
                            else:
                                logger.debug(f"Non-JSON line: {decoded[:100]}")
                            continue

                        # 解析为统一事件
                        events = self._parse_raw_data(parser, data)
                        for event in events:
                            # 检测 stdout 中的 error 事件（如 item.type=error）
                            if (
                                event.category.value == "system"
                                and getattr(event, "severity", "") == "error"
                                and not fatal_error_event.is_set()
                            ):
                                error_msg = getattr(event, "message", "")
                                # 检查是否是可忽略的错误（如重连消息）
                                if not self._is_ignorable_error(error_msg):
                                    fatal_error_event.set()
                                    fatal_error_message.append(
                                        error_msg or "Error event in stdout"
                                    )
                                    logger.warning(
                                        f"[FATAL ERROR] Detected error event in stdout: "
                                        f"{fatal_error_message[0][:100]}"
                                    )
                                else:
                                    logger.debug(f"Ignoring transient error: {error_msg[:100]}")

                            # 消息累积逻辑：合并连续的 delta 消息
                            is_delta_message = (
                                event.category.value == "message"
                                and getattr(event, "is_delta", False)
                            )

                            if is_delta_message:
                                # 累积 delta 消息
                                if pending_event is None:
                                    pending_event = event
                                    pending_text = getattr(event, "text", "")
                                else:
                                    # 检查是否同一角色
                                    pending_role = getattr(pending_event, "role", "")
                                    current_role = getattr(event, "role", "")
                                    if pending_role == current_role:
                                        pending_text += getattr(event, "text", "")
                                    else:
                                        # 角色不同，先刷新之前的
                                        flushed = flush_pending()
                                        if flushed:
                                            yield flushed
                                        pending_event = event
                                        pending_text = getattr(event, "text", "")
                            else:
                                # 非 delta 消息：先刷新累积的，再 yield 当前
                                flushed = flush_pending()
                                if flushed:
                                    yield flushed
                                yield event

            # 流结束，刷新剩余的累积消息
            flushed = flush_pending()
            if flushed:
                yield flushed

            # 处理致命错误（如果检测到）
            if fatal_error_event.is_set():
                # 终止子进程
                logger.warning(f"[FATAL ERROR] Terminating process due to fatal error")
                await self._terminate_subprocess()

                # 设置错误信息
                error_msg = fatal_error_message[0] if fatal_error_message else "Fatal error detected in stderr"
                self._exit_error = f"{self.cli_name} fatal error: {error_msg}"

                # 向 GUI 发送错误事件
                if self._event_callback:
                    self._send_error_event(self._exit_error, error_type="fatal_error")

                return  # 跳过正常的进程等待流程

            # 等待 stderr 读取完成
            await stderr_task

            # 等待进程结束
            await self._process.wait()

            # 获取 stderr 内容用于错误检查
            stderr_content = b"".join(stderr_chunks).decode("utf-8", errors="replace")

            # 检查返回码
            if self._process.returncode != 0:
                error_msg = f"{self.cli_name} exited with code {self._process.returncode}"
                if stderr_content:
                    # 取最后 5 行，更容易捕获 API 错误
                    lines = stderr_content.strip().split("\n")
                    last_lines = "\n".join(lines[-5:]) if len(lines) > 5 else stderr_content.strip()
                    error_msg += f":\n{last_lines}"
                elif self._captured_errors:
                    # stderr 为空但 stdout 中捕获了错误（opencode 等会输出错误到 stdout）
                    # 使用捕获的错误信息
                    captured = "\n".join(self._captured_errors[-5:])  # 取最后 5 条
                    error_msg += f":\n{captured}"
                logger.warning(error_msg)
                self._exit_error = error_msg  # 保存错误信息供 execute 使用

                # 向 GUI 发送错误事件
                if self._event_callback:
                    self._send_error_event(error_msg, error_type="exit_error")

            # 钩子：允许子类在流处理结束后检查额外的错误条件
            # 例如 OpenCode 可能返回码为 0 但输出中包含错误
            self._check_execution_errors(stderr_content)

        finally:
            # DEBUG: 无论正常结束、取消还是异常，统一输出调试信息
            try:
                stderr_content = b"".join(stderr_chunks).decode("utf-8", errors="replace")
                stdout_content = "\n".join(stdout_lines_raw)
                process_pid = self._process.pid if self._process else "N/A"
                return_code = self._process.returncode if self._process else "N/A"
                logger.debug(
                    f"[SUBPROCESS] Exit: pid={process_pid}\n"
                    f"  Return code: {return_code}\n"
                    f"  Stdout lines: {len(stdout_lines_raw)}\n"
                    f"  Stderr size: {len(stderr_content)} chars\n"
                    f"  Captured errors: {len(self._captured_errors)}\n"
                    f"  Fatal error: {fatal_error_event.is_set()}"
                )
                if stdout_content.strip():
                    logger.debug(f"[SUBPROCESS] Stdout:\n{stdout_content}")
                if stderr_content.strip():
                    logger.debug(f"[SUBPROCESS] Stderr:\n{stderr_content}")
            except Exception as e:
                logger.debug(f"[SUBPROCESS] Debug info error: {e}")

            # 确保 stderr task 被取消
            if not stderr_task.done():
                stderr_task.cancel()
                try:
                    await stderr_task
                except asyncio.CancelledError:
                    pass

            # 确保子进程被终止（防止孤儿进程）
            if self._process is not None and self._process.returncode is None:
                logger.debug(f"Terminating subprocess pid={self._process.pid}")
                await self._terminate_subprocess()

            self._process = None

    async def _terminate_subprocess(self) -> None:
        """安全终止子进程及其子孙进程，先 SIGTERM 后 SIGKILL。

        使用进程组终止策略确保不留孤儿进程：
        - POSIX: os.killpg() 发送信号到整个进程组
        - Windows: 使用 CTRL_BREAK_EVENT 或回退到 terminate/kill

        Cancel-safe 实现：
        - 整个终止流程被 asyncio.shield() 保护
        - 即使被取消也会完成 SIGTERM -> SIGKILL 升级
        - finally 块确保 process.wait() 被调用以收割僵尸进程
        """
        if self._process is None:
            return

        pid = self._process.pid
        process = self._process  # 保存引用，防止 self._process 被清理

        async def _do_terminate() -> None:
            """实际的终止逻辑，被 shield 保护。"""
            try:
                # 先尝试优雅终止（发送到进程组）
                if sys.platform == "win32":
                    # Windows: 尝试 CTRL_BREAK_EVENT
                    try:
                        import signal
                        os.kill(pid, signal.CTRL_BREAK_EVENT)
                        logger.debug(f"Sent CTRL_BREAK_EVENT to pid={pid}")
                    except (ProcessLookupError, OSError):
                        process.terminate()
                else:
                    # POSIX: 发送 SIGTERM 到进程组
                    try:
                        import signal
                        pgid = os.getpgid(pid)
                        os.killpg(pgid, signal.SIGTERM)
                        logger.debug(f"Sent SIGTERM to process group pgid={pgid}")
                    except (ProcessLookupError, OSError) as e:
                        logger.debug(f"killpg failed, falling back to terminate: {e}")
                        process.terminate()

                # 等待最多 2 秒
                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    pass

                # 如果还没退出，强制 kill（发送到进程组）
                if process.returncode is None:
                    logger.debug(f"Force killing subprocess pid={pid}")
                    if sys.platform == "win32":
                        process.kill()
                    else:
                        # POSIX: 发送 SIGKILL 到进程组
                        try:
                            import signal
                            pgid = os.getpgid(pid)
                            os.killpg(pgid, signal.SIGKILL)
                            logger.debug(f"Sent SIGKILL to process group pgid={pgid}")
                        except (ProcessLookupError, OSError):
                            process.kill()

                    # 再等待最多 1 秒
                    try:
                        await asyncio.wait_for(process.wait(), timeout=1.0)
                    except asyncio.TimeoutError:
                        logger.warning(f"Subprocess pid={pid} did not exit after kill")

                logger.debug(f"Subprocess terminated: pid={pid}, code={process.returncode}")

            except ProcessLookupError:
                # 进程已经退出
                pass
            except Exception as e:
                logger.debug(f"Error terminating subprocess: {e}")
            finally:
                # 确保 wait() 被调用，收割僵尸进程
                if process.returncode is None:
                    try:
                        await process.wait()
                    except Exception:
                        pass

        # 使用 shield 保护整个终止流程
        # 即使外部取消，内部任务也会继续执行完成
        task = asyncio.create_task(_do_terminate())
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            # 外部取消，但我们需要等待清理完成后再传播取消
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                # 二次取消，任务仍在后台执行
                logger.debug(f"Double cancel during subprocess termination pid={pid}")
            logger.debug(f"_terminate_subprocess cancelled but cleanup completed for pid={pid}")
            raise

    def _parse_raw_data(self, parser: Any, data: dict[str, Any]) -> list["UnifiedEvent"]:
        """解析原始数据为统一事件。

        Args:
            parser: 解析器实例
            data: 原始 JSON 数据

        Returns:
            统一事件列表
        """
        # 使用解析器的 parse 方法
        result = parser.parse(data)
        # parse() 可能返回单个事件或事件列表
        if isinstance(result, list):
            return result
        return [result] if result else []

    def _process_event(self, event: "UnifiedEvent", params: CommonParams) -> None:
        """处理事件，提取有用信息。

        Args:
            event: 统一事件
            params: 调用参数
        """
        self._collected_messages.append(event.raw)
        self._debug_info.message_count += 1

        # 提取 session_id
        if not self._session_id and hasattr(event, "session_id"):
            if event.session_id:
                self._session_id = event.session_id

        # 收集 assistant 消息（排除 reasoning）
        # 设计：
        # - is_delta=True: 累积到当前 _final_answer
        # - is_delta=False: 之前的 _final_answer 移到 _agent_messages，新消息成为 _final_answer
        if event.category.value == "message" and getattr(event, "role", "") == "assistant":
            content_type = getattr(event, "content_type", None)
            # content_type 可能是枚举或字符串
            content_type_str = content_type.value if hasattr(content_type, "value") else str(content_type)
            if content_type_str != "reasoning":
                text = getattr(event, "text", "")
                is_delta = getattr(event, "is_delta", False)
                if text:
                    if is_delta:
                        # Delta 消息：累积到当前答案
                        self._final_answer += text
                    else:
                        # 完整消息：之前的移到中间列表，新消息成为最终答案
                        if self._final_answer:
                            self._agent_messages.append(self._final_answer)
                        self._final_answer = text

        raw = event.raw

        # 模型名称
        if not self._debug_info.model:
            model = raw.get("model") or raw.get("metadata", {}).get("model")
            if model:
                self._debug_info.model = model

        # Token 统计
        stats = raw.get("stats") or raw.get("usage") or {}
        if stats:
            if stats.get("input_tokens"):
                self._debug_info.input_tokens = stats["input_tokens"]
            if stats.get("output_tokens"):
                self._debug_info.output_tokens = stats["output_tokens"]
            if stats.get("cached_input_tokens"):
                self._debug_info.cached_input_tokens = stats["cached_input_tokens"]
            # Gemini 格式
            if stats.get("total_input_tokens"):
                self._debug_info.input_tokens = stats["total_input_tokens"]
            if stats.get("total_output_tokens"):
                self._debug_info.output_tokens = stats["total_output_tokens"]

        # 工具调用计数
        if event.category.value == "operation" and event.operation_type:
            if event.operation_type.value in ("tool_call", "function_call", "command"):
                self._debug_info.tool_call_count += 1

    def _send_cancel_event(self, params: CommonParams) -> None:
        """发送取消事件到 GUI。

        Args:
            params: 调用参数
        """
        from ..parsers import make_fallback_event, CLISource

        # 创建一个合成的取消事件
        cancel_data = {
            "type": "system",
            "subtype": "cancelled",
            "severity": "warning",  # 取消是警告级别
            "message": "Execution cancelled by user",
            "session_id": self._session_id,
            "source": self.cli_name,
        }

        try:
            source = CLISource(self.cli_name)
        except ValueError:
            source = CLISource.UNKNOWN

        event = make_fallback_event(source, cancel_data)

        if self._event_callback:
            self._event_callback(event)

    def _send_process_started_event(self) -> None:
        """发送进程启动事件到 GUI。"""
        from ..parsers import make_fallback_event, CLISource

        started_data = {
            "type": "system",
            "subtype": "info",
            "severity": "info",  # 信息级别
            "message": f"{self.cli_name} CLI started",
            "source": self.cli_name,
        }

        try:
            source = CLISource(self.cli_name)
        except ValueError:
            source = CLISource.UNKNOWN

        event = make_fallback_event(source, started_data)

        if self._event_callback:
            self._event_callback(event)

    def _extract_error_from_line(self, line: str) -> tuple[str, str] | None:
        """从非 JSON 行中提取错误信息。

        Args:
            line: 非 JSON 行内容

        Returns:
            (error_type, error_message) 元组，如果不是错误行则返回 None
        """
        # 跳过启动日志
        if line.startswith("[STARTUP]"):
            return None

        # 尝试匹配错误模式
        for pattern, error_type in self._ERROR_PATTERNS:
            match = re.search(pattern, line)
            if match:
                # 提取错误消息
                groups = match.groups()
                if len(groups) >= 2:
                    # 有状态码和消息
                    error_msg = f"[{groups[0]}] {groups[1]}"
                elif len(groups) == 1:
                    error_msg = groups[0]
                else:
                    error_msg = line
                # 尝试从 JSON 格式提取更详细的错误
                json_match = re.search(r'\{.*"error".*\}', error_msg)
                if json_match:
                    try:
                        error_json = json.loads(json_match.group())
                        if "error" in error_json:
                            err = error_json["error"]
                            code = err.get("code", "")
                            msg = err.get("message", "")
                            if code and msg:
                                error_msg = f"[{code}] {msg}"
                    except json.JSONDecodeError:
                        pass
                return (error_type, error_msg)

        return None

    def _check_stderr_line_for_fatal_error(
        self,
        line: str,
        fatal_patterns: list[re.Pattern[str]],
        error_counts: dict[str, int],
        fatal_event: asyncio.Event,
        fatal_message: list[str],
    ) -> bool:
        """检测 stderr 行是否包含致命错误。

        致命错误检测策略：
        1. 模式匹配：检测 _FATAL_ERROR_PATTERNS 中定义的模式
        2. 重复检测：同一错误信息重复超过 _FATAL_ERROR_REPEAT_THRESHOLD 次

        Args:
            line: stderr 行内容
            fatal_patterns: 编译后的致命错误正则表达式列表
            error_counts: 错误计数字典（用于检测重复）
            fatal_event: 致命错误事件（用于通知主循环）
            fatal_message: 致命错误消息列表（用于存储错误信息）

        Returns:
            True 如果检测到致命错误，False 否则
        """
        if not line.strip():
            return False

        # 如果已经检测到致命错误，不再重复检测
        if fatal_event.is_set():
            return True

        # 先检查是否是可忽略的错误（如重连消息）
        if self._is_ignorable_error(line):
            logger.debug(f"Ignoring transient stderr error: {line[:100]}")
            return False

        # 1. 模式匹配检测
        for pattern in fatal_patterns:
            if pattern.search(line):
                logger.warning(f"[FATAL ERROR DETECTED] Pattern match: {line[:200]}")
                fatal_message.clear()
                fatal_message.append(line)
                fatal_event.set()
                return True

        # 2. 重复错误检测
        # 标准化错误信息（移除时间戳、数字等变化部分）
        normalized = re.sub(r'\d+', '#', line.strip())
        error_counts[normalized] = error_counts.get(normalized, 0) + 1

        if error_counts[normalized] >= self._FATAL_ERROR_REPEAT_THRESHOLD:
            logger.warning(
                f"[FATAL ERROR DETECTED] Repeated error ({error_counts[normalized]}x): {line[:200]}"
            )
            fatal_message.clear()
            fatal_message.append(f"Repeated error ({error_counts[normalized]}x): {line}")
            fatal_event.set()
            return True

        return False

    def _check_execution_errors(self, stderr_content: str = "") -> None:
        """检查执行错误的钩子方法。

        在流处理结束后、返回码检查之后调用。
        子类可以覆盖此方法来处理特殊的错误情况，例如：
        - CLI 返回码为 0 但输出中包含错误（如 OpenCode）
        - 需要从 captured_errors 或 stderr 中提取特定错误

        Args:
            stderr_content: 子进程的 stderr 输出内容

        如果检测到错误，应设置 self._exit_error 并可选地发送错误事件。

        默认实现为空（无额外检查）。
        """
        pass

    def _is_ignorable_error(self, error_msg: str) -> bool:
        """检查错误消息是否可忽略（如重连消息）。

        子类可以覆盖此方法来定义可忽略的错误模式。

        Args:
            error_msg: 错误消息

        Returns:
            True 如果错误可忽略，False 否则
        """
        return False

    def _send_error_event(
        self,
        message: str,
        error_type: str = "error",
        severity: str = "error",
    ) -> None:
        """发送错误事件到 GUI。

        Args:
            message: 错误消息
            error_type: 错误子类型（error, startup_failed, exit_error, api_error, tool_error）
            severity: 严重级别（error, warning, info）
        """
        from ..parsers import make_fallback_event, CLISource

        error_data = {
            "type": "system",
            "subtype": error_type,
            "severity": severity,
            "message": message,
            "session_id": self._session_id,
            "source": self.cli_name,
        }

        try:
            source = CLISource(self.cli_name)
        except ValueError:
            source = CLISource.UNKNOWN

        event = make_fallback_event(source, error_data)

        if self._event_callback:
            self._event_callback(event)

    async def cancel(self) -> None:
        """取消正在执行的命令。

        使用 _terminate_subprocess() 确保：
        - 进程组感知（终止子进程及其子孙）
        - 正确的 SIGTERM -> SIGKILL 升级
        - 收割僵尸进程（await wait()）
        - Cancel-safe 实现
        """
        if self._process and self._process.returncode is None:
            logger.info(f"Cancelling {self.cli_name} process (pid={self._process.pid})")
            await self._terminate_subprocess()
