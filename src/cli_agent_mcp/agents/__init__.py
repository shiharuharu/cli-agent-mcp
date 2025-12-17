"""Agent 适配器模块。

提供无状态的 CLI 适配器，实现请求上下文隔离。

用法：
    from cli_agent_mcp.agents import create_adapter, ExecutionContext

    # 创建适配器（可复用）
    adapter = create_adapter("codex")

    # 每次请求创建新的执行上下文
    context = ExecutionContext()

    # 构建命令
    cmd = adapter.build_command(params)

    # 从事件中提取 session_id
    session_id = adapter.extract_session_id(event)
    if session_id:
        context.session_id = session_id
"""

from __future__ import annotations

from .base import AgentAdapter, EventCallback, ExecutionContext
from .codex import CodexAdapter
from .gemini import GeminiAdapter
from .claude import ClaudeAdapter

__all__ = [
    # 基类和上下文
    "AgentAdapter",
    "ExecutionContext",
    "EventCallback",
    # 具体适配器
    "CodexAdapter",
    "GeminiAdapter",
    "ClaudeAdapter",
    # 工厂函数
    "create_adapter",
    "get_adapter",
]

# 适配器单例缓存（适配器是无状态的，可以安全缓存）
_ADAPTER_CACHE: dict[str, AgentAdapter] = {}


def create_adapter(cli_type: str) -> AgentAdapter:
    """创建 CLI 适配器实例。

    适配器是无状态的，可以安全地复用。

    Args:
        cli_type: CLI 类型（codex, gemini, claude）

    Returns:
        对应的适配器实例

    Raises:
        ValueError: 不支持的 CLI 类型
    """
    cli_type = cli_type.lower()

    if cli_type == "codex":
        return CodexAdapter()
    elif cli_type == "gemini":
        return GeminiAdapter()
    elif cli_type == "claude":
        return ClaudeAdapter()
    else:
        raise ValueError(f"Unsupported CLI type: {cli_type}")


def get_adapter(cli_type: str) -> AgentAdapter:
    """获取 CLI 适配器实例（带缓存）。

    由于适配器是无状态的，可以安全地缓存和复用。

    Args:
        cli_type: CLI 类型（codex, gemini, claude）

    Returns:
        对应的适配器实例（缓存的）
    """
    cli_type = cli_type.lower()
    if cli_type not in _ADAPTER_CACHE:
        _ADAPTER_CACHE[cli_type] = create_adapter(cli_type)
    return _ADAPTER_CACHE[cli_type]
