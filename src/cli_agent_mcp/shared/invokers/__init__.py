"""CLI 调用器模块。

cli-agent-mcp shared/invokers v0.1.0
同步日期: 2025-12-16

提供统一的 CLI 调用接口，封装 Codex、Gemini、Claude 三个 CLI。

重构说明（请求上下文隔离）：
- ExecutionContext: 持有 per-request 的执行态
- 每次 execute() 创建新的上下文，确保请求间状态隔离
- invoker 实例可以安全复用（但建议每请求创建新实例）

基础用法:
    from invokers import CodexInvoker, CodexParams

    invoker = CodexInvoker()
    result = await invoker.execute(CodexParams(
        prompt="Review this code",
        workspace=Path("/path/to/repo"),
    ))

流式用法（配合 GUI）:
    from invokers import GeminiInvoker, GeminiParams
    from gui import LiveViewer

    viewer = LiveViewer(title="GeminiMCP")
    invoker = GeminiInvoker(event_callback=viewer.push_event)

    async for event in invoker.stream(params):
        pass  # 事件已通过回调推送到 GUI

工厂函数:
    from invokers import create_invoker, CLIType

    invoker = create_invoker(CLIType.CLAUDE)
"""

from __future__ import annotations

__version__ = "0.1.0"

from .base import CLIInvoker, EventCallback, ExecutionContext, FirstEventTimeoutError
from .claude import ClaudeInvoker
from .codex import CodexInvoker
from .gemini import GeminiInvoker
from .opencode import OpencodeInvoker
from .banana import BananaInvoker, BananaParams, BananaExecutionResult
from .image import ImageInvoker, ImageParams, ImageExecutionResult
from .types import (
    CLIType,
    ClaudeParams,
    CodexParams,
    CommonParams,
    DebugInfo,
    ExecutionResult,
    GeminiParams,
    GUIMetadata,
    OpencodeParams,
    Permission,
    PERMISSION_MAP_CLAUDE,
    PERMISSION_MAP_CODEX,
)

__all__ = [
    # 版本
    "__version__",
    # 类型
    "CLIType",
    "Permission",
    "CommonParams",
    "CodexParams",
    "GeminiParams",
    "ClaudeParams",
    "OpencodeParams",
    "BananaParams",
    "ImageParams",
    "ExecutionResult",
    "BananaExecutionResult",
    "ImageExecutionResult",
    "GUIMetadata",
    "DebugInfo",
    # 映射表
    "PERMISSION_MAP_CODEX",
    "PERMISSION_MAP_CLAUDE",
    # 基类和上下文
    "CLIInvoker",
    "EventCallback",
    "ExecutionContext",
    "FirstEventTimeoutError",
    # 调用器
    "CodexInvoker",
    "GeminiInvoker",
    "ClaudeInvoker",
    "OpencodeInvoker",
    "BananaInvoker",
    "ImageInvoker",
    # 工厂函数
    "create_invoker",
]


def create_invoker(
    cli_type: CLIType | str,
    event_callback: EventCallback | None = None,
) -> CLIInvoker | BananaInvoker | ImageInvoker:
    """创建指定 CLI 的调用器实例。

    Args:
        cli_type: CLI 类型
        event_callback: 可选的事件回调函数

    Returns:
        对应的调用器实例

    Raises:
        ValueError: 不支持的 CLI 类型
    """
    if isinstance(cli_type, str):
        cli_type = CLIType(cli_type.lower())

    if cli_type == CLIType.CODEX:
        return CodexInvoker(event_callback=event_callback)
    elif cli_type == CLIType.GEMINI:
        return GeminiInvoker(event_callback=event_callback)
    elif cli_type == CLIType.CLAUDE:
        return ClaudeInvoker(event_callback=event_callback)
    elif cli_type == CLIType.OPENCODE:
        return OpencodeInvoker(event_callback=event_callback)
    elif cli_type == CLIType.BANANA:
        return BananaInvoker(event_callback=event_callback)
    elif cli_type == CLIType.IMAGE:
        return ImageInvoker(event_callback=event_callback)
    else:
        raise ValueError(f"Unsupported CLI type: {cli_type}")
