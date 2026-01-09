"""Tool Handler 基础抽象。

定义工具处理器的协议和上下文。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from mcp.types import TextContent

if TYPE_CHECKING:
    from fastmcp import Context
    from ..config import Config
    from ..gui_manager import GUIManager
    from ..orchestrator import RequestRegistry

__all__ = [
    "ToolContext",
    "ToolHandler",
]

logger = logging.getLogger(__name__)


@dataclass
class ToolContext:
    """工具执行上下文。

    封装工具执行所需的所有依赖，避免在函数间传递大量参数。
    """

    config: "Config"
    gui_manager: "GUIManager | None"
    registry: "RequestRegistry | None"
    push_to_gui: Callable[[dict[str, Any]], None]
    push_user_prompt: Callable[[str, str, str], None]
    make_event_callback: Callable[[str, str, int | None], Callable[[Any], None] | None]
    mcp_context: "Context | None" = field(default=None)

    def resolve_debug(self, arguments: dict[str, Any]) -> bool:
        """统一解析 debug 开关。"""
        return bool(arguments.get("debug")) or self.config.debug

    def has_progress_token(self) -> bool:
        """检查当前 MCP 请求是否带有 progressToken。"""
        if not self.mcp_context:
            return False
        request_context = getattr(self.mcp_context, "request_context", None)
        if not request_context:
            return False
        meta = getattr(request_context, "meta", None)
        if not meta:
            return False
        return getattr(meta, "progressToken", None) is not None

    async def report_progress(
        self,
        progress: float,
        total: float | None = None,
        message: str | None = None,
    ) -> None:
        """报告进度（用于长时间运行的任务保活）。

        Args:
            progress: 当前进度值
            total: 总进度值（可选）
            message: 进度消息（可选）
        """
        if self.mcp_context:
            await self.mcp_context.report_progress(
                progress=progress,
                total=total,
                message=message,
            )

    async def report_progress_safe(
        self,
        progress: float,
        total: float | None = None,
        message: str | None = None,
    ) -> None:
        """best-effort 报告进度，失败仅记录日志不影响主流程。"""
        try:
            await self.report_progress(progress=progress, total=total, message=message)
        except Exception as e:
            logger.warning(
                "Failed to report progress (progress=%s, total=%s, message=%r): %s",
                progress,
                total,
                message,
                e,
                exc_info=True,
            )


class ToolHandler(ABC):
    """工具处理器协议。

    所有工具处理器必须实现此接口。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称。"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述。"""
        ...

    @abstractmethod
    def get_input_schema(self) -> dict[str, Any]:
        """获取输入参数 schema。"""
        ...

    @abstractmethod
    async def handle(
        self,
        arguments: dict[str, Any],
        ctx: ToolContext,
    ) -> list[TextContent]:
        """处理工具调用。

        Args:
            arguments: 工具参数
            ctx: 执行上下文

        Returns:
            TextContent 列表
        """
        ...

    def validate(self, arguments: dict[str, Any]) -> str | None:
        """验证参数。

        Args:
            arguments: 工具参数

        Returns:
            错误消息，如果验证通过则返回 None
        """
        return None
