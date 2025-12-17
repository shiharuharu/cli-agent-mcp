"""Claude Agent 适配器 - 无状态。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from .base import AgentAdapter

if TYPE_CHECKING:
    from ..shared.parsers import UnifiedEvent

__all__ = ["ClaudeAdapter"]

# Permission 到 Claude tools 参数的映射
PERMISSION_MAP_CLAUDE = {
    "read-only": "Read,Grep,Glob",
    "workspace-write": "Read,Edit,Write,Bash",
    "unlimited": "default",
}


class ClaudeAdapter(AgentAdapter):
    """Claude CLI 适配器 - 无状态。

    只负责：
    - 命令行参数构建
    - session_id 抽取规则（claude 使用 system/init 事件中的 session_id）
    """

    def __init__(self, claude_path: str = "claude") -> None:
        """初始化适配器。

        Args:
            claude_path: claude 可执行文件路径
        """
        self._claude_path = claude_path

    @property
    def cli_type(self) -> str:
        return "claude"

    def build_command(self, params: Any) -> list[str]:
        """构建 Claude CLI 命令。

        Args:
            params: ClaudeParams 实例

        Returns:
            命令行参数列表
        """
        cmd = [self._claude_path]

        # 硬编码：非交互模式
        cmd.append("-p")

        # 硬编码：流式 JSON 输出
        cmd.extend(["--output-format", "stream-json"])
        cmd.append("--verbose")

        # 工作目录
        cmd.extend(["--add-dir", str(Path(params.workspace).absolute())])

        # Permission 映射到 tools 参数
        permission_value = params.permission.value if hasattr(params.permission, "value") else str(params.permission)
        tools_value = PERMISSION_MAP_CLAUDE.get(permission_value, "Read,Grep,Glob")
        cmd.extend(["--tools", tools_value])

        # 可选：模型
        if params.model:
            cmd.extend(["--model", params.model])

        # Claude 特有：系统提示词
        if hasattr(params, "system_prompt") and params.system_prompt:
            cmd.extend(["--system-prompt", params.system_prompt])
        elif hasattr(params, "append_system_prompt") and params.append_system_prompt:
            cmd.extend(["--append-system-prompt", params.append_system_prompt])

        # 会话恢复
        if params.session_id:
            cmd.extend(["--resume", params.session_id])

        return cmd

    def validate_params(self, params: Any) -> None:
        """验证 Claude 特有参数。"""
        super().validate_params(params)

        # 不能同时指定 system_prompt 和 append_system_prompt
        if (hasattr(params, "system_prompt") and params.system_prompt and
            hasattr(params, "append_system_prompt") and params.append_system_prompt):
            raise ValueError(
                "Cannot specify both system_prompt and append_system_prompt. "
                "Use system_prompt to completely override, or append_system_prompt to add to existing."
            )

    def extract_session_id(self, event: "UnifiedEvent") -> str | None:
        """从事件中提取 session_id。

        Claude 的 session_id 在 system/init 事件中。
        """
        # 先尝试基类的通用提取
        session_id = super().extract_session_id(event)
        if session_id:
            return session_id

        # Claude 特有：system/init 事件
        raw = event.raw
        if raw.get("type") == "system" and raw.get("subtype") == "init":
            session_id = raw.get("session_id", "")
            if session_id:
                return session_id

        return None
