"""GUI 颜色方案。

cli-agent-mcp shared/gui v0.1.0
同步日期: 2025-12-16

深色主题颜色配置，参考 VS Code 风格。
"""

from __future__ import annotations

__all__ = [
    "COLORS",
    "SOURCE_COLORS",
]

# 基础颜色方案
COLORS = {
    # 背景和边框
    "bg": "#1E1E1E",
    "bg_secondary": "#252526",
    "border": "#3C3C3C",
    "hover": "#2A2A2A",
    "selection": "#264F78",

    # 文本基础
    "fg": "#D4D4D4",
    "fg_dim": "#5A5A5A",
    "fg_muted": "#6A6A6A",

    # 时间戳和标签
    "timestamp": "#5A5A5A",
    "label": "#569CD6",
    "session": "#4EC9B0",

    # 消息角色
    "user": "#7CFC00",         # 亮绿色 - 用户输入醒目
    "assistant": "#F5F5F5",    # 近白色 - 助手输出
    "reasoning": "#8B8B8B",    # 灰色 - 思考过程

    # 操作类型
    "tool": "#6A6A6A",         # 暗灰 - 工具调用（低调）
    "command": "#CE9178",      # 橙色 - 命令
    "file": "#DCDCAA",         # 黄色 - 文件操作
    "mcp": "#C586C0",          # 紫色 - MCP 调用
    "search": "#4FC1FF",       # 天蓝 - 搜索
    "todo": "#D4D4D4",         # 默认色 - TODO

    # 状态
    "success": "#89D185",
    "error": "#F44747",
    "warning": "#DCDCAA",
    "running": "#4FC1FF",
}

# 来源颜色（多端模式下区分不同 CLI）
SOURCE_COLORS = {
    "gemini": "#4285F4",   # Google 蓝
    "codex": "#10A37F",    # OpenAI 绿
    "claude": "#CC785C",   # Anthropic 棕橙
    "opencode": "#8B5CF6", # 紫罗兰色
    "banana": "#FFD700",   # 金黄色（香蕉色）
    "image": "#10B981",    # 翠绿色
    "unknown": "#6A6A6A",  # 灰色
}
