"""CLI Agent MCP Server。

统一的 CLI Agent MCP 服务器，支持 Codex、Gemini、Claude 三个 CLI。

环境变量:
    CAM_TOOLS: 允许的工具列表（空=全部）
    CAM_GUI: 是否启动 GUI (默认 true)
    CAM_GUI_DETAIL: GUI 详细模式 (默认 false)
    CAM_SIGINT_MODE: SIGINT 处理模式 (cancel/exit/cancel_then_exit)
    CAM_SIGINT_DOUBLE_TAP_WINDOW: 双击退出窗口时间 (默认 1.0s)

用法:
    uvx cli-agent-mcp
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import anyio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .config import get_config
from .gui_manager import GUIConfig, GUIManager
from .orchestrator import RequestRegistry
from .signal_manager import SignalManager
from .shared.response_formatter import (
    ResponseFormatter,
    ResponseData,
    DebugInfo as FormatterDebugInfo,
    get_formatter,
)

# 支持的工具列表（用于校验）
SUPPORTED_TOOLS = {"codex", "gemini", "claude", "opencode", "banana", "image"}


def _resolve_debug(arguments: dict[str, Any], config: Any) -> bool:
    """统一解析 debug 开关。

    优先使用 arguments 中显式传入的值，否则跟随 config.debug。
    """
    if "debug" in arguments:
        return bool(arguments["debug"])
    return config.debug


def _format_error_response(error: str) -> list[TextContent]:
    """统一的错误响应格式化函数。

    确保所有错误都以 <response><error>...</error></response> 格式返回，
    保持 API 契约一致性。
    """
    formatter = get_formatter()
    response_data = ResponseData(
        answer="",
        session_id="",
        success=False,
        error=error,
    )
    return [TextContent(type="text", text=formatter.format(response_data))]

from .shared.invokers import (
    CLIType,
    ClaudeInvoker,
    ClaudeParams,
    CodexInvoker,
    CodexParams,
    GeminiInvoker,
    GeminiParams,
    OpencodeInvoker,
    OpencodeParams,
    BananaInvoker,
    BananaParams,
    ImageInvoker,
    ImageParams,
    Permission,
    create_invoker,
)

__all__ = ["main", "create_server"]

logger = logging.getLogger(__name__)

# 工具描述
TOOL_DESCRIPTIONS = {
    "codex": """Run OpenAI Codex CLI agent (deep analysis / critical review).

NO SHARED MEMORY:
- Cannot see messages/outputs from gemini/claude/opencode.
- Only sees: (1) this prompt, (2) files in context_paths, (3) its own history via continuation_id.

CROSS-AGENT HANDOFF:
- Small data: paste into prompt.
- Large data: save_file -> context_paths -> prompt says "Read <file>".

CAPABILITIES:
- Strongest deep analysis and reflection abilities
- Excellent at finding issues, edge cases, and potential bugs
- Good at critical code review and architectural assessment

BEST PRACTICES:
- Be explicit about scope: "Only fix X, don't refactor Y"
- Specify constraints: "Keep it simple, no new abstractions"

Supports: image attachments.""",

    "gemini": """Run Google Gemini CLI agent (UI design / comprehensive analysis).

NO SHARED MEMORY:
- Cannot see messages/outputs from codex/claude/opencode.
- Only sees: (1) this prompt, (2) files in context_paths, (3) its own history via continuation_id.

CROSS-AGENT HANDOFF:
- Small data: paste into prompt.
- Large data: save_file -> context_paths -> prompt says "Read <file>".

CAPABILITIES:
- Strongest UI design and image understanding abilities
- Excellent at rapid UI prototyping and visual tasks
- Great at inferring original requirements from code clues
- Best for full-text analysis and detective work

BEST PRACTICES:
- Enable verbose_output when doing research or analysis
- Good first choice for "understand this codebase" tasks""",

    "claude": """Run Anthropic Claude CLI agent (code implementation).

NO SHARED MEMORY:
- Cannot see messages/outputs from codex/gemini/opencode.
- Only sees: (1) this prompt, (2) files in context_paths, (3) its own history via continuation_id.

CROSS-AGENT HANDOFF:
- Small data: paste into prompt.
- Large data: save_file -> context_paths -> prompt says "Read <file>".

CAPABILITIES:
- Strongest code writing and implementation abilities
- Excellent at translating requirements into working code
- Good at following patterns and conventions

BEST PRACTICES:
- Be explicit about target: "Replace old implementation completely"
- Specify cleanup: "Remove deprecated code paths"

Supports: system_prompt, append_system_prompt, agent parameter.""",

    "opencode": """Run OpenCode CLI agent (full-stack development).

NO SHARED MEMORY:
- Cannot see messages/outputs from codex/gemini/claude.
- Only sees: (1) this prompt, (2) files in context_paths, (3) its own history via continuation_id.

CROSS-AGENT HANDOFF:
- Small data: paste into prompt.
- Large data: save_file -> context_paths -> prompt says "Read <file>".

CAPABILITIES:
- Excellent at rapid prototyping and development tasks
- Good at working with multiple frameworks and tools
- Supports multiple AI providers (Anthropic, OpenAI, Google, etc.)

BEST PRACTICES:
- Specify agent type for specialized tasks (e.g., --agent build)
- Use file attachments for context-heavy tasks

Supports: file attachments, multiple agents (build, plan, etc.).""",

    "banana": """Generate images using Nano Banana Pro (Gemini 3 Pro Image).

CAPABILITIES:
- Text-to-image generation with high quality output
- Image editing and transformation with reference images
- Multiple aspect ratios and resolutions (1K/2K/4K)
- Style transfer and multi-image fusion
- Optional search grounding for factual content

RESPONSE FORMAT:
- Returns XML with file paths to generated images
- Images are saved to disk (no base64 in response)
- Includes text descriptions and optional thinking process

BEST PRACTICES:
- Be descriptive: describe scenes, not just keywords
- Use negative constraints in prompt: "no text", "no watermark"
- For editing: provide reference image and specify what to keep
- For style transfer: provide style reference image

Supports: reference images with roles (edit_base, style_ref, etc.).""",

    "image": """Generate images via OpenRouter-compatible or OpenAI-compatible endpoints.

CAPABILITIES:
- Text-to-image generation with multiple providers
- Image editing and transformation with reference images
- Multiple aspect ratios and resolutions (1K/2K/4K)

RESPONSE FORMAT:
- Returns XML with file paths to generated images
- Images saved to disk (no base64 in response)
- Includes text descriptions when available

BEST PRACTICES:
- Be descriptive: describe scenes, lighting, style, composition
- Use negative constraints in prompt: "no text", "no watermark", "no blur"
- For editing: provide reference image and specify what to keep

