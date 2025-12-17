"""CLI Agent MCP - 统一 CLI Agent MCP 服务器。

环境变量:
    CAM_TOOLS: 允许的工具列表（空=全部）
    CAM_GUI: 是否启动 GUI (默认 true)
    CAM_GUI_DETAIL: GUI 详细模式 (默认 false)

用法:
    uvx cli-agent-mcp
"""

__version__ = "0.1.2"

from .server import main

__all__ = ["__version__", "main"]
