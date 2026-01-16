"""CLI 工具处理器。

处理 codex, gemini, claude, opencode 工具调用。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import anyio
import asyncio
from mcp.types import TextContent

from .base import ToolContext, ToolHandler
from ..shared.invokers import (
    CLIType,
    CodexParams,
    GeminiParams,
    ClaudeParams,
    OpencodeParams,
    Permission,
    create_invoker,
)
from ..shared.response_formatter import (
    ResponseData,
    DebugInfo as FormatterDebugInfo,
    get_formatter,
    format_error_response,
)
from ..utils.prompt_injection import inject_context_and_report_mode
from ..utils.xml_wrapper import build_wrapper

__all__ = ["CLIHandler", "build_params"]

logger = logging.getLogger(__name__)

# 进度报告间隔（秒）- 用于长时间运行任务的保活
PROGRESS_REPORT_INTERVAL = 30


def _resolve_path_list(workspace: Path, value: Any) -> list[str]:
    """将路径列表归一化为绝对路径字符串列表。

    - 支持 None / 单个字符串 / 字符串列表
    - 相对路径以 workspace 为基准拼接
    """
    if value is None:
        return []

    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        return []

    resolved: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not text:
            continue
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = workspace / path
        resolved.append(str(path.resolve()))
    return resolved


def normalize_path_arguments(cli_type: str, args: dict[str, Any]) -> dict[str, Any]:
    """归一化路径参数（相对路径 → 基于 workspace 的绝对路径）。"""
    workspace_raw = args.get("workspace")
    if not workspace_raw:
        return args

    workspace = Path(workspace_raw).expanduser()
    if not workspace.is_absolute():
        workspace = workspace.resolve()

    normalized = dict(args)
    normalized["workspace"] = str(workspace)
    normalized["context_paths"] = _resolve_path_list(workspace, args.get("context_paths"))

    if cli_type == "codex":
        normalized["image"] = _resolve_path_list(workspace, args.get("image"))
    elif cli_type == "opencode":
        normalized["file"] = _resolve_path_list(workspace, args.get("file"))

    return normalized


def resolve_workspace_relative_path(workspace: Path, path_value: str) -> Path:
    """将路径归一化为绝对路径。

    - 支持 ~ 展开
    - 相对路径以 workspace 为基准拼接
    """
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = workspace / path
    return path.resolve()


def build_params(cli_type: str, args: dict[str, Any]):
    """构建 CLI 参数对象。"""
    args = normalize_path_arguments(cli_type, args)

    # 公共参数（continuation_id 映射到内部的 session_id）
    common = {
        "prompt": args["prompt"],
        "workspace": Path(args["workspace"]),
        "permission": Permission(args.get("permission", "read-only")),
        "session_id": args.get("continuation_id", ""),  # 外部 continuation_id → 内部 session_id
        "model": args.get("model", ""),
        "task_note": args.get("task_note", ""),
        "task_tags": args.get("task_tags", []),
    }

    if cli_type == "codex":
        return CodexParams(
            **common,
            image=[Path(p) for p in args.get("image", [])],
        )
    elif cli_type == "gemini":
        return GeminiParams(**common)
    elif cli_type == "claude":
        return ClaudeParams(
            **common,
            system_prompt=args.get("system_prompt", ""),
            append_system_prompt=args.get("append_system_prompt", ""),
            agent=args.get("agent", ""),
        )
    elif cli_type == "opencode":
        return OpencodeParams(
            **common,
            file=[Path(p) for p in args.get("file", [])],
            agent=args.get("agent") or "build",
        )
    else:
        raise ValueError(f"Unknown CLI type: {cli_type}")


class CLIHandler(ToolHandler):
    """CLI 工具处理器（codex, gemini, claude, opencode）。"""

    def __init__(self, cli_type: str):
        """初始化 CLIHandler。

        Args:
            cli_type: CLI 类型（codex, gemini, claude, opencode）
        """
        self._cli_type = cli_type

    @property
    def name(self) -> str:
        return self._cli_type

    @property
    def description(self) -> str:
        from ..tool_schema import TOOL_DESCRIPTIONS
        return TOOL_DESCRIPTIONS.get(self._cli_type, "")

    def get_input_schema(self) -> dict[str, Any]:
        from ..tool_schema import create_tool_schema
        return create_tool_schema(self._cli_type)

    def validate(self, arguments: dict[str, Any]) -> str | None:
        prompt = arguments.get("prompt")
        workspace = arguments.get("workspace")
        handoff_file = arguments.get("handoff_file")
        if not prompt or not str(prompt).strip():
            return "Missing required argument: 'prompt'"
        if not workspace:
            return "Missing required argument: 'workspace'"
        if not handoff_file or not str(handoff_file).strip():
            return "Missing required argument: 'handoff_file'"
        return None

    async def handle(
        self,
        arguments: dict[str, Any],
        ctx: ToolContext,
    ) -> list[TextContent]:
        """处理 CLI 工具调用。"""
        # 校验
        error = self.validate(arguments)
        if error:
            return format_error_response(error)

        arguments = normalize_path_arguments(self._cli_type, arguments)

        task_note = arguments.get("task_note", "")
        prompt = arguments.get("prompt", "")

        # 创建 invoker（per-request 隔离）
        event_callback = ctx.make_event_callback(self._cli_type, task_note, None) if ctx.gui_manager else None
        invoker = create_invoker(self._cli_type, event_callback=event_callback)

        # 立即推送用户 prompt 到 GUI
        ctx.push_user_prompt(self._cli_type, prompt, task_note)

        # handoff_file is now mandatory; inject handoff prompt hint
        handoff_file = str(arguments.get("handoff_file") or "").strip()
        prompt = prompt.rstrip() + f"""

