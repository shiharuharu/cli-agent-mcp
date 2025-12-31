"""Tool Schema 定义。

包含工具描述、参数 schema 和 schema 创建函数。
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "SUPPORTED_TOOLS",
    "PARALLEL_SUPPORTED_TOOLS",
    "TOOL_DESCRIPTIONS",
    "normalize_tool_name",
    "create_tool_schema",
]

# 支持的工具列表（用于校验）
SUPPORTED_TOOLS = {"codex", "gemini", "claude", "opencode", "banana", "image"}

# 支持 parallel 的 CLI 工具
PARALLEL_SUPPORTED_TOOLS = ["codex", "gemini", "claude", "opencode"]

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
        "maxItems": 100,
        "description": "Complete prompts for parallel execution. Each spawns an independent subprocess.",
        "items": {"type": "string", "minLength": 1},
    },
    "parallel_task_notes": {
        "type": "array",
        "minItems": 1,
        "maxItems": 100,
        "description": "Labels for each task. Length MUST equal parallel_prompts.",
        "items": {"type": "string", "minLength": 1, "maxLength": 120},
    },
    "parallel_max_concurrency": {
        "type": "integer",
        "default": 20,
        "minimum": 1,
        "maximum": 100,
        "description": "Max concurrent subprocesses.",
    },
    "parallel_fail_fast": {
        "type": "boolean",
        "default": False,
        "description": "Stop spawning new tasks when any fails (already running tasks continue).",
    },
}


def normalize_tool_name(name: str) -> tuple[str, bool]:
    """返回 (base_name, is_parallel)"""
    if name.endswith("_parallel"):
        return name.removesuffix("_parallel"), True
    return name, False


def create_tool_schema(cli_type: str, is_parallel: bool = False) -> dict[str, Any]:
    """创建工具的 JSON Schema。

    参数顺序：
    1. prompt, workspace (必填) - parallel 模式下 prompt 被忽略
    2. continuation_id, permission, model, save_file (常用)
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
    # parallel 模式下排除 prompt, continuation_id, save_file_with_append_mode, save_file_with_wrapper, model
    if is_parallel:
        for key, value in COMMON_PROPERTIES.items():
            if key in ("prompt", "continuation_id", "save_file_with_append_mode", "save_file_with_wrapper", "model"):
                continue
            properties[key] = value
        # parallel 模式下 model 改为数组类型
        properties["model"] = {
            "type": "array",
            "items": {"type": "string"},
            "default": [],
            "description": (
                "Model override(s). If single element, all tasks use that model. "
                "If multiple elements, must match parallel_prompts length - each task uses corresponding model. "
                "Empty array uses CLI default."
            ),
        }
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
