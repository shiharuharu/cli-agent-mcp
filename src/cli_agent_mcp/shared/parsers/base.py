"""基础类型和枚举定义。

cli-agent-mcp shared/parsers v0.1.0
同步日期: 2025-12-16

本模块定义了统一事件系统的基础类型，包括：
- CLI 来源标识
- 事件分类枚举
- 状态机枚举
"""

from __future__ import annotations

from enum import Enum
from typing import Final

__all__ = [
    # CLI 来源
    "CLISource",
    # 事件分类
    "EventCategory",
    "ContentType",
    "OperationType",
    "Status",
    # 版本信息
    "VERSION",
]

# 模块版本，用于分发追踪
VERSION: Final[str] = "0.1.0"


class CLISource(str, Enum):
    """CLI 来源标识。

    标识事件来自哪个 CLI 客户端或工具。
    设计为可扩展，新增 CLI/工具只需添加枚举值。
    """

    GEMINI = "gemini"
    CODEX = "codex"
    CLAUDE = "claude"
    OPENCODE = "opencode"
    BANANA = "banana"    # 图像生成工具
    IMAGE = "image"      # 图像生成工具
    UNKNOWN = "unknown"


class EventCategory(str, Enum):
    """顶层事件分类。

    决定 GUI 如何渲染容器：
    - LIFECYCLE: 进度条、Spinner、会话状态
    - MESSAGE: 聊天气泡、文本内容
    - OPERATION: 工具调用卡片、命令终端视图
    - SYSTEM: Toast 提示、Debug 面板
    """

    LIFECYCLE = "lifecycle"
    MESSAGE = "message"
    OPERATION = "operation"
    SYSTEM = "system"


class ContentType(str, Enum):
    """消息内容子类型。"""

    TEXT = "text"
    REASONING = "reasoning"  # 思考过程


class OperationType(str, Enum):
    """操作子类型。"""

    COMMAND = "command"       # Shell 命令执行
    FILE = "file_change"      # 文件修改
    TOOL = "tool_call"        # 通用工具调用
    MCP = "mcp_call"          # MCP 工具调用
    SEARCH = "web_search"     # Web 搜索
    TODO = "todo"             # 待办事项


class Status(str, Enum):
    """统一状态机。

    表示操作的执行状态，GUI 可据此显示不同的视觉指示。
    """

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
