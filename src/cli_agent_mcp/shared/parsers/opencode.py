"""OpenCode CLI 事件解析器。

cli-agent-mcp shared/parsers v0.1.0
同步日期: 2025-12-17

将 OpenCode CLI 的 JSON 流事件解析为统一格式。

OpenCode CLI 事件类型:
- tool_use: 工具调用完成
- step_start: 步骤开始
- step_finish: 步骤结束
- text: 文本输出
- error: 错误事件
"""

from __future__ import annotations

import json
import time
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
    "parse_opencode_event",
    "OpencodeParser",
]


class OpencodeParser:
    """OpenCode CLI 事件解析器。

    维护解析状态，支持流式事件的 ID 关联。

    Example:
        parser = OpencodeParser()
        for line in stream:
            event = parser.parse(json.loads(line))
            if event:
                gui.push_event(event)
    """

    def __init__(self) -> None:
        self.session_id: str | None = None
        self.model: str | None = None

    def parse(self, data: dict[str, Any]) -> UnifiedEvent:
        """解析单个 OpenCode 事件。

        Args:
            data: 原始事件字典

        Returns:
            统一事件实例
        """
        event_type = data.get("type", "")
        timestamp = data.get("timestamp", time.time() * 1000)
        # OpenCode 使用毫秒时间戳，转换为秒
        if timestamp > 10000000000:  # 如果是毫秒
            timestamp = timestamp / 1000

        # 从事件中提取 sessionID
        session_id = data.get("sessionID", "")
        if session_id and not self.session_id:
            self.session_id = session_id

        base_kwargs = {
            "source": CLISource.OPENCODE,
            "timestamp": timestamp,
            "raw": data,
            "session_id": self.session_id,
        }

        # 分发到具体的解析方法
        if event_type == "tool_use":
            return self._parse_tool_use(data, base_kwargs)
        elif event_type == "step_start":
            return self._parse_step_start(data, base_kwargs)
        elif event_type == "step_finish":
            return self._parse_step_finish(data, base_kwargs)
        elif event_type == "text":
            return self._parse_text(data, base_kwargs)
        elif event_type == "error":
            return self._parse_error(data, base_kwargs)
        else:
            # Fallback: 未识别的事件类型
            return make_fallback_event(CLISource.OPENCODE, data)

    def _parse_tool_use(
        self, data: dict[str, Any], base: dict[str, Any]
    ) -> OperationEvent:
        """解析 tool_use 事件。"""
        part = data.get("part", {})
        tool_name = part.get("tool", "unknown")
        state = part.get("state", {})

        # 获取工具输入参数
        input_data = state.get("input", {})
        try:
            input_str = json.dumps(input_data, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            input_str = str(input_data)

        # 获取工具输出
        output = state.get("output", "")
        title = state.get("title", "")

        # 确定状态
        status_str = state.get("status", "completed")
        if status_str == "completed":
            status = Status.SUCCESS
        elif status_str == "running":
            status = Status.RUNNING
        elif status_str == "failed" or status_str == "error":
            status = Status.FAILED
        else:
            status = Status.SUCCESS

        return OperationEvent(
            event_id=make_event_id("opencode", f"tool_{tool_name}"),
            operation_type=OperationType.TOOL,
            name=tool_name,
            input=input_str,
            output=output or title,
            status=status,
            metadata={"state": state, "title": title},
            **base,
        )

    def _parse_step_start(
        self, data: dict[str, Any], base: dict[str, Any]
    ) -> LifecycleEvent:
        """解析 step_start 事件。"""
        return LifecycleEvent(
            event_id=make_event_id("opencode", "step_start"),
            lifecycle_type="turn_start",
            status=Status.RUNNING,
            **base,
        )

    def _parse_step_finish(
        self, data: dict[str, Any], base: dict[str, Any]
    ) -> LifecycleEvent:
        """解析 step_finish 事件。"""
        return LifecycleEvent(
            event_id=make_event_id("opencode", "step_finish"),
            lifecycle_type="turn_end",
            status=Status.SUCCESS,
            **base,
        )

    def _parse_text(
        self, data: dict[str, Any], base: dict[str, Any]
    ) -> MessageEvent:
        """解析 text 事件。"""
        part = data.get("part", {})
        text = part.get("text", "")
        time_info = part.get("time", {})

        # 如果有 end 时间，说明是完整消息
        is_delta = not time_info.get("end")

        return MessageEvent(
            event_id=make_event_id("opencode", "text"),
            content_type=ContentType.TEXT,
            role="assistant",
            text=text,
            is_delta=is_delta,
            **base,
        )

    def _parse_error(
        self, data: dict[str, Any], base: dict[str, Any]
    ) -> SystemEvent:
        """解析 error 事件。"""
        error = data.get("error", {})
        if isinstance(error, dict):
            message = error.get("message", error.get("name", "Unknown error"))
            if "data" in error and isinstance(error["data"], dict):
                message = error["data"].get("message", message)
        else:
            message = str(error)

        return SystemEvent(
            event_id=make_event_id("opencode", "error"),
            severity="error",
            message=message,
            **base,
        )


def parse_opencode_event(data: dict[str, Any]) -> UnifiedEvent:
    """无状态解析单个 OpenCode 事件。

    注意: 此函数不维护状态。
    如需完整功能，请使用 OpencodeParser 类。

    Args:
        data: 原始事件字典

    Returns:
        统一事件实例
    """
    parser = OpencodeParser()
    return parser.parse(data)
