"""Gemini Agent 适配器 - 无状态。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from .base import AgentAdapter

if TYPE_CHECKING:
    from ..shared.parsers import UnifiedEvent

__all__ = ["GeminiAdapter"]


class GeminiAdapter(AgentAdapter):
    """Gemini CLI 适配器 - 无状态。

    只负责：
    - 命令行参数构建
    - session_id 抽取规则（gemini 使用 init 事件中的 session_id）
    """

    def __init__(self, gemini_path: str = "gemini") -> None:
        """初始化适配器。

        Args:
            gemini_path: gemini 可执行文件路径
        """
        self._gemini_path = gemini_path

    @property
    def cli_type(self) -> str:
        return "gemini"

    @property
    def uses_stdin_prompt(self) -> bool:
        """Gemini 使用位置参数而非 stdin 传递 prompt。"""
        return False

    def build_command(self, params: Any) -> list[str]:
        """构建 Gemini CLI 命令。

        Args:
            params: GeminiParams 实例

        Returns:
            命令行参数列表
        """
        cmd = [self._gemini_path]

        # 硬编码：流式 JSON 输出
        cmd.extend(["-o", "stream-json"])

        # 工作目录
        cmd.extend(["--include-directories", str(Path(params.workspace).absolute())])

        # Permission 映射
        # Gemini 的 sandbox 是开关式的
        permission_value = params.permission.value if hasattr(params.permission, "value") else str(params.permission)
        if permission_value != "unlimited":
            cmd.append("--sandbox")

        # 可选：模型
        if params.model:
            cmd.extend(["--model", params.model])

        # 会话恢复
        if params.session_id:
            cmd.extend(["--resume", params.session_id])

        # Prompt 作为位置参数
        cmd.append(params.prompt)

        return cmd

    def extract_session_id(self, event: "UnifiedEvent") -> str | None:
        """从事件中提取 session_id。

        Gemini 的 session_id 在 init 事件中。
        """
        # 先尝试基类的通用提取
        session_id = super().extract_session_id(event)
        if session_id:
            return session_id

        # Gemini 特有：init 事件
        raw = event.raw
        if raw.get("type") == "init":
            session_id = raw.get("session_id", "")
            if session_id:
                return session_id

        return None
