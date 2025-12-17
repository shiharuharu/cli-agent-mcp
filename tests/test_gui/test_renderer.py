"""GUI 渲染器单元测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 添加 shared 到路径（在 conftest.py 也设置了，但这里确保独立运行也可以）
SHARED_DIR = Path(__file__).parent.parent.parent / "shared"
if SHARED_DIR.exists() and str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

from gui.renderer import EventRenderer, RenderConfig


class TestEventRenderer:
    """测试事件渲染器。"""

    def test_render_lifecycle_session_start(self):
        """测试渲染会话开始事件。"""
        renderer = EventRenderer()
        event = {
            "category": "lifecycle",
            "lifecycle_type": "session_start",
            "session_id": "abc12345",
            "model": "gemini-2.0-flash",
            "source": "gemini",
            "timestamp": "2025-12-16T10:30:00Z",
        }
        html = renderer.render(event)

        assert "[SESSION]" in html
        assert "abc12345" in html
        assert "gemini-2.0-flash" in html

    def test_render_lifecycle_session_end(self):
        """测试渲染会话结束事件。"""
        renderer = EventRenderer()
        event = {
            "category": "lifecycle",
            "lifecycle_type": "session_end",
            "session_id": "abc12345",
            "status": "success",
            "stats": {
                "total_tokens": 250,
                "duration_ms": 5000,
            },
            "source": "gemini",
        }
        html = renderer.render(event)

        assert "[RESULT]" in html
        assert "SUCCESS" in html
        assert "tokens=250" in html
        assert "duration=5000ms" in html

    def test_render_message_user(self):
        """测试渲染用户消息。"""
        renderer = EventRenderer()
        event = {
            "category": "message",
            "content_type": "text",
            "role": "user",
            "text": "Hello, world!",
            "source": "gemini",
            "session_id": "abc12345",
        }
        html = renderer.render(event)

        assert "[USER]" in html
        assert "Hello, world!" in html
        assert 'class="usr"' in html

    def test_render_message_assistant(self):
        """测试渲染助手消息。"""
        renderer = EventRenderer()
        event = {
            "category": "message",
            "content_type": "text",
            "role": "assistant",
            "text": "I can help you with that.",
            "source": "gemini",
            "session_id": "abc12345",
        }
        html = renderer.render(event)

        assert "[ASSISTANT]" in html
        assert "I can help you with that." in html
        assert 'class="ast"' in html

    def test_render_message_reasoning(self):
        """测试渲染推理消息。"""
        renderer = EventRenderer()
        event = {
            "category": "message",
            "content_type": "reasoning",
            "role": "assistant",
            "text": "Let me think about this...",
            "source": "codex",
            "session_id": "abc12345",
        }
        html = renderer.render(event)

        assert "[REASONING]" in html
        assert "Let me think about this..." in html
        assert 'class="rsn"' in html

    def test_render_operation_tool(self):
        """测试渲染工具操作。"""
        renderer = EventRenderer()
        event = {
            "category": "operation",
            "operation_type": "tool",
            "name": "read_file",
            "operation_id": "tool-001",
            "status": "running",
            "input": '{"path": "/src/main.py"}',
            "source": "gemini",
            "session_id": "abc12345",
        }
        html = renderer.render(event)

        assert "[TOOL]" in html
        assert "read_file" in html
        assert "●" in html  # running indicator

    def test_render_operation_command(self):
        """测试渲染命令操作。"""
        renderer = EventRenderer()
        event = {
            "category": "operation",
            "operation_type": "command",
            "name": "Bash",
            "operation_id": "cmd-001",
            "status": "success",
            "output": "file1.py\nfile2.py",
            "source": "claude",
            "session_id": "abc12345",
        }
        html = renderer.render(event)

        assert "[COMMAND]" in html
        assert "Bash" in html
        assert "✓" in html  # success indicator

    def test_render_operation_failed(self):
        """测试渲染失败操作。"""
        renderer = EventRenderer()
        event = {
            "category": "operation",
            "operation_type": "command",
            "name": "Bash",
            "operation_id": "cmd-001",
            "status": "failed",
            "output": "Error: file not found",
            "source": "claude",
            "session_id": "abc12345",
        }
        html = renderer.render(event)

        assert "✗" in html  # failed indicator
        assert 'class="err"' in html

    def test_render_system_error(self):
        """测试渲染系统错误。"""
        renderer = EventRenderer()
        event = {
            "category": "system",
            "severity": "error",
            "message": "API rate limit exceeded",
            "source": "gemini",
        }
        html = renderer.render(event)

        assert "[ERROR]" in html
        assert "API rate limit exceeded" in html
        assert 'class="err"' in html

    def test_render_system_fallback(self):
        """测试渲染 fallback 事件。"""
        renderer = EventRenderer()
        event = {
            "category": "system",
            "is_fallback": True,
            "raw": {"type": "unknown_event", "data": "something"},
            "source": "unknown",
        }
        html = renderer.render(event)

        assert "[UNKNOWN]" in html
        assert "unknown_event" in html


class TestRenderConfigMultiSource:
    """测试多端模式渲染。"""

    def test_single_source_mode_no_label(self):
        """单端模式不显示来源标签。"""
        config = RenderConfig(multi_source_mode=False)
        renderer = EventRenderer(config)
        event = {
            "category": "message",
            "content_type": "text",
            "role": "user",
            "text": "Hello",
            "source": "gemini",
            "session_id": "abc12345",
        }
        html = renderer.render(event)

        # 不应该有来源标签
        assert "[GEMINI]" not in html
        assert 'class="src"' not in html

    def test_multi_source_mode_has_label(self):
        """多端模式显示来源标签。"""
        config = RenderConfig(multi_source_mode=True)
        renderer = EventRenderer(config)
        event = {
            "category": "message",
            "content_type": "text",
            "role": "user",
            "text": "Hello",
            "source": "gemini",
            "session_id": "abc12345",
        }
        html = renderer.render(event)

        # 应该有来源标签
        assert "[GEMINI]" in html
        assert 'class="src"' in html

    def test_multi_source_different_colors(self):
        """多端模式下不同来源有不同颜色。"""
        config = RenderConfig(multi_source_mode=True)
        renderer = EventRenderer(config)

        sources = ["gemini", "codex", "claude"]
        colors = set()

        for src in sources:
            event = {
                "category": "message",
                "content_type": "text",
                "role": "user",
                "text": "Hello",
                "source": src,
                "session_id": f"{src}-session",
            }
            html = renderer.render(event)
            # 提取颜色
            import re
            match = re.search(r'style="color:(#[A-Fa-f0-9]+)"', html)
            if match:
                colors.add(match.group(1))

        # 应该有 3 种不同颜色
        assert len(colors) == 3


class TestTruncation:
    """测试内容截断。"""

    def test_truncate_long_output(self):
        """测试截断长输出。"""
        config = RenderConfig(max_output_chars=100)
        renderer = EventRenderer(config)
        event = {
            "category": "message",
            "content_type": "text",
            "role": "assistant",
            "text": "A" * 200,  # 超过 100 字符
            "source": "gemini",
        }
        html = renderer.render(event)

        # 应该被截断
        assert "..." in html
        assert "A" * 200 not in html

    def test_truncate_many_lines(self):
        """测试截断多行输出。"""
        config = RenderConfig(max_output_lines=5)
        renderer = EventRenderer(config)
        event = {
            "category": "message",
            "content_type": "text",
            "role": "assistant",
            "text": "\n".join([f"Line {i}" for i in range(20)]),
            "source": "gemini",
        }
        html = renderer.render(event)

        # 应该被截断
        assert "more lines" in html
        assert "Line 19" not in html


class TestSessionExtraction:
    """测试 session ID 提取。"""

    def test_extract_from_top_level(self):
        """从顶层提取 session_id。"""
        renderer = EventRenderer()
        event = {
            "category": "message",
            "content_type": "text",
            "role": "user",
            "text": "Hello",
            "session_id": "top-level-session",
            "source": "gemini",
        }
        html = renderer.render(event)

        assert "top-level-session" in html

    def test_extract_from_metadata(self):
        """从 metadata 提取 session_id。"""
        renderer = EventRenderer()
        event = {
            "category": "message",
            "content_type": "text",
            "role": "user",
            "text": "Hello",
            "metadata": {"session_id": "metadata-session"},
            "source": "gemini",
        }
        html = renderer.render(event)

        assert "metadata-session" in html

    def test_short_session_id_display(self):
        """长 session ID 只显示后 8 位。"""
        renderer = EventRenderer()
        event = {
            "category": "message",
            "content_type": "text",
            "role": "user",
            "text": "Hello",
            "session_id": "very-long-session-id-abc12345",
            "source": "gemini",
        }
        html = renderer.render(event)

        # 应该显示短 ID
        assert "#abc12345" in html


class TestSeverityRendering:
    """测试不同 severity 级别的渲染颜色。"""

    def test_error_severity_renders_red(self):
        """error 级别渲染红色（err class）。"""
        renderer = EventRenderer()
        event = {
            "category": "system",
            "severity": "error",
            "message": "Execution failed: CLI not found",
            "source": "codex",
        }
        html = renderer.render(event)

        assert "[ERROR]" in html
        assert 'class="err"' in html
        assert "Execution failed" in html

    def test_warning_severity_renders_yellow(self):
        """warning 级别渲染黄色（wrn class）。"""
        renderer = EventRenderer()
        event = {
            "category": "system",
            "severity": "warning",
            "message": "Execution cancelled by user",
            "source": "gemini",
        }
        html = renderer.render(event)

        assert "[WARNING]" in html
        assert 'class="wrn"' in html
        assert "cancelled" in html

    def test_info_severity_renders_dim(self):
        """info 级别渲染灰色（dm class）。"""
        renderer = EventRenderer()
        event = {
            "category": "system",
            "severity": "info",
            "message": "codex CLI started",
            "source": "codex",
        }
        html = renderer.render(event)

        assert "[INFO]" in html
        assert 'class="dm"' in html
        assert "started" in html

    def test_startup_error_event(self):
        """进程启动失败事件渲染红色。"""
        renderer = EventRenderer()
        event = {
            "category": "system",
            "severity": "error",
            "message": "Execution failed: FileNotFoundError: codex not found",
            "source": "codex",
            "is_fallback": False,
        }
        html = renderer.render(event)

        # 错误应该是红色
        assert 'class="err"' in html
        assert "[ERROR]" in html

    def test_exit_error_event(self):
        """非零退出码事件渲染红色。"""
        renderer = EventRenderer()
        event = {
            "category": "system",
            "severity": "error",
            "message": "gemini exited with code 1: API error",
            "source": "gemini",
            "is_fallback": False,
        }
        html = renderer.render(event)

        assert 'class="err"' in html
        assert "exited with code" in html

    def test_non_fallback_event_uses_severity(self):
        """非 fallback 事件使用 severity 渲染。"""
        renderer = EventRenderer()
        # 合成事件（有 severity 和 message）应该不是 fallback
        event = {
            "category": "system",
            "severity": "warning",
            "message": "Test warning",
            "is_fallback": False,
            "source": "claude",
        }
        html = renderer.render(event)

        # 不应该显示 [UNKNOWN]
        assert "[UNKNOWN]" not in html
        # 应该显示 [WARNING]
        assert "[WARNING]" in html
        assert 'class="wrn"' in html

