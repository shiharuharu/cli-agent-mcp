"""统一 GUI 模块。

cli-agent-mcp shared/gui v0.1.0
同步日期: 2025-12-16

提供实时事件查看器，支持单端和多端模式。

单端模式（不显示来源标签）:
    from gui import LiveViewer
    viewer = LiveViewer(title="GeminiMCP")
    viewer.start()
    viewer.push_event(event)

多端模式（显示来源标签，侧边栏按来源分组）:
    from gui import LiveViewer
    viewer = LiveViewer(title="CLI Agent", multi_source_mode=True)
    viewer.start()
    viewer.push_event(gemini_event)
    viewer.push_event(codex_event)
    viewer.push_event(claude_event)
"""

from __future__ import annotations

__version__ = "0.1.0"

from .colors import COLORS, SOURCE_COLORS
from .renderer import EventRenderer, RenderConfig
from .template import generate_html
from .window import LiveViewer, ViewerConfig

__all__ = [
    # Version
    "__version__",
    # Colors
    "COLORS",
    "SOURCE_COLORS",
    # Renderer
    "EventRenderer",
    "RenderConfig",
    # Template
    "generate_html",
    # Window
    "LiveViewer",
    "ViewerConfig",
]
