"""Codex CLI 事件解析器。

cli-agent-mcp shared/parsers v0.1.0
同步日期: 2025-12-16

将 Codex CLI 的 JSON 流事件解析为统一格式。

Codex CLI 事件类型:
- thread.started: 会话开始
- turn.started: 轮次开始
- turn.completed: 轮次结束
- turn.failed: 轮次失败
- error: 错误事件
- item.started/item.updated/item.completed: 包含嵌套 item 对象
  - item.type: agent_message, reasoning, command_execution,
               file_change, function_call, function_call_output,
               mcp_tool_call, web_search, todo_list
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
    "parse_codex_event",
    "CodexParser",
]


class CodexParser:
    """Codex CLI 事件解析器。

    维护解析状态，支持 item 的 started/updated/completed 状态跟踪。

    Example:
        parser = CodexParser()
        for line in stream:
            event = parser.parse(json.loads(line))
            if event:
                gui.push_event(event)
    """

    def __init__(self) -> None:
        self.session_id: str | None = None
        self._item_states: dict[str, dict[str, Any]] = {}  # item_id -> item data
        self._function_names: dict[str, str] = {}  # call_id -> function name

    def parse(self, data: dict[str, Any]) -> UnifiedEvent:
        """解析单个 Codex 事件。

        Args:
            data: 原始事件字典

        Returns:
            统一事件实例
        """
        event_type = data.get("type", "")

        base_kwargs = {
            "source": CLISource.CODEX,
            "raw": data,
        }

        # 顶层事件分发
        if event_type == "thread.started":
            return self._parse_thread_started(data, base_kwargs)
        elif event_type == "turn.started":
            return self._parse_turn_started(data, base_kwargs)
        elif event_type == "turn.completed":
            return self._parse_turn_completed(data, base_kwargs)
        elif event_type == "turn.failed":
            return self._parse_turn_failed(data, base_kwargs)
        elif event_type == "error":
            return self._parse_error(data, base_kwargs)
        elif event_type in ("item.started", "item.updated", "item.completed"):
            return self._parse_item(data, event_type, base_kwargs)
        else:
            # Fallback: 未识别的事件类型
            return make_fallback_event(CLISource.CODEX, data)

    def _parse_thread_started(
        self, data: dict[str, Any], base: dict[str, Any]
    ) -> LifecycleEvent:
        """解析 thread.started 事件。"""
        self.session_id = data.get("thread_id")

        return LifecycleEvent(
            event_id=make_event_id("codex", "thread"),
            lifecycle_type="session_start",
            session_id=self.session_id,
            status=Status.SUCCESS,
            **base,
        )

    def _parse_turn_started(
        self, data: dict[str, Any], base: dict[str, Any]
    ) -> LifecycleEvent:
        """解析 turn.started 事件。"""
        return LifecycleEvent(
            event_id=make_event_id("codex", "turn_start"),
            lifecycle_type="turn_start",
            session_id=self.session_id,
            status=Status.RUNNING,
            **base,
        )

    def _parse_turn_completed(
        self, data: dict[str, Any], base: dict[str, Any]
    ) -> LifecycleEvent:
        """解析 turn.completed 事件。"""
        usage = data.get("usage", {})
        stats = {}
        if usage:
            stats = {
                "input_tokens": usage.get("input_tokens"),
                "cached_input_tokens": usage.get("cached_input_tokens"),
                "output_tokens": usage.get("output_tokens"),
            }

        return LifecycleEvent(
            event_id=make_event_id("codex", "turn_end"),
            lifecycle_type="turn_end",
            session_id=self.session_id,
            status=Status.SUCCESS,
            stats=stats,
            **base,
        )

    def _parse_turn_failed(
        self, data: dict[str, Any], base: dict[str, Any]
    ) -> LifecycleEvent:
        """解析 turn.failed 事件。"""
        error = data.get("error", {})
        error_msg = ""
        if isinstance(error, dict):
            error_msg = error.get("message", "Turn failed")
        elif isinstance(error, str):
            error_msg = error

        return LifecycleEvent(
            event_id=make_event_id("codex", "turn_fail"),
            lifecycle_type="turn_end",
            session_id=self.session_id,
            status=Status.FAILED,
            stats={"error": error_msg},
            **base,
        )

    def _parse_error(
        self, data: dict[str, Any], base: dict[str, Any]
    ) -> SystemEvent:
        """解析 error 事件。"""
        message = data.get("message", "Unknown error")

        return SystemEvent(
            event_id=make_event_id("codex", "error"),
            severity="error",
            message=message,
            **base,
        )

    def _parse_item(
        self, data: dict[str, Any], event_type: str, base: dict[str, Any]
    ) -> UnifiedEvent:
        """解析 item.* 事件。

        将嵌套的 item 结构扁平化为统一事件。
        """
        item = data.get("item", {})
        if not isinstance(item, dict):
            return make_fallback_event(CLISource.CODEX, data)

        item_type = item.get("type", "")
        item_id = item.get("id", "")
        item_status = item.get("status", "")
        is_completed = event_type == "item.completed"

        # 缓存 item 状态
        if item_id:
            self._item_states[item_id] = item

        # 根据 item.type 分发
        if item_type == "error":
            # item.completed 中的 error 类型（如 context limit warning）
            return SystemEvent(
                event_id=make_event_id("codex", "item_error"),
                severity="error",
                message=item.get("message") or item.get("text", "Unknown error"),
                session_id=self.session_id,
                **base,
            )
        elif item_type == "agent_message":
            return self._parse_agent_message(item, is_completed, base)
        elif item_type == "reasoning":
            return self._parse_reasoning(item, is_completed, base)
        elif item_type == "command_execution":
            return self._parse_command(item, item_status, is_completed, base)
        elif item_type == "file_change":
            return self._parse_file_change(item, item_status, is_completed, base)
        elif item_type == "function_call":
            return self._parse_function_call(item, is_completed, base)
        elif item_type == "function_call_output":
            return self._parse_function_output(item, is_completed, base)
        elif item_type == "mcp_tool_call":
            return self._parse_mcp_call(item, is_completed, base)
        elif item_type == "web_search":
            return self._parse_web_search(item, is_completed, base)
        elif item_type == "todo_list":
            return self._parse_todo_list(item, is_completed, base)
        else:
            # Fallback: 未识别的 item 类型
            return make_fallback_event(
                CLISource.CODEX, data, f"Unknown item type: {item_type}"
            )

    def _parse_agent_message(
        self, item: dict[str, Any], is_completed: bool, base: dict[str, Any]
    ) -> MessageEvent:
        """解析 agent_message。"""
        text = item.get("text", "")

        return MessageEvent(
            event_id=make_event_id("codex", "msg"),
            content_type=ContentType.TEXT,
            role="assistant",
            text=text,
            is_delta=not is_completed,
            session_id=self.session_id,
            **base,
        )

    def _parse_reasoning(
        self, item: dict[str, Any], is_completed: bool, base: dict[str, Any]
    ) -> MessageEvent:
        """解析 reasoning。"""
        text = item.get("text", "")

        return MessageEvent(
            event_id=make_event_id("codex", "reasoning"),
            content_type=ContentType.REASONING,
            role="assistant",
            text=text,
            is_delta=not is_completed,
            session_id=self.session_id,
            **base,
        )

    def _parse_command(
        self,
        item: dict[str, Any],
        item_status: str,
        is_completed: bool,
        base: dict[str, Any],
    ) -> OperationEvent:
        """解析 command_execution。"""
        command = item.get("command", "")
        output = item.get("aggregated_output", "")
        exit_code = item.get("exit_code")

        # 确定状态
        if is_completed:
            if exit_code is not None and exit_code != 0:
                status = Status.FAILED
            else:
                status = Status.SUCCESS
        elif item_status == "in_progress":
            status = Status.RUNNING
        else:
            status = Status.PENDING

        return OperationEvent(
            event_id=make_event_id("codex", "cmd"),
            operation_type=OperationType.COMMAND,
            name=command[:50] if command else "shell",
            input=command,
            output=output if output else None,
            status=status,
            session_id=self.session_id,
            metadata={
                "exit_code": exit_code,
                "item_id": item.get("id"),
            },
            **base,
        )

    def _parse_file_change(
        self,
        item: dict[str, Any],
        item_status: str,
        is_completed: bool,
        base: dict[str, Any],
    ) -> OperationEvent:
        """解析 file_change。"""
        changes = item.get("changes", [])

        # 构建变更摘要
        change_summary = []
        for c in changes[:10]:  # 最多显示 10 个
            if isinstance(c, dict):
                kind = c.get("kind", "")
                path = c.get("path", "")
                change_summary.append(f"{kind}: {path}")

        status = Status.SUCCESS if is_completed else Status.RUNNING

        return OperationEvent(
            event_id=make_event_id("codex", "file"),
            operation_type=OperationType.FILE,
            name=f"{len(changes)} files",
            output="\n".join(change_summary) if change_summary else None,
            status=status,
            session_id=self.session_id,
            metadata={
                "changes": changes,
                "count": len(changes),
            },
            **base,
        )

    def _parse_function_call(
        self, item: dict[str, Any], is_completed: bool, base: dict[str, Any]
    ) -> OperationEvent:
        """解析 function_call。"""
        name = item.get("name", "unknown")
        call_id = item.get("call_id", "")
        arguments = item.get("arguments", "{}")

        # 缓存 call_id -> name 映射
        if call_id:
            self._function_names[call_id] = name

        # 解析参数
        try:
            if isinstance(arguments, str):
                args = json.loads(arguments)
            else:
                args = arguments
            input_str = json.dumps(args, ensure_ascii=False, indent=2)
        except (json.JSONDecodeError, TypeError):
            input_str = str(arguments)

        return OperationEvent(
            event_id=make_event_id("codex", f"call_{name}"),
            operation_type=OperationType.TOOL,
            name=name,
            operation_id=call_id,
            input=input_str,
            status=Status.RUNNING,
            session_id=self.session_id,
            metadata={"arguments": arguments},
            **base,
        )

    def _parse_function_output(
        self, item: dict[str, Any], is_completed: bool, base: dict[str, Any]
    ) -> OperationEvent:
        """解析 function_call_output。"""
        call_id = item.get("call_id", "")
        output = item.get("output", "")

        # 从缓存获取函数名
        name = self._function_names.get(call_id, "unknown")

        # 判断是否有错误
        has_error = isinstance(output, str) and "error" in output.lower()
        status = Status.FAILED if has_error else Status.SUCCESS

        output_str = output if isinstance(output, str) else str(output)

        return OperationEvent(
            event_id=make_event_id("codex", f"output_{name}"),
            operation_type=OperationType.TOOL,
            name=name,
            operation_id=call_id,
            output=output_str,
            status=status,
            session_id=self.session_id,
            **base,
        )

    def _parse_mcp_call(
        self, item: dict[str, Any], is_completed: bool, base: dict[str, Any]
    ) -> OperationEvent:
        """解析 mcp_tool_call。"""
        server = item.get("server", "")
        tool = item.get("tool", "")
        arguments = item.get("arguments", {})
        result = item.get("result", {})
        error = item.get("error")

        name = f"{server}/{tool}" if server else tool

        # 确定状态
        if error:
            status = Status.FAILED
        elif is_completed and result:
            status = Status.SUCCESS
        else:
            status = Status.RUNNING

        # 解析输入
        try:
            input_str = json.dumps(arguments, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            input_str = str(arguments)

        # 解析输出
        output_str = None
        if error and isinstance(error, dict):
            output_str = error.get("message", str(error))
        elif result:
            # MCP 结果通常是 { content: [{ type: "text", text: "..." }] }
            content = result.get("content", [])
            texts = [
                b.get("text", "")
                for b in content[:5]
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            output_str = "\n".join(texts) if texts else str(result)

        return OperationEvent(
            event_id=make_event_id("codex", f"mcp_{tool}"),
            operation_type=OperationType.MCP,
            name=name,
            input=input_str,
            output=output_str,
            status=status,
            session_id=self.session_id,
            metadata={
                "server": server,
                "tool": tool,
                "arguments": arguments,
            },
            **base,
        )

    def _parse_web_search(
        self, item: dict[str, Any], is_completed: bool, base: dict[str, Any]
    ) -> OperationEvent:
        """解析 web_search。"""
        query = item.get("query", "")

        return OperationEvent(
            event_id=make_event_id("codex", "search"),
            operation_type=OperationType.SEARCH,
            name="web_search",
            input=query,
            status=Status.SUCCESS if is_completed else Status.RUNNING,
            session_id=self.session_id,
            **base,
        )

    def _parse_todo_list(
        self, item: dict[str, Any], is_completed: bool, base: dict[str, Any]
    ) -> OperationEvent:
        """解析 todo_list。"""
        items = item.get("items", [])

        # 构建待办摘要
        done_count = sum(
            1 for t in items if isinstance(t, dict) and t.get("completed", False)
        )
        total_count = len(items)

        # 构建输出文本
        todo_lines = []
        for t in items[:30]:  # 最多显示 30 个
            if isinstance(t, dict):
                marker = "✓" if t.get("completed", False) else "○"
                text = t.get("text", "")
                todo_lines.append(f"{marker} {text}")

        return OperationEvent(
            event_id=make_event_id("codex", "todo"),
            operation_type=OperationType.TODO,
            name=f"TODO {done_count}/{total_count}",
            output="\n".join(todo_lines) if todo_lines else None,
            status=Status.SUCCESS if is_completed else Status.RUNNING,
            session_id=self.session_id,
            metadata={
                "items": items,
                "done": done_count,
                "total": total_count,
            },
            **base,
        )


def parse_codex_event(data: dict[str, Any]) -> UnifiedEvent:
    """无状态解析单个 Codex 事件。

    注意: 此函数不维护状态，无法关联 function_call 和 function_call_output。
    如需完整功能，请使用 CodexParser 类。

    Args:
        data: 原始事件字典

    Returns:
        统一事件实例
    """
    parser = CodexParser()
    return parser.parse(data)