Supports: reference images for editing.""",
}

# 公共参数 schema（按重要性排序）
COMMON_PROPERTIES = {
    # === 必填参数 ===
    "prompt": {
        "type": "string",
        "description": (
            "Detailed instructions for the agent. "
            "IMPORTANT: If 'continuation_id' is NOT set, you MUST include ALL context "
            "(background, file contents, errors, constraints), as the agent has no memory. "
            "If 'continuation_id' IS set, you may be brief and reference previous context."
        ),
    },
    "workspace": {
        "type": "string",
        "description": (
            "Project root directory. Boundary for 'workspace-write'. "
            "Use absolute paths or relative paths."
        ),
    },
    # === 常用参数 ===
    "continuation_id": {
        "type": "string",
        "default": "",
        "description": (
            "Resume session WITHIN THIS TOOL ONLY. "
            "Use only the <continuation_id> returned by this same tool. "
            "IDs are agent-specific: codex ID won't work with gemini/claude/opencode. "
            "Switching agents does NOT sync info; pass updates via prompt or context_paths."
        ),
    },
    "permission": {
        "type": "string",
        "enum": ["read-only", "workspace-write", "unlimited"],
        "default": "read-only",
        "description": (
            "Security level: "
            "'read-only' (analyze files), "
            "'workspace-write' (modify inside workspace), "
            "'unlimited' (full system access). "
            "Default: 'read-only'."
        ),
    },
    "model": {
        "type": "string",
        "default": "",
        "description": "Optional model override (e.g., 'gemini-2.5-pro'). Use only if specifically requested.",
    },
    "save_file": {
        "type": "string",
        "description": (
            "PREFERRED when agent needs to write files or produce lengthy output. "
            "Output is written directly to this path, avoiding context overflow. "
            "This write is permitted even in read-only mode (server-handled). "
            "Essential for: code generation, detailed reports, documentation."
        ),
    },
    "save_file_with_wrapper": {
        "type": "boolean",
        "default": False,
        "description": (
            "When true AND save_file is set, wrap output in <agent-output> XML tags "
            "with metadata (agent name, continuation_id). For multi-agent assembly."
        ),
    },
    "save_file_with_append_mode": {
        "type": "boolean",
        "default": False,
        "description": (
            "When true AND save_file is set, append instead of overwrite. "
            "For multi-agent collaboration on same document."
        ),
    },
    "verbose_output": {
        "type": "boolean",
        "default": False,
        "description": "Include internal reasoning/tool traces in response. Useful for debugging.",
    },
    "report_mode": {
        "type": "boolean",
        "default": False,
        "description": "Generate a standalone, document-style report (no chat filler) suitable for sharing.",
    },
    "context_paths": {
        "type": "array",
        "items": {"type": "string"},
        "default": [],
        "description": "List of relevant files/dirs to preload as context hints.",
    },
}

# 特有参数（插入到公共参数之后）
CODEX_PROPERTIES = {
    "image": {
        "type": "array",
        "items": {"type": "string"},
        "default": [],
        "description": (
            "Absolute paths to image files for visual context. "
            "Use for: UI screenshots, error dialogs, design mockups. "
            "Example: ['/path/to/screenshot.png']"
        ),
    },
}

CLAUDE_PROPERTIES = {
    "system_prompt": {
        "type": "string",
        "default": "",
        "description": (
            "Complete replacement for the default system prompt. "
            "Use only when you need full control over agent behavior. "
            "Prefer append_system_prompt for most cases."
        ),
    },
    "append_system_prompt": {
        "type": "string",
        "default": "",
        "description": (
            "Additional instructions appended to the default system prompt. "
            "Recommended way to customize behavior. "
            "Example: 'Focus on performance optimization, avoid adding new dependencies'"
        ),
    },
    "agent": {
        "type": "string",
        "default": "",
        "description": (
            "Specify an agent for the current session (overrides the default agent setting). "
            "Use predefined agent names configured in Claude Code settings."
        ),
    },
}

OPENCODE_PROPERTIES = {
    "file": {
        "type": "array",
        "items": {"type": "string"},
        "default": [],
        "description": (
            "Absolute paths to files to attach to the message. "
            "Use for: Source code files, configuration files, documentation. "
            "Example: ['/path/to/main.py', '/path/to/config.json']"
        ),
    },
    "agent": {
        "type": "string",
        "default": "build",
        "description": (
            "Agent type to use for the task. "
            "Common agents: 'build' (default, general development), 'plan' (planning). "
            "Example: 'build'"
        ),
    },
}

BANANA_PROPERTIES = {
    "images": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Absolute path to the image file",
                },
                "role": {
                    "type": "string",
                    "enum": ["edit_base", "subject_ref", "style_ref", "layout_ref", "background_ref", "object_ref"],
                    "description": "Role of the reference image",
                },
                "label": {
                    "type": "string",
                    "description": "Optional label for the image",
                },
            },
            "required": ["source"],
        },
        "default": [],
        "description": (
            "Reference images for editing or style transfer. "
            "Roles: edit_base (image to edit), subject_ref (person/character), "
            "style_ref (style reference), layout_ref (layout), background_ref, object_ref."
        ),
    },
    "aspect_ratio": {
        "type": "string",
        "enum": ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"],
        "default": "1:1",
        "description": "Output image aspect ratio. Default: 1:1 (square).",
    },
    "resolution": {
        "type": "string",
        "enum": ["1K", "2K", "4K"],
        "default": "4K",
        "description": "Output resolution. 1K (1024px), 2K (2048px), 4K (4096px). Default: 4K.",
    },
    "use_search": {
        "type": "boolean",
        "default": False,
        "description": "Enable search grounding for factual content. Adds text to response.",
    },
    "include_thoughts": {
        "type": "boolean",
        "default": False,
        "description": "Include model's thinking process in response.",
    },
    "temperature": {
        "type": "number",
        "default": 1.0,
        "minimum": 0.0,
        "maximum": 2.0,
        "description": "Controls randomness (0.0-2.0). Higher = more creative. Default: 1.0.",
    },
    "top_p": {
        "type": "number",
        "default": 0.95,
        "minimum": 0.0,
        "maximum": 1.0,
        "description": "Nucleus sampling threshold (0.0-1.0). Default: 0.95.",
    },
    "top_k": {
        "type": "integer",
        "default": 40,
        "minimum": 1,
        "maximum": 100,
        "description": "Top-k sampling (1-100). Default: 40.",
    },
    "num_images": {
        "type": "integer",
        "default": 1,
        "minimum": 1,
        "maximum": 4,
        "description": "Number of images to generate (1-4). Default: 1.",
    },
    "save_path": {
        "type": "string",
        "description": "Base directory for saving images. Files saved to {save_path}/{task_note}/.",
    },
}

IMAGE_PROPERTIES = {
    "images": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Absolute path to the image file",
                },
            },
            "required": ["source"],
        },
        "default": [],
        "description": "Reference images for editing or style transfer.",
    },
    "model": {
        "type": "string",
        "default": "",
        "description": "Model to use (default: from IMAGE_MODEL env).",
    },
    "aspect_ratio": {
        "type": "string",
        "enum": ["1:1", "16:9", "9:16", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "21:9"],
        "default": "1:1",
        "description": "Output image aspect ratio. Default: 1:1 (square).",
    },
    "resolution": {
        "type": "string",
        "enum": ["1K", "2K", "4K"],
        "default": "1K",
        "description": "Output resolution. 1K (1024px), 2K (2048px), 4K (4096px). Default: 1K.",
    },
    "quality": {
        "type": "string",
        "default": "standard",
        "description": "Image quality (OpenAI generations API). Options: standard, hd.",
    },
    "save_path": {
        "type": "string",
        "description": "Base directory for saving images. Files saved to {save_path}/{task_note}/.",
    },
    "api_type": {
        "type": "string",
        "enum": ["openrouter_chat", "openai_images", "openai_responses"],
        "default": "openrouter_chat",
        "description": "API type to use. Default: from IMAGE_API_TYPE env var (openrouter_chat).",
    },
}

# 末尾参数（所有工具共用）
TAIL_PROPERTIES = {
    "task_note": {
        "type": "string",
        "default": "",
        "description": (
            "REQUIRED user-facing label. "
            "Summarize action in < 60 chars (e.g., '[Fix] Auth logic' or '[Read] config.py'). "
            "Shown in GUI progress bar to inform user."
        ),
    },
    "debug": {
        "type": "boolean",
        "description": "Enable execution stats (tokens, duration) for this call.",
    },
}

# Parallel 专用参数
PARALLEL_PROPERTIES = {
    "parallel_prompts": {
        "type": "array",
        "minItems": 1,
        "maxItems": 20,
        "description": "Complete prompts for parallel execution. Each spawns an independent subprocess.",
        "items": {"type": "string", "minLength": 1},
    },
    "parallel_task_notes": {
        "type": "array",
        "minItems": 1,
        "maxItems": 20,
        "description": "Labels for each task. Length MUST equal parallel_prompts.",
        "items": {"type": "string", "minLength": 1, "maxLength": 120},
    },
    "parallel_max_concurrency": {
        "type": "integer",
        "default": 4,
        "minimum": 1,
        "maximum": 16,
        "description": "Max concurrent subprocesses.",
    },
    "parallel_fail_fast": {
        "type": "boolean",
        "default": False,
        "description": "Stop spawning new tasks when any fails (already running tasks continue).",
    },
}

# 支持 parallel 的 CLI 工具
PARALLEL_SUPPORTED_TOOLS = ["codex", "gemini", "claude", "opencode"]


def normalize_tool_name(name: str) -> tuple[str, bool]:
    """返回 (base_name, is_parallel)"""
    if name.endswith("_parallel"):
        return name.removesuffix("_parallel"), True
    return name, False


def create_tool_schema(cli_type: str, is_parallel: bool = False) -> dict[str, Any]:
    """创建工具的 JSON Schema。

    参数顺序：
    1. prompt, workspace (必填) - parallel 模式下 prompt 被忽略
    2. continuation_id, permission, model, save_file, verbose_output (常用)
    3. 特有参数 (image / system_prompt / append_system_prompt / file / agent / images)
    4. parallel 参数 (仅 parallel 模式)
    5. task_note, debug (末尾)
    """
    # Banana 工具使用简化的 schema（不支持 parallel）
    if cli_type == "banana":
        properties: dict[str, Any] = {
            "prompt": {
                "type": "string",
                "description": (
                    "Image generation prompt. Structure: "
                    "<goal>what you want to generate (can be a statement)</goal> "
                    "<context>detailed background info - the more the better</context> "
                    "<hope>desired visual outcome, can be abstract</hope>. "
                    "Example: <goal>Generate 6 weather icons for a mobile app</goal> "
                    "<context>Target users are young professionals, app has a friendly casual vibe, needs to match existing UI with rounded corners</context> "
                    "<hope>pastel colors, consistent 3px stroke, 64x64 base size</hope>"
                ),
            },
        }
        properties.update(BANANA_PROPERTIES)
        properties["task_note"] = {
            "type": "string",
            "description": "Subdirectory name for saving images (English recommended, e.g., 'hero-banner', 'product-shot'). Also shown in GUI.",
        }
        return {
            "type": "object",
            "properties": properties,
            "required": ["prompt", "save_path", "task_note"],
        }

    # Image 工具使用简化的 schema（不支持 parallel）
    if cli_type == "image":
        properties: dict[str, Any] = {
            "prompt": {
                "type": "string",
                "description": (
                    "Image generation prompt. Structure: "
                    "<goal>what you want to generate (can be a statement)</goal> "
                    "<context>detailed background info - the more the better</context> "
                    "<hope>desired visual outcome, can be abstract</hope>. "
                    "Example: <goal>Create a 4-panel comic about debugging</goal> "
                    "<context>Developer finds a bug at 3am, tries multiple fixes, finally discovers it was a typo, comedic relief for tech blog</context> "
                    "<hope>simple black-white line art, speech bubbles, exaggerated tired expressions</hope>"
                ),
            },
        }
        properties.update(IMAGE_PROPERTIES)
        properties["task_note"] = {
            "type": "string",
            "description": "Subdirectory name for saving images (English recommended, e.g., 'hero-banner', 'product-shot'). Also shown in GUI.",
        }
        return {
            "type": "object",
            "properties": properties,
            "required": ["prompt", "save_path", "task_note"],
        }

    # 按顺序构建 properties
    properties = {}

    # 1. 公共参数（必填 + 常用）
    # parallel 模式下排除 prompt, continuation_id, save_file_with_append_mode, save_file_with_wrapper
    if is_parallel:
        for key, value in COMMON_PROPERTIES.items():
            if key in ("prompt", "continuation_id", "save_file_with_append_mode", "save_file_with_wrapper"):
                continue
            properties[key] = value
    else:
        properties.update(COMMON_PROPERTIES)

    # 2. 特有参数
    if cli_type == "codex":
        properties.update(CODEX_PROPERTIES)
    elif cli_type == "claude":
        properties.update(CLAUDE_PROPERTIES)
    elif cli_type == "opencode":
        properties.update(OPENCODE_PROPERTIES)

    # 3. Parallel 参数（仅 parallel 模式）
    if is_parallel:
        properties.update(PARALLEL_PROPERTIES)

    # 4. 末尾参数（parallel 模式下排除 task_note）
    if is_parallel:
        properties["debug"] = TAIL_PROPERTIES["debug"]
    else:
        properties.update(TAIL_PROPERTIES)

    # 构建 required 字段
    if is_parallel:
        required = ["workspace", "save_file", "parallel_prompts", "parallel_task_notes"]
    else:
        required = ["prompt", "workspace"]

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


def create_server(
    gui_manager: GUIManager | None = None,
    registry: RequestRegistry | None = None,
) -> Server:
    """创建 MCP Server 实例。

    Args:
        gui_manager: GUI 管理器（可选）
        registry: 请求注册表（可选，用于信号隔离）
    """
    config = get_config()
    server = Server("cli-agent-mcp")

    def push_to_gui(event_dict: dict[str, Any]) -> None:
        """推送事件到 GUI。"""
        if gui_manager and gui_manager.is_running:
            gui_manager.push_event(event_dict)

    def push_user_prompt(cli_type: str, prompt: str, task_note: str = "") -> None:
        """推送用户 prompt 到 GUI。"""
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

    def push_system_info(cli_type: str, message: str) -> None:
        """推送系统信息到 GUI。"""
        push_to_gui({
            "category": "system",
            "source": cli_type,
            "message": message,
            "severity": "info",
            "content_type": "text",
            "timestamp": time.time(),
            "raw": {"type": "system", "subtype": "info", "message": message},
        })

    # 创建调用器（带 GUI 回调）
    def make_event_callback(cli_type: str, task_note: str = ""):
        def callback(event):
            if gui_manager and gui_manager.is_running:
                # 转换 UnifiedEvent 为字典
                event_dict = event.model_dump() if hasattr(event, "model_dump") else dict(event.__dict__)
                event_dict["source"] = cli_type
                # 注入 task_note 到 metadata
                if task_note:
                    metadata = event_dict.get("metadata", {}) or {}
                    metadata["task_note"] = task_note
                    event_dict["metadata"] = metadata
                gui_manager.push_event(event_dict)
        return callback

    # 重构说明：移除了 invoker 单例缓存
    # 原有代码（已删除）：
    #   invokers = {
    #       "codex": CodexInvoker(...),
    #       "gemini": GeminiInvoker(...),
    #       "claude": ClaudeInvoker(...),
    #   }
    #
    # 新实现：每次请求创建新的 invoker，确保请求间状态完全隔离
    # 虽然 CLIInvoker 内部已实现 ExecutionContext per-request 隔离，
    # 但每次请求创建新 invoker 可以进一步确保隔离的明确性。
    def create_invoker_for_request(cli_type: str, task_note: str = ""):
        """为当前请求创建新的 invoker 实例（per-request 隔离）。"""
        event_callback = make_event_callback(cli_type, task_note) if gui_manager else None
        return create_invoker(cli_type, event_callback=event_callback)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """列出可用工具。"""
        tools = []
        for cli_type in ["codex", "gemini", "claude", "opencode", "banana", "image"]:
            if config.is_tool_allowed(cli_type):
                tools.append(
                    Tool(
                        name=cli_type,
                        description=TOOL_DESCRIPTIONS[cli_type],
                        inputSchema=create_tool_schema(cli_type),
                    )
                )
                # 追加 *_parallel 工具（仅支持的 CLI 工具）
                if cli_type in PARALLEL_SUPPORTED_TOOLS:
                    parallel_name = f"{cli_type}_parallel"
                    parallel_desc = (
                        f"Run multiple {cli_type} tasks in parallel. "
                        f"All tasks share workspace/permission/save_file. "
                        f"Results are appended to save_file with XML wrappers "
                        f"(<agent-output agent=... continuation_id=... task_note=... task_index=... status=...>)."
                    )
                    tools.append(
                        Tool(
                            name=parallel_name,
                            description=parallel_desc,
                            inputSchema=create_tool_schema(cli_type, is_parallel=True),
                        )
                    )
        # 添加 get_gui_url 工具
        if gui_manager:
            tools.append(
                Tool(
                    name="get_gui_url",
                    description="Get the GUI dashboard URL. Returns the HTTP URL where the live event viewer is accessible.",
                    inputSchema={"type": "object", "properties": {}, "required": []},
                )
            )
        # DEBUG: 记录工具列表请求（通常是客户端初始化后的第一个调用）
        logger.debug(
            f"[MCP] list_tools called, returning {len(tools)} tools: "
            f"{[t.name for t in tools]}"
        )
        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        """调用工具。"""
        # DEBUG: 记录完整的请求信息
        logger.debug(
            f"[MCP] call_tool request:\n"
            f"  Tool: {name}\n"
            f"  Arguments: {json.dumps({k: v[:100] + '...' if isinstance(v, str) and len(v) > 100 else v for k, v in arguments.items()}, ensure_ascii=False, default=str)}"
        )
        logger.debug(f"call_tool: name={name}, registry={registry is not None}")

        # 处理 get_gui_url 工具
        if name == "get_gui_url":
            if gui_manager and gui_manager.url:
                return [TextContent(type="text", text=gui_manager.url)]
            return [TextContent(type="text", text="GUI not available or URL not ready")]

        # 解析工具名称（支持 *_parallel 后缀）
        base_name, is_parallel = normalize_tool_name(name)

        # 检查工具是否启用（使用 base_name）
        if not config.is_tool_allowed(base_name):
            return _format_error_response(f"Tool '{name}' is not enabled")

        # 验证工具名称
        if base_name not in SUPPORTED_TOOLS:
            return _format_error_response(f"Unknown tool '{name}'")

        # parallel 模式只支持特定工具
        if is_parallel and base_name not in PARALLEL_SUPPORTED_TOOLS:
            return _format_error_response(f"Tool '{base_name}' does not support parallel mode")

        # 校验 banana/image 必填参数（在登记前校验，避免无效请求占用 registry）
        if base_name == "banana":
            if not arguments.get("prompt"):
                return _format_error_response("Missing required argument: 'prompt'")
            if not arguments.get("save_path"):
                return _format_error_response("Missing required argument: 'save_path'")
            if not arguments.get("task_note"):
                return _format_error_response("Missing required argument: 'task_note'")

        if base_name == "image":
            if not arguments.get("prompt"):
                return _format_error_response("Missing required argument: 'prompt'")
            if not arguments.get("save_path"):
                return _format_error_response("Missing required argument: 'save_path'")
            if not arguments.get("task_note"):
                return _format_error_response("Missing required argument: 'task_note'")

        # 生成请求 ID 并登记（如果 registry 可用）- 统一覆盖所有工具
        task_note = arguments.get("task_note", "") or (
            " + ".join(arguments.get("parallel_task_notes", [])) if is_parallel else ""
        )
        request_id = None
        if registry is not None:
            request_id = registry.generate_request_id()
            current_task = asyncio.current_task()
            logger.debug(f"Registering: request_id={request_id[:8]}..., current_task={current_task is not None}")
            if current_task:
                registry.register(request_id, name, current_task, task_note)
                logger.debug(f"Registered request: {request_id[:8]}... ({name})")
            else:
                logger.warning(f"No current_task, cannot register request")
        else:
            logger.debug(f"No registry available")

        try:
            # Banana 工具使用独立的处理流程
            if base_name == "banana":
                return await _handle_banana_tool(arguments, push_user_prompt, push_to_gui, gui_manager, config)

            # Image 工具使用独立的处理流程
            if base_name == "image":
                return await _handle_image_tool(arguments, push_user_prompt, push_to_gui, gui_manager, config)

            # Parallel 模式使用独立的处理流程
            if is_parallel:
                return await _handle_parallel_call(
                    base_name, arguments, make_event_callback, push_user_prompt, push_to_gui, gui_manager, config
                )

            # 校验 CLI 工具必填参数
            prompt = arguments.get("prompt")
            workspace = arguments.get("workspace")
            if not prompt or not str(prompt).strip():
                return _format_error_response("Missing required argument: 'prompt'")
            if not workspace:
                return _format_error_response("Missing required argument: 'workspace'")

            # 核心变更：每次请求创建新的 invoker（per-request 隔离）
            invoker = create_invoker_for_request(base_name, task_note)
            prompt = arguments.get("prompt", "")

            # 立即推送用户 prompt 到 GUI
            push_user_prompt(name, prompt, task_note)
            # 使用 helper 注入 report_mode 和 context_paths
            report_mode = arguments.get("report_mode", False)
            context_paths = arguments.get("context_paths", [])
            injected_prompt = _inject_context_and_report_mode(
                arguments["prompt"], context_paths, report_mode
            )
            arguments = {**arguments, "prompt": injected_prompt}

            # 构建参数
            params = _build_params(name, arguments)

            # 执行（取消异常会直接传播，不会返回）
            result = await invoker.execute(params)

            # 获取参数
            verbose_output = arguments.get("verbose_output", False)
            debug_enabled = _resolve_debug(arguments, config)
            save_file_path = arguments.get("save_file", "")

            # 构建 debug_info（当 debug 开启时始终构建，包含 log_file）
            debug_info = None
            if debug_enabled:
                debug_info = FormatterDebugInfo(
                    model=result.debug_info.model if result.debug_info else None,
                    duration_sec=result.debug_info.duration_sec if result.debug_info else 0.0,
                    message_count=result.debug_info.message_count if result.debug_info else 0,
                    tool_call_count=result.debug_info.tool_call_count if result.debug_info else 0,
                    input_tokens=result.debug_info.input_tokens if result.debug_info else None,
                    output_tokens=result.debug_info.output_tokens if result.debug_info else None,
                    cancelled=result.cancelled,
                    log_file=config.log_file if config.log_debug else None,
                )

            # 构建 ResponseData（直接使用 invoker 提取的统一数据）
            # 错误时也尽力返回已收集的内容和 session_id，方便客户端发送"继续"
            response_data = ResponseData(
                answer=result.agent_messages,  # 即使失败也返回已收集的内容
                session_id=result.session_id or "",
                thought_steps=result.thought_steps if (verbose_output or not result.success) else [],
                debug_info=debug_info,
                success=result.success,
                error=result.error,
            )

            # 格式化响应
            formatter = get_formatter()
            response = formatter.format(
                response_data,
                verbose_output=verbose_output,
                debug=debug_enabled,
            )

            # DEBUG: 记录响应摘要
            logger.debug(
                f"[MCP] call_tool response:\n"
                f"  Tool: {name}\n"
                f"  Success: {result.success}\n"
                f"  Response length: {len(response)} chars\n"
                f"  Duration: {result.debug_info.duration_sec:.3f}s" if result.debug_info else ""
            )

            # 保存到文件（如果指定）
            # NOTE: save_file 是权限限制的例外，它仅用于落盘分析记录结果，
            # 而非通用的文件写入能力。CLI agent 的实际文件操作仍受 permission 参数控制。
            # 这是一个便捷功能，让编排器无需单独写文件来保存分析结果。
            if save_file_path and result.success:
                try:
                    file_content = formatter.format_for_file(
                        response_data,
                        verbose_output=verbose_output,
                    )

                    # 添加 XML wrapper（如果启用）
                    if arguments.get("save_file_with_wrapper", False):
                        continuation_id = result.session_id or ""
                        file_content = (
                            f'<agent-output agent="{name}" continuation_id="{continuation_id}">\n'
                            f'{file_content}\n'
                            f'</agent-output>\n'
                        )

                    # 追加或覆盖
                    file_path = Path(save_file_path)
                    if arguments.get("save_file_with_append_mode", False) and file_path.exists():
                        with file_path.open("a", encoding="utf-8") as f:
                            f.write("\n" + file_content)
                        logger.info(f"Appended output to: {save_file_path}")
                    else:
                        file_path.write_text(file_content, encoding="utf-8")
                        logger.info(f"Saved output to: {save_file_path}")
                except Exception as e:
                    logger.warning(f"Failed to save output to {save_file_path}: {e}")

            return [TextContent(type="text", text=response)]

        except anyio.get_cancelled_exc_class() as e:
            # 取消通知已由 invoker._send_cancel_event() 推送到 GUI
            # 直接 re-raise 让 MCP 框架处理
            logger.info(f"Tool '{name}' cancelled (type={type(e).__name__})")
            raise

        except asyncio.CancelledError as e:
            # 捕获 asyncio.CancelledError（可能与 anyio 不同）
            logger.info(f"Tool '{name}' cancelled via asyncio.CancelledError")
            raise

        except BaseException as e:
            # 捕获所有异常，包括 SystemExit, KeyboardInterrupt
            logger.error(
                f"Tool '{name}' BaseException: type={type(e).__name__}, "
                f"msg={e}, mro={type(e).__mro__}"
            )
            if isinstance(e, Exception):
                return _format_error_response(str(e))
            raise

        finally:
            # 注销请求
            logger.debug(f"Tool '{name}' finally block, request_id={request_id}")
            if registry and request_id:
                registry.unregister(request_id)
                logger.debug(f"Unregistered request: {request_id[:8]}...")

    return server


async def _handle_banana_tool(
    arguments: dict[str, Any],
    push_user_prompt: Any,
    push_to_gui: Any,
    gui_manager: Any,
    config: Any,
) -> list[TextContent]:
    """处理 banana 工具调用。

    Args:
        arguments: 工具参数
        push_user_prompt: 推送用户 prompt 的函数
        push_to_gui: 推送事件到 GUI 的函数
        gui_manager: GUI 管理器
        config: 配置对象

    Returns:
        TextContent 列表
    """
    prompt = arguments.get("prompt", "")
    task_note = arguments.get("task_note", "")

    # 推送用户 prompt 到 GUI
    push_user_prompt("banana", prompt, task_note)

    # 创建事件回调
    def event_callback(event):
        if gui_manager and gui_manager.is_running:
            event_dict = event.model_dump() if hasattr(event, "model_dump") else dict(event.__dict__)
            event_dict["source"] = "banana"
            gui_manager.push_event(event_dict)

    # 创建 invoker 并执行
    invoker = BananaInvoker(event_callback=event_callback)

    params = BananaParams(
        prompt=prompt,
        images=arguments.get("images", []),
        aspect_ratio=arguments.get("aspect_ratio", "1:1"),
        resolution=arguments.get("resolution", "4K"),
        use_search=arguments.get("use_search", False),
        include_thoughts=arguments.get("include_thoughts", False),
        temperature=arguments.get("temperature", 1.0),
        top_p=arguments.get("top_p", 0.95),
        top_k=arguments.get("top_k", 40),
        num_images=arguments.get("num_images", 1),
        save_path=arguments.get("save_path", ""),
        task_note=task_note,
    )

    try:
        result = await invoker.execute(params)

        if result.success:
            # 返回 XML 响应
            response = result.response_xml

            # 添加 debug_info（仅当 debug 开启时）
            debug_enabled = _resolve_debug(arguments, config)
            if debug_enabled and result.artifacts:
                response += (
                    f"\n<debug_info>"
                    f"\n  <image_count>{len(result.artifacts)}</image_count>"
                    f"\n  <duration_sec>{result.duration_sec:.3f}</duration_sec>"
                    f"\n  <model>{result.model}</model>"
                    f"\n  <api_endpoint>{result.api_endpoint}</api_endpoint>"
                    f"\n  <auth_token>{result.auth_token_masked}</auth_token>"
                    f"\n</debug_info>"
                )

            # 推送结果到 GUI
            gui_metadata: dict[str, Any] = {
                "artifacts": result.artifacts,
                "task_note": task_note,
            }
            if debug_enabled:
                gui_metadata["debug"] = {
                    "image_count": len(result.artifacts),
                    "duration_sec": result.duration_sec,
                    "model": result.model,
                    "api_endpoint": result.api_endpoint,
                    "auth_token": result.auth_token_masked,
                }
            push_to_gui({
                "category": "operation",
                "operation_type": "tool_call",
                "source": "banana",
                "session_id": f"banana_{result.request_id}",
                "name": "banana",
                "status": "success",
                "output": response,
                "metadata": gui_metadata,
            })

            return [TextContent(type="text", text=response)]
        else:
            return _format_error_response(result.error or "Unknown error")

    except asyncio.CancelledError:
        # 取消错误必须 re-raise，不能被吞掉
        raise

    except Exception as e:
        logger.exception(f"Banana tool error: {e}")
        return _format_error_response(str(e))


async def _handle_image_tool(
    arguments: dict[str, Any],
    push_user_prompt: Any,
    push_to_gui: Any,
    gui_manager: Any,
    config: Any,
) -> list[TextContent]:
    """处理 image 工具调用。

    Args:
        arguments: 工具参数
        push_user_prompt: 推送用户 prompt 的函数
        push_to_gui: 推送事件到 GUI 的函数
        gui_manager: GUI 管理器
        config: 配置对象

    Returns:
        TextContent 列表
    """
    prompt = arguments.get("prompt", "")
    task_note = arguments.get("task_note", "")

    # 推送用户 prompt 到 GUI
    push_user_prompt("image", prompt, task_note)

    # 创建事件回调
    def event_callback(event):
        if gui_manager and gui_manager.is_running:
            event_dict = event.model_dump() if hasattr(event, "model_dump") else dict(event.__dict__)
            event_dict["source"] = "image"
            gui_manager.push_event(event_dict)

    # 创建 invoker 并执行
    invoker = ImageInvoker(event_callback=event_callback)

    params = ImageParams(
        prompt=prompt,
        model=arguments.get("model", ""),
        images=arguments.get("images", []),
        save_path=arguments.get("save_path", ""),
        task_note=task_note,
        aspect_ratio=arguments.get("aspect_ratio", "1:1"),
        resolution=arguments.get("resolution", "1K"),
        quality=arguments.get("quality", "standard"),
        api_type=arguments.get("api_type", ""),
    )

    try:
        result = await invoker.execute(params)

        if result.success:
            # 返回 XML 响应
            response = result.response_xml

            # 添加 debug_info（仅当 debug 开启时）
            debug_enabled = _resolve_debug(arguments, config)
            if debug_enabled:
                response += (
                    f"\n<debug_info>"
                    f"\n  <image_count>{len(result.artifacts) if result.artifacts else 0}</image_count>"
                    f"\n  <duration_sec>{result.duration_sec:.3f}</duration_sec>"
                    f"\n  <model>{params.model or 'env:IMAGE_MODEL'}</model>"
                    f"\n  <api_type>{params.api_type or 'env:IMAGE_API_TYPE'}</api_type>"
                    f"\n</debug_info>"
                )

            # 推送结果到 GUI
            gui_metadata: dict[str, Any] = {
                "artifacts": result.artifacts,
                "task_note": task_note,
            }
            if debug_enabled:
                gui_metadata["debug"] = {
                    "image_count": len(result.artifacts) if result.artifacts else 0,
                    "duration_sec": result.duration_sec,
                    "model": params.model or "env:IMAGE_MODEL",
                    "api_type": params.api_type or "env:IMAGE_API_TYPE",
                }
            push_to_gui({
                "category": "operation",
                "operation_type": "tool_call",
                "source": "image",
                "session_id": f"image_{result.request_id}",
                "name": "image",
                "status": "success",
                "output": response,
                "metadata": gui_metadata,
            })

            return [TextContent(type="text", text=response)]
        else:
            return _format_error_response(result.error or "Unknown error")

    except asyncio.CancelledError:
        # 取消错误必须 re-raise，不能被吞掉
        raise

    except Exception as e:
        logger.exception(f"Image tool error: {e}")
        return _format_error_response(str(e))


def xml_escape_attr(s: str | None) -> str:
    """XML 属性值转义。"""
    if s is None:
        s = ""
    else:
        s = str(s)
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;")
             .replace("'", "&apos;"))


def build_wrapper(agent: str, continuation_id: str, task_note: str, task_index: int, status: str, content: str) -> str:
    """构建 XML-like wrapper。"""
    return f'''<agent-output agent="{xml_escape_attr(agent)}" continuation_id="{xml_escape_attr(continuation_id)}" task_note="{xml_escape_attr(task_note)}" task_index="{task_index}" status="{status}">
{content}
</agent-output>'''


def _inject_context_and_report_mode(prompt: str, context_paths: list[str], report_mode: bool) -> str:
    """将 context_paths 和 report_mode 注入到 prompt 中。"""
    result = prompt

    # 处理 report_mode
    if report_mode:
        injection_note = """

