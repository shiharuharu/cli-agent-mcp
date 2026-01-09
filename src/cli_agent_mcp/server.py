"""CLI Agent MCP Server (FastMCP)。

统一的 CLI Agent MCP 服务器，支持 Codex、Gemini、Claude 三个 CLI。

环境变量:
    CAM_ENABLE: 启用的工具列表（空/未设置=全部）
    CAM_DISABLE: 禁用的工具列表（从 enable 中减去）
    CAM_GUI: 是否启动 GUI (默认 true)
    CAM_GUI_DETAIL: GUI 详细模式 (默认 false)
    CAM_SIGINT_MODE: SIGINT 处理模式 (cancel/exit/cancel_then_exit)
    CAM_SIGINT_DOUBLE_TAP_WINDOW: 双击退出窗口时间 (默认 1.0s)

用法:
    uvx cli-agent-mcp
"""

import asyncio
import logging
import time
from typing import Annotated, Any, Literal, Optional

from fastmcp import FastMCP, Context
from pydantic import Field

from .config import get_config
from .gui_manager import GUIManager
from .orchestrator import RequestRegistry
from .tool_schema import (
    BANANA_PROPERTIES,
    CLAUDE_PROPERTIES,
    CODEX_PROPERTIES,
    COMMON_PROPERTIES,
    IMAGE_PROPERTIES,
    OPENCODE_PROPERTIES,
    PARALLEL_PROPERTIES,
    SUPPORTED_TOOLS,
    TOOL_DESCRIPTIONS,
    TAIL_PROPERTIES,
    create_tool_schema,
    normalize_tool_name,
)
from .handlers import ToolContext, BananaHandler, ImageHandler, CLIHandler, ParallelHandler
from .shared.response_formatter import format_error_response

__all__ = ["create_server"]

logger = logging.getLogger(__name__)

# 参数描述（保持与 tool_schema.py 一致）
PROMPT_DESCRIPTION = COMMON_PROPERTIES["prompt"]["description"]
WORKSPACE_DESCRIPTION = COMMON_PROPERTIES["workspace"]["description"]
CONTINUATION_ID_DESCRIPTION = COMMON_PROPERTIES["continuation_id"]["description"]
PERMISSION_DESCRIPTION = COMMON_PROPERTIES["permission"]["description"]
MODEL_DESCRIPTION = COMMON_PROPERTIES["model"]["description"]
SAVE_FILE_DESCRIPTION = COMMON_PROPERTIES["save_file"]["description"]
SAVE_FILE_WITH_WRAPPER_DESCRIPTION = COMMON_PROPERTIES["save_file_with_wrapper"]["description"]
SAVE_FILE_WITH_APPEND_MODE_DESCRIPTION = COMMON_PROPERTIES["save_file_with_append_mode"]["description"]
REPORT_MODE_DESCRIPTION = COMMON_PROPERTIES["report_mode"]["description"]
CONTEXT_PATHS_DESCRIPTION = COMMON_PROPERTIES["context_paths"]["description"]
TASK_TAGS_DESCRIPTION = COMMON_PROPERTIES["task_tags"]["description"]
CONTEXT_PATHS_PARALLEL_DESCRIPTION = PARALLEL_PROPERTIES["context_paths_parallel"]["description"]

TASK_NOTE_DESCRIPTION = TAIL_PROPERTIES["task_note"]["description"]
DEBUG_DESCRIPTION = TAIL_PROPERTIES["debug"]["description"]

CODEX_IMAGE_DESCRIPTION = CODEX_PROPERTIES["image"]["description"]

CLAUDE_SYSTEM_PROMPT_DESCRIPTION = CLAUDE_PROPERTIES["system_prompt"]["description"]
CLAUDE_APPEND_SYSTEM_PROMPT_DESCRIPTION = CLAUDE_PROPERTIES["append_system_prompt"]["description"]
CLAUDE_AGENT_DESCRIPTION = CLAUDE_PROPERTIES["agent"]["description"]

OPENCODE_FILE_DESCRIPTION = OPENCODE_PROPERTIES["file"]["description"]
OPENCODE_AGENT_DESCRIPTION = OPENCODE_PROPERTIES["agent"]["description"]

