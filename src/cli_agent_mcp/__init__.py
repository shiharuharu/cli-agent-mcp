"""CLI Agent MCP - 统一 CLI Agent MCP 服务器。

环境变量:
    CAM_ENABLE: 启用的工具列表（空/未设置=全部）
    CAM_DISABLE: 禁用的工具列表（从 enable 中减去）
    CAM_GUI: 是否启动 GUI (默认 true)
    CAM_GUI_DETAIL: GUI 详细模式 (默认 false)

用法:
    uvx cli-agent-mcp
"""

__version__ = "0.1.4"

from .app import main
from .server import create_server

__all__ = ["__version__", "main", "create_server"]
