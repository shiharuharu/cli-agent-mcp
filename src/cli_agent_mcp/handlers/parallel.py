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
from .cli import build_params, normalize_path_arguments, resolve_workspace_relative_path
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

# 进度报告间隔（秒）- 用于 parallel 模式长任务保活
PROGRESS_REPORT_INTERVAL = 30


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
            f"All tasks share workspace/permission/handoff_file. "
            f"Results are appended to handoff_file with XML wrappers "
            f"(<agent-output agent=... continuation_id=... task_note=... task_index=... status=...>)."
        )

    def get_input_schema(self) -> dict[str, Any]:
        from ..tool_schema import create_tool_schema
        return create_tool_schema(self._base_name, is_parallel=True)

    def validate(self, arguments: dict[str, Any]) -> str | None:
        prompts = arguments.get("parallel_prompts", [])
        task_notes = arguments.get("parallel_task_notes", [])
        continuation_ids = arguments.get("parallel_continuation_ids", [])
        context_paths_parallel = arguments.get("context_paths_parallel", [])

        # 类型校验
        if not isinstance(prompts, list):
            return "parallel_prompts must be a list"
        if not isinstance(task_notes, list):
            return "parallel_task_notes must be a list"
        if not isinstance(continuation_ids, list):
            return "parallel_continuation_ids must be a list"
        if not isinstance(context_paths_parallel, list):
            return "context_paths_parallel must be a list"

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

        if len(prompts) > 100:
            return "parallel_prompts exceeds maximum of 100"

        # continuation_ids 校验：如果提供，长度必须与 prompts 一致
        if continuation_ids and len(continuation_ids) != len(prompts):
            return f"parallel_continuation_ids length ({len(continuation_ids)}) must equal parallel_prompts length ({len(prompts)})"

        # model 数组校验
        models = arguments.get("model", [])
        if isinstance(models, list) and len(models) > 1 and len(models) != len(prompts):
            return f"model array length ({len(models)}) must be 1 or match parallel_prompts length ({len(prompts)})"

        # context_paths_parallel 校验：如果提供，长度必须为空或与 prompts 一致
        if context_paths_parallel and len(context_paths_parallel) != len(prompts):
            return (
                f"context_paths_parallel length ({len(context_paths_parallel)}) must be empty or "
                f"match parallel_prompts length ({len(prompts)})"
            )
        for i, paths in enumerate(context_paths_parallel):
            if not isinstance(paths, list):
                return f"context_paths_parallel[{i}] must be a list"
            for j, p in enumerate(paths):
                if not isinstance(p, str):
                    return f"context_paths_parallel[{i}][{j}] must be a string"

        if not arguments.get("handoff_file"):
            return "handoff_file is required in parallel mode"

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

        arguments = normalize_path_arguments(self._base_name, arguments)

        prompts = arguments.get("parallel_prompts", [])
        task_notes = arguments.get("parallel_task_notes", [])
        handoff_file_raw = arguments.get("handoff_file") or ""
        workspace_raw = arguments.get("workspace") or ""
        workspace = Path(workspace_raw)
        handoff_file = (
            str(resolve_workspace_relative_path(workspace, handoff_file_raw))
            if handoff_file_raw
            else handoff_file_raw
        )

        # clamp concurrency (handle string/invalid types)
        try:
            max_conc = int(arguments.get("parallel_max_concurrency", 20))
        except (TypeError, ValueError):
            max_conc = 20
        max_conc = max(1, min(100, max_conc))
        fail_fast = arguments.get("parallel_fail_fast", False)

        # 推送用户 prompt 到 GUI（每个 prompt 单独推送）
        for prompt, note in zip(prompts, task_notes):
            ctx.push_user_prompt(f"{self._base_name}_parallel", prompt, note)

        # 2) 构建子任务
        sub_tasks = []
        report_mode = arguments.get("report_mode", False)
        models = arguments.get("model", [])
        continuation_ids = arguments.get("parallel_continuation_ids", []) or []
        shared_context_paths = arguments.get("context_paths", []) or []
        parallel_context_paths = arguments.get("context_paths_parallel", []) or []
        if not isinstance(models, list):
            models = [models] if models else []

        for idx, (prompt, note) in enumerate(zip(prompts, task_notes), start=1):
            # 注入 report_mode + context_paths（shared + per-task）
            per_task_paths = parallel_context_paths[idx - 1] if idx <= len(parallel_context_paths) else []
            merged_paths_raw = [*shared_context_paths, *per_task_paths] if per_task_paths else shared_context_paths
            merged_paths = normalize_path_arguments(
                self._base_name,
                {"workspace": arguments.get("workspace"), "context_paths": merged_paths_raw},
            ).get("context_paths", [])
            final_prompt = inject_context_and_report_mode(prompt, merged_paths, report_mode)
            # model 分发：单个则共享，多个则按索引分配
            if len(models) == 1:
                model = models[0]
            elif len(models) >= idx:
                model = models[idx - 1]
            else:
                model = ""
            # continuation_id 分发：按索引分配，空字符串表示新任务
            continuation_id = continuation_ids[idx - 1] if idx <= len(continuation_ids) else ""
            sub_tasks.append({
                "prompt": final_prompt,
                "_original_prompt": prompt,  # 保存原始 prompt 用于 handoff
                "workspace": arguments.get("workspace"),
                "permission": arguments.get("permission", "read-only"),
                "model": model,
                "task_note": note,
                "continuation_id": continuation_id,  # 支持续聊
                "task_tags": arguments.get("task_tags", []),
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
        results: list[tuple[int, str, str, Any]] = []  # (task_index, task_note, original_prompt, result|Exception|None)

        # progress reporter（MCP 保活）
        progress_task: asyncio.Task | None = None
        done_count = 0
        total_tasks = len(sub_tasks)

        async def progress_reporter():
            """定期报告进度以保持连接活跃。"""
            try:
                while True:
                    await asyncio.sleep(PROGRESS_REPORT_INTERVAL)
                    await ctx.report_progress_safe(
                        progress=done_count,
                        total=total_tasks,
                        message=f"Parallel running... ({done_count}/{total_tasks} completed)",
                    )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"Parallel progress reporter crashed: {e}", exc_info=True)

        async def stop_progress_reporter() -> None:
            """停止后台进度保活任务，并确保异常不会泄漏。"""
            nonlocal progress_task
            if not progress_task:
                return
            if not progress_task.done():
                progress_task.cancel()
            try:
                await progress_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"Parallel progress reporter task failed: {e}", exc_info=True)
            finally:
                progress_task = None

        async def run_one(sub_args: dict):
            nonlocal should_stop, done_count
            original_prompt = sub_args.get("_original_prompt", "")

            async with sem:
                try:
                    # fail_fast 检查必须在拿到 semaphore 后
                    if fail_fast and should_stop:
                        return (sub_args["_task_index"], sub_args["task_note"], original_prompt, None)  # skipped

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
                    return (sub_args["_task_index"], sub_args["task_note"], original_prompt, result)

                except asyncio.CancelledError:
                    # 必须 re-raise，不能当作普通异常处理
                    raise
                except Exception as e:
                    if fail_fast:
                        should_stop = True
                    return (sub_args["_task_index"], sub_args["task_note"], original_prompt, e)
                finally:
                    done_count += 1
                    if ctx.has_progress_token():
                        asyncio.create_task(
                            ctx.report_progress_safe(
                                progress=done_count,
                                total=total_tasks,
                                message=f"Parallel progress: {done_count}/{total_tasks}",
                            )
                        )

        start_time = time.time()
        try:
            if ctx.has_progress_token():
                progress_task = asyncio.create_task(progress_reporter())

            raw_results = await asyncio.gather(*[run_one(t) for t in sub_tasks], return_exceptions=True)
        except asyncio.CancelledError:
            raise
        finally:
            await stop_progress_reporter()
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

        for idx, note, original_prompt, result in results:
            if result is None:
                # skipped (fail_fast)
                skipped_count += 1
                summary_lines.append(f"- [{idx}] {note} | skipped")
                continue
            elif isinstance(result, Exception):
                response_data = ResponseData(
                    answer="",
                    session_id="",
                    thought_steps=[],
                    debug_info=None,
                    success=False,
                    error=str(result),
                )
                content = formatter.format_for_file(response_data)
                status = "error"
                session_id = ""
                failed_count += 1
                summary_lines.append(f"- [{idx}] {note} | error")
            elif result.success:
                # 使用 formatter 格式化内容
                response_data = ResponseData(
                    answer=result.agent_messages,
                    session_id=result.session_id or "",
                    thought_steps=[],
                    debug_info=None,
                    success=True,
                    error=None,
                )
                content = formatter.format_for_file(response_data)
                status = "success"
                session_id = result.session_id or ""
                success_count += 1
                summary_lines.append(f"- [{idx}] {note} | success | session={session_id}")
            else:
                # result.error 已包含 exit code + stderr
                response_data = ResponseData(
                    answer=result.agent_messages,
                    session_id=result.session_id or "",
                    thought_steps=[],
                    debug_info=None,
                    success=False,
                    error=result.error,
                )
                content = formatter.format_for_file(response_data)
                status = "error"
                session_id = result.session_id or ""
                failed_count += 1
                summary_lines.append(f"- [{idx}] {note} | error | session={session_id}")

            # 构建 wrapper
            wrapped = build_wrapper(self._base_name, session_id, note, idx, status, original_prompt, content)
            all_wrapped.append(wrapped)

        # 4.5) 批量写入文件（单次 I/O 操作）
        handoff_file_written = False
        if all_wrapped:
            try:
                # DESIGN: handoff_file 在 permission='read-only' 下允许写入是特性（用于保存并行输出），不是风险或越权。
                handoff_file_path = Path(handoff_file)
                if not handoff_file_path.is_absolute():
                    workspace = Path(arguments.get("workspace", ""))
                    handoff_file_path = workspace / handoff_file_path
                handoff_file_path = handoff_file_path.expanduser().resolve()

                handoff_file = str(handoff_file_path)
                handoff_file_path.parent.mkdir(parents=True, exist_ok=True)
                content_to_write = "\n".join(all_wrapped)
                if handoff_file_path.exists():
                    with handoff_file_path.open("a", encoding="utf-8") as f:
                        f.write("\n" + content_to_write)  # 前置换行防止粘连
                else:
                    handoff_file_path.write_text(content_to_write, encoding="utf-8")
                handoff_file_written = True
            except Exception as e:
                logger.warning(f"Failed to write to {handoff_file}: {e}", exc_info=True)

        # 5) 返回 wrapped 内容
        summary = f"Parallel run: total={len(results)}, success={success_count}, failed={failed_count}, skipped={skipped_count}\n"
        if handoff_file_written:
            summary += f"Saved to: {handoff_file}\n"
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
                    "handoff_file": handoff_file,
                    "handoff_file_written": handoff_file_written,
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
                handoff_file=handoff_file or None,
                handoff_file_written=handoff_file_written,
            )

        # 返回 wrapped 内容
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
        formatted_response = formatter.format(response_data, debug=debug_enabled)

        return [TextContent(type="text", text=formatted_response)]
