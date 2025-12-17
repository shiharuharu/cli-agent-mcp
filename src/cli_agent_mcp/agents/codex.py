"""Codex Agent 适配器 - 无状态。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from .base import AgentAdapter

if TYPE_CHECKING:
    from ..shared.parsers import UnifiedEvent

__all__ = ["CodexAdapter"]

# Permission 到 Codex sandbox 参数的映射
PERMISSION_MAP_CODEX = {
    "read-only": "read-only",
    "workspace-write": "workspace-write",
    "unlimited": "danger-full-access",
}


class CodexAdapter(AgentAdapter):
    """Codex CLI 适配器 - 无状态。

    只负责：
    - 命令行参数构建
    - session_id 抽取规则（codex 使用 thread_id）
    """

    def __init__(self, codex_path: str = "codex") -> None:
        """初始化适配器。

        Args:
            codex_path: codex 可执行文件路径
        """
        self._codex_path = codex_path

    @property
    def cli_type(self) -> str:
        return "codex"

    def build_command(self, params: Any) -> list[str]:
        """构建 Codex CLI 命令。

        Args:
            params: CodexParams 实例

        Returns:
            命令行参数列表
        """
        cmd = [self._codex_path, "exec"]

        # 工作目录
        cmd.extend(["--cd", str(Path(params.workspace).absolute())])

        # Permission 映射到 sandbox 参数
        permission_value = params.permission.value if hasattr(params.permission, "value") else str(params.permission)
        sandbox_value = PERMISSION_MAP_CODEX.get(permission_value, "read-only")
        cmd.extend(["--sandbox", sandbox_value])

        # 硬编码参数
        cmd.append("--skip-git-repo-check")
        cmd.append("--json")

        # 可选：模型
        if params.model:
            cmd.extend(["--model", params.model])

        # Codex 特有：图片附件
        if hasattr(params, "image"):
            for img_path in params.image:
                cmd.extend(["--image", str(Path(img_path).absolute())])

        # 会话恢复
        if params.session_id:
            cmd.append("resume")
            cmd.append(params.session_id)

        # Prompt 通过 stdin 传递（使用 -- 分隔）
        cmd.append("--")

        return cmd

    def validate_params(self, params: Any) -> None:
        """验证 Codex 特有参数。"""
        super().validate_params(params)

        # 验证图片路径
        if hasattr(params, "image"):
            for img_path in params.image:
                if not Path(img_path).exists():
                    raise ValueError(f"Image file does not exist: {img_path}")

    def extract_session_id(self, event: "UnifiedEvent") -> str | None:
        """从事件中提取 session_id。

        Codex 的 session_id 在 thread.started 事件的 thread_id 字段中。
        """
        # 先尝试基类的通用提取
        session_id = super().extract_session_id(event)
        if session_id:
            return session_id

        # Codex 特有：thread.started 事件
        raw = event.raw
        if raw.get("type") == "thread.started":
            thread_id = raw.get("thread_id", "")
            if thread_id:
                return thread_id

        return None
