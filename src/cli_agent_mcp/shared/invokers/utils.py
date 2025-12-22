"""Invoker 工具函数。

提供 invokers 共用的工具函数，避免代码重复。
"""

from __future__ import annotations

import re

__all__ = [
    "sanitize_task_note",
    "escape_xml",
]


def sanitize_task_note(name: str) -> str:
    """将 task_note 转换为安全的文件名前缀。

    Args:
        name: 原始 task_note

    Returns:
        安全的文件名前缀（最多 50 字符）
    """
    if not name:
        return ""
    sanitized = re.sub(r'[^\w\-]', '-', name)
    sanitized = re.sub(r'-+', '-', sanitized)
    return sanitized.strip('-')[:50]


def escape_xml(text: str) -> str:
    """转义 XML 特殊字符。

    Args:
        text: 原始文本

    Returns:
        转义后的文本
    """
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
