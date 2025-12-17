"""MCP 调用器类型定义。

cli-agent-mcp shared/mcp v0.1.0
同步日期: 2025-12-16

定义公共参数、权限映射、返回结构等类型。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal

__all__ = [
    "Permission",
    "CLIType",
    "CommonParams",
    "CodexParams",
    "GeminiParams",
    "ClaudeParams",
    "OpencodeParams",
    "ExecutionResult",
    "GUIMetadata",
    "DebugInfo",
    "PERMISSION_MAP_CODEX",
    "PERMISSION_MAP_CLAUDE",
]


class Permission(str, Enum):
    """权限级别枚举。

    控制 CLI 对文件系统的访问权限：
    - read_only: 只读，不能修改任何文件（最安全）
    - workspace_write: 可写，但限制在 workspace 内
    - unlimited: 无限制，可以访问/修改任何位置
    """

    READ_ONLY = "read-only"
    WORKSPACE_WRITE = "workspace-write"
    UNLIMITED = "unlimited"


class CLIType(str, Enum):
    """CLI 类型枚举。"""

    CODEX = "codex"
    GEMINI = "gemini"
    CLAUDE = "claude"
    OPENCODE = "opencode"


# Permission 到 Codex sandbox 参数的映射
PERMISSION_MAP_CODEX: dict[Permission, str] = {
    Permission.READ_ONLY: "read-only",
    Permission.WORKSPACE_WRITE: "workspace-write",
    Permission.UNLIMITED: "danger-full-access",
}

# Permission 到 Claude tools 参数的映射
PERMISSION_MAP_CLAUDE: dict[Permission, str] = {
    Permission.READ_ONLY: "Read,Grep,Glob",
    Permission.WORKSPACE_WRITE: "Read,Edit,Write,Bash",
    Permission.UNLIMITED: "default",
}


@dataclass
class CommonParams:
    """公共参数。

    所有三个 CLI 共享的参数集合。

    Attributes:
        prompt: 任务指令（必需）
        workspace: 工作目录，标定允许操作的范围（必需）
        permission: 读写权限
        session_id: 恢复指定会话
        model: 模型选择
        full_output: 返回完整过程信息
        task_note: 任务备注，用于 GUI 显示
        task_tags: 任务标签列表
    """

    prompt: str
    workspace: Path
    permission: Permission = Permission.READ_ONLY
    session_id: str = ""
    model: str = ""
    full_output: bool = False
    task_note: str = ""
    task_tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """确保 workspace 是 Path 对象，permission 是枚举。"""
        if isinstance(self.workspace, str):
            self.workspace = Path(self.workspace)
        if isinstance(self.permission, str):
            self.permission = Permission(self.permission)


@dataclass
class CodexParams(CommonParams):
    """Codex CLI 参数。

    继承公共参数，增加 Codex 特有参数。

    Attributes:
        image: 附加图片路径列表
    """

    image: list[Path] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        # 确保 image 是 Path 列表
        self.image = [Path(p) if isinstance(p, str) else p for p in self.image]


@dataclass
class GeminiParams(CommonParams):
    """Gemini CLI 参数。

    继承公共参数，无特有参数。
    """

    pass


@dataclass
class ClaudeParams(CommonParams):
    """Claude CLI 参数。

    继承公共参数，增加 Claude 特有参数。

    Attributes:
        system_prompt: 覆盖默认系统提示词
        append_system_prompt: 追加到默认系统提示词末尾
        agent: 指定 agent 名称（覆盖默认 agent 设置）
    """

    system_prompt: str = ""
    append_system_prompt: str = ""
    agent: str = ""


@dataclass
class OpencodeParams(CommonParams):
    """OpenCode CLI 参数。

    继承公共参数，增加 OpenCode 特有参数。

    Attributes:
        file: 附加文件路径列表
        agent: 使用的 agent 名称（默认 "build"）
    """

    file: list[Path] = field(default_factory=list)
    agent: str = "build"

    def __post_init__(self) -> None:
        super().__post_init__()
        # 确保 file 是 Path 列表
        self.file = [Path(p) if isinstance(p, str) else p for p in self.file]


@dataclass
class GUIMetadata:
    """GUI 元数据。

    随执行结果返回的 GUI 显示信息。

    Attributes:
        task_note: 任务备注
        task_tags: 任务标签
        source: CLI 来源
        start_time: 开始时间戳
        end_time: 结束时间戳
    """

    task_note: str = ""
    task_tags: list[str] = field(default_factory=list)
    source: str = ""
    start_time: float = 0.0
    end_time: float = 0.0


@dataclass
class DebugInfo:
    """调试信息。

    尽力而为收集的执行统计信息。

    Attributes:
        model: 模型名称
        duration_sec: 执行时长（秒，带小数）
        message_count: 消息数量
        tool_call_count: 工具调用次数
        input_tokens: 输入 token 数（如果可用）
        output_tokens: 输出 token 数（如果可用）
        exit_code: CLI 退出码（仅当非零时有意义）
        cancelled: 是否被取消
    """

    model: str = ""
    duration_sec: float = 0.0
    message_count: int = 0
    tool_call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    exit_code: int | None = None
    cancelled: bool = False

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        result: dict[str, Any] = {
            "model": self.model,
            "duration_sec": round(self.duration_sec, 3),
            "message_count": self.message_count,
            "tool_call_count": self.tool_call_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }
        if self.exit_code is not None:
            result["exit_code"] = self.exit_code
        if self.cancelled:
            result["cancelled"] = self.cancelled
        return result


@dataclass
class ExecutionResult:
    """执行结果。

    CLI 调用返回的统一结果结构。

    Attributes:
        success: 执行是否成功
        session_id: 会话 ID，用于后续恢复
        agent_messages: 最终答案（最后一条 agent 回复）
        thought_steps: 中间思考步骤（除最后一条外的 agent 消息）
        error: 错误信息（仅失败时）
        all_messages: 完整消息列表（仅 full_output=True）
        log_file: 日志文件路径
        gui_metadata: GUI 元数据
        debug_info: 调试信息（仅 debug=True）
        cancelled: 是否被取消
    """

    success: bool
    session_id: str = ""
    agent_messages: str = ""  # 最终答案
    thought_steps: list[str] = field(default_factory=list)  # 中间消息
    error: str | None = None
    all_messages: list[dict[str, Any]] | None = None
    log_file: str | None = None
    gui_metadata: GUIMetadata | None = None
    debug_info: DebugInfo | None = None
    cancelled: bool = False

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        result: dict[str, Any] = {
            "success": self.success,
            "session_id": self.session_id,
            "agent_messages": self.agent_messages,
        }
        if self.error:
            result["error"] = self.error
        if self.cancelled:
            result["cancelled"] = True
        if self.all_messages is not None:
            result["all_messages"] = self.all_messages
        if self.log_file:
            result["log_file"] = self.log_file
        if self.gui_metadata:
            result["gui_metadata"] = {
                "task_note": self.gui_metadata.task_note,
                "task_tags": self.gui_metadata.task_tags,
                "source": self.gui_metadata.source,
                "start_time": self.gui_metadata.start_time,
                "end_time": self.gui_metadata.end_time,
            }
        if self.debug_info:
            result["debug_info"] = self.debug_info.to_dict()
        return result