# Parallel 参数描述（保持与 tool_schema.py 一致）
PARALLEL_PROMPTS_DESCRIPTION = PARALLEL_PROPERTIES["parallel_prompts"]["description"]
PARALLEL_TASK_NOTES_DESCRIPTION = PARALLEL_PROPERTIES["parallel_task_notes"]["description"]
PARALLEL_CONTINUATION_IDS_DESCRIPTION = PARALLEL_PROPERTIES["parallel_continuation_ids"]["description"]
PARALLEL_MAX_CONCURRENCY_DESCRIPTION = PARALLEL_PROPERTIES["parallel_max_concurrency"]["description"]
PARALLEL_FAIL_FAST_DESCRIPTION = PARALLEL_PROPERTIES["parallel_fail_fast"]["description"]
PARALLEL_MODEL_DESCRIPTION = create_tool_schema("codex", is_parallel=True)["properties"]["model"]["description"]
PARALLEL_CONTEXT_PATHS_DESCRIPTION = create_tool_schema("codex", is_parallel=True)["properties"]["context_paths"]["description"]

# Banana/Image 参数描述（保持与 tool_schema.py 一致）
BANANA_PROMPT_DESCRIPTION = create_tool_schema("banana")["properties"]["prompt"]["description"]
BANANA_SAVE_PATH_DESCRIPTION = BANANA_PROPERTIES["save_path"]["description"]
BANANA_IMAGES_DESCRIPTION = BANANA_PROPERTIES["images"]["description"]
BANANA_ASPECT_RATIO_DESCRIPTION = BANANA_PROPERTIES["aspect_ratio"]["description"]
BANANA_RESOLUTION_DESCRIPTION = BANANA_PROPERTIES["resolution"]["description"]
BANANA_USE_SEARCH_DESCRIPTION = BANANA_PROPERTIES["use_search"]["description"]
BANANA_INCLUDE_THOUGHTS_DESCRIPTION = BANANA_PROPERTIES["include_thoughts"]["description"]
BANANA_TEMPERATURE_DESCRIPTION = BANANA_PROPERTIES["temperature"]["description"]
BANANA_TOP_P_DESCRIPTION = BANANA_PROPERTIES["top_p"]["description"]
BANANA_TOP_K_DESCRIPTION = BANANA_PROPERTIES["top_k"]["description"]
BANANA_NUM_IMAGES_DESCRIPTION = BANANA_PROPERTIES["num_images"]["description"]
BANANA_TASK_NOTE_DESCRIPTION = create_tool_schema("banana")["properties"]["task_note"]["description"]

IMAGE_PROMPT_DESCRIPTION = create_tool_schema("image")["properties"]["prompt"]["description"]
IMAGE_SAVE_PATH_DESCRIPTION = IMAGE_PROPERTIES["save_path"]["description"]
IMAGE_IMAGES_DESCRIPTION = IMAGE_PROPERTIES["images"]["description"]
IMAGE_MODEL_DESCRIPTION = IMAGE_PROPERTIES["model"]["description"]
IMAGE_ASPECT_RATIO_DESCRIPTION = IMAGE_PROPERTIES["aspect_ratio"]["description"]
IMAGE_RESOLUTION_DESCRIPTION = IMAGE_PROPERTIES["resolution"]["description"]
IMAGE_QUALITY_DESCRIPTION = IMAGE_PROPERTIES["quality"]["description"]
IMAGE_API_TYPE_DESCRIPTION = IMAGE_PROPERTIES["api_type"]["description"]
IMAGE_TASK_NOTE_DESCRIPTION = create_tool_schema("image")["properties"]["task_note"]["description"]

# 类型别名
PermissionType = Literal["read-only", "workspace-write", "unlimited"]
AspectRatioType = Literal["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"]
ResolutionType = Literal["1K", "2K", "4K"]
ImageApiType = Literal["", "openrouter_chat", "openai_images", "openai_responses"]


