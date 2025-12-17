#!/usr/bin/env python3
"""单端 GUI 测试 Demo。

测试 shared/gui 模块在单端模式下的表现（不显示来源标签）。

Usage:
    python tests/gui/demo_single_source.py gemini
    python tests/gui/demo_single_source.py codex
    python tests/gui/demo_single_source.py claude
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

# 添加 shared 到路径
SHARED_DIR = Path(__file__).parent.parent.parent / "shared"
sys.path.insert(0, str(SHARED_DIR))

from gui import LiveViewer


def generate_gemini_events() -> list[dict]:
    """生成模拟 Gemini 统一事件。"""
    session_id = "gemini-session-abc12345"
    return [
        {
            "category": "lifecycle",
            "lifecycle_type": "session_start",
            "session_id": session_id,
            "model": "gemini-2.0-flash",
            "source": "gemini",
            "timestamp": "2025-12-16T10:30:00Z",
        },
        {
            "category": "message",
            "content_type": "text",
            "role": "user",
            "text": "Write a Python function to calculate fibonacci numbers",
            "source": "gemini",
            "session_id": session_id,
            "timestamp": "2025-12-16T10:30:01Z",
        },
        {
            "category": "message",
            "content_type": "text",
            "role": "assistant",
            "text": "I'll create an efficient fibonacci function using memoization for better performance.",
            "is_delta": True,
            "source": "gemini",
            "session_id": session_id,
            "timestamp": "2025-12-16T10:30:02Z",
        },
        {
            "category": "operation",
            "operation_type": "file",
            "name": "write_file",
            "operation_id": "tool-001",
            "status": "running",
            "input": '{"path": "fib.py", "content": "def fib(n):\\n    ..."}',
            "source": "gemini",
            "session_id": session_id,
            "timestamp": "2025-12-16T10:30:03Z",
        },
        {
            "category": "operation",
            "operation_type": "file",
            "name": "write_file",
            "operation_id": "tool-001",
            "status": "success",
            "output": "File written successfully: fib.py",
            "source": "gemini",
            "session_id": session_id,
            "timestamp": "2025-12-16T10:30:04Z",
        },
        {
            "category": "message",
            "content_type": "text",
            "role": "assistant",
            "text": "Done! I've created fib.py with a memoized fibonacci function.",
            "source": "gemini",
            "session_id": session_id,
            "timestamp": "2025-12-16T10:30:05Z",
        },
        {
            "category": "lifecycle",
            "lifecycle_type": "session_end",
            "session_id": session_id,
            "status": "success",
            "stats": {
                "total_tokens": 250,
                "input_tokens": 80,
                "output_tokens": 170,
                "duration_ms": 5000,
                "tool_calls": 1,
            },
            "source": "gemini",
            "timestamp": "2025-12-16T10:30:06Z",
        },
    ]


def generate_codex_events() -> list[dict]:
    """生成模拟 Codex 统一事件。"""
    session_id = "019b25ad-271b-7d93-9738-9bf9e1fc817a"
    return [
        {
            "category": "lifecycle",
            "lifecycle_type": "session_start",
            "session_id": session_id,
            "source": "codex",
            "timestamp": "2025-12-16T10:30:00Z",
        },
        {
            "category": "message",
            "content_type": "reasoning",
            "role": "assistant",
            "text": "**Analyzing the request**\n\nI need to understand what fibonacci numbers are and implement an efficient solution using dynamic programming.",
            "source": "codex",
            "session_id": session_id,
            "timestamp": "2025-12-16T10:30:01Z",
        },
        {
            "category": "message",
            "content_type": "text",
            "role": "assistant",
            "text": "I'll implement the fibonacci function with dynamic programming for better performance.",
            "source": "codex",
            "session_id": session_id,
            "timestamp": "2025-12-16T10:30:02Z",
        },
        {
            "category": "operation",
            "operation_type": "command",
            "name": "shell",
            "operation_id": "cmd-001",
            "status": "running",
            "input": "/bin/zsh -lc 'python fib.py'",
            "source": "codex",
            "session_id": session_id,
            "timestamp": "2025-12-16T10:30:03Z",
        },
        {
            "category": "operation",
            "operation_type": "command",
            "name": "shell",
            "operation_id": "cmd-001",
            "status": "success",
            "output": "Testing: fib(10) = 55\nfib(20) = 6765",
            "metadata": {"exit_code": 0},
            "source": "codex",
            "session_id": session_id,
            "timestamp": "2025-12-16T10:30:04Z",
        },
        {
            "category": "lifecycle",
            "lifecycle_type": "turn_end",
            "session_id": session_id,
            "status": "success",
            "stats": {
                "input_tokens": 150,
                "output_tokens": 200,
            },
            "source": "codex",
            "timestamp": "2025-12-16T10:30:05Z",
        },
    ]


def generate_claude_events() -> list[dict]:
    """生成模拟 Claude 统一事件。"""
    session_id = "16cdb7ae-cabd-47ad-ad30-4efd2ce48b01"
    return [
        {
            "category": "lifecycle",
            "lifecycle_type": "session_start",
            "session_id": session_id,
            "model": "claude-opus-4-5-20251101",
            "stats": {
                "tools_count": 15,
                "mcp_servers": ["tavily", "context7"],
            },
            "source": "claude",
            "timestamp": "2025-12-16T10:30:00Z",
        },
        {
            "category": "message",
            "content_type": "reasoning",
            "role": "assistant",
            "text": "The user wants me to write a fibonacci function. Let me think about the most efficient approach...",
            "source": "claude",
            "session_id": session_id,
            "timestamp": "2025-12-16T10:30:01Z",
        },
        {
            "category": "message",
            "content_type": "text",
            "role": "assistant",
            "text": "I'll create an efficient fibonacci implementation for you.",
            "source": "claude",
            "session_id": session_id,
            "timestamp": "2025-12-16T10:30:02Z",
        },
        {
            "category": "operation",
            "operation_type": "command",
            "name": "Bash",
            "operation_id": "toolu_001",
            "status": "running",
            "input": '{"command": "cat > fib.py << EOF\\ndef fib(n):\\n    ...\\nEOF"}',
            "source": "claude",
            "session_id": session_id,
            "timestamp": "2025-12-16T10:30:03Z",
        },
        {
            "category": "operation",
            "operation_type": "command",
            "name": "Bash",
            "operation_id": "toolu_001",
            "status": "success",
            "output": "",
            "source": "claude",
            "session_id": session_id,
            "timestamp": "2025-12-16T10:30:04Z",
        },
        {
            "category": "message",
            "content_type": "text",
            "role": "assistant",
            "text": "I've created the fibonacci function. Would you like me to run some tests?",
            "source": "claude",
            "session_id": session_id,
            "timestamp": "2025-12-16T10:30:05Z",
        },
        {
            "category": "lifecycle",
            "lifecycle_type": "session_end",
            "session_id": session_id,
            "status": "success",
            "stats": {
                "duration_ms": 9832,
                "total_cost_usd": 0.30612,
                "input_tokens": 9,
                "output_tokens": 218,
            },
            "source": "claude",
            "timestamp": "2025-12-16T10:30:06Z",
        },
    ]


def run_demo(source: str) -> None:
    """运行单端 Demo。"""
    # 获取事件
    if source == "gemini":
        events = generate_gemini_events()
        title = "GeminiMCP Live Output"
    elif source == "codex":
        events = generate_codex_events()
        title = "CodexMCP Live Output"
    elif source == "claude":
        events = generate_claude_events()
        title = "ClaudeMCP Live Output"
    else:
        print(f"Unknown source: {source}")
        print("Usage: python demo_single_source.py [gemini|codex|claude]")
        return

    print(f"Starting {title} (Single Source Mode)")
    print("Events will be pushed with 0.5s interval...")

    # 创建查看器（单端模式）
    viewer = LiveViewer(
        title=title,
        multi_source_mode=False,  # 单端模式
    )

    # 启动事件推送线程
    def push_events():
        time.sleep(1)  # 等待窗口加载
        for event in events:
            viewer.push_event(event)
            time.sleep(0.5)
        print("All events pushed!")

    threading.Thread(target=push_events, daemon=True).start()

    # 启动查看器（阻塞）
    viewer.start(blocking=True)


def main():
    if len(sys.argv) < 2:
        source = "gemini"  # 默认
    else:
        source = sys.argv[1].lower()

    run_demo(source)


if __name__ == "__main__":
    main()
