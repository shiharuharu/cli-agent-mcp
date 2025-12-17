"""Agent Adapter 基类 - 无状态适配器。

这是重构后的核心模块，实现请求上下文隔离。

设计原则：
- AgentAdapter 是无状态的，只负责：
  1. 参数 -> 命令行映射
  2. session_id 抽取规则
  3. 创建解析器
- 执行态由 ExecutionContext 持有（per-request）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from ..shared.parsers import UnifiedEvent

__all__ = [
    "AgentAdapter",
    "ExecutionContext",
    "EventCallback",
]

# 类型别名：事件回调函数
EventCallback = Callable[["UnifiedEvent"], None]


@dataclass
class ExecutionContext:
    """执行上下文 - 持有 per-request 的执行态。

    每次请求创建新的 ExecutionContext，确保请求间状态隔离。

    Attributes:
        session_id: 从事件流中提取的会话 ID
        collected_messages: 收集的原始消息
        agent_messages: 过程中的 assistant 消息
        final_answer: 最终答案
        exit_error: 非零退出码的错误信息
        captured_errors: 捕获的非 JSON 错误信息
        debug_info: 调试统计信息
    """
    # 会话状态
    session_id: str = ""

    # 消息收集
    collected_messages: list[dict[str, Any]] = field(default_factory=list)
    agent_messages: list[str] = field(default_factory=list)
    final_answer: str = ""

    # 错误状态
    exit_error: str | None = None
    captured_errors: list[str] = field(default_factory=list)

    # 调试信息（使用字典，避免循环导入）
    debug_info: dict[str, Any] = field(default_factory=lambda: {
        "model": "",
        "duration_sec": 0.0,
        "message_count": 0,
        "tool_call_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
    })

    def reset(self) -> None:
        """重置上下文状态。"""
        self.session_id = ""
        self.collected_messages.clear()
        self.agent_messages.clear()
        self.final_answer = ""
        self.exit_error = None
        self.captured_errors.clear()
        self.debug_info = {
            "model": "",
            "duration_sec": 0.0,
            "message_count": 0,
            "tool_call_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }


class AgentAdapter(ABC):
    """Agent 适配器基类 - 无状态。

    子类需要实现：
    - cli_type: CLI 类型标识
    - build_command(): 构建命令行参数
    - extract_session_id(): 从事件中提取 session_id

    特点：
    - 完全无状态，可以安全地在多个请求间共享
    - 只负责命令构建和 session_id 抽取逻辑
    - 不持有任何执行过程中的状态
    """

    @property
    @abstractmethod
    def cli_type(self) -> str:
        """返回 CLI 类型标识（如 'codex', 'gemini', 'claude'）。"""
        ...

    @property
    def uses_stdin_prompt(self) -> bool:
        """是否通过 stdin 传递 prompt。

        默认 True（codex/claude 使用 stdin），子类可重写。
        Gemini 使用位置参数，返回 False。
        """
        return True

    @abstractmethod
    def build_command(self, params: Any) -> list[str]:
        """构建 CLI 命令行参数。

        Args:
            params: 调用参数（CommonParams 或其子类）

        Returns:
            命令行参数列表
        """
        ...

    def extract_session_id(self, event: "UnifiedEvent") -> str | None:
        """从事件中提取 session_id。

        子类可重写此方法来实现 CLI 特定的 session_id 抽取逻辑。

        Args:
            event: 统一事件

        Returns:
            session_id 或 None
        """
        # 默认实现：尝试从 event.session_id 获取
        if hasattr(event, "session_id") and event.session_id:
            return event.session_id
        return None

    def create_parser(self) -> Any:
        """创建 CLI 对应的解析器。

        Returns:
            解析器实例
        """
        from ..shared.parsers import create_parser
        return create_parser(self.cli_type)

    def validate_params(self, params: Any) -> None:
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
