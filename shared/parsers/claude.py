"""Claude Code CLI 事件解析器。

cli-agent-mcp shared/parsers v0.1.0
同步日期: 2025-12-16

将 Claude Code CLI 的 JSON 流事件解析为统一格式。

Claude Code CLI 事件类型:
- system/init: 会话初始化（包含 session_id, model, tools, mcp_servers 等）
- assistant: 助手消息，content[] 可包含 thinking/text/tool_use
- user: 用户消息或工具结果，content[] 可包含 tool_result
- result: 会话结束，包含统计信息
"""

from __future__ import annotations

import json
from typing import Any

from .base import CLISource, ContentType, OperationType, Status
from .unified import (
    LifecycleEvent,
    MessageEvent,
    OperationEvent,
    SystemEvent,
    UnifiedEvent,
    make_event_id,
    make_fallback_event,
)

__all__ = [
    "parse_claude_event",
    "ClaudeParser",
]


class ClaudeParser:
    """Claude Code CLI 事件解析器。

    Claude Code 的 stream-json 格式特点：
    - 顶层 type: system/assistant/user/result
    - assistant/user 消息的 content 是数组，可包含多种内容类型
    - tool_use 和 tool_result 嵌套在消息的 content 数组中

    Example:
        parser = ClaudeParser()
        for line in stream:
            events = parser.parse(json.loads(line))
            for event in events:
                gui.push_event(event)
    """

    def __init__(self) -> None:
        self.session_id: str | None = None
        self.model: str | None = None
        self._tool_names: dict[str, str] = {}  # tool_use_id -> tool_name

    def parse(self, data: dict[str, Any]) -> list[UnifiedEvent]:
        """解析单个 Claude 事件。

        注意：一个 Claude 事件可能产生多个统一事件
        （例如一个 assistant 消息包含 thinking + tool_use）

        Args:
            data: 原始事件字典

        Returns:
            统一事件列表
        """
        event_type = data.get("type", "")
        subtype = data.get("subtype", "")

        base_kwargs = {
            "source": CLISource.CLAUDE,
            "raw": data,
        }

        if event_type == "system" and subtype == "init":
            return [self._parse_init(data, base_kwargs)]
        elif event_type == "assistant":
            return self._parse_assistant(data, base_kwargs)
        elif event_type == "user":
            return self._parse_user(data, base_kwargs)
        elif event_type == "result":
            return [self._parse_result(data, base_kwargs)]
        else:
            # Fallback: 未识别的事件类型
            return [make_fallback_event(CLISource.CLAUDE, data)]

    def _parse_init(
        self, data: dict[str, Any], base: dict[str, Any]
    ) -> LifecycleEvent:
        """解析 system/init 事件。"""
        self.session_id = data.get("session_id")
        self.model = data.get("model")

        return LifecycleEvent(
            event_id=make_event_id("claude", "init"),
            lifecycle_type="session_start",
            session_id=self.session_id,
            model=self.model,
            status=Status.SUCCESS,
            stats={
                "cwd": data.get("cwd"),
                "tools_count": len(data.get("tools", [])),
                "mcp_servers": [
                    s.get("name") for s in data.get("mcp_servers", [])
                    if s.get("status") == "connected"
                ],
                "claude_code_version": data.get("claude_code_version"),
            },
            **base,
        )

    def _parse_assistant(
        self, data: dict[str, Any], base: dict[str, Any]
    ) -> list[UnifiedEvent]:
        """解析 assistant 消息。

        一个 assistant 消息的 content[] 可能包含多个内容块：
        - thinking: 思考过程
        - text: 文本输出
        - tool_use: 工具调用
        """
        events: list[UnifiedEvent] = []
        message = data.get("message", {})
        content_list = message.get("content", [])
        session_id = data.get("session_id") or self.session_id

        for content in content_list:
            content_type = content.get("type", "")

            if content_type == "thinking":
                # 思考过程
                thinking_text = content.get("thinking", "")
                if thinking_text:
                    events.append(MessageEvent(
                        event_id=make_event_id("claude", "thinking"),
                        content_type=ContentType.REASONING,
                        role="assistant",
                        text=thinking_text,
                        is_delta=False,
                        session_id=session_id,  # 传递 session_id
                        **base,
                    ))

            elif content_type == "text":
                # 文本输出
                text = content.get("text", "")
                if text:
                    events.append(MessageEvent(
                        event_id=make_event_id("claude", "text"),
                        content_type=ContentType.TEXT,
                        role="assistant",
                        text=text,
                        is_delta=False,
                        session_id=session_id,  # 传递 session_id
                        **base,
                    ))

            elif content_type == "tool_use":
                # 工具调用
                tool_name = content.get("name", "unknown")
                tool_id = content.get("id", "")
                tool_input = content.get("input", {})

                # 缓存 tool_id -> tool_name
                if tool_id:
                    self._tool_names[tool_id] = tool_name

                # 序列化输入
                try:
                    input_str = json.dumps(tool_input, ensure_ascii=False, indent=2)
                except (TypeError, ValueError):
                    input_str = str(tool_input)

                # 确定操作类型
                op_type = self._get_operation_type(tool_name)

                events.append(OperationEvent(
                    event_id=make_event_id("claude", f"call_{tool_name}"),
                    operation_type=op_type,
                    name=tool_name,
                    operation_id=tool_id,
                    input=input_str,
                    status=Status.RUNNING,
                    session_id=session_id,  # 传递 session_id
                    metadata={"input": tool_input},
                    **base,
                ))

        return events if events else [make_fallback_event(CLISource.CLAUDE, data)]

    def _parse_user(
        self, data: dict[str, Any], base: dict[str, Any]
    ) -> list[UnifiedEvent]:
        """解析 user 消息。

        user 消息通常包含 tool_result（工具执行结果）。
        """
        events: list[UnifiedEvent] = []
        message = data.get("message", {})
        content_list = message.get("content", [])
        session_id = data.get("session_id") or self.session_id

        for content in content_list:
            content_type = content.get("type", "")

            if content_type == "tool_result":
                tool_id = content.get("tool_use_id", "")
                output = content.get("content", "")
                is_error = content.get("is_error", False)

                # 从缓存获取工具名
                tool_name = self._tool_names.get(tool_id, "unknown")
                op_type = self._get_operation_type(tool_name)

                events.append(OperationEvent(
                    event_id=make_event_id("claude", f"result_{tool_name}"),
                    operation_type=op_type,
                    name=tool_name,
                    operation_id=tool_id,
                    output=output if isinstance(output, str) else str(output),
                    status=Status.FAILED if is_error else Status.SUCCESS,
                    session_id=session_id,  # 传递 session_id
                    **base,
                ))

            elif content_type == "text":
                # 用户文本输入（较少见）
                text = content.get("text", "")
                if text:
                    events.append(MessageEvent(
                        event_id=make_event_id("claude", "user_text"),
                        content_type=ContentType.TEXT,
                        role="user",
                        text=text,
                        is_delta=False,
                        session_id=session_id,  # 传递 session_id
                        **base,
                    ))

        return events if events else [make_fallback_event(CLISource.CLAUDE, data)]

    def _parse_result(
        self, data: dict[str, Any], base: dict[str, Any]
    ) -> LifecycleEvent:
        """解析 result 事件（会话结束）。"""
        subtype = data.get("subtype", "")
        is_error = data.get("is_error", False)
        usage = data.get("usage", {})

        status = Status.FAILED if is_error or subtype == "error" else Status.SUCCESS

        stats = {
            "duration_ms": data.get("duration_ms"),
            "duration_api_ms": data.get("duration_api_ms"),
            "num_turns": data.get("num_turns"),
            "total_cost_usd": data.get("total_cost_usd"),
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
        }

        return LifecycleEvent(
            event_id=make_event_id("claude", "result"),
            lifecycle_type="session_end",
            session_id=data.get("session_id") or self.session_id,
            model=self.model,
            status=status,
            stats=stats,
            **base,
        )

    def _get_operation_type(self, tool_name: str) -> OperationType:
        """根据工具名确定操作类型。"""
        name_lower = tool_name.lower()

        if name_lower == "bash":
            return OperationType.COMMAND
        elif name_lower in ("edit", "write"):
            return OperationType.FILE
        elif name_lower == "websearch":
            return OperationType.SEARCH
        elif name_lower == "todowrite":
            return OperationType.TODO
        elif name_lower.startswith("mcp__"):
            return OperationType.MCP
        else:
            return OperationType.TOOL


def parse_claude_event(data: dict[str, Any]) -> list[UnifiedEvent]:
    """无状态解析单个 Claude 事件。

    注意：
    1. 此函数不维护状态，无法关联 tool_use 和 tool_result 的工具名
    2. 返回的是事件列表（一个 Claude 事件可能产生多个统一事件）

    如需完整功能，请使用 ClaudeParser 类。

    Args:
        data: 原始事件字典

    Returns:
        统一事件列表
    """
    parser = ClaudeParser()
    return parser.parse(data)
