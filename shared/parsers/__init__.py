"""统一事件解析器模块。

cli-agent-mcp shared/parsers v0.1.0
同步日期: 2025-12-16

本模块提供统一的事件解析接口，支持自动检测 CLI 来源。

Example:
    from parsers import parse_event, create_parser

    # 方式 1: 自动检测（无状态，简单用法）
    event = parse_event(raw_data)

    # 方式 2: 使用 Parser 类（有状态，完整功能）
    parser = create_parser("gemini")
    for line in stream:
        event = parser.parse(json.loads(line))
        gui.push_event(event)
"""

from __future__ import annotations

from typing import Any

from .base import (
    VERSION,
    CLISource,
    ContentType,
    EventCategory,
    OperationType,
    Status,
)
from .claude import ClaudeParser, parse_claude_event
from .codex import CodexParser, parse_codex_event
from .gemini import GeminiParser, parse_gemini_event
from .opencode import OpencodeParser, parse_opencode_event
from .unified import (
    LifecycleEvent,
    MessageEvent,
    OperationEvent,
    SystemEvent,
    UnifiedEvent,
    UnifiedEventBase,
    make_event_id,
    make_fallback_event,
)

__all__ = [
    # 版本
    "VERSION",
    # 基础类型
    "CLISource",
    "EventCategory",
    "ContentType",
    "OperationType",
    "Status",
    # 统一事件
    "UnifiedEventBase",
    "LifecycleEvent",
    "MessageEvent",
    "OperationEvent",
    "SystemEvent",
    "UnifiedEvent",
    # 工厂函数
    "make_event_id",
    "make_fallback_event",
    # 解析器类
    "GeminiParser",
    "CodexParser",
    "ClaudeParser",
    "OpencodeParser",
    # 便捷函数
    "parse_event",
    "parse_events",
    "parse_gemini_event",
    "parse_codex_event",
    "parse_claude_event",
    "parse_opencode_event",
    "detect_source",
    "create_parser",
]


def detect_source(data: dict[str, Any]) -> CLISource:
    """检测事件来源 CLI。

    根据事件中的特征字段判断来自哪个 CLI。

    Args:
        data: 原始事件字典

    Returns:
        CLISource 枚举值
    """
    event_type = data.get("type", "")
    subtype = data.get("subtype", "")

    # OpenCode CLI 特征
    # OpenCode 事件包含 sessionID 字段（注意大小写与其他 CLI 不同）
    if "sessionID" in data:
        # 特有事件类型
        if event_type in ("tool_use", "step_start", "step_finish", "text", "error"):
            # 检查是否有 part 字段（OpenCode 特有）
            if "part" in data or event_type == "error":
                return CLISource.OPENCODE

    # Claude Code CLI 特征
    # system/init 事件包含 claude_code_version
    if event_type == "system" and subtype == "init":
        if "claude_code_version" in data or "session_id" in data:
            return CLISource.CLAUDE
    # assistant/user/result 事件包含 message 结构
    if event_type in ("assistant", "user", "result"):
        if "message" in data or "session_id" in data:
            return CLISource.CLAUDE

    # Gemini CLI 特征
    if event_type == "init" and "session_id" in data and "model" in data:
        return CLISource.GEMINI
    if event_type in ("message", "tool_use", "tool_result"):
        if event_type == "message" and "role" in data:
            return CLISource.GEMINI
        if event_type in ("tool_use", "tool_result") and "tool_id" in data:
            return CLISource.GEMINI
    if event_type == "result" and "stats" in data:
        return CLISource.GEMINI

    # Codex CLI 特征
    if event_type == "thread.started" and "thread_id" in data:
        return CLISource.CODEX
    if event_type in ("item.started", "item.completed", "item.updated"):
        return CLISource.CODEX
    if event_type in ("turn.started", "turn.completed", "turn.failed"):
        return CLISource.CODEX

    # Live 事件标识（MCP 内部包装）
    if data.get("geminimcp") == "live":
        return CLISource.GEMINI
    if data.get("codexmcp") == "live":
        return CLISource.CODEX
    if data.get("claudemcp") == "live":
        return CLISource.CLAUDE
    if data.get("opencodemcp") == "live":
        return CLISource.OPENCODE

    return CLISource.UNKNOWN


def create_parser(source: CLISource | str) -> GeminiParser | CodexParser | ClaudeParser | OpencodeParser:
    """创建指定 CLI 的解析器实例。

    Args:
        source: CLI 来源标识

    Returns:
        对应的 Parser 实例

    Raises:
        ValueError: 不支持的 CLI 来源
    """
    if isinstance(source, str):
        source = CLISource(source.lower())

    if source == CLISource.GEMINI:
        return GeminiParser()
    elif source == CLISource.CODEX:
        return CodexParser()
    elif source == CLISource.CLAUDE:
        return ClaudeParser()
    elif source == CLISource.OPENCODE:
        return OpencodeParser()
    else:
        raise ValueError(f"Unsupported CLI source: {source}")


def parse_event(data: dict[str, Any]) -> UnifiedEvent:
    """自动检测并解析事件，返回单个事件。

    这是一个无状态的便捷函数，自动检测 CLI 来源并解析。
    对于需要维护状态的场景（如关联 tool_call 和 tool_result），
    请使用 create_parser() 创建 Parser 实例。

    注意：对于 Claude CLI，一个原始事件可能产生多个统一事件，
    此函数只返回第一个。如需获取所有事件，请使用 parse_events()。

    Args:
        data: 原始事件字典

    Returns:
        统一事件实例
    """
    events = parse_events(data)
    return events[0] if events else make_fallback_event(CLISource.UNKNOWN, data)


def parse_events(data: dict[str, Any]) -> list[UnifiedEvent]:
    """自动检测并解析事件，返回事件列表。

    对于 Claude CLI，一个原始事件（如 assistant 消息）可能包含
    多个内容块（thinking + text + tool_use），每个都会产生一个统一事件。

    Args:
        data: 原始事件字典

    Returns:
        统一事件列表
    """
    source = detect_source(data)

    if source == CLISource.GEMINI:
        return [parse_gemini_event(data)]
    elif source == CLISource.CODEX:
        return [parse_codex_event(data)]
    elif source == CLISource.CLAUDE:
        return parse_claude_event(data)
    elif source == CLISource.OPENCODE:
        return [parse_opencode_event(data)]
    else:
        # 无法识别的来源，返回 Fallback
        return [make_fallback_event(CLISource.UNKNOWN, data)]
