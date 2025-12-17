"""结果收集器模块。

cli-agent-mcp shared/mcp v0.1.0
同步日期: 2025-12-16

将事件流处理和结果收集逻辑从 CLIInvoker 中抽离，
提供独立、可测试的结果收集能力。

职责：
- 从事件流中提取 session_id
- 收集 assistant 消息（区分中间步骤和最终答案）
- 统计 debug 信息（token、duration、tool_call）
- 捕获和分类错误
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from .types import DebugInfo, ExecutionResult, GUIMetadata

if TYPE_CHECKING:
    from ..parsers import UnifiedEvent

__all__ = [
    "ResultCollector",
    "ErrorCategory",
    "CollectedResult",
]

logger = logging.getLogger(__name__)


class ErrorCategory(str, Enum):
    """错误分类枚举。

    区分不同类型的错误，便于上层处理和用户提示。

    - NONE: 无错误
    - CANCELLED: 请求被取消（用户中断、MCP 取消）
    - EXIT_ERROR: CLI 非零退出码
    - API_ERROR: API 调用错误（重试、限流等）
    - VALIDATION_ERROR: 参数验证错误
    - INTERNAL_ERROR: 内部错误（解析、编码等）
    """

    NONE = "none"
    CANCELLED = "cancelled"
    EXIT_ERROR = "exit_error"
    API_ERROR = "api_error"
    VALIDATION_ERROR = "validation_error"
    INTERNAL_ERROR = "internal_error"


@dataclass
class CollectedResult:
    """收集的结果数据。

    ResultCollector 的输出，包含从事件流中提取的所有信息。

    Attributes:
        session_id: 会话 ID
        final_answer: 最终答案（最后一条 agent 消息）
        thought_steps: 中间思考步骤
        all_messages: 完整消息列表
        debug_info: 调试统计信息
        error_category: 错误分类
        error_message: 错误消息
        exit_code: CLI 退出码（仅当有退出错误时）
        captured_errors: 捕获的非 JSON 错误信息
    """

    session_id: str = ""
    final_answer: str = ""
    thought_steps: list[str] = field(default_factory=list)
    all_messages: list[dict[str, Any]] = field(default_factory=list)
    debug_info: DebugInfo = field(default_factory=DebugInfo)
    error_category: ErrorCategory = ErrorCategory.NONE
    error_message: str | None = None
    exit_code: int | None = None
    captured_errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """是否执行成功。"""
        return self.error_category == ErrorCategory.NONE

    @property
    def cancelled(self) -> bool:
        """是否被取消。"""
        return self.error_category == ErrorCategory.CANCELLED

    def to_execution_result(
        self,
        cli_name: str,
        task_note: str = "",
        task_tags: list[str] | None = None,
        start_time: float = 0.0,
        end_time: float = 0.0,
        full_output: bool = False,
    ) -> ExecutionResult:
        """转换为 ExecutionResult。

        Args:
            cli_name: CLI 名称
            task_note: 任务备注
            task_tags: 任务标签
            start_time: 开始时间戳
            end_time: 结束时间戳
            full_output: 是否包含完整消息

        Returns:
            ExecutionResult 实例
        """
        # 更新 debug_info 中的 exit_code（如果有）
        debug_info = self.debug_info
        debug_info.duration_sec = end_time - start_time

        return ExecutionResult(
            success=self.success,
            session_id=self.session_id,
            agent_messages=self.final_answer,
            thought_steps=self.thought_steps,
            error=self.error_message,
            all_messages=self.all_messages if full_output else None,
            gui_metadata=GUIMetadata(
                task_note=task_note,
                task_tags=task_tags or [],
                source=cli_name,
                start_time=start_time,
                end_time=end_time,
            ),
            debug_info=debug_info,
            cancelled=self.cancelled,
        )


class ResultCollector:
    """结果收集器。

    从事件流中收集和聚合执行结果，包括：
    - session_id 提取
    - assistant 消息收集（区分中间步骤和最终答案）
    - debug 信息统计
    - 错误捕获和分类

    使用示例:
        collector = ResultCollector()

        async for event in event_stream:
            collector.process_event(event)

        result = collector.get_result()

    线程安全性：
        ResultCollector 是 per-request 的，不共享状态。
    """

    # 非 JSON 行中的错误模式
    _ERROR_PATTERNS = [
        # Gemini API 重试错误
        (r"Attempt \d+ failed with status (\d+)\. .* ApiError: (.+)", ErrorCategory.API_ERROR),
        # 工具执行错误
        (r"Error executing tool (\w+): (.+)", ErrorCategory.INTERNAL_ERROR),
        # 通用 API 错误
        (r"ApiError: (.+)", ErrorCategory.API_ERROR),
    ]

    def __init__(self) -> None:
        """初始化收集器。"""
        # 会话状态
        self._session_id: str = ""

        # 消息收集
        self._all_messages: list[dict[str, Any]] = []
        self._thought_steps: list[str] = []
        self._final_answer: str = ""

        # 错误状态
        self._error_category: ErrorCategory = ErrorCategory.NONE
        self._error_message: str | None = None
        self._exit_code: int | None = None
        self._captured_errors: list[str] = []

        # 调试信息
        self._debug_info: DebugInfo = DebugInfo()

    def process_event(self, event: "UnifiedEvent") -> None:
        """处理单个事件。

        Args:
            event: 统一事件
        """
        self._all_messages.append(event.raw)
        self._debug_info.message_count += 1

        # 提取 session_id
        if not self._session_id and hasattr(event, "session_id"):
            if event.session_id:
                self._session_id = event.session_id

        # 收集 assistant 消息（排除 reasoning）
        self._collect_assistant_message(event)

        # 提取 debug 信息
        self._extract_debug_info(event)

    def _collect_assistant_message(self, event: "UnifiedEvent") -> None:
        """收集 assistant 消息。

        设计逻辑：
        - is_delta=True: 累积到当前 _final_answer
        - is_delta=False: 之前的 _final_answer 移到 _thought_steps，新消息成为 _final_answer

        Args:
            event: 统一事件
        """
        if event.category.value != "message":
            return

        if getattr(event, "role", "") != "assistant":
            return

        # 排除 reasoning 类型
        content_type = getattr(event, "content_type", None)
        content_type_str = content_type.value if hasattr(content_type, "value") else str(content_type)
        if content_type_str == "reasoning":
            return

        text = getattr(event, "text", "")
        if not text:
            return

        is_delta = getattr(event, "is_delta", False)
        if is_delta:
            # Delta 消息：累积到当前答案
            self._final_answer += text
        else:
            # 完整消息：之前的移到中间列表
            if self._final_answer:
                self._thought_steps.append(self._final_answer)
            self._final_answer = text

    def _extract_debug_info(self, event: "UnifiedEvent") -> None:
        """从事件中提取 debug 信息。

        Args:
            event: 统一事件
        """
        raw = event.raw

        # 模型名称
        if not self._debug_info.model:
            model = raw.get("model") or raw.get("metadata", {}).get("model")
            if model:
                self._debug_info.model = model

        # Token 统计
        stats = raw.get("stats", {})
        if stats:
            # Codex/Claude 格式
            if stats.get("input_tokens"):
                self._debug_info.input_tokens = stats["input_tokens"]
            if stats.get("output_tokens"):
                self._debug_info.output_tokens = stats["output_tokens"]
            # Gemini 格式
            if stats.get("total_input_tokens"):
                self._debug_info.input_tokens = stats["total_input_tokens"]
            if stats.get("total_output_tokens"):
                self._debug_info.output_tokens = stats["total_output_tokens"]

        # 工具调用计数
        if event.category.value == "operation" and event.operation_type:
            if event.operation_type.value in ("tool_call", "function_call", "command"):
                self._debug_info.tool_call_count += 1

    def process_non_json_line(self, line: str) -> tuple[ErrorCategory, str] | None:
        """处理非 JSON 行，尝试提取错误信息。

        Args:
            line: 非 JSON 行内容

        Returns:
            (error_category, error_message) 元组，如果不是错误行则返回 None
        """
        # 跳过启动日志
        if line.startswith("[STARTUP]"):
            return None

        # 尝试匹配错误模式
        for pattern, error_category in self._ERROR_PATTERNS:
            match = re.search(pattern, line)
            if match:
                groups = match.groups()
                if len(groups) >= 2:
                    error_msg = f"[{groups[0]}] {groups[1]}"
                elif len(groups) == 1:
                    error_msg = groups[0]
                else:
                    error_msg = line

                # 尝试从 JSON 格式提取更详细的错误
                error_msg = self._extract_json_error(error_msg)
                self._captured_errors.append(error_msg)

                return (error_category, error_msg)

        return None

    def _extract_json_error(self, error_msg: str) -> str:
        """尝试从错误消息中提取 JSON 格式的详细错误。

        Args:
            error_msg: 原始错误消息

        Returns:
            处理后的错误消息
        """
        json_match = re.search(r'\{.*"error".*\}', error_msg)
        if json_match:
            try:
                error_json = json.loads(json_match.group())
                if "error" in error_json:
                    err = error_json["error"]
                    code = err.get("code", "")
                    msg = err.get("message", "")
                    if code and msg:
                        return f"[{code}] {msg}"
            except json.JSONDecodeError:
                pass
        return error_msg

    def set_exit_error(self, exit_code: int, stderr: str = "") -> None:
        """设置退出错误。

        Args:
            exit_code: 退出码
            stderr: stderr 内容
        """
        self._exit_code = exit_code
        self._error_category = ErrorCategory.EXIT_ERROR
        self._error_message = f"CLI exited with code {exit_code}"
        if stderr:
            # 取最后 5 行
            lines = stderr.strip().split("\n")
            last_lines = "\n".join(lines[-5:]) if len(lines) > 5 else stderr.strip()
            self._error_message += f":\n{last_lines}"

    def set_cancelled(self) -> None:
        """标记为已取消。"""
        self._error_category = ErrorCategory.CANCELLED
        self._error_message = "Execution cancelled"

    def set_validation_error(self, message: str) -> None:
        """设置验证错误。

        Args:
            message: 错误消息
        """
        self._error_category = ErrorCategory.VALIDATION_ERROR
        self._error_message = message

    def set_internal_error(self, message: str) -> None:
        """设置内部错误。

        Args:
            message: 错误消息
        """
        self._error_category = ErrorCategory.INTERNAL_ERROR
        self._error_message = message

    def get_result(self) -> CollectedResult:
        """获取收集的结果。

        Returns:
            CollectedResult 实例
        """
        return CollectedResult(
            session_id=self._session_id,
            final_answer=self._final_answer,
            thought_steps=self._thought_steps.copy(),
            all_messages=self._all_messages.copy(),
            debug_info=self._debug_info,
            error_category=self._error_category,
            error_message=self._error_message,
            exit_code=self._exit_code,
            captured_errors=self._captured_errors.copy(),
        )

    @property
    def session_id(self) -> str:
        """当前 session_id。"""
        return self._session_id

    @property
    def debug_info(self) -> DebugInfo:
        """当前 debug 信息。"""
        return self._debug_info
