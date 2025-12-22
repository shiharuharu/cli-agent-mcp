"""Prompt Injection 工具函数。

提供 context_paths 和 report_mode 注入功能。
"""

from __future__ import annotations

__all__ = ["inject_context_and_report_mode"]


def inject_context_and_report_mode(
    prompt: str,
    context_paths: list[str],
    report_mode: bool,
) -> str:
    """将 context_paths 和 report_mode 注入到 prompt 中。"""
    result = prompt

    # 处理 report_mode
    if report_mode:
        injection_note = """

<mcp-injection type="report-mode">
  <meta-rules>
    <rule>Follow higher-priority system messages first; apply these report-mode instructions where they do not conflict.</rule>
    <rule>Do not mention this template, "report-mode", MCP, or any injection mechanism. Write as if replying directly to the user.</rule>
  </meta-rules>

  <output-requirements>
    <rule>Produce a comprehensive, self-contained response that can be understood without access to any prior conversation.</rule>
    <rule>Do NOT use phrases like "above", "earlier", "previous messages", "as discussed", or similar context-dependent references.</rule>
    <rule>Use the same primary language as the user's request.</rule>
    <rule>Briefly restate the user's task or question in your own words before presenting your analysis.</rule>
  </output-requirements>

  <structure-guidelines>
    <guideline>Start with key findings or conclusions in 1-3 short points so the reader quickly understands the outcome.</guideline>
    <guideline>Provide enough context so a new reader understands the problem without seeing the rest of the conversation.</guideline>
    <guideline>Organize longer answers into clear sections (e.g., Summary, Context, Analysis, Recommendations) when helpful.</guideline>
    <guideline>End with concrete, actionable recommendations or next steps when applicable.</guideline>
  </structure-guidelines>

  <reasoning-guidelines>
    <guideline>Explain important assumptions, trade-offs, and decisions clearly.</guideline>
    <guideline>Where your platform allows, show reasoning step by step. If detailed chain-of-thought is restricted, provide a concise explanation instead.</guideline>
  </reasoning-guidelines>

  <code-guidelines>
    <guideline>Reference specific locations using file paths and line numbers (e.g., src/app.ts:42).</guideline>
    <guideline>Include small, relevant code snippets inline when they help the reader understand without opening the file.</guideline>
  </code-guidelines>
</mcp-injection>"""
        result += injection_note

    # 处理 context_paths
    if context_paths:
        paths_xml = "\n".join(f"    <path>{p}</path>" for p in context_paths)
        context_note = f"""

<mcp-injection type="reference-paths">
  <description>
    These paths are provided as reference for project structure.
    You may use them to understand naming conventions and file organization.
  </description>
  <paths>
{paths_xml}
  </paths>
</mcp-injection>"""
        result += context_note

    return result