def create_server(
    gui_manager: Optional[GUIManager] = None,
    registry: Optional[RequestRegistry] = None,
) -> FastMCP:
    """创建 FastMCP Server 实例。"""
    config = get_config()
    mcp = FastMCP("cli-agent-mcp")

    def push_to_gui(event_dict: dict[str, Any]) -> None:
        if gui_manager and gui_manager.is_running:
            gui_manager.push_event(event_dict)

    def push_user_prompt(cli_type: str, prompt: str, task_note: str = "") -> None:
        push_to_gui({
            "category": "message",
            "source": cli_type,
            "role": "user",
            "text": prompt,
            "content_type": "text",
            "timestamp": time.time(),
            "raw": {"type": "user", "content": prompt},
            "metadata": {"task_note": task_note} if task_note else {},
        })

    def make_event_callback(cli_type: str, task_note: str = "", task_index: Optional[int] = None):
        def callback(event):
            if gui_manager and gui_manager.is_running:
                event_dict = event.model_dump() if hasattr(event, "model_dump") else dict(event.__dict__)
                event_dict["source"] = cli_type
                metadata = event_dict.get("metadata", {}) or {}
                if task_note:
                    metadata["task_note"] = task_note
                if task_index is not None:
                    metadata["task_index"] = task_index
                if metadata:
                    event_dict["metadata"] = metadata
                gui_manager.push_event(event_dict)
        return callback

    def create_tool_context(ctx: Optional[Context] = None) -> ToolContext:
        tool_ctx = ToolContext(
            config=config,
            gui_manager=gui_manager,
            registry=registry,
            push_to_gui=push_to_gui,
            push_user_prompt=push_user_prompt,
            make_event_callback=make_event_callback,
        )
        tool_ctx.mcp_context = ctx
        return tool_ctx

    async def handle_tool(name: str, arguments: dict[str, Any], ctx: Optional[Context] = None) -> str:
        """统一的工具调用处理。"""
        base_name, is_parallel = normalize_tool_name(name)
        task_note = arguments.get("task_note", "") or (
            " + ".join(arguments.get("parallel_task_notes", [])) if is_parallel else ""
        )

        request_id = None
        if registry is not None:
            request_id = registry.generate_request_id()
            current_task = asyncio.current_task()
            if current_task:
                registry.register(request_id, name, current_task, task_note)

        tool_ctx = create_tool_context(ctx)

        try:
            if base_name == "banana":
                handler = BananaHandler()
                result = await handler.handle(arguments, tool_ctx)
            elif base_name == "image":
                handler = ImageHandler()
                result = await handler.handle(arguments, tool_ctx)
            elif is_parallel:
                handler = ParallelHandler(base_name)
                result = await handler.handle(arguments, tool_ctx)
            else:
                handler = CLIHandler(base_name)
                result = await handler.handle(arguments, tool_ctx)

            return result[0].text if result else ""

        except asyncio.CancelledError:
            logger.info(f"Tool '{name}' cancelled")
            raise
        except BaseException as e:
            logger.error(f"Tool '{name}' error: {type(e).__name__}: {e}", exc_info=True)
            if isinstance(e, Exception):
                return format_error_response(str(e))[0].text
            raise
        finally:
            if registry and request_id:
                registry.unregister(request_id)

    def register_tool_with_schema(*, name: str, description: str, schema: dict[str, Any], fn: Any) -> None:
        tool = mcp.tool(fn, name=name, description=description, output_schema=None)
        tool.parameters = schema

    # === CLI 工具 ===
    if config.is_tool_allowed("codex"):
        async def codex(
            prompt: Annotated[str, Field(description=PROMPT_DESCRIPTION)],
            workspace: Annotated[str, Field(description=WORKSPACE_DESCRIPTION)],
            ctx: Context,
            continuation_id: Annotated[str, Field(description=CONTINUATION_ID_DESCRIPTION)] = "",
            permission: Annotated[PermissionType, Field(description=PERMISSION_DESCRIPTION)] = "read-only",
            model: Annotated[str, Field(description=MODEL_DESCRIPTION)] = "",
            save_file: Annotated[str, Field(description=SAVE_FILE_DESCRIPTION)] = "",
            save_file_with_wrapper: Annotated[bool, Field(description=SAVE_FILE_WITH_WRAPPER_DESCRIPTION)] = False,
            save_file_with_append_mode: Annotated[bool, Field(description=SAVE_FILE_WITH_APPEND_MODE_DESCRIPTION)] = False,
            report_mode: Annotated[bool, Field(description=REPORT_MODE_DESCRIPTION)] = False,
            context_paths: Annotated[list[str], Field(description=CONTEXT_PATHS_DESCRIPTION)] = Field(default_factory=list),
            task_tags: Annotated[list[str], Field(description=TASK_TAGS_DESCRIPTION)] = Field(default_factory=list),
            image: Annotated[list[str], Field(description=CODEX_IMAGE_DESCRIPTION)] = Field(default_factory=list),
            task_note: Annotated[str, Field(description=TASK_NOTE_DESCRIPTION)] = "",
            debug: Annotated[bool, Field(description=DEBUG_DESCRIPTION)] = False,
        ) -> str:
            arguments = {k: v for k, v in locals().items() if k != "ctx"}
            return await handle_tool("codex", arguments, ctx)
        register_tool_with_schema(
            name="codex",
            description=TOOL_DESCRIPTIONS["codex"],
            schema=create_tool_schema("codex"),
            fn=codex,
        )

    if config.is_tool_allowed("gemini"):
        async def gemini(
            prompt: Annotated[str, Field(description=PROMPT_DESCRIPTION)],
            workspace: Annotated[str, Field(description=WORKSPACE_DESCRIPTION)],
            ctx: Context,
            continuation_id: Annotated[str, Field(description=CONTINUATION_ID_DESCRIPTION)] = "",
            permission: Annotated[PermissionType, Field(description=PERMISSION_DESCRIPTION)] = "read-only",
            model: Annotated[str, Field(description=MODEL_DESCRIPTION)] = "",
            save_file: Annotated[str, Field(description=SAVE_FILE_DESCRIPTION)] = "",
            save_file_with_wrapper: Annotated[bool, Field(description=SAVE_FILE_WITH_WRAPPER_DESCRIPTION)] = False,
            save_file_with_append_mode: Annotated[bool, Field(description=SAVE_FILE_WITH_APPEND_MODE_DESCRIPTION)] = False,
            report_mode: Annotated[bool, Field(description=REPORT_MODE_DESCRIPTION)] = False,
            context_paths: Annotated[list[str], Field(description=CONTEXT_PATHS_DESCRIPTION)] = Field(default_factory=list),
            task_tags: Annotated[list[str], Field(description=TASK_TAGS_DESCRIPTION)] = Field(default_factory=list),
            task_note: Annotated[str, Field(description=TASK_NOTE_DESCRIPTION)] = "",
            debug: Annotated[bool, Field(description=DEBUG_DESCRIPTION)] = False,
        ) -> str:
            arguments = {k: v for k, v in locals().items() if k != "ctx"}
            return await handle_tool("gemini", arguments, ctx)
        register_tool_with_schema(
            name="gemini",
            description=TOOL_DESCRIPTIONS["gemini"],
            schema=create_tool_schema("gemini"),
            fn=gemini,
        )

    if config.is_tool_allowed("claude"):
        async def claude(
            prompt: Annotated[str, Field(description=PROMPT_DESCRIPTION)],
            workspace: Annotated[str, Field(description=WORKSPACE_DESCRIPTION)],
            ctx: Context,
            continuation_id: Annotated[str, Field(description=CONTINUATION_ID_DESCRIPTION)] = "",
            permission: Annotated[PermissionType, Field(description=PERMISSION_DESCRIPTION)] = "read-only",
            model: Annotated[str, Field(description=MODEL_DESCRIPTION)] = "",
            save_file: Annotated[str, Field(description=SAVE_FILE_DESCRIPTION)] = "",
            save_file_with_wrapper: Annotated[bool, Field(description=SAVE_FILE_WITH_WRAPPER_DESCRIPTION)] = False,
            save_file_with_append_mode: Annotated[bool, Field(description=SAVE_FILE_WITH_APPEND_MODE_DESCRIPTION)] = False,
            report_mode: Annotated[bool, Field(description=REPORT_MODE_DESCRIPTION)] = False,
            context_paths: Annotated[list[str], Field(description=CONTEXT_PATHS_DESCRIPTION)] = Field(default_factory=list),
            task_tags: Annotated[list[str], Field(description=TASK_TAGS_DESCRIPTION)] = Field(default_factory=list),
            system_prompt: Annotated[str, Field(description=CLAUDE_SYSTEM_PROMPT_DESCRIPTION)] = "",
            append_system_prompt: Annotated[str, Field(description=CLAUDE_APPEND_SYSTEM_PROMPT_DESCRIPTION)] = "",
            agent: Annotated[str, Field(description=CLAUDE_AGENT_DESCRIPTION)] = "",
            task_note: Annotated[str, Field(description=TASK_NOTE_DESCRIPTION)] = "",
            debug: Annotated[bool, Field(description=DEBUG_DESCRIPTION)] = False,
        ) -> str:
            arguments = {k: v for k, v in locals().items() if k != "ctx"}
            return await handle_tool("claude", arguments, ctx)
        register_tool_with_schema(
            name="claude",
            description=TOOL_DESCRIPTIONS["claude"],
            schema=create_tool_schema("claude"),
            fn=claude,
        )

    if config.is_tool_allowed("opencode"):
        async def opencode(
            prompt: Annotated[str, Field(description=PROMPT_DESCRIPTION)],
            workspace: Annotated[str, Field(description=WORKSPACE_DESCRIPTION)],
            ctx: Context,
            continuation_id: Annotated[str, Field(description=CONTINUATION_ID_DESCRIPTION)] = "",
            permission: Annotated[PermissionType, Field(description=PERMISSION_DESCRIPTION)] = "read-only",
            model: Annotated[str, Field(description=MODEL_DESCRIPTION)] = "",
            save_file: Annotated[str, Field(description=SAVE_FILE_DESCRIPTION)] = "",
            save_file_with_wrapper: Annotated[bool, Field(description=SAVE_FILE_WITH_WRAPPER_DESCRIPTION)] = False,
            save_file_with_append_mode: Annotated[bool, Field(description=SAVE_FILE_WITH_APPEND_MODE_DESCRIPTION)] = False,
            report_mode: Annotated[bool, Field(description=REPORT_MODE_DESCRIPTION)] = False,
            context_paths: Annotated[list[str], Field(description=CONTEXT_PATHS_DESCRIPTION)] = Field(default_factory=list),
            task_tags: Annotated[list[str], Field(description=TASK_TAGS_DESCRIPTION)] = Field(default_factory=list),
            file: Annotated[list[str], Field(description=OPENCODE_FILE_DESCRIPTION)] = Field(default_factory=list),
            agent: Annotated[str, Field(description=OPENCODE_AGENT_DESCRIPTION)] = "build",
            task_note: Annotated[str, Field(description=TASK_NOTE_DESCRIPTION)] = "",
            debug: Annotated[bool, Field(description=DEBUG_DESCRIPTION)] = False,
        ) -> str:
            arguments = {k: v for k, v in locals().items() if k != "ctx"}
            return await handle_tool("opencode", arguments, ctx)
        register_tool_with_schema(
            name="opencode",
            description=TOOL_DESCRIPTIONS["opencode"],
            schema=create_tool_schema("opencode"),
            fn=opencode,
        )

    # === Parallel 工具 ===
    if config.is_tool_allowed("codex"):
        async def codex_parallel(
            workspace: Annotated[str, Field(description=WORKSPACE_DESCRIPTION)],
            save_file: Annotated[str, Field(description=SAVE_FILE_DESCRIPTION)],
            parallel_prompts: Annotated[list[str], Field(description=PARALLEL_PROMPTS_DESCRIPTION)],
            parallel_task_notes: Annotated[list[str], Field(description=PARALLEL_TASK_NOTES_DESCRIPTION)],
            ctx: Context,
            parallel_continuation_ids: Annotated[list[str], Field(description=PARALLEL_CONTINUATION_IDS_DESCRIPTION)] = Field(default_factory=list),
            permission: Annotated[PermissionType, Field(description=PERMISSION_DESCRIPTION)] = "read-only",
            model: Annotated[list[str], Field(description=PARALLEL_MODEL_DESCRIPTION)] = Field(default_factory=list),
            report_mode: Annotated[bool, Field(description=REPORT_MODE_DESCRIPTION)] = False,
            context_paths: Annotated[list[str], Field(description=PARALLEL_CONTEXT_PATHS_DESCRIPTION)] = Field(default_factory=list),
            context_paths_parallel: Annotated[list[list[str]], Field(description=CONTEXT_PATHS_PARALLEL_DESCRIPTION)] = Field(default_factory=list),
            task_tags: Annotated[list[str], Field(description=TASK_TAGS_DESCRIPTION)] = Field(default_factory=list),
            image: Annotated[list[str], Field(description=CODEX_IMAGE_DESCRIPTION)] = Field(default_factory=list),
            parallel_max_concurrency: Annotated[int, Field(description=PARALLEL_MAX_CONCURRENCY_DESCRIPTION)] = 20,
            parallel_fail_fast: Annotated[bool, Field(description=PARALLEL_FAIL_FAST_DESCRIPTION)] = False,
            debug: Annotated[bool, Field(description=DEBUG_DESCRIPTION)] = False,
        ) -> str:
            arguments = {k: v for k, v in locals().items() if k != "ctx"}
            return await handle_tool("codex_parallel", arguments, ctx)
        register_tool_with_schema(
            name="codex_parallel",
            description="Run multiple codex tasks in parallel. Results appended to save_file with XML wrappers.",
            schema=create_tool_schema("codex", is_parallel=True),
            fn=codex_parallel,
        )

    if config.is_tool_allowed("gemini"):
        async def gemini_parallel(
            workspace: Annotated[str, Field(description=WORKSPACE_DESCRIPTION)],
            save_file: Annotated[str, Field(description=SAVE_FILE_DESCRIPTION)],
            parallel_prompts: Annotated[list[str], Field(description=PARALLEL_PROMPTS_DESCRIPTION)],
            parallel_task_notes: Annotated[list[str], Field(description=PARALLEL_TASK_NOTES_DESCRIPTION)],
            ctx: Context,
            parallel_continuation_ids: Annotated[list[str], Field(description=PARALLEL_CONTINUATION_IDS_DESCRIPTION)] = Field(default_factory=list),
            permission: Annotated[PermissionType, Field(description=PERMISSION_DESCRIPTION)] = "read-only",
            model: Annotated[list[str], Field(description=PARALLEL_MODEL_DESCRIPTION)] = Field(default_factory=list),
            report_mode: Annotated[bool, Field(description=REPORT_MODE_DESCRIPTION)] = False,
            context_paths: Annotated[list[str], Field(description=PARALLEL_CONTEXT_PATHS_DESCRIPTION)] = Field(default_factory=list),
            context_paths_parallel: Annotated[list[list[str]], Field(description=CONTEXT_PATHS_PARALLEL_DESCRIPTION)] = Field(default_factory=list),
            task_tags: Annotated[list[str], Field(description=TASK_TAGS_DESCRIPTION)] = Field(default_factory=list),
            parallel_max_concurrency: Annotated[int, Field(description=PARALLEL_MAX_CONCURRENCY_DESCRIPTION)] = 20,
            parallel_fail_fast: Annotated[bool, Field(description=PARALLEL_FAIL_FAST_DESCRIPTION)] = False,
            debug: Annotated[bool, Field(description=DEBUG_DESCRIPTION)] = False,
        ) -> str:
            arguments = {k: v for k, v in locals().items() if k != "ctx"}
            return await handle_tool("gemini_parallel", arguments, ctx)
        register_tool_with_schema(
            name="gemini_parallel",
            description="Run multiple gemini tasks in parallel.",
            schema=create_tool_schema("gemini", is_parallel=True),
            fn=gemini_parallel,
        )

    if config.is_tool_allowed("claude"):
        async def claude_parallel(
            workspace: Annotated[str, Field(description=WORKSPACE_DESCRIPTION)],
            save_file: Annotated[str, Field(description=SAVE_FILE_DESCRIPTION)],
            parallel_prompts: Annotated[list[str], Field(description=PARALLEL_PROMPTS_DESCRIPTION)],
            parallel_task_notes: Annotated[list[str], Field(description=PARALLEL_TASK_NOTES_DESCRIPTION)],
            ctx: Context,
            parallel_continuation_ids: Annotated[list[str], Field(description=PARALLEL_CONTINUATION_IDS_DESCRIPTION)] = Field(default_factory=list),
            permission: Annotated[PermissionType, Field(description=PERMISSION_DESCRIPTION)] = "read-only",
            model: Annotated[list[str], Field(description=PARALLEL_MODEL_DESCRIPTION)] = Field(default_factory=list),
            report_mode: Annotated[bool, Field(description=REPORT_MODE_DESCRIPTION)] = False,
            context_paths: Annotated[list[str], Field(description=PARALLEL_CONTEXT_PATHS_DESCRIPTION)] = Field(default_factory=list),
            context_paths_parallel: Annotated[list[list[str]], Field(description=CONTEXT_PATHS_PARALLEL_DESCRIPTION)] = Field(default_factory=list),
            task_tags: Annotated[list[str], Field(description=TASK_TAGS_DESCRIPTION)] = Field(default_factory=list),
            system_prompt: Annotated[str, Field(description=CLAUDE_SYSTEM_PROMPT_DESCRIPTION)] = "",
            append_system_prompt: Annotated[str, Field(description=CLAUDE_APPEND_SYSTEM_PROMPT_DESCRIPTION)] = "",
            agent: Annotated[str, Field(description=CLAUDE_AGENT_DESCRIPTION)] = "",
            parallel_max_concurrency: Annotated[int, Field(description=PARALLEL_MAX_CONCURRENCY_DESCRIPTION)] = 20,
            parallel_fail_fast: Annotated[bool, Field(description=PARALLEL_FAIL_FAST_DESCRIPTION)] = False,
            debug: Annotated[bool, Field(description=DEBUG_DESCRIPTION)] = False,
        ) -> str:
            arguments = {k: v for k, v in locals().items() if k != "ctx"}
            return await handle_tool("claude_parallel", arguments, ctx)
        register_tool_with_schema(
            name="claude_parallel",
            description="Run multiple claude tasks in parallel.",
            schema=create_tool_schema("claude", is_parallel=True),
            fn=claude_parallel,
        )

    if config.is_tool_allowed("opencode"):
        async def opencode_parallel(
            workspace: Annotated[str, Field(description=WORKSPACE_DESCRIPTION)],
            save_file: Annotated[str, Field(description=SAVE_FILE_DESCRIPTION)],
            parallel_prompts: Annotated[list[str], Field(description=PARALLEL_PROMPTS_DESCRIPTION)],
            parallel_task_notes: Annotated[list[str], Field(description=PARALLEL_TASK_NOTES_DESCRIPTION)],
            ctx: Context,
            parallel_continuation_ids: Annotated[list[str], Field(description=PARALLEL_CONTINUATION_IDS_DESCRIPTION)] = Field(default_factory=list),
            permission: Annotated[PermissionType, Field(description=PERMISSION_DESCRIPTION)] = "read-only",
            model: Annotated[list[str], Field(description=PARALLEL_MODEL_DESCRIPTION)] = Field(default_factory=list),
            report_mode: Annotated[bool, Field(description=REPORT_MODE_DESCRIPTION)] = False,
            context_paths: Annotated[list[str], Field(description=PARALLEL_CONTEXT_PATHS_DESCRIPTION)] = Field(default_factory=list),
            context_paths_parallel: Annotated[list[list[str]], Field(description=CONTEXT_PATHS_PARALLEL_DESCRIPTION)] = Field(default_factory=list),
            task_tags: Annotated[list[str], Field(description=TASK_TAGS_DESCRIPTION)] = Field(default_factory=list),
            file: Annotated[list[str], Field(description=OPENCODE_FILE_DESCRIPTION)] = Field(default_factory=list),
            agent: Annotated[str, Field(description=OPENCODE_AGENT_DESCRIPTION)] = "build",
            parallel_max_concurrency: Annotated[int, Field(description=PARALLEL_MAX_CONCURRENCY_DESCRIPTION)] = 20,
            parallel_fail_fast: Annotated[bool, Field(description=PARALLEL_FAIL_FAST_DESCRIPTION)] = False,
            debug: Annotated[bool, Field(description=DEBUG_DESCRIPTION)] = False,
        ) -> str:
            arguments = {k: v for k, v in locals().items() if k != "ctx"}
            return await handle_tool("opencode_parallel", arguments, ctx)
        register_tool_with_schema(
            name="opencode_parallel",
            description="Run multiple opencode tasks in parallel.",
            schema=create_tool_schema("opencode", is_parallel=True),
            fn=opencode_parallel,
        )

    # === 图像工具 ===
    if config.is_tool_allowed("banana"):
        async def banana(
            prompt: Annotated[str, Field(description=BANANA_PROMPT_DESCRIPTION)],
            save_path: Annotated[str, Field(description=BANANA_SAVE_PATH_DESCRIPTION)],
            task_note: Annotated[str, Field(description=BANANA_TASK_NOTE_DESCRIPTION)],
            ctx: Context,
            images: Annotated[list[dict], Field(description=BANANA_IMAGES_DESCRIPTION)] = Field(default_factory=list),
            aspect_ratio: Annotated[AspectRatioType, Field(description=BANANA_ASPECT_RATIO_DESCRIPTION)] = "1:1",
            resolution: Annotated[ResolutionType, Field(description=BANANA_RESOLUTION_DESCRIPTION)] = "4K",
            use_search: Annotated[bool, Field(description=BANANA_USE_SEARCH_DESCRIPTION)] = False,
            include_thoughts: Annotated[bool, Field(description=BANANA_INCLUDE_THOUGHTS_DESCRIPTION)] = False,
            temperature: Annotated[float, Field(description=BANANA_TEMPERATURE_DESCRIPTION)] = 1.0,
            top_p: Annotated[float, Field(description=BANANA_TOP_P_DESCRIPTION)] = 0.95,
            top_k: Annotated[int, Field(description=BANANA_TOP_K_DESCRIPTION)] = 40,
            num_images: Annotated[int, Field(description=BANANA_NUM_IMAGES_DESCRIPTION)] = 1,
            debug: Annotated[bool, Field(description=DEBUG_DESCRIPTION)] = False,
        ) -> str:
            arguments = {k: v for k, v in locals().items() if k != "ctx"}
            return await handle_tool("banana", arguments, ctx)
        register_tool_with_schema(
            name="banana",
            description=TOOL_DESCRIPTIONS["banana"],
            schema=create_tool_schema("banana"),
            fn=banana,
        )

    if config.is_tool_allowed("image"):
        async def image(
            prompt: Annotated[str, Field(description=IMAGE_PROMPT_DESCRIPTION)],
            save_path: Annotated[str, Field(description=IMAGE_SAVE_PATH_DESCRIPTION)],
            task_note: Annotated[str, Field(description=IMAGE_TASK_NOTE_DESCRIPTION)],
            ctx: Context,
            images: Annotated[list[dict], Field(description=IMAGE_IMAGES_DESCRIPTION)] = Field(default_factory=list),
            model: Annotated[str, Field(description=IMAGE_MODEL_DESCRIPTION)] = "",
            aspect_ratio: Annotated[AspectRatioType, Field(description=IMAGE_ASPECT_RATIO_DESCRIPTION)] = "1:1",
            resolution: Annotated[ResolutionType, Field(description=IMAGE_RESOLUTION_DESCRIPTION)] = "1K",
            quality: Annotated[str, Field(description=IMAGE_QUALITY_DESCRIPTION)] = "standard",
            api_type: Annotated[ImageApiType, Field(description=IMAGE_API_TYPE_DESCRIPTION)] = "",
            debug: Annotated[bool, Field(description=DEBUG_DESCRIPTION)] = False,
        ) -> str:
            arguments = {k: v for k, v in locals().items() if k != "ctx"}
            return await handle_tool("image", arguments, ctx)
        register_tool_with_schema(
            name="image",
            description=TOOL_DESCRIPTIONS["image"],
            schema=create_tool_schema("image"),
            fn=image,
        )

    # === GUI URL 工具 ===
    if gui_manager:
        async def get_gui_url() -> str:
            if gui_manager and gui_manager.url:
                return gui_manager.url
            return "GUI not available or URL not ready"
        register_tool_with_schema(
            name="get_gui_url",
            description="Get the GUI dashboard URL. Returns the HTTP URL where the live event viewer is accessible.",
            schema={"type": "object", "properties": {}, "required": []},
            fn=get_gui_url,
        )

    logger.debug(f"[MCP] Server created with tools: {[t for t in SUPPORTED_TOOLS if config.is_tool_allowed(t)]}")
    return mcp
