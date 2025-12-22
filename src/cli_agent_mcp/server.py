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
import json
import logging
import time
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from .config import get_config
from .gui_manager import GUIManager
from .orchestrator import RequestRegistry
from .tool_schema import (
    SUPPORTED_TOOLS,
    PARALLEL_SUPPORTED_TOOLS,
    TOOL_DESCRIPTIONS,
    normalize_tool_name,
    create_tool_schema,
)
from .handlers import (
    ToolContext,
    BananaHandler,
    ImageHandler,
    CLIHandler,
    ParallelHandler,
)
from .shared.response_formatter import format_error_response

__all__ = ["create_server"]

logger = logging.getLogger(__name__)


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

    def make_event_callback(cli_type: str, task_note: str = "", task_index: int | None = None):
        """创建事件回调函数。"""
        def callback(event):
            if gui_manager and gui_manager.is_running:
                # 转换 UnifiedEvent 为字典
                event_dict = event.model_dump() if hasattr(event, "model_dump") else dict(event.__dict__)
                event_dict["source"] = cli_type
                # 注入 task_note 和 task_index 到 metadata
                metadata = event_dict.get("metadata", {}) or {}
                if task_note:
                    metadata["task_note"] = task_note
                if task_index is not None:
                    metadata["task_index"] = task_index
                if metadata:
                    event_dict["metadata"] = metadata
                gui_manager.push_event(event_dict)
        return callback

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
            return format_error_response(f"Tool '{name}' is not enabled")

        # 验证工具名称
        if base_name not in SUPPORTED_TOOLS:
            return format_error_response(f"Unknown tool '{name}'")

        # parallel 模式只支持特定工具
        if is_parallel and base_name not in PARALLEL_SUPPORTED_TOOLS:
            return format_error_response(f"Tool '{base_name}' does not support parallel mode")

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

        # 创建工具上下文（供 handlers 使用）
        tool_ctx = ToolContext(
            config=config,
            gui_manager=gui_manager,
            registry=registry,
            push_to_gui=push_to_gui,
            push_user_prompt=push_user_prompt,
            make_event_callback=make_event_callback,
        )

        try:
            # 选择并执行 handler
            if base_name == "banana":
                handler = BananaHandler()
                return await handler.handle(arguments, tool_ctx)

            if base_name == "image":
                handler = ImageHandler()
                return await handler.handle(arguments, tool_ctx)

            if is_parallel:
                handler = ParallelHandler(base_name)
                return await handler.handle(arguments, tool_ctx)

            # CLI 工具（codex, gemini, claude, opencode）
            handler = CLIHandler(base_name)
            return await handler.handle(arguments, tool_ctx)

        except asyncio.CancelledError:
            logger.info(f"Tool '{name}' cancelled")
            raise

        except BaseException as e:
            logger.error(
                f"Tool '{name}' BaseException: type={type(e).__name__}, "
                f"msg={e}"
            )
            if isinstance(e, Exception):
                return format_error_response(str(e))
            raise

        finally:
            # 注销请求
            logger.debug(f"Tool '{name}' finally block, request_id={request_id}")
            if registry and request_id:
                registry.unregister(request_id)
                logger.debug(f"Unregistered request: {request_id[:8]}...")

    return server
