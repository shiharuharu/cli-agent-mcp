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
    Permission,
    create_invoker,
)

__all__ = ["main", "create_server"]

logger = logging.getLogger(__name__)

# 工具描述
TOOL_DESCRIPTIONS = {
    "codex": """Invoke OpenAI Codex CLI agent for deep code analysis and critical review.

CAPABILITIES:
- Strongest deep analysis and reflection abilities
- Excellent at finding issues, edge cases, and potential bugs
- Good at critical code review and architectural assessment

LIMITATIONS:
- Tends to over-engineer solutions or over-simplify features
- May suggest unnecessary abstractions

BEST PRACTICES:
- Be explicit about scope: "Only fix X, don't refactor Y"
- Specify constraints: "Keep it simple, no new abstractions"
- Use for: Code review, bug hunting, security analysis

SUPPORTS: Image attachments for UI/screenshot analysis""",

    "gemini": """Invoke Google Gemini CLI agent for UI design and comprehensive analysis.

CAPABILITIES:
- Strongest UI design and image understanding abilities
- Excellent at rapid UI prototyping and visual tasks
- Great at inferring original requirements from code clues
- Best for full-text analysis and detective work

LIMITATIONS:
- Not good at summarization (outputs can be verbose)
- May need full_output=true for research tasks

BEST PRACTICES:
- Use for: UI mockups, image analysis, requirement discovery
- Enable full_output when doing research or analysis
- Good first choice for "understand this codebase" tasks""",

    "claude": """Invoke Anthropic Claude CLI agent for code implementation.

CAPABILITIES:
- Strongest code writing and implementation abilities
- Excellent at translating requirements into working code
- Good at following patterns and conventions

LIMITATIONS:
- May leave compatibility shims or legacy code paths
- Sometimes adds unnecessary backwards-compatibility

BEST PRACTICES:
- Be explicit about target: "Replace old implementation completely"
- Specify cleanup: "Remove deprecated code paths"
- Use for: Feature implementation, refactoring, code generation

SUPPORTS: Custom system prompts via system_prompt or append_system_prompt, agent selection via agent parameter""",

    "opencode": """Invoke OpenCode CLI agent for full-stack development.

CAPABILITIES:
- Excellent at rapid prototyping and development tasks
- Good at working with multiple frameworks and tools
- Supports multiple AI providers (Anthropic, OpenAI, Google, etc.)

LIMITATIONS:
- May need explicit model selection for best results
- Permission system differs from other CLI agents

BEST PRACTICES:
- Use for: Rapid prototyping, multi-framework projects
- Specify agent type for specialized tasks (e.g., --agent build)
- Use file attachments for context-heavy tasks

SUPPORTS: File attachments, multiple agents (build, plan, etc.)""",
}

