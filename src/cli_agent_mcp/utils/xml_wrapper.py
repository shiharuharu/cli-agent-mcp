"""XML Wrapper 工具函数。

提供 XML 属性转义和 wrapper 构建功能。
"""

from __future__ import annotations

__all__ = ["xml_escape_attr", "build_wrapper"]


def xml_escape_attr(s: str | None) -> str:
    """XML 属性值转义。"""
    if s is None:
        s = ""
    else:
        s = str(s)
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;")
             .replace("'", "&apos;"))


def build_wrapper(
    agent: str,
    continuation_id: str,
    task_note: str,
    task_index: int,
    status: str,
    prompt: str,
    response: str,
) -> str:
    """构建 XML-like wrapper。"""
    return f'''<agent-output agent="{xml_escape_attr(agent)}" continuation_id="{xml_escape_attr(continuation_id)}" task_note="{xml_escape_attr(task_note)}" task_index="{task_index}" status="{xml_escape_attr(status)}">
  <prompt>
{prompt}
  </prompt>
  <response>
{response}
  </response>
</agent-output>'''
