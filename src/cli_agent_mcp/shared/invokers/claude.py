"""Claude CLI 调用器。

cli-agent-mcp shared/mcp v0.1.0
同步日期: 2025-12-17

实现 Claude CLI 的命令构建和调用逻辑。

命令格式:
    claude \
      -p \
      --output-format stream-json \
      --add-dir {workspace} \
      --tools {tools_map[permission]} \
      [--system-prompt "{system_prompt}"] \
      [--append-system-prompt "{append_system_prompt}"] \
      [--agent {agent}] \
      [--model {model}] \
      [--resume {session_id}] \
      "{prompt}"
"""

from __future__ import annotations

from typing import Any

from .base import CLIInvoker, EventCallback
from .types import (
    CLIType,
    ClaudeParams,
    CommonParams,
    Permission,
    PERMISSION_MAP_CLAUDE,
)

__all__ = ["ClaudeInvoker"]


class ClaudeInvoker(CLIInvoker):
    """Claude CLI 调用器。

    封装 Claude CLI 的调用逻辑，包括：
    - 命令行参数构建
    - Permission 到 --tools 参数映射
    - system_prompt / append_system_prompt 支持

    Example:
        invoker = ClaudeInvoker()
        result = await invoker.execute(ClaudeParams(
            prompt="Review authentication module",
            workspace=Path("/path/to/repo"),
            append_system_prompt="Focus on OWASP Top 10 vulnerabilities.",
        ))
    """

    def __init__(
        self,
        claude_path: str = "claude",
        event_callback: EventCallback | None = None,
        parser: Any | None = None,
    ) -> None:
        """初始化 Claude 调用器。

        Args:
            claude_path: claude 可执行文件路径，默认 "claude"
            event_callback: 事件回调函数
            parser: 自定义解析器
        """
        super().__init__(event_callback=event_callback, parser=parser)
        self._claude_path = claude_path

    @property
    def cli_type(self) -> CLIType:
        return CLIType.CLAUDE

    def validate_params(self, params: CommonParams) -> None:
        """验证 Claude 特有参数。"""
        super().validate_params(params)

        if isinstance(params, ClaudeParams):
            # 不能同时指定 system_prompt 和 append_system_prompt
            if params.system_prompt and params.append_system_prompt:
                raise ValueError(
                    "Cannot specify both system_prompt and append_system_prompt. "
                    "Use system_prompt to completely override, or append_system_prompt to add to existing."
                )

    def build_command(self, params: CommonParams) -> list[str]:
        """构建 Claude CLI 命令。

        Args:
            params: 调用参数

        Returns:
            命令行参数列表
        """
        cmd = [self._claude_path]

        # 硬编码：非交互模式
        cmd.append("-p")

        # 硬编码：流式 JSON 输出（需要 --verbose）
        cmd.extend(["--output-format", "stream-json"])
        cmd.append("--verbose")  # stream-json 在 -p 模式下需要 --verbose

        # 工作目录
        cmd.extend(["--add-dir", str(params.workspace.absolute())])

        # Permission 映射到 tools 参数
        # read-only: 只允许读取类工具
        # workspace-write: 允许编辑和 Bash
        # unlimited: 使用默认工具集
        tools_value = PERMISSION_MAP_CLAUDE.get(params.permission, "Read,Grep,Glob")
        cmd.extend(["--tools", tools_value])

        # 可选：模型
        if params.model:
            cmd.extend(["--model", params.model])

        # Claude 特有：系统提示词
        if isinstance(params, ClaudeParams):
            if params.system_prompt:
                cmd.extend(["--system-prompt", params.system_prompt])
            elif params.append_system_prompt:
                cmd.extend(["--append-system-prompt", params.append_system_prompt])

            # Agent 选择
            if params.agent:
                cmd.extend(["--agent", params.agent])

        # 会话恢复
        if params.session_id:
            cmd.extend(["--resume", params.session_id])

        # Prompt 通过 stdin 传递，不作为命令行参数

        return cmd

    def _process_event(self, event: Any, params: CommonParams) -> None:
        """处理 Claude 特有的事件。

        Claude 的 session_id 在 system/init 事件中。
        """
        super()._process_event(event, params)

        if not self._session_id:
            raw = event.raw
            if raw.get("type") == "system" and raw.get("subtype") == "init":
                session_id = raw.get("session_id", "")
                if session_id:
                    self._session_id = session_id
