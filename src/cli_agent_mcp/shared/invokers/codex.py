"""Codex CLI 调用器。

cli-agent-mcp shared/mcp v0.1.0
同步日期: 2025-12-16

实现 Codex CLI 的命令构建和调用逻辑。

命令格式:
    codex exec \
      --cd {workspace} \
      --sandbox {permission} \
      --skip-git-repo-check \
      --json \
      [--image {image}] \
      [--model {model}] \
      [resume {session_id}] \
      -- "{prompt}"
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import CLIInvoker, EventCallback
from .types import (
    CLIType,
    CodexParams,
    CommonParams,
    Permission,
    PERMISSION_MAP_CODEX,
)

__all__ = ["CodexInvoker"]


class CodexInvoker(CLIInvoker):
    """Codex CLI 调用器。

    封装 Codex CLI 的调用逻辑，包括：
    - 命令行参数构建
    - Permission 到 --sandbox 参数映射
    - 图片附件支持

    Example:
        invoker = CodexInvoker()
        result = await invoker.execute(CodexParams(
            prompt="Review this code",
            workspace=Path("/path/to/repo"),
            image=[Path("screenshot.png")],
        ))
    """

    def __init__(
        self,
        codex_path: str = "codex",
        event_callback: EventCallback | None = None,
        parser: Any | None = None,
    ) -> None:
        """初始化 Codex 调用器。

        Args:
            codex_path: codex 可执行文件路径，默认 "codex"
            event_callback: 事件回调函数
            parser: 自定义解析器
        """
        super().__init__(event_callback=event_callback, parser=parser)
        self._codex_path = codex_path

    @property
    def cli_type(self) -> CLIType:
        return CLIType.CODEX

    def validate_params(self, params: CommonParams) -> None:
        """验证 Codex 特有参数。"""
        super().validate_params(params)

        if isinstance(params, CodexParams):
            # 验证图片路径
            for img_path in params.image:
                if not Path(img_path).exists():
                    raise ValueError(f"Image file does not exist: {img_path}")

    def build_command(self, params: CommonParams) -> list[str]:
        """构建 Codex CLI 命令。

        Args:
            params: 调用参数

        Returns:
            命令行参数列表
        """
        cmd = [self._codex_path, "exec"]

        # 工作目录
        cmd.extend(["--cd", str(params.workspace.absolute())])

        # Permission 映射到 sandbox 参数
        sandbox_value = PERMISSION_MAP_CODEX.get(params.permission, "read-only")
        cmd.extend(["--sandbox", sandbox_value])

        # 硬编码参数
        cmd.append("--skip-git-repo-check")
        cmd.append("--json")

        # 可选：模型
        if params.model:
            cmd.extend(["--model", params.model])

        # Codex 特有：图片附件
        if isinstance(params, CodexParams):
            for img_path in params.image:
                cmd.extend(["--image", str(Path(img_path).absolute())])

        # 会话恢复
        if params.session_id:
            cmd.append("resume")
            cmd.append(params.session_id)

        # Prompt 通过 stdin 传递（使用 -- 分隔）
        cmd.append("--")

        return cmd

    def _process_event(self, event: Any, params: CommonParams) -> None:
        """处理 Codex 特有的事件。

        Codex 的 session_id 可能在 thread.started 事件中。
        """
        super()._process_event(event, params)

        if not self._session_id:
            raw = event.raw
            if raw.get("type") == "thread.started":
                thread_id = raw.get("thread_id", "")
                if thread_id:
                    self._session_id = thread_id
