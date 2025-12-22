"""OpenCode CLI 调用器。

cli-agent-mcp shared/mcp v0.1.0
同步日期: 2025-12-17

实现 OpenCode CLI 的命令构建和调用逻辑。

命令格式:
    opencode run \
      --format json \
      [--model {provider/model}] \
      [--session {session_id}] \
      [--agent {agent}] \
      [--file {file}]... \
      "{prompt}"  # 位置参数

注意：OpenCode 的错误处理比较特殊：
- 错误输出到 stdout（不是 stderr）
- 退出码通常为 0（即使发生错误）
- 错误格式是堆栈跟踪，不是 JSON
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from .base import CLIInvoker, EventCallback
from .types import (
    CLIType,
    CommonParams,
    OpencodeParams,
    Permission,
)

__all__ = ["OpencodeInvoker"]

# OpenCode 错误模式匹配
_OPENCODE_ERROR_PATTERNS = [
    # 错误类名（如 ProviderModelNotFoundError: ...）
    (r'^(\w+Error):\s*(.*)$', 'error'),
    # 堆栈跟踪指示符
    (r'^\s*\^$', 'stacktrace'),
    # throw 语句
    (r'throw new (\w+)', 'throw'),
    # at ... 堆栈位置
    (r'^\s+at\s+\w+', 'stacktrace'),
    # data: { ... } 错误数据块开始
    (r'^\s*data:\s*\{', 'error_data'),
]


class OpencodeInvoker(CLIInvoker):
    """OpenCode CLI 调用器。

    封装 OpenCode CLI 的调用逻辑，包括：
    - 命令行参数构建
    - Permission 到环境变量映射
    - 支持文件附加和 agent 选择
    - 特殊的错误处理（stdout 输出，退出码 0）

    Example:
        invoker = OpencodeInvoker()
        result = await invoker.execute(OpencodeParams(
            prompt="Analyze this project",
            workspace=Path("/path/to/repo"),
        ))
    """

    def __init__(
        self,
        opencode_path: str = "opencode",
        event_callback: EventCallback | None = None,
        parser: Any | None = None,
    ) -> None:
        """初始化 OpenCode 调用器。

        Args:
            opencode_path: opencode 可执行文件路径，默认 "opencode"
            event_callback: 事件回调函数
            parser: 自定义解析器
        """
        super().__init__(event_callback=event_callback, parser=parser)
        self._opencode_path = opencode_path

    @property
    def cli_type(self) -> CLIType:
        return CLIType.OPENCODE

    def build_command(self, params: CommonParams) -> list[str]:
        """构建 OpenCode CLI 命令。

        Args:
            params: 调用参数

        Returns:
            命令行参数列表
        """
        cmd = [self._opencode_path, "run"]

        # JSON 输出格式（JSONL 流式输出）
        cmd.extend(["--format", "json"])

        # 可选：模型（格式为 provider/model）
        if params.model:
            cmd.extend(["--model", params.model])

        # 会话恢复
        if params.session_id:
            cmd.extend(["--session", params.session_id])

        # OpenCode 特有参数
        if isinstance(params, OpencodeParams):
            # Agent 选择
            if params.agent:
                cmd.extend(["--agent", params.agent])

            # 附加文件
            for file_path in params.file:
                cmd.extend(["--file", str(file_path.absolute())])

        # Prompt 作为位置参数
        cmd.append(params.prompt)

        return cmd

    def get_env(self, params: CommonParams) -> dict[str, str] | None:
        """获取环境变量覆盖。

        OpenCode 使用环境变量 OPENCODE_PERMISSION 来设置权限。
        注意：返回的 env 会完全覆盖子进程的环境变量，所以需要继承系统环境。

        Args:
            params: 调用参数

        Returns:
            环境变量字典（包含系统环境），或 None 使用默认
        """
        # 继承系统环境变量
        env = dict(os.environ)

        # Permission 映射到 OPENCODE_PERMISSION 环境变量
        # OpenCode 的权限模型与其他 CLI 不同，使用 JSON 格式的配置
        permission_config = self._build_permission_config(params.permission)
        if permission_config:
            env["OPENCODE_PERMISSION"] = json.dumps(permission_config)

        return env

    def _build_permission_config(self, permission: Permission) -> dict[str, Any]:
        """构建 OpenCode 权限配置。

        Args:
            permission: 权限级别

        Returns:
            OpenCode 权限配置字典
        """
        if permission == Permission.READ_ONLY:
            # 只读模式：禁止编辑和执行
            return {
                "edit": "deny",
                "bash": "deny",
                "webfetch": "deny",
            }
        elif permission == Permission.WORKSPACE_WRITE:
            # 工作区写入模式：允许编辑，bash 需要确认
            return {
                "edit": "allow",
                "bash": "ask",
                "webfetch": "ask",
            }
        else:  # UNLIMITED
            # 无限制模式：允许所有操作
            return {
                "edit": "allow",
                "bash": "allow",
                "webfetch": "allow",
                "external_directory": "allow",
            }

    @property
    def uses_stdin_prompt(self) -> bool:
        """OpenCode 使用位置参数而非 stdin 传递 prompt。"""
        return False

    def _extract_error_from_line(self, line: str) -> tuple[str, str] | None:
        """从非 JSON 行中提取 OpenCode 错误信息。

        OpenCode 的错误以堆栈跟踪格式输出到 stdout。
        我们识别主错误行（如 ProviderModelNotFoundError: ...）并返回。

        Args:
            line: 非 JSON 行内容

        Returns:
            (error_type, error_message) 元组，如果不是错误行则返回 None
        """
        # 检查是否是主错误行（如 ProviderModelNotFoundError: ...）
        match = re.match(r'^(\w+Error):\s*(.*)$', line)
        if match:
            error_name = match.group(1)
            error_msg = match.group(2) or error_name
            return (error_name, error_msg)

        return None

    def _process_event(self, event: Any, params: CommonParams) -> None:
        """处理 OpenCode 特有的事件。

        OpenCode 的 session_id 在事件的 sessionID 字段中。
        """
        super()._process_event(event, params)

        # 从事件中提取 session_id
        if not self._session_id:
            raw = event.raw
            session_id = raw.get("sessionID", "")
            if session_id:
                self._session_id = session_id

    def _check_execution_errors(self, stderr_content: str = "") -> None:
        """检查 OpenCode 特有的错误情况。

        OpenCode 的特殊行为：
        - 错误输出到 stdout 或 stderr（取决于错误类型）
        - 退出码通常为 0（即使发生错误）
        - 错误格式是堆栈跟踪，不是 JSON

        如果捕获到了错误但 _exit_error 为空（返回码为 0），
        则从 stderr 或 _captured_errors 中构建错误信息。

        Args:
            stderr_content: 子进程的 stderr 输出内容
        """
        # 如果已经有错误（返回码非 0），不需要额外处理
        if self._exit_error:
            return

        # 优先检查 stderr（opencode 的某些错误输出到 stderr）
        if stderr_content.strip():
            error_msg = f"OpenCode error (exit code 0):\n{stderr_content.strip()}"
            self._exit_error = error_msg

            # 向 GUI 发送错误事件
            if self._event_callback:
                self._send_error_event(error_msg, error_type="opencode_error")
            return

        # 如果 stderr 为空，检查 stdout 中捕获的错误
        if self._captured_errors:
            error_msg = f"OpenCode error (exit code 0):\n"
            error_msg += "\n".join(self._captured_errors[-5:])  # 取最后 5 条

            self._exit_error = error_msg

            # 向 GUI 发送错误事件
            if self._event_callback:
                self._send_error_event(error_msg, error_type="opencode_error")
