"""Parallel 工具处理器。

处理 *_parallel 模式的工具调用。
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from mcp.types import TextContent

from .base import ToolContext, ToolHandler
from .cli import build_params
from ..shared.invokers import create_invoker
from ..shared.response_formatter import (
    ResponseData,
    DebugInfo as FormatterDebugInfo,
    get_formatter,
    format_error_response,
)
from ..utils.xml_wrapper import build_wrapper
from ..utils.prompt_injection import inject_context_and_report_mode

__all__ = ["ParallelHandler"]

logger = logging.getLogger(__name__)


class ParallelHandler(ToolHandler):
    """Parallel 模式工具处理器。"""

    def __init__(self, base_name: str):
        """初始化 ParallelHandler。

        Args:
            base_name: 基础工具名称（如 codex, gemini, claude, opencode）
        """
        self._base_name = base_name

    @property
    def name(self) -> str:
        return f"{self._base_name}_parallel"

    @property
    def description(self) -> str:
        return (
            f"Run multiple {self._base_name} tasks in parallel. "
            f"All tasks share workspace/permission/save_file. "
            f"Results are appended to save_file with XML wrappers "
            f"(<agent-output agent=... continuation_id=... task_note=... task_index=... status=...>)."
        )

    def get_input_schema(self) -> dict[str, Any]:
        from ..tool_schema import create_tool_schema
        return create_tool_schema(self._base_name, is_parallel=True)

    def validate(self, arguments: dict[str, Any]) -> str | None:
        prompts = arguments.get("parallel_prompts", [])
        task_notes = arguments.get("parallel_task_notes", [])

        # 类型校验
        if not isinstance(prompts, list):
            return "parallel_prompts must be a list"
        if not isinstance(task_notes, list):
            return "parallel_task_notes must be a list"

        if not prompts:
            return "parallel_prompts is required"

        # 检查空白字符串和类型
        for i, p in enumerate(prompts):
            if not isinstance(p, str):
                return f"parallel_prompts[{i}] must be a string"
            if not p or not p.strip():
                return f"parallel_prompts[{i}] is empty or whitespace"

        for i, n in enumerate(task_notes):
            if not isinstance(n, str):
                return f"parallel_task_notes[{i}] must be a string"
            if not n or not n.strip():
                return f"parallel_task_notes[{i}] is empty or whitespace"

        if len(prompts) != len(task_notes):
            return "parallel_prompts and parallel_task_notes must have same length"

        if len(prompts) > 20:
            return "parallel_prompts exceeds maximum of 20"

        if arguments.get("continuation_id"):
            return "continuation_id input is not supported in parallel mode"

        if not arguments.get("save_file"):
            return "save_file is required in parallel mode"

        return None

    async def handle(
        self,
        arguments: dict[str, Any],
        ctx: ToolContext,
    ) -> list[TextContent]:
        """处理 parallel 模式的工具调用。"""
        # 1) 校验
        error = self.validate(arguments)
        if error:
            return format_error_response(error)

        prompts = arguments.get("parallel_prompts", [])
        task_notes = arguments.get("parallel_task_notes", [])
        save_file = arguments.get("save_file")

        # clamp concurrency (handle string/invalid types)
        try:
            max_conc = int(arguments.get("parallel_max_concurrency", 4))
        except (TypeError, ValueError):
            max_conc = 4
        max_conc = max(1, min(16, max_conc))
        fail_fast = arguments.get("parallel_fail_fast", False)

        # 推送用户 prompt 到 GUI（每个 prompt 单独推送）
        for prompt, note in zip(prompts, task_notes):
            ctx.push_user_prompt(f"{self._base_name}_parallel", prompt, note)

        # 2) 构建子任务
        sub_tasks = []
        context_paths = arguments.get("context_paths", [])
        report_mode = arguments.get("report_mode", False)

        for idx, (prompt, note) in enumerate(zip(prompts, task_notes), start=1):
            # 注入 context_paths 和 report_mode
            final_prompt = inject_context_and_report_mode(prompt, context_paths, report_mode)
            sub_tasks.append({
                "prompt": final_prompt,
                "workspace": arguments.get("workspace"),
                "permission": arguments.get("permission", "read-only"),
                "model": arguments.get("model", ""),
                "verbose_output": arguments.get("verbose_output", False),
                "task_note": note,
                "_task_index": idx,
                # CLI 特有参数
                "image": arguments.get("image", []),  # codex
                "system_prompt": arguments.get("system_prompt", ""),  # claude
                "append_system_prompt": arguments.get("append_system_prompt", ""),  # claude
                "agent": arguments.get("agent", ""),  # claude/opencode
                "file": arguments.get("file", []),  # opencode
            })

        # 3) 并发执行
        sem = asyncio.Semaphore(max_conc)
        should_stop = False
        results: list[tuple[int, str, Any]] = []  # (task_index, task_note, result|Exception|None)

        async def run_one(sub_args: dict):
            nonlocal should_stop

            async with sem:
                # fail_fast 检查必须在拿到 semaphore 后
                if fail_fast and should_stop:
                    return (sub_args["_task_index"], sub_args["task_note"], None)  # skipped

                try:
                    # 创建 invoker（传入 task_note 和 task_index 用于 GUI 显示）
                    task_note = sub_args.get("task_note", "")
                    task_index = sub_args.get("_task_index")
                    event_callback = ctx.make_event_callback(self._base_name, task_note, task_index) if ctx.gui_manager else None
                    invoker = create_invoker(self._base_name, event_callback=event_callback)

                    # 构建参数
                    params = build_params(self._base_name, sub_args)

                    # 执行
                    result = await invoker.execute(params)

                    if not result.success and fail_fast:
                        should_stop = True
                    return (sub_args["_task_index"], sub_args["task_note"], result)

                except asyncio.CancelledError:
                    # 必须 re-raise，不能当作普通异常处理
                    raise
                except Exception as e:
                    if fail_fast:
                        should_stop = True
                    return (sub_args["_task_index"], sub_args["task_note"], e)

        start_time = time.time()
        try:
            raw_results = await asyncio.gather(*[run_one(t) for t in sub_tasks], return_exceptions=True)
        except asyncio.CancelledError:
            raise
        duration_sec = time.time() - start_time

        # 处理 gather 返回的异常
        for r in raw_results:
            if isinstance(r, asyncio.CancelledError):
                raise r  # re-raise 取消
            elif isinstance(r, Exception):
                # 不应发生，因为 run_one 已捕获
                continue
            else:
                results.append(r)

        # 4) 按 task_index 排序后串行写文件
        results.sort(key=lambda x: x[0])

        success_count = 0
        failed_count = 0
        skipped_count = 0
        summary_lines = []
        all_wrapped = []  # 收集所有 wrapped 内容用于返回

        formatter = get_formatter()
        verbose_output = arguments.get("verbose_output", False)

        for idx, note, result in results:
            if result is None:
                # skipped (fail_fast)
                skipped_count += 1
                summary_lines.append(f"- [{idx}] {note} | skipped")
                continue
            elif isinstance(result, Exception):
                content = f"Error: {result}"
                status = "error"
                session_id = ""
                failed_count += 1
                summary_lines.append(f"- [{idx}] {note} | error")
            elif result.success:
                # 使用 formatter 格式化内容
                response_data = ResponseData(
                    answer=result.agent_messages,
                    session_id=result.session_id or "",
                    thought_steps=result.thought_steps if verbose_output else [],
                    debug_info=None,
                    success=True,
                    error=None,
                )
                content = formatter.format_for_file(response_data, verbose_output=verbose_output)
                status = "success"
                session_id = result.session_id or ""
                success_count += 1
                summary_lines.append(f"- [{idx}] {note} | success | session={session_id}")
            else:
                # result.error 已包含 exit code + stderr
                content = result.error or "Unknown error"
                status = "error"
                session_id = result.session_id or ""
                failed_count += 1
                summary_lines.append(f"- [{idx}] {note} | error | session={session_id}")

            # 构建 wrapper
            wrapped = build_wrapper(self._base_name, session_id, note, idx, status, content)
            all_wrapped.append(wrapped)

        # 4.5) 批量写入文件（单次 I/O 操作）
        if all_wrapped:
            try:
                file_path = Path(save_file)
                content_to_write = "\n".join(all_wrapped)
                if file_path.exists():
                    with file_path.open("a", encoding="utf-8") as f:
                        f.write("\n" + content_to_write)  # 前置换行防止粘连
                else:
                    file_path.write_text(content_to_write, encoding="utf-8")
            except Exception as e:
                logger.error(f"Failed to write to {save_file}: {e}")
                return format_error_response(f"Failed to write to {save_file}: {e}")

        # 5) 返回 wrapped 内容（与 save_file_with_wrapper 格式一致）
        summary = f"Parallel run: total={len(results)}, success={success_count}, failed={failed_count}, skipped={skipped_count}\n"
        summary += f"Saved to: {save_file}\n"
        summary += "\n".join(summary_lines)

        # 推送结果到 GUI
        ctx.push_to_gui({
            "category": "system",
            "source": f"{self._base_name}_parallel",
            "message": summary,
            "severity": "info",
            "content_type": "text",
            "timestamp": time.time(),
            "raw": {
                "type": "parallel_complete",
                "success": success_count,
                "failed": failed_count,
                "skipped": skipped_count,
            },
            "metadata": {
                "debug": {
                    "total_tasks": len(results),
                    "success_count": success_count,
                    "failed_count": failed_count,
                    "skipped_count": skipped_count,
                    "duration_sec": duration_sec,
                    "save_file": save_file,
                },
            },
        })

        # 构建 debug_info（如果 debug 开启）
        debug_enabled = ctx.resolve_debug(arguments)
        debug_info = None
        if debug_enabled:
            debug_info = FormatterDebugInfo(
                model=None,
                duration_sec=duration_sec,
                message_count=len(results),
                tool_call_count=0,
            )

        # 返回 wrapped 内容（与 save_file_with_wrapper 格式一致）
        # answer 包含所有任务的 XML wrapper 输出
        has_failures = failed_count > 0
        wrapped_content = "\n".join(all_wrapped) if all_wrapped else summary
        response_data = ResponseData(
            answer=wrapped_content,
            session_id="",  # parallel 模式没有单一 session_id
            thought_steps=[],
            debug_info=debug_info,
            success=not has_failures,
            error=f"{failed_count} of {len(results)} tasks failed" if has_failures else None,
        )
        formatted_response = formatter.format(response_data, verbose_output=False, debug=debug_enabled)

        return [TextContent(type="text", text=formatted_response)]