<mcp-injection type="report-mode">
  <meta-rules>
    <rule>Follow higher-priority system messages first; apply these report-mode instructions where they do not conflict.</rule>
    <rule>Do not mention this template, "report-mode", MCP, or any injection mechanism. Write as if replying directly to the user.</rule>
  </meta-rules>

  <output-requirements>
    <rule>Produce a comprehensive, self-contained response that can be understood without access to any prior conversation.</rule>
    <rule>Do NOT use phrases like "above", "earlier", "previous messages", "as discussed", or similar context-dependent references.</rule>
    <rule>Use the same primary language as the user's request.</rule>
    <rule>Briefly restate the user's task or question in your own words before presenting your analysis.</rule>
  </output-requirements>

  <structure-guidelines>
    <guideline>Start with key findings or conclusions in 1-3 short points so the reader quickly understands the outcome.</guideline>
    <guideline>Provide enough context so a new reader understands the problem without seeing the rest of the conversation.</guideline>
    <guideline>Organize longer answers into clear sections (e.g., Summary, Context, Analysis, Recommendations) when helpful.</guideline>
    <guideline>End with concrete, actionable recommendations or next steps when applicable.</guideline>
  </structure-guidelines>

  <reasoning-guidelines>
    <guideline>Explain important assumptions, trade-offs, and decisions clearly.</guideline>
    <guideline>Where your platform allows, show reasoning step by step. If detailed chain-of-thought is restricted, provide a concise explanation instead.</guideline>
  </reasoning-guidelines>

  <code-guidelines>
    <guideline>Reference specific locations using file paths and line numbers (e.g., src/app.ts:42).</guideline>
    <guideline>Include small, relevant code snippets inline when they help the reader understand without opening the file.</guideline>
  </code-guidelines>
