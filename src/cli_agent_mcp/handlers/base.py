"""Tool Handler 基础抽象。

定义工具处理器的协议和上下文。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Protocol

from mcp.types import TextContent

if TYPE_CHECKING:
    from ..config import Config
    from ..gui_manager import GUIManager
    from ..orchestrator import RequestRegistry

__all__ = [
    "ToolContext",
    "ToolHandler",
]


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

    def resolve_debug(self, arguments: dict[str, Any]) -> bool:
        """统一解析 debug 开关。"""
        if "debug" in arguments:
            return bool(arguments["debug"])
        return self.config.debug


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
