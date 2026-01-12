"""统一事件模型定义。

cli-agent-mcp shared/parsers v0.1.0
同步日期: 2025-12-16

将不同 CLI 的事件格式统一为 GUI 可消费的标准模型。
设计原则：
1. 粗粒度分类 - 按 GUI 行为分为 4 大类
2. 向前兼容 - 使用 extra='ignore' 忽略未知字段
3. Fallback 友好 - 保留 raw 字段用于 Debug
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .base import (
    CLISource,
    ContentType,
    EventCategory,
    OperationType,
    Status,
)

__all__ = [
    # 基类
    "UnifiedEventBase",
    # 具体事件
    "LifecycleEvent",
    "MessageEvent",
    "OperationEvent",
    "SystemEvent",
    # 联合类型
    "UnifiedEvent",
    # 工厂函数
    "make_event_id",
    "make_fallback_event",
]


def make_event_id(source: str, hint: str = "") -> str:
    """生成事件 ID。

    格式: {source}_{hint}_{uuid短码}
    """
    short_uuid = uuid.uuid4().hex[:8]
    if hint:
        return f"{source}_{hint}_{short_uuid}"
    return f"{source}_{short_uuid}"


class UnifiedEventBase(BaseModel):
    """所有统一事件的基类。

    Attributes:
        event_id: 唯一 ID，用于去重和 UI 更新
        timestamp: Unix 时间戳（秒）
        source: CLI 来源标识
        category: 事件分类
        session_id: 会话 ID（可选）
        raw: 原始数据，用于 Debug 或 Fallback 展示
    """

    model_config = ConfigDict(
        extra="ignore",
        frozen=False,
    )

    event_id: str = Field(default_factory=lambda: make_event_id("unknown"))
    timestamp: float = Field(default_factory=time.time)
    source: CLISource = CLISource.UNKNOWN
    category: EventCategory
    session_id: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class LifecycleEvent(UnifiedEventBase):
    """生命周期事件。

    对应:
    - Gemini: init, result
    - Codex: thread.started, turn.started, turn.completed, turn.failed

    GUI 用途: 进度条、Spinner、会话状态指示
    """

    category: Literal[EventCategory.LIFECYCLE] = EventCategory.LIFECYCLE
    lifecycle_type: Literal[
        "session_start",
        "turn_start",
        "turn_end",
        "session_end",
    ]
    model: str | None = None
    status: Status = Status.SUCCESS
    stats: dict[str, Any] = Field(default_factory=dict)


class MessageEvent(UnifiedEventBase):
    """消息/内容事件。

    对应:
    - Gemini: message (role=user/assistant)
    - Codex: agent_message, reasoning

    GUI 用途: 聊天气泡、Markdown 渲染
    """

    category: Literal[EventCategory.MESSAGE] = EventCategory.MESSAGE
    content_type: ContentType = ContentType.TEXT
    role: Literal["user", "assistant"] = "assistant"
    text: str = ""
    is_delta: bool = False  # True=增量更新, False=全量


class OperationEvent(UnifiedEventBase):
    """操作/工具事件。

    对应:
    - Gemini: tool_use, tool_result
    - Codex: command_execution, file_change, function_call,
             mcp_tool_call, web_search, todo_list

    GUI 用途: 工具调用卡片、命令终端视图、文件变更列表
    """

    category: Literal[EventCategory.OPERATION] = EventCategory.OPERATION
    operation_type: OperationType
    name: str = ""              # 工具名 或 命令
    operation_id: str | None = None  # 用于关联 call 和 result
    input: str | None = None    # 参数、命令内容
    output: str | None = None   # 执行结果
    status: Status = Status.RUNNING
    # 特定类型的额外元数据（使用 Dict 保持灵活性）
    metadata: dict[str, Any] = Field(default_factory=dict)


class SystemEvent(UnifiedEventBase):
    """系统/错误事件。

    用于:
    - 错误和警告
    - 未识别的事件类型（Fallback）
    - 调试信息

    GUI 用途: Toast 提示、Debug 面板
    """

    category: Literal[EventCategory.SYSTEM] = EventCategory.SYSTEM
    severity: Literal["debug", "info", "warning", "error"] = "info"
    message: str = ""
    is_fallback: bool = False  # True 表示这是未识别事件的 fallback


# 统一联合类型
UnifiedEvent = LifecycleEvent | MessageEvent | OperationEvent | SystemEvent


def make_fallback_event(
    source: CLISource,
    raw: dict[str, Any],
    message: str | None = None,
) -> SystemEvent:
    """创建 Fallback 事件。

    当遇到无法识别的事件类型时，包装为 SystemEvent。
    也可用于创建合成的系统事件（如错误、取消等）。
    GUI 可以选择显示 Debug 视图或忽略。

    Args:
        source: CLI 来源
        raw: 原始事件数据
        message: 可选的说明消息（优先于 raw 中的 message）

    Returns:
        SystemEvent 实例
    """
    event_type = raw.get("type", "unknown")

    # 从 raw 提取 severity，默认 debug
    severity = raw.get("severity", "debug")
    if severity not in ("debug", "info", "warning", "error"):
        severity = "debug"

    # 从 raw 提取 message，或使用默认
    candidate_message = message or raw.get("message") or f"Unknown event type: {event_type}"
    if isinstance(candidate_message, str):
        final_message = candidate_message
    else:
        try:
            final_message = json.dumps(candidate_message, ensure_ascii=False, default=str)
        except Exception:
            final_message = str(candidate_message)

    # 如果有明确的 severity/message，说明这是合成事件而非未知事件
    is_fallback = raw.get("severity") is None and raw.get("message") is None

    return SystemEvent(
        event_id=make_event_id(source.value, "fallback"),
        source=source,
        severity=severity,
        message=final_message,
        raw=raw,
        is_fallback=is_fallback,
    )