# 公共参数 schema（按重要性排序）
COMMON_PROPERTIES = {
    # === 必填参数 ===
    "prompt": {
        "type": "string",
        "description": (
            "Task instruction for the agent. "
            "IMPORTANT: This agent has NO memory of previous calls - each call starts fresh. "
            "When starting a NEW conversation (no continuation_id), include ALL relevant context:\n"
            "- Background: What problem are you solving? What's the goal?\n"
            "- Specifics: File paths, function names, error messages, code snippets\n"
            "- Constraints: What to avoid, scope limits, patterns to follow\n"
            "- Prior findings: Relevant discoveries from your own analysis\n"
            "If the user's request references prior context (e.g., 'fix that bug', 'continue the work'), "
            "you must either provide continuation_id OR expand the reference into concrete details. "
            "Never pass vague references without context - the agent cannot resolve them.\n"
            "When CONTINUING a conversation (with continuation_id), you can be brief - "
            "the agent retains context from that session."
        ),
    },
    "workspace": {
        "type": "string",
        "description": (
            "Absolute path to the project directory. "
            "Use the path mentioned in conversation, or the current project root. "
            "Supports relative paths (resolved against server CWD). "
            "Example: '/Users/dev/my-project' or './src'"
        ),
    },
    # === 常用参数 ===
    "continuation_id": {
        "type": "string",
        "default": "",
        "description": (
            "Unique conversation ID for multi-turn conversations. "
            "When provided, the agent retains full context from that session, "
            "so your prompt can be brief (e.g., 'now fix the second issue'). "
            "When empty, this is a NEW conversation - make your prompt self-contained "
            "with all necessary context since the agent has no memory of prior calls. "
            "Get this ID from the <continuation_id> field in previous responses."
        ),
    },
    "permission": {
        "type": "string",
        "enum": ["read-only", "workspace-write", "unlimited"],
        "default": "read-only",
        "description": (
            "File system permission level:\n"
            "- 'read-only': Can only read files, safe for analysis tasks\n"
            "- 'workspace-write': Can modify files within workspace only (recommended for most tasks)\n"
            "- 'unlimited': (DANGER) Full system access, use only when explicitly needed"
        ),
    },
    "model": {
        "type": "string",
        "default": "",
        "description": "Model override. Only specify if user explicitly requests a specific model.",
    },
    "save_file": {
        "type": "string",
        "description": (
            "Save agent output to a file at the specified path. "
            "The file will contain the agent's response without debug info. "
            "This saves the orchestrator from having to write files separately. "
            "Example: '/path/to/output.md'\n\n"
            "NOTE: This is intentionally exempt from permission restrictions. "
            "It serves as a convenience for persisting analysis results, "
            "not as a general file-write capability. The CLI agent's actual "
            "file operations are still governed by the 'permission' parameter."
        ),
    },
    "save_file_with_wrapper": {
        "type": "boolean",
        "default": False,
        "description": (
            "When true AND save_file is set, wrap output with <agent-output> XML tags "
            "containing metadata (agent name, continuation_id). "
            "Useful for later parsing or multi-agent document assembly."
        ),
    },
    "save_file_with_append_mode": {
        "type": "boolean",
        "default": False,
        "description": (
            "When true AND save_file is set, append to the file instead of overwriting. "
            "Useful for multi-agent collaboration where each agent adds to the same document. "
            "Example workflow: Codex analyzes → Gemini adds ideas → Claude summarizes, all to one file."
        ),
    },
    "full_output": {
        "type": "boolean",
        "default": False,
        "description": (
            "Return detailed output including reasoning and tool calls. "
            "Recommended for Gemini research/analysis tasks. "
            "Default: false (concise output)"
        ),
    },
    "report_mode": {
        "type": "boolean",
        "default": False,
        "description": (
            "Enable report mode for comprehensive, standalone output. "
            "Injects formatting guidance asking the model to produce detailed, "
            "self-contained analysis that can be understood without conversation context. "
            "Useful for generating analysis reports, documentation, or shareable summaries."
        ),
    },
    "context_paths": {
        "type": "array",
        "items": {"type": "string"},
        "default": [],
        "description": (
            "List of relevant file or directory paths to provide context. "
            "Use when you want to hint which files the agent should focus on. "
            "Paths are injected into the prompt as reference information. "
            "Example: ['/src/api/handlers.py', '/config/']"
        ),
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

# 末尾参数（所有工具共用）
TAIL_PROPERTIES = {
    "task_note": {
        "type": "string",
        "default": "",
        "description": "Display label for GUI, e.g., '[Review] PR #123'",
    },
    "debug": {
        "type": "boolean",
        "description": (
            "Override global debug setting for this call. "
            "When true, response includes execution stats (model, duration, tokens). "
            "When omitted, uses global CAM_DEBUG setting."
        ),
    },
}


def create_tool_schema(cli_type: str) -> dict[str, Any]:
    """创建工具的 JSON Schema。

    参数顺序：
    1. prompt, workspace (必填)
    2. continuation_id, permission, model, save_file, full_output (常用)
    3. 特有参数 (image / system_prompt / append_system_prompt / file / agent)
    4. task_note, debug (末尾)
    """
    # 按顺序构建 properties
    properties: dict[str, Any] = {}

    # 1. 公共参数（必填 + 常用）
    properties.update(COMMON_PROPERTIES)

    # 2. 特有参数
    if cli_type == "codex":
        properties.update(CODEX_PROPERTIES)
    elif cli_type == "claude":
        properties.update(CLAUDE_PROPERTIES)
    elif cli_type == "opencode":
        properties.update(OPENCODE_PROPERTIES)

    # 3. 末尾参数
    properties.update(TAIL_PROPERTIES)

    return {
        "type": "object",
        "properties": properties,
        "required": ["prompt", "workspace"],
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
    def make_event_callback(cli_type: str):
        def callback(event):
            if gui_manager and gui_manager.is_running:
                # 转换 UnifiedEvent 为字典
                event_dict = event.model_dump() if hasattr(event, "model_dump") else dict(event.__dict__)
                event_dict["source"] = cli_type
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
    def create_invoker_for_request(cli_type: str):
        """为当前请求创建新的 invoker 实例（per-request 隔离）。"""
        event_callback = make_event_callback(cli_type) if gui_manager else None
        return create_invoker(cli_type, event_callback=event_callback)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """列出可用工具。"""
        tools = []
        for cli_type in ["codex", "gemini", "claude", "opencode"]:
            if config.is_tool_allowed(cli_type):
                tools.append(
                    Tool(
                        name=cli_type,
                        description=TOOL_DESCRIPTIONS[cli_type],
                        inputSchema=create_tool_schema(cli_type),
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

        if not config.is_tool_allowed(name):
            return [TextContent(type="text", text=f"Error: Tool '{name}' is not enabled")]

        # 验证工具名称
        if name not in ["codex", "gemini", "claude", "opencode"]:
            return [TextContent(type="text", text=f"Error: Unknown tool '{name}'")]

        # 核心变更：每次请求创建新的 invoker（per-request 隔离）
        invoker = create_invoker_for_request(name)
        prompt = arguments.get("prompt", "")
        task_note = arguments.get("task_note", "")

        # 立即推送用户 prompt 到 GUI
        push_user_prompt(name, prompt, task_note)

        # 生成请求 ID 并登记（如果 registry 可用）
        request_id = None
        if registry is not None:  # 明确检查 None，而不是 truthiness
            request_id = registry.generate_request_id()
            # 获取当前任务并登记
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
            # 处理 report_mode：注入输出格式要求
            report_mode = arguments.get("report_mode", False)
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
                arguments = {**arguments, "prompt": arguments["prompt"] + injection_note}

            # 处理 context_paths：注入参考路径
            context_paths = arguments.get("context_paths", [])
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
                arguments = {**arguments, "prompt": arguments["prompt"] + context_note}

            # 构建参数
            params = _build_params(name, arguments)

            # 执行（取消异常会直接传播，不会返回）
            result = await invoker.execute(params)

            # 获取参数
            full_output = arguments.get("full_output", False)
            debug_enabled = arguments.get("debug") if "debug" in arguments else config.debug
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
            response_data = ResponseData(
                answer=result.agent_messages if result.success else "",
                session_id=result.session_id or "",
                thought_steps=result.thought_steps if full_output else [],
                debug_info=debug_info,
                success=result.success,
                error=result.error,
            )

            # 格式化响应
            formatter = get_formatter()
            response = formatter.format(
                response_data,
                full_output=full_output,
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
                        full_output=full_output,
                    )

                    # 添加 XML wrapper（如果启用）
                    if args.get("save_file_with_wrapper", False):
                        continuation_id = result.session_id or ""
                        file_content = (
                            f'<agent-output agent="{name}" continuation_id="{continuation_id}">\n'
                            f'{file_content}\n'
                            f'</agent-output>\n'
                        )

                    # 追加或覆盖
                    file_path = Path(save_file_path)
                    if args.get("save_file_with_append_mode", False) and file_path.exists():
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
                return [TextContent(type="text", text=f"Error: {str(e)}")]
            raise

        finally:
            # 注销请求
            logger.debug(f"Tool '{name}' finally block, request_id={request_id}")
            if registry and request_id:
                registry.unregister(request_id)
                logger.debug(f"Unregistered request: {request_id[:8]}...")

    return server


def _build_params(cli_type: str, args: dict[str, Any]):
    """构建 CLI 参数对象。"""
    # 公共参数（continuation_id 映射到内部的 session_id）
    common = {
        "prompt": args["prompt"],
        "workspace": Path(args["workspace"]),
        "permission": Permission(args.get("permission", "read-only")),
        "session_id": args.get("continuation_id", ""),  # 外部 continuation_id → 内部 session_id
        "model": args.get("model", ""),
        "full_output": args.get("full_output", False),
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
            agent=args.get("agent", "build"),
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
