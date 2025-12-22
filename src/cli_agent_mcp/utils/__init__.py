"""Utility 模块。

提供通用工具函数。
"""

from .xml_wrapper import xml_escape_attr, build_wrapper
from .prompt_injection import inject_context_and_report_mode

__all__ = [
    "xml_escape_attr",
    "build_wrapper",
    "inject_context_and_report_mode",
]
