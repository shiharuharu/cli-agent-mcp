"""Gemini CLI 事件解析器。

cli-agent-mcp shared/parsers v0.1.0
同步日期: 2025-12-16

将 Gemini CLI 的 JSON 流事件解析为统一格式。

Gemini CLI 事件类型:
- init: 会话初始化
- message: 用户/助手消息
- tool_use: 工具调用请求
- tool_result: 工具执行结果
- error: 错误事件
- result: 会话结束
"""

from __future__ import annotations

import json
from datetime import datetime
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
    "parse_gemini_event",
    "GeminiParser",
]


def _parse_timestamp(ts: str | None) -> float:
    """解析 ISO 时间戳为 Unix 时间戳。"""
    if not ts:
        import time
        return time.time()
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
        return dt.timestamp()
    except (ValueError, TypeError):
        import time
        return time.time()


class GeminiParser:
    """Gemini CLI 事件解析器。

    维护解析状态，支持流式事件的 ID 关联。

    Example:
        parser = GeminiParser()
        for line in stream:
            event = parser.parse(json.loads(line))
            if event:
                gui.push_event(event)
    """

    def __init__(self) -> None:
        self.session_id: str | None = None
        self.model: str | None = None
        self._tool_names: dict[str, str] = {}  # tool_id -> tool_name

    def parse(self, data: dict[str, Any]) -> UnifiedEvent:
        """解析单个 Gemini 事件。

        Args:
            data: 原始事件字典

        Returns:
            统一事件实例
        """
        event_type = data.get("type", "")
        timestamp = _parse_timestamp(data.get("timestamp"))

        base_kwargs = {
            "source": CLISource.GEMINI,
            "timestamp": timestamp,
            "raw": data,
        }

        # 分发到具体的解析方法
        if event_type == "init":
            return self._parse_init(data, base_kwargs)
        elif event_type == "message":
            return self._parse_message(data, base_kwargs)
        elif event_type == "tool_use":
            return self._parse_tool_use(data, base_kwargs)
        elif event_type == "tool_result":
            return self._parse_tool_result(data, base_kwargs)
        elif event_type == "error":
            return self._parse_error(data, base_kwargs)
        elif event_type == "result":
            return self._parse_result(data, base_kwargs)
        else:
            # Fallback: 未识别的事件类型
            return make_fallback_event(CLISource.GEMINI, data)

    def _parse_init(
        self, data: dict[str, Any], base: dict[str, Any]
    ) -> LifecycleEvent:
        """解析 init 事件。"""
        self.session_id = data.get("session_id")
        self.model = data.get("model")

        return LifecycleEvent(
            event_id=make_event_id("gemini", "init"),
            lifecycle_type="session_start",
            session_id=self.session_id,
            model=self.model,
            status=Status.SUCCESS,
            **base,
        )

    def _parse_message(
        self, data: dict[str, Any], base: dict[str, Any]
    ) -> MessageEvent:
        """解析 message 事件。"""
        role = data.get("role", "assistant")
        content = data.get("content", "")
        is_delta = data.get("delta", False)

        return MessageEvent(
            event_id=make_event_id("gemini", f"msg_{role}"),
            content_type=ContentType.TEXT,
            role=role if role in ("user", "assistant") else "assistant",
            text=content,
            is_delta=is_delta,
            session_id=self.session_id,
            **base,
        )

    def _parse_tool_use(
        self, data: dict[str, Any], base: dict[str, Any]
    ) -> OperationEvent:
        """解析 tool_use 事件。"""
        tool_name = data.get("tool_name", "unknown")
        tool_id = data.get("tool_id", "")
        parameters = data.get("parameters", {})

        # 缓存 tool_id -> tool_name 映射
        if tool_id:
            self._tool_names[tool_id] = tool_name

        # 将参数序列化为字符串
        try:
            input_str = json.dumps(parameters, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            input_str = str(parameters)

        return OperationEvent(
            event_id=make_event_id("gemini", f"tool_{tool_name}"),
            operation_type=OperationType.TOOL,
            name=tool_name,
            operation_id=tool_id,
            input=input_str,
            status=Status.RUNNING,
            session_id=self.session_id,  # 传递 session_id
            metadata={"parameters": parameters},
            **base,
        )

    def _parse_tool_result(
        self, data: dict[str, Any], base: dict[str, Any]
    ) -> OperationEvent:
        """解析 tool_result 事件。"""
        tool_id = data.get("tool_id", "")
        status_str = data.get("status", "success")
        output = data.get("output")
        error = data.get("error")

        # 从缓存获取工具名
        tool_name = self._tool_names.get(tool_id, "unknown")

        # 确定状态
        if status_str == "error" or error:
            status = Status.FAILED
            error_msg = ""
            if isinstance(error, dict):
                error_msg = error.get("message", "")
            elif isinstance(error, str):
                error_msg = error
            output_str = error_msg or output or ""
        else:
            status = Status.SUCCESS
            output_str = output if isinstance(output, str) else str(output) if output else ""

        return OperationEvent(
            event_id=make_event_id("gemini", f"result_{tool_name}"),
            operation_type=OperationType.TOOL,
            name=tool_name,
            operation_id=tool_id,
            output=output_str,
            status=status,
            session_id=self.session_id,  # 传递 session_id
            **base,
        )

    def _parse_error(
        self, data: dict[str, Any], base: dict[str, Any]
    ) -> SystemEvent:
        """解析 error 事件。"""
        severity = data.get("severity", "error")
        message = data.get("message", "Unknown error")

        # 映射 severity
        sev_map = {"warning": "warning", "error": "error"}
        unified_sev = sev_map.get(severity, "error")

        return SystemEvent(
            event_id=make_event_id("gemini", "error"),
            severity=unified_sev,
            message=message,
            session_id=self.session_id,  # 传递 session_id
            **base,
        )

    def _parse_result(
        self, data: dict[str, Any], base: dict[str, Any]
    ) -> LifecycleEvent:
        """解析 result 事件（会话结束）。"""
        status_str = data.get("status", "success")
        error = data.get("error")
        stats = data.get("stats", {})

        # 确定状态
        if status_str == "error" or error:
            status = Status.FAILED
        else:
            status = Status.SUCCESS

        # 构建统计信息
        unified_stats = {}
        if stats:
            unified_stats = {
                "total_tokens": stats.get("total_tokens"),
                "input_tokens": stats.get("input_tokens"),
                "output_tokens": stats.get("output_tokens"),
                "duration_ms": stats.get("duration_ms"),
                "tool_calls": stats.get("tool_calls"),
            }

        return LifecycleEvent(
            event_id=make_event_id("gemini", "result"),
            lifecycle_type="session_end",
            session_id=self.session_id,
            model=self.model,
            status=status,
            stats=unified_stats,
            **base,
        )


def parse_gemini_event(data: dict[str, Any]) -> UnifiedEvent:
    """无状态解析单个 Gemini 事件。

    注意: 此函数不维护状态，无法关联 tool_use 和 tool_result。
    如需完整功能，请使用 GeminiParser 类。

    Args:
        data: 原始事件字典

    Returns:
        统一事件实例
    """
    parser = GeminiParser()
    return parser.parse(data)
