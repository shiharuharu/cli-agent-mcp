"""MCP 响应格式化器。

使用 XML-wrapped Markdown 格式，对 LLM 友好。

格式说明:
    - <thought_process>: 中间思考过程（错误时输出）
    - <answer>: 最终答案
    - <debug_info>: 调试信息（debug=True 时输出）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.types import TextContent


@dataclass
class DebugInfo:
    """调试信息。"""

    model: str | None = None
    duration_sec: float = 0.0
    message_count: int = 0
    tool_call_count: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    cancelled: bool = False
    log_file: str | None = None  # DEBUG 日志文件路径

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        data: dict[str, Any] = {}
        if self.model:
            data["model"] = self.model
        data["duration_sec"] = round(self.duration_sec, 3)
        data["message_count"] = self.message_count
        data["tool_call_count"] = self.tool_call_count
        if self.input_tokens is not None:
            data["input_tokens"] = self.input_tokens
        if self.output_tokens is not None:
            data["output_tokens"] = self.output_tokens
        if self.cancelled:
            data["cancelled"] = True
        if self.log_file:
            data["log_file"] = self.log_file
        return data


@dataclass
class ResponseData:
    """响应数据。"""

    # 最终答案（必须）
    answer: str

    # 会话 ID（用于继续对话）
    session_id: str = ""

    # 中间思考过程（可选，错误时使用）
    thought_steps: list[str] = field(default_factory=list)

    # 调试信息（可选，debug 时使用）
    debug_info: DebugInfo | None = None

    # 是否成功
    success: bool = True

    # 错误信息
    error: str | None = None


class ResponseFormatter:
    """MCP 响应格式化器。

    使用 XML-wrapped Markdown 格式，对 LLM 友好。

    Example:
        >>> formatter = ResponseFormatter()
        >>> data = ResponseData(
        ...     answer="建议修改 xxx",
        ...     thought_steps=["分析步骤1...", "分析步骤2..."],
        ...     debug_info=DebugInfo(model="gpt-4", duration_sec=1.5)
        ... )
        >>> output = formatter.format(data, debug=True)
    """

    def format(
        self,
        data: ResponseData,
        *,
        debug: bool = False,
    ) -> str:
        """格式化响应数据。

        Args:
            data: 响应数据
            debug: 是否输出调试信息

        Returns:
            XML-wrapped Markdown 格式的响应字符串
        """
        if not data.success:
            return self._format_error(
                data.error or "Unknown error",
                debug=debug,
                debug_info=data.debug_info,
                session_id=data.session_id,
                thought_steps=data.thought_steps,
                partial_answer=data.answer,
            )

        parts = ["<response>"]

        # 1. 思考过程（错误时在 _format_error 中输出）
        if data.thought_steps:
            parts.append(self._format_thought_process(data.thought_steps))

        # 2. 最终答案
        parts.append(self._format_answer(data.answer))

        # 3. 会话 ID（用于继续对话，外部名称为 continuation_id）
        if data.session_id:
            parts.append(f"  <continuation_id>{data.session_id}</continuation_id>")

        # 4. 调试信息（debug 时输出）
        if debug and data.debug_info:
            parts.append(self._format_debug_info(data.debug_info))

        parts.append("</response>")

        return "\n".join(parts)

    def format_for_file(
        self,
        data: ResponseData,
    ) -> str:
        """格式化用于保存到文件的内容。

        不包含 debug 信息，适合作为纯内容保存。

        Args:
            data: 响应数据

        Returns:
            纯 Markdown 格式的内容（无 XML 包装）
        """
        if not data.success:
            return f"Error: {data.error or 'Unknown error'}"

        parts = []

        # 1. 思考过程
        if data.thought_steps:
            parts.append("## Thought Process\n")
            for i, step in enumerate(data.thought_steps, 1):
                parts.append(f"### Step {i}\n")
                parts.append(step.strip())
                parts.append("\n")

        # 2. 最终答案
        if data.thought_steps:
            parts.append("## Answer\n")
        parts.append(data.answer)

        return "\n".join(parts)

    def _format_thought_process(self, steps: list[str]) -> str:
        """格式化思考过程。"""
        lines = ["  <thought_process>"]
        for i, step in enumerate(steps, 1):
            clean_text = step.strip()
            lines.append(f'    <step index="{i}">')
            lines.append(clean_text)
            lines.append("    </step>")
        lines.append("  </thought_process>")
        return "\n".join(lines)

    def _format_answer(self, answer: str) -> str:
        """格式化最终答案。"""
        return f"  <answer>\n{answer}\n  </answer>"

    def _format_debug_info(self, debug_info: DebugInfo) -> str:
        """格式化调试信息（XML 格式）。"""
        lines = ["  <debug_info>"]
        if debug_info.model:
            lines.append(f"    <model>{debug_info.model}</model>")
        lines.append(f"    <duration_sec>{debug_info.duration_sec:.3f}</duration_sec>")
        lines.append(f"    <message_count>{debug_info.message_count}</message_count>")
        lines.append(f"    <tool_call_count>{debug_info.tool_call_count}</tool_call_count>")
        if debug_info.input_tokens is not None:
            lines.append(f"    <input_tokens>{debug_info.input_tokens}</input_tokens>")
        if debug_info.output_tokens is not None:
            lines.append(f"    <output_tokens>{debug_info.output_tokens}</output_tokens>")
        if debug_info.cancelled:
            lines.append("    <cancelled>true</cancelled>")
        if debug_info.log_file:
            lines.append(f"    <log_file>{debug_info.log_file}</log_file>")
        lines.append("  </debug_info>")
        return "\n".join(lines)

    def _format_error(
        self,
        error: str,
        *,
        debug: bool = False,
        debug_info: DebugInfo | None = None,
        session_id: str = "",
        thought_steps: list[str] | None = None,
        partial_answer: str = "",
    ) -> str:
        """格式化错误响应。

        Args:
            error: 错误信息
            debug: 是否输出调试信息
            debug_info: 调试信息（可选）
            session_id: 会话 ID（用于继续对话）
            thought_steps: 已收集的思考步骤
            partial_answer: 已收集的部分答案

        Returns:
            XML 格式的错误响应
        """
        parts = ["<response>"]
        parts.append(f"  <error>{error}</error>")

        # 错误时也返回已收集的思考步骤（方便调试和继续）
        if thought_steps:
            parts.append(self._format_thought_process(thought_steps))

        # 错误时也返回已收集的部分答案
        if partial_answer and partial_answer.strip():
            parts.append(f"  <partial_answer>{partial_answer}</partial_answer>")

        # 错误时也返回 session_id（方便客户端发送"继续"）
        if session_id:
            parts.append(f"  <continuation_id>{session_id}</continuation_id>")
            # 如果有部分输出，提示客户端可以继续
            if thought_steps or (partial_answer and partial_answer.strip()):
                parts.append("  <hint>Task failed. Above is the output collected so far. You can send 'continue' with this continuation_id to retry.</hint>")

        # 错误情况下也输出 debug_info（如果开启 debug）
        if debug and debug_info:
            parts.append(self._format_debug_info(debug_info))

        parts.append("</response>")
        return "\n".join(parts)


# 全局实例
_formatter: ResponseFormatter | None = None


def get_formatter() -> ResponseFormatter:
    """获取全局格式化器实例。"""
    global _formatter
    if _formatter is None:
        _formatter = ResponseFormatter()
    return _formatter


def format_error_response(error: str) -> list[TextContent]:
    """统一的错误响应格式化函数。

    确保所有错误都以 <response><error>...</error></response> 格式返回，
    保持 API 契约一致性。
    """
    from mcp.types import TextContent

    formatter = get_formatter()
    response_data = ResponseData(
        answer="",
        session_id="",
        success=False,
        error=error,
    )
    return [TextContent(type="text", text=formatter.format(response_data))]