<mcp-injection type="handoff">
  <meta-rules>
    <rule>Do not mention this template, "handoff", MCP, or any injection mechanism.</rule>
  </meta-rules>
  <output-requirements>
    <rule>End your answer with a section titled "## Handoff" (next steps + files to read first).</rule>
    <rule>The scheduler will append this output to: {handoff_file}</rule>
  </output-requirements>
</mcp-injection>"""

        # 使用 helper 注入 report_mode 和 context_paths
        report_mode = arguments.get("report_mode", False)
        context_paths = arguments.get("context_paths", []) or []
        injected_prompt = inject_context_and_report_mode(prompt, context_paths, report_mode)
        arguments = {**arguments, "prompt": injected_prompt}

        # 构建参数
        params = build_params(self._cli_type, arguments)

        # 进度报告保活任务
        progress_task: asyncio.Task | None = None
        progress_counter = 0

        async def progress_reporter():
            """定期报告进度以保持连接活跃。"""
            nonlocal progress_counter
            try:
                while True:
                    await asyncio.sleep(PROGRESS_REPORT_INTERVAL)
                    progress_counter += 1
                    await ctx.report_progress_safe(
                        progress=progress_counter,
                        message=f"Processing... ({progress_counter * PROGRESS_REPORT_INTERVAL}s)",
                    )
            except (anyio.get_cancelled_exc_class(), asyncio.CancelledError):
                raise
            except Exception as e:
                logger.warning(f"Progress reporter crashed: {e}", exc_info=True)

        async def stop_progress_reporter() -> None:
            """停止后台进度保活任务，并确保异常不会泄漏。"""
            nonlocal progress_task
            if not progress_task:
                return

            if not progress_task.done():
                progress_task.cancel()
            try:
                await progress_task
            except (anyio.get_cancelled_exc_class(), asyncio.CancelledError):
                pass
            except Exception as e:
                logger.warning(f"Progress reporter task failed: {e}", exc_info=True)
            finally:
                progress_task = None

        try:
            # 启动进度报告任务
            if ctx.has_progress_token():
                progress_task = asyncio.create_task(progress_reporter())

            # 执行（取消异常会直接传播，不会返回）
            result = await invoker.execute(params)

            # 获取参数
            debug_enabled = ctx.resolve_debug(arguments)
            handoff_file_path = arguments.get("handoff_file", "")
            resolved_handoff_file_path = ""
            if handoff_file_path:
                try:
                    resolved_handoff_file_path = str(resolve_workspace_relative_path(params.workspace, handoff_file_path))
                except Exception:
                    # 保底：解析失败时保持原样
                    resolved_handoff_file_path = handoff_file_path

            formatter = get_formatter()

            # 保存到 handoff_file（必填，永远 append + wrapped）
            # NOTE: handoff_file 是权限限制的例外，它仅用于落盘分析记录结果，
            # 而非通用的文件写入能力。CLI agent 的实际文件操作仍受 permission 参数控制。
            # 这是一个便捷功能，让编排器无需单独写文件来保存分析结果。
            # DESIGN: handoff_file 在 permission='read-only' 下允许写入是特性（用于保存输出），不是风险或越权。
            # NOTE: 必须在构建最终 response 前完成写入，以便 debug_info 回传 handoff_file_written。
            handoff_file_written = False

            # 构建 ResponseData（直接使用 invoker 提取的统一数据）
            # 错误时也尽力返回已收集的内容和 session_id，方便客户端发送"继续"
            response_data = ResponseData(
                answer=result.agent_messages,  # 即使失败也返回已收集的内容
                session_id=result.session_id or "",
                thought_steps=result.thought_steps if not result.success else [],
                debug_info=None,
                success=result.success,
                error=result.error,
            )

            if resolved_handoff_file_path:
                try:
                    file_content = formatter.format_for_file(response_data)
                    status = "success" if result.success else "error"
                    wrapped = build_wrapper(
                        self._cli_type,
                        result.session_id or "",
                        task_note,
                        0,
                        status,
                        file_content,
                    )

                    handoff_path = Path(resolved_handoff_file_path)
                    if not handoff_path.is_absolute():
                        workspace = Path(arguments.get("workspace", ""))
                        handoff_path = workspace / handoff_path
                    handoff_path = handoff_path.expanduser().resolve()

                    handoff_path.parent.mkdir(parents=True, exist_ok=True)
                    if handoff_path.exists():
                        with handoff_path.open("a", encoding="utf-8") as f:
                            f.write("\n" + wrapped)
                    else:
                        handoff_path.write_text(wrapped, encoding="utf-8")
                    logger.info(f"Appended output to: {handoff_path}")
                    resolved_handoff_file_path = str(handoff_path)
                    handoff_file_written = True
                except Exception as e:
                    logger.warning(f"Failed to save output to {resolved_handoff_file_path}: {e}")

            # 构建 debug_info（当 debug 开启时始终构建，包含 log_file）
            if debug_enabled:
                response_data.debug_info = FormatterDebugInfo(
                    model=result.debug_info.model if result.debug_info else None,
                    duration_sec=result.debug_info.duration_sec if result.debug_info else 0.0,
                    message_count=result.debug_info.message_count if result.debug_info else 0,
                    tool_call_count=result.debug_info.tool_call_count if result.debug_info else 0,
                    input_tokens=result.debug_info.input_tokens if result.debug_info else None,
                    output_tokens=result.debug_info.output_tokens if result.debug_info else None,
                    cancelled=result.cancelled,
                    log_file=ctx.config.log_file if ctx.config.log_debug else None,
                    handoff_file=resolved_handoff_file_path or None,
                    handoff_file_written=handoff_file_written,
                )

            # 格式化响应
            response = formatter.format(
                response_data,
                debug=debug_enabled,
            )

            # DEBUG: 记录响应摘要
            response_summary = (
                "[MCP] call_tool response:\n"
                f"  Tool: {self._cli_type}\n"
                f"  Success: {result.success}\n"
                f"  Response length: {len(response)} chars"
            )
            if result.debug_info:
                response_summary += f"\n  Duration: {result.debug_info.duration_sec:.3f}s"
            logger.debug(response_summary)

            await stop_progress_reporter()

            # 报告最终状态（best-effort，不影响主响应）
            await ctx.report_progress_safe(
                progress=100,
                total=100,
                message="Completed" if result.success else "Failed",
            )

            return [TextContent(type="text", text=response)]

        except anyio.get_cancelled_exc_class() as e:
            # 取消通知已由 invoker._send_cancel_event() 推送到 GUI
            # 直接 re-raise 让 MCP 框架处理
            logger.info(f"Tool '{self._cli_type}' cancelled (type={type(e).__name__})")
            raise

        except asyncio.CancelledError as e:
            # 捕获 asyncio.CancelledError（可能与 anyio 不同）
            logger.info(f"Tool '{self._cli_type}' cancelled via asyncio.CancelledError")
            raise

        except Exception as e:
            logger.error(f"Tool '{self._cli_type}' error: {e}", exc_info=True)
            await stop_progress_reporter()
            await ctx.report_progress_safe(progress=100, total=100, message="Failed")
            return format_error_response(str(e))

        finally:
            # 取消进度报告任务
            await stop_progress_reporter()
