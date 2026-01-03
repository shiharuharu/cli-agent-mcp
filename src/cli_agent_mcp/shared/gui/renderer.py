"""事件渲染器。

cli-agent-mcp shared/gui v0.1.0
同步日期: 2025-12-16

将统一事件格式渲染为 HTML，支持单端/多端模式。
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .colors import COLORS, SOURCE_COLORS

__all__ = [
    "EventRenderer",
    "RenderConfig",
]

# 文件 URL 解析器类型
FileUrlResolver = Any  # Callable[[str], str] | None


@dataclass
class RenderConfig:
    """渲染配置。

    Attributes:
        multi_source_mode: 是否为多端模式（显示来源标签）
        max_output_chars: 输出内容最大字符数（超出截断）
        max_output_lines: 输出内容最大行数
        show_raw_on_unknown: 未知事件是否显示原始 JSON
    """
    multi_source_mode: bool = False
    max_output_chars: int = 2000
    max_output_lines: int = 50
    show_raw_on_unknown: bool = True


class EventRenderer:
    """事件渲染器。

    将统一事件（UnifiedEvent）渲染为 HTML 片段。

    Example:
        renderer = EventRenderer(multi_source_mode=True)
        html = renderer.render(event)
    """

    def __init__(self, config: RenderConfig | None = None, file_url_resolver: FileUrlResolver = None) -> None:
        self.config = config or RenderConfig()
        self._fold_id = 0
        self._file_url_resolver = file_url_resolver

    def render(self, event: dict[str, Any]) -> str:
        """渲染单个事件为 HTML。

        Args:
            event: 统一事件字典（UnifiedEvent.model_dump()）

        Returns:
            HTML 字符串
        """
        category = event.get("category", "")
        timestamp = self._format_timestamp(event.get("timestamp"))
        source = event.get("source", "unknown")
        session_id = self._extract_session_id(event)

        # 构建前缀
        prefix_parts = [f'<span class="ts">[{timestamp}]</span>']

        if session_id:
            short_id = session_id[-8:] if len(session_id) > 8 else session_id
            prefix_parts.append(
                f'<span class="ss" data-session="{session_id}" '
                f'onclick="copyText(\'{session_id}\')">[#{short_id}]</span>'
            )

        if self.config.multi_source_mode:
            color = SOURCE_COLORS.get(source, SOURCE_COLORS["unknown"])
            prefix_parts.append(f'<span class="src" style="color:{color}">[{source.upper()}]</span>')

        prefix = " ".join(prefix_parts)

        # 按类别渲染
        if category == "lifecycle":
            return self._render_lifecycle(event, prefix)
        elif category == "message":
            return self._render_message(event, prefix)
        elif category == "operation":
            return self._render_operation(event, prefix)
        elif category == "system":
            return self._render_system(event, prefix)
        else:
            return self._render_unknown(event, prefix)

    def _format_timestamp(self, ts: float | int | str | None) -> str:
        """格式化时间戳为 YYYY-MM-DD HH:MM:SS。

        支持:
        - float/int: Unix 时间戳（秒），自动兼容毫秒（> 1e10）
        - str: ISO 格式字符串
        - None: 使用当前时间
        """
        if ts is None:
            return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            if isinstance(ts, (int, float)):
                # 兼容毫秒级时间戳
                if ts > 1e10:
                    ts = ts / 1000
                dt = datetime.fromtimestamp(ts)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            # str 类型
            if "T" in ts:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            return ts[:19] if len(ts) >= 19 else ts
        except (ValueError, TypeError, OSError):
            return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _extract_session_id(self, event: dict[str, Any]) -> str:
        """提取 session ID。"""
        # 优先从顶层获取
        if event.get("session_id"):
            return event["session_id"]
        # 从 metadata 获取
        metadata = event.get("metadata", {})
        return metadata.get("session_id", "") or metadata.get("thread_id", "")

    def _render_lifecycle(self, event: dict[str, Any], prefix: str) -> str:
        """渲染生命周期事件。"""
        lifecycle_type = event.get("lifecycle_type", "")
        status = event.get("status", "")
        model = event.get("model", "")
        stats = event.get("stats", {})

        if lifecycle_type == "session_start":
            model_info = f" | model={model}" if model else ""
            session_id_val = event.get("session_id", "")
            return (
                f'<div class="e" data-session="{session_id_val}">'
                f'{prefix} <span class="lb">[SESSION]</span> '
                f'<span class="ss" onclick="filterBySession(\'{session_id_val}\')">{session_id_val}</span>{model_info}'
                f'</div>'
            )
        elif lifecycle_type == "session_end":
            status_cls = "ok" if status == "success" else "err"
            stats_info = self._format_stats(stats)
            return (
                f'<div class="e" data-session="{event.get("session_id", "")}">'
                f'{prefix} <span class="lb">[RESULT]</span> '
                f'<span class="{status_cls}">{status.upper()}</span> '
                f'<span class="dm">{stats_info}</span>'
                f'</div>'
            )
        elif lifecycle_type in ("turn_start", "turn_end"):
            label = "TURN_START" if lifecycle_type == "turn_start" else "TURN_END"
            stats_info = self._format_stats(stats)
            return (
                f'<div class="e" data-session="{event.get("session_id", "")}">'
                f'{prefix} <span class="lb">[{label}]</span> '
                f'<span class="dm">{stats_info}</span>'
                f'</div>'
            )
        else:
            return (
                f'<div class="e">{prefix} <span class="lb">[{lifecycle_type.upper()}]</span></div>'
            )

    def _render_message(self, event: dict[str, Any], prefix: str) -> str:
        """渲染消息事件。"""
        role = event.get("role", "")
        content_type = event.get("content_type", "text")
        session_id = self._extract_session_id(event)

        if content_type == "reasoning":
            text = self._escape_and_truncate(event.get("text", ""))
            return (
                f'<div class="e" data-session="{session_id}">'
                f'{prefix} <span class="lb">[REASONING]</span> '
                f'<span class="rsn">{text}</span>'
                f'</div>'
            )
        elif role == "user":
            text = self._escape_and_truncate(event.get("text", ""))
            return (
                f'<div class="e" data-session="{session_id}">'
                f'{prefix} <span class="lb">[USER]</span> '
                f'<span class="usr">{text}</span>'
                f'</div>'
            )
        else:  # assistant - 不截断，完整输出
            text = self._esc(event.get("text", "")).replace("\n", "<br>")
            return (
                f'<div class="e" data-session="{session_id}">'
                f'{prefix} <span class="lb">[ASSISTANT]</span> '
                f'<span class="ast">{text}</span>'
                f'</div>'
            )

    def _render_operation(self, event: dict[str, Any], prefix: str) -> str:
        """渲染操作事件（工具调用、命令执行等）。"""
        op_type = event.get("operation_type", "tool")
        name = event.get("name", "")
        status = event.get("status", "")
        input_data = event.get("input", "")
        output = event.get("output", "")
        session_id = self._extract_session_id(event)

        # 选择颜色类
        type_cls = {
            "command": "cmd",
            "file": "file",
            "mcp": "mcp",
            "search": "search",
        }.get(op_type, "tl")

        # 状态图标
        if status == "success":
            status_html = '<span class="ok">✓</span>'
        elif status == "failed":
            status_html = '<span class="err">✗</span>'
        elif status == "running":
            status_html = '<span class="run">●</span>'
        else:
            status_html = ""

        # 操作类型标签
        label = op_type.upper() if op_type else "TOOL"

        # 基本行
        base_html = (
            f'<div class="e" data-session="{session_id}">'
            f'{prefix} <span class="lb">[{label}]</span> '
            f'{status_html} <span class="{type_cls}">{self._esc(name)}</span>'
        )

        # 如果有输入或输出，添加折叠内容
        if input_data or output:
            fold_id = f"f{self._fold_id}"
            self._fold_id += 1

            content_parts = []
            if input_data:
                input_escaped = self._escape_and_truncate(input_data)
                content_parts.append(f'<span class="dm">Input:</span> {input_escaped}')
            if output:
                output_escaped = self._escape_and_truncate(output)
                content_parts.append(f'<span class="dm">Output:</span> {output_escaped}')

            # 渲染图片缩略图
            metadata = event.get("metadata", {})
            artifacts = metadata.get("artifacts", [])
            if artifacts and self._file_url_resolver:
                img_html = '<div class="img-grid">'
                for path in artifacts:
                    url = self._file_url_resolver(path)
                    img_html += f'<img class="img-thumb" src="{url}" onclick="window.open(\'{url}\')">'
                img_html += '</div>'
                content_parts.append(img_html)

            fold_content = "<br>".join(content_parts)
            base_html += (
                f' <span class="fold" onclick="toggle(\'{fold_id}\', this)">▶</span>'
                f'<div class="fold-content" id="{fold_id}">{fold_content}</div>'
            )

        base_html += '</div>'
        return base_html

    def _render_system(self, event: dict[str, Any], prefix: str) -> str:
        """渲染系统事件。"""
        severity = event.get("severity", "info")
        message = self._escape_and_truncate(event.get("message", ""))
        is_fallback = event.get("is_fallback", False)
        session_id = self._extract_session_id(event)

        if is_fallback:
            raw_preview = ""
            if self.config.show_raw_on_unknown:
                raw = event.get("raw", {})
                raw_str = json.dumps(raw, ensure_ascii=False)[:100]
                raw_preview = f' <span class="dm">{self._esc(raw_str)}...</span>'
            return (
                f'<div class="e" data-session="{session_id}">'
                f'{prefix} <span class="dm">[UNKNOWN]</span>{raw_preview}'
                f'</div>'
            )

        severity_cls = {"error": "err", "warning": "wrn"}.get(severity, "dm")
        label = severity.upper()

        return (
            f'<div class="e" data-session="{session_id}">'
            f'{prefix} <span class="{severity_cls}">[{label}]</span> '
            f'<span class="{severity_cls}">{message}</span>'
            f'</div>'
        )

    def _render_unknown(self, event: dict[str, Any], prefix: str) -> str:
        """渲染未知事件。"""
        raw_str = json.dumps(event, ensure_ascii=False)[:100]
        return (
            f'<div class="e">'
            f'{prefix} <span class="dm">[?]</span> '
            f'<span class="dm">{self._esc(raw_str)}...</span>'
            f'</div>'
        )

    def _format_stats(self, stats: dict[str, Any]) -> str:
        """格式化统计信息。"""
        parts = []
        if stats.get("total_tokens"):
            parts.append(f"tokens={stats['total_tokens']}")
        elif stats.get("input_tokens") or stats.get("output_tokens"):
            in_tok = stats.get("input_tokens", 0)
            out_tok = stats.get("output_tokens", 0)
            parts.append(f"tokens={in_tok}+{out_tok}")
        if stats.get("duration_ms"):
            parts.append(f"duration={stats['duration_ms']}ms")
        if stats.get("tool_calls"):
            parts.append(f"tools={stats['tool_calls']}")
        if stats.get("total_cost_usd"):
            parts.append(f"cost=${stats['total_cost_usd']:.4f}")
        return f"[{' '.join(parts)}]" if parts else ""

    def _esc(self, text: str) -> str:
        """HTML 转义。"""
        return html.escape(str(text))

    def _escape_and_truncate(self, text: str) -> str:
        """HTML 转义并截断。"""
        text = str(text).strip()
        # 行数截断
        lines = text.split("\n")
        if len(lines) > self.config.max_output_lines:
            text = "\n".join(lines[: self.config.max_output_lines])
            text += f"\n... ({len(lines) - self.config.max_output_lines} more lines)"
        # 字符截断
        if len(text) > self.config.max_output_chars:
            text = text[: self.config.max_output_chars] + "..."
        return html.escape(text).replace("\n", "<br>")