</mcp-injection>"""
        result += injection_note

    # 处理 context_paths
    if context_paths:
        paths_xml = "\n".join(f"    <path>{p}</path>" for p in context_paths)
        context_note = f"""

<mcp-injection type="reference-paths">
  <description>
    These paths are provided as reference for project structure.
    You may use them to understand naming conventions and file organization.
  </description>
  <paths>
{paths_xml}
  </paths>
</mcp-injection>"""
        result += context_note

    return result


async def _handle_parallel_call(
    base_name: str,
    arguments: dict[str, Any],
    make_event_callback: Any,
    push_user_prompt: Any,
    push_to_gui: Any,
    gui_manager: Any,
    config: Any,
) -> list[TextContent]:
    """处理 parallel 模式的工具调用。

    Args:
        base_name: 基础工具名称（如 codex, gemini, claude, opencode）
        arguments: 工具参数
        make_event_callback: 创建事件回调的函数
        push_user_prompt: 推送用户 prompt 的函数
        push_to_gui: 推送事件到 GUI 的函数
        gui_manager: GUI 管理器
        config: 配置对象

    Returns:
        TextContent 列表
    """
    # 1) 校验
    prompts = arguments.get("parallel_prompts", [])
    task_notes = arguments.get("parallel_task_notes", [])

    # 类型校验
    if not isinstance(prompts, list):
        return _format_error_response("parallel_prompts must be a list")
    if not isinstance(task_notes, list):
        return _format_error_response("parallel_task_notes must be a list")

    if not prompts:
        return _format_error_response("parallel_prompts is required")

    # 检查空白字符串和类型
    for i, p in enumerate(prompts):
        if not isinstance(p, str):
            return _format_error_response(f"parallel_prompts[{i}] must be a string")
        if not p or not p.strip():
            return _format_error_response(f"parallel_prompts[{i}] is empty or whitespace")

    for i, n in enumerate(task_notes):
        if not isinstance(n, str):
            return _format_error_response(f"parallel_task_notes[{i}] must be a string")
        if not n or not n.strip():
            return _format_error_response(f"parallel_task_notes[{i}] is empty or whitespace")

    if len(prompts) != len(task_notes):
        return _format_error_response("parallel_prompts and parallel_task_notes must have same length")

    if len(prompts) > 20:
        return _format_error_response("parallel_prompts exceeds maximum of 20")

    if arguments.get("continuation_id"):
        return _format_error_response("continuation_id input is not supported in parallel mode")

    save_file = arguments.get("save_file")
    if not save_file:
        return _format_error_response("save_file is required in parallel mode")

    # clamp concurrency (handle string/invalid types)
    try:
        max_conc = int(arguments.get("parallel_max_concurrency", 4))
    except (TypeError, ValueError):
        max_conc = 4
    max_conc = max(1, min(16, max_conc))
    fail_fast = arguments.get("parallel_fail_fast", False)

    # 推送用户 prompt 到 GUI（每个 prompt 单独推送）
    for prompt, note in zip(prompts, task_notes):
        push_user_prompt(f"{base_name}_parallel", prompt, note)

    # 2) 构建子任务
    sub_tasks = []
    context_paths = arguments.get("context_paths", [])
    report_mode = arguments.get("report_mode", False)

    for idx, (prompt, note) in enumerate(zip(prompts, task_notes), start=1):
        # 注入 context_paths 和 report_mode
        final_prompt = _inject_context_and_report_mode(prompt, context_paths, report_mode)
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
                # 创建 invoker（传入 task_note 用于 GUI 显示）
                task_note = sub_args.get("task_note", "")
                event_callback = make_event_callback(base_name, task_note) if gui_manager else None
                invoker = create_invoker(base_name, event_callback=event_callback)

                # 构建参数
                params = _build_params(base_name, sub_args)

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

        # 构建 wrapper 并追加到文件
        wrapped = build_wrapper(base_name, session_id, note, idx, status, content)
        all_wrapped.append(wrapped)
        try:
            file_path = Path(save_file)
            if file_path.exists():
                with file_path.open("a", encoding="utf-8") as f:
                    f.write("\n" + wrapped)  # 前置换行防止粘连
            else:
                file_path.write_text(wrapped, encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to write to {save_file}: {e}")
            return _format_error_response(f"Failed to write to {save_file}: {e}")

    # 5) 返回 wrapped 内容（与 save_file_with_wrapper 格式一致）
    summary = f"Parallel run: total={len(results)}, success={success_count}, failed={failed_count}, skipped={skipped_count}\n"
    summary += f"Saved to: {save_file}\n"
    summary += "\n".join(summary_lines)

    # 推送结果到 GUI
    push_to_gui({
        "category": "system",
        "source": f"{base_name}_parallel",
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
    debug_enabled = _resolve_debug(arguments, config)
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


def _build_params(cli_type: str, args: dict[str, Any]):
    """构建 CLI 参数对象。"""
    # 公共参数（continuation_id 映射到内部的 session_id）
    common = {
        "prompt": args["prompt"],
        "workspace": Path(args["workspace"]),
        "permission": Permission(args.get("permission", "read-only")),
        "session_id": args.get("continuation_id", ""),  # 外部 continuation_id → 内部 session_id
        "model": args.get("model", ""),
        "verbose_output": args.get("verbose_output", False),
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


async def run_server() -> None:
    """运行 MCP Server。

    启动 MCP 服务器，并集成信号管理器以支持：
    - SIGINT: 取消活动请求（而不是直接退出）
    - SIGTERM: 优雅退出

    使用并发任务架构：
    - server_task: 运行 MCP server
    - shutdown_watcher: 监听 shutdown 事件并取消 server_task
    """
    config = get_config()
    logger.info(f"Starting CLI Agent MCP Server: {config}")

    # 创建请求注册表和信号管理器
    registry = RequestRegistry()
    gui_manager = None
    signal_manager = None
    server_task: asyncio.Task | None = None
    shutdown_watcher: asyncio.Task | None = None

    # 启动 GUI（如果启用）
    if config.gui_enabled:
        # 创建日志通知推送函数（用于首次启动和重启时）
        def push_log_debug_notice():
            if gui_manager:
                # 推送 GUI URL
                if gui_manager.url:
                    logger.debug(f"GUI URL: {gui_manager.url}")
                    gui_manager.push_event({
                        "category": "system",
                        "source": "server",
                        "message": f"GUI URL: {gui_manager.url}",
                        "severity": "info",
                        "content_type": "text",
                        "timestamp": time.time(),
                        "raw": {"type": "system", "subtype": "gui_url", "url": gui_manager.url},
                    })
                # 推送日志路径
                if config.log_debug and config.log_file:
                    gui_manager.push_event({
                        "category": "system",
                        "source": "server",
                        "message": f"Debug log: {config.log_file}",
                        "severity": "info",
                        "content_type": "text",
                        "timestamp": time.time(),
                        "raw": {"type": "system", "subtype": "log_path", "path": config.log_file},
                    })

        gui_manager = GUIManager(
            GUIConfig(
                title="CLI Agent MCP",
                detail_mode=config.gui_detail,
                keep_on_exit=config.gui_keep,
                on_restart=push_log_debug_notice,  # GUI 启动/重启时自动调用
            )
        )
        if gui_manager.start():
            logger.info("GUI starting in background...")
            # 注意：日志通知由 on_restart 回调在 GUI 真正启动后自动发送
        else:
            logger.warning("Failed to start GUI, continuing without it")
            gui_manager = None

    # 创建关闭回调
    def on_shutdown():
        """信号管理器触发的关闭回调。"""
        logger.info("Shutdown callback triggered")
        if gui_manager:
            gui_manager.stop()
        # 关闭 stdin 以中断 stdio_server 的阻塞读取
        # 这是让进程能够正常退出的关键
        try:
            sys.stdin.close()
            logger.debug("stdin closed to unblock stdio_server")
        except Exception as e:
            logger.debug(f"Error closing stdin: {e}")

    # 创建信号管理器
    signal_manager = SignalManager(
        registry=registry,
        on_shutdown=on_shutdown,
    )

    # 创建并运行 server
    server = create_server(gui_manager, registry)

    # 定义 server 运行协程
    async def _run_server_impl():
        """运行 MCP server 的内部实现。"""
        async with stdio_server() as (read_stream, write_stream):
            logger.debug("stdio_server context entered, starting server.run()")
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
            logger.debug("server.run() completed normally")

    # 定义 shutdown 监听协程
    async def _watch_shutdown():
        """监听 shutdown 事件并取消 server task。"""
        await signal_manager.wait_for_shutdown()
        logger.info("Shutdown signal received, cancelling server task...")
        if server_task and not server_task.done():
            server_task.cancel()

    try:
        # 启动信号管理器
        await signal_manager.start()
        logger.info(
            f"Signal manager started (mode={signal_manager.sigint_mode.value}, "
            f"double_tap_window={signal_manager.double_tap_window}s)"
        )

        # 创建并发任务
        server_task = asyncio.create_task(_run_server_impl(), name="mcp-server")
        shutdown_watcher = asyncio.create_task(_watch_shutdown(), name="shutdown-watcher")

        # 等待 server 任务完成（正常退出或被取消）
        try:
            await server_task
        except asyncio.CancelledError:
            logger.info("Server task cancelled by shutdown signal")

    except asyncio.CancelledError:
        logger.info("run_server: asyncio.CancelledError caught")
        raise

    except BaseException as e:
        logger.error(
            f"run_server: BaseException caught: type={type(e).__name__}, "
            f"msg={e}"
        )
        raise

    finally:
        logger.info("run_server: entering finally block")

        # 清理 shutdown watcher
        if shutdown_watcher and not shutdown_watcher.done():
            shutdown_watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await shutdown_watcher

        # 停止信号管理器
        if signal_manager:
            await signal_manager.stop()

        # 停止 GUI
        if gui_manager:
            gui_manager.stop()

        logger.info("run_server: cleanup completed")

        # 检查是否需要强制退出（双击 SIGINT）
        if signal_manager and signal_manager.is_force_exit:
            logger.warning("Force exit requested, terminating with exit code 130")
            sys.exit(130)  # 128 + SIGINT(2) = 130


def main() -> None:
    """主入口点。"""
    import sys

    config = get_config()

    # 配置日志输出
    log_handlers: list[logging.Handler] = []

    if config.log_debug and config.log_file:
        # LOG_DEBUG 模式：输出到临时文件
        file_handler = logging.FileHandler(config.log_file, encoding="utf-8")

        # 自定义格式化器：尝试将对象 JSON 序列化
        class JsonSerializingFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                # 尝试序列化 args 中的对象
                if record.args:
                    import json
                    new_args = []
                    for arg in record.args:
                        try:
                            if hasattr(arg, "model_dump"):
                                # Pydantic 模型
                                new_args.append(json.dumps(arg.model_dump(), ensure_ascii=False))
                            elif hasattr(arg, "__dict__") and not isinstance(arg, (str, int, float, bool, type(None))):
                                # 普通对象
                                new_args.append(json.dumps(vars(arg), ensure_ascii=False, default=str))
                            elif isinstance(arg, dict):
                                new_args.append(json.dumps(arg, ensure_ascii=False, default=str))
                            else:
                                new_args.append(arg)
                        except Exception:
                            new_args.append(arg)
                    record.args = tuple(new_args)
                return super().format(record)

        file_handler.setFormatter(JsonSerializingFormatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
        log_handlers.append(file_handler)
        log_level = logging.DEBUG
    else:
        # 默认模式：输出到 stderr
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        log_handlers.append(stderr_handler)
        log_level = logging.INFO

    logging.basicConfig(
        level=log_level,
        handlers=log_handlers,
    )

    asyncio.run(run_server())


if __name__ == "__main__":
    main()
