"""Gemini CLI 调用器。

cli-agent-mcp shared/mcp v0.1.0
同步日期: 2025-12-16

实现 Gemini CLI 的命令构建和调用逻辑。

命令格式:
    gemini \
      -o stream-json \
      --include-directories {workspace} \
      [--sandbox]  # if permission != "unlimited"
      [--allowed-tools ...]  # 允许的工具列表
      [--model {model}] \
      [--resume {session_id}] \
      "{prompt}"  # 位置参数
"""

from __future__ import annotations

from typing import Any

from .base import CLIInvoker, EventCallback
from .types import (
    CLIType,
    CommonParams,
    GeminiParams,
    Permission,
)

__all__ = ["GeminiInvoker"]

# Gemini 只读工具列表
GEMINI_READ_ONLY_TOOLS = [
    "glob",
    "read_file",
    "list_directory",
    "search_file_content",
]

# Gemini 完整工具列表（包含写操作）
GEMINI_ALL_TOOLS = [
    *GEMINI_READ_ONLY_TOOLS,
    "replace",
    "write_file",
    "run_shell_command",
    "write_todos",
]


class GeminiInvoker(CLIInvoker):
    """Gemini CLI 调用器。

    封装 Gemini CLI 的调用逻辑，包括：
    - 命令行参数构建
    - Permission 到 --sandbox 参数映射
    - 最精简的参数集（无特有参数）

    Example:
        invoker = GeminiInvoker()
        result = await invoker.execute(GeminiParams(
            prompt="Analyze this project",
            workspace=Path("/path/to/repo"),
        ))
    """

    def __init__(
        self,
        gemini_path: str = "gemini",
        event_callback: EventCallback | None = None,
        parser: Any | None = None,
    ) -> None:
        """初始化 Gemini 调用器。

        Args:
            gemini_path: gemini 可执行文件路径，默认 "gemini"
            event_callback: 事件回调函数
            parser: 自定义解析器
        """
        super().__init__(event_callback=event_callback, parser=parser)
        self._gemini_path = gemini_path

    @property
    def cli_type(self) -> CLIType:
        return CLIType.GEMINI

    def build_command(self, params: CommonParams) -> list[str]:
        """构建 Gemini CLI 命令。

        Args:
            params: 调用参数

        Returns:
            命令行参数列表
        """
        cmd = [self._gemini_path]

        # 硬编码：流式 JSON 输出（实时 JSONL）
        cmd.extend(["-o", "stream-json"])

        # 工作目录
        cmd.extend(["--include-directories", str(params.workspace.absolute())])

        # Permission 映射
        # Gemini 的 sandbox 是开关式的，不是像 Codex 那样有具体值
        # read-only 和 workspace-write 都启用 sandbox
        # unlimited 则不启用 sandbox
        if params.permission != Permission.UNLIMITED:
            cmd.append("--sandbox")

        # 允许的工具列表（基于权限级别）
        # read-only: 只允许读取类工具
        # workspace-write/unlimited: 允许所有工具
        if params.permission == Permission.READ_ONLY:
            allowed_tools = GEMINI_READ_ONLY_TOOLS
        else:
            allowed_tools = GEMINI_ALL_TOOLS
        cmd.extend(["--allowed-tools", ",".join(allowed_tools)])

        # 可选：模型
        if params.model:
            cmd.extend(["--model", params.model])

        # 会话恢复
        if params.session_id:
            cmd.extend(["--resume", params.session_id])

        # Prompt 作为位置参数（gemini 0.20+ 废弃了 -p 参数）
        cmd.append(params.prompt)

        return cmd

    @property
    def uses_stdin_prompt(self) -> bool:
        """Gemini 使用位置参数而非 stdin 传递 prompt。"""
        return False

    def _process_event(self, event: Any, params: CommonParams) -> None:
        """处理 Gemini 特有的事件。

        Gemini 的 session_id 在 init 事件中。
        """
        super()._process_event(event, params)

        if not self._session_id:
            raw = event.raw
            if raw.get("type") == "init":
                session_id = raw.get("session_id", "")
                if session_id:
                    self._session_id = session_id
