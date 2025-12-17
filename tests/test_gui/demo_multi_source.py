#!/usr/bin/env python3
"""多端混合 GUI 测试 Demo。

测试 shared/gui 模块在多端模式下的表现：
- 显示来源标签 [GEMINI] [CODEX] [CLAUDE]
- 侧边栏按来源分组
- 混合事件流按时间排序

这模拟 cli-agent-mcp 的最密集使用场景。

Usage:
    python tests/gui/demo_multi_source.py
"""

from __future__ import annotations

import random
import sys
import threading
import time
from pathlib import Path

# 添加 shared 到路径
SHARED_DIR = Path(__file__).parent.parent.parent / "shared"
sys.path.insert(0, str(SHARED_DIR))

from gui import LiveViewer


def generate_mixed_events() -> list[dict]:
    """生成混合多端事件流。

    模拟并发场景：多个 session 交错产生事件。
    """
    gemini_session = "gemini-abc12345"
    codex_session = "019b25ad-271b-7d93"
    claude_session = "claude-xyz78901"

    events = [
        # === 各端会话开始 ===
        {
            "category": "lifecycle",
            "lifecycle_type": "session_start",
            "session_id": gemini_session,
            "model": "gemini-2.0-flash",
            "source": "gemini",
            "timestamp": "2025-12-16T10:30:00.000Z",
        },
        {
            "category": "lifecycle",
            "lifecycle_type": "session_start",
            "session_id": codex_session,
            "source": "codex",
            "timestamp": "2025-12-16T10:30:00.100Z",
        },
        {
            "category": "lifecycle",
            "lifecycle_type": "session_start",
            "session_id": claude_session,
            "model": "claude-opus-4-5-20251101",
            "source": "claude",
            "timestamp": "2025-12-16T10:30:00.200Z",
        },

        # === 用户输入（各端） ===
        {
            "category": "message",
            "content_type": "text",
            "role": "user",
            "text": "[Gemini] Write a fibonacci function",
            "source": "gemini",
            "session_id": gemini_session,
            "timestamp": "2025-12-16T10:30:01.000Z",
        },
        {
            "category": "message",
            "content_type": "text",
            "role": "user",
            "text": "[Codex] List all Python files in the project",
            "source": "codex",
            "session_id": codex_session,
            "timestamp": "2025-12-16T10:30:01.100Z",
        },
        {
            "category": "message",
            "content_type": "text",
            "role": "user",
            "text": "[Claude] Explain the codebase architecture",
            "source": "claude",
            "session_id": claude_session,
            "timestamp": "2025-12-16T10:30:01.200Z",
        },

        # === 思考过程交错 ===
        {
            "category": "message",
            "content_type": "reasoning",
            "role": "assistant",
            "text": "**Analyzing fibonacci requirements**\nI need to implement an efficient fibonacci function...",
            "source": "codex",
            "session_id": codex_session,
            "timestamp": "2025-12-16T10:30:02.000Z",
        },
        {
            "category": "message",
            "content_type": "reasoning",
            "role": "assistant",
            "text": "Let me think about the codebase structure first...",
            "source": "claude",
            "session_id": claude_session,
            "timestamp": "2025-12-16T10:30:02.100Z",
        },

        # === 工具调用交错 ===
        {
            "category": "operation",
            "operation_type": "file",
            "name": "write_file",
            "operation_id": "gemini-tool-001",
            "status": "running",
            "input": '{"path": "fib.py"}',
            "source": "gemini",
            "session_id": gemini_session,
            "timestamp": "2025-12-16T10:30:03.000Z",
        },
        {
            "category": "operation",
            "operation_type": "command",
            "name": "shell",
            "operation_id": "codex-cmd-001",
            "status": "running",
            "input": "find . -name '*.py'",
            "source": "codex",
            "session_id": codex_session,
            "timestamp": "2025-12-16T10:30:03.100Z",
        },
        {
            "category": "operation",
            "operation_type": "tool",
            "name": "Read",
            "operation_id": "claude-toolu-001",
            "status": "running",
            "input": '{"file_path": "/src/main.py"}',
            "source": "claude",
            "session_id": claude_session,
            "timestamp": "2025-12-16T10:30:03.200Z",
        },

        # === 工具结果交错 ===
        {
            "category": "operation",
            "operation_type": "file",
            "name": "write_file",
            "operation_id": "gemini-tool-001",
            "status": "success",
            "output": "File written: fib.py",
            "source": "gemini",
            "session_id": gemini_session,
            "timestamp": "2025-12-16T10:30:04.000Z",
        },
        {
            "category": "operation",
            "operation_type": "command",
            "name": "shell",
            "operation_id": "codex-cmd-001",
            "status": "success",
            "output": "./src/main.py\n./src/utils.py\n./tests/test_main.py",
            "metadata": {"exit_code": 0},
            "source": "codex",
            "session_id": codex_session,
            "timestamp": "2025-12-16T10:30:04.100Z",
        },
        {
            "category": "operation",
            "operation_type": "tool",
            "name": "Read",
            "operation_id": "claude-toolu-001",
            "status": "success",
            "output": "def main():\n    print('Hello World')\n\nif __name__ == '__main__':\n    main()",
            "source": "claude",
            "session_id": claude_session,
            "timestamp": "2025-12-16T10:30:04.200Z",
        },

        # === 助手回复交错 ===
        {
            "category": "message",
            "content_type": "text",
            "role": "assistant",
            "text": "I've created the fibonacci function in fib.py with memoization.",
            "source": "gemini",
            "session_id": gemini_session,
            "timestamp": "2025-12-16T10:30:05.000Z",
        },
        {
            "category": "message",
            "content_type": "text",
            "role": "assistant",
            "text": "Found 3 Python files in the project:\n- src/main.py\n- src/utils.py\n- tests/test_main.py",
            "source": "codex",
            "session_id": codex_session,
            "timestamp": "2025-12-16T10:30:05.100Z",
        },
        {
            "category": "message",
            "content_type": "text",
            "role": "assistant",
            "text": "The codebase has a simple structure with a main entry point in src/main.py.",
            "source": "claude",
            "session_id": claude_session,
            "timestamp": "2025-12-16T10:30:05.200Z",
        },

        # === MCP 调用示例 ===
        {
            "category": "operation",
            "operation_type": "mcp",
            "name": "mcp__tavily__search",
            "operation_id": "claude-mcp-001",
            "status": "running",
            "input": '{"query": "Python best practices"}',
            "source": "claude",
            "session_id": claude_session,
            "timestamp": "2025-12-16T10:30:06.000Z",
        },
        {
            "category": "operation",
            "operation_type": "mcp",
            "name": "mcp__tavily__search",
            "operation_id": "claude-mcp-001",
            "status": "success",
            "output": "Found 10 results about Python best practices...",
            "source": "claude",
            "session_id": claude_session,
            "timestamp": "2025-12-16T10:30:07.000Z",
        },

        # === 会话结束 ===
        {
            "category": "lifecycle",
            "lifecycle_type": "session_end",
            "session_id": gemini_session,
            "status": "success",
            "stats": {
                "total_tokens": 250,
                "duration_ms": 7000,
                "tool_calls": 1,
            },
            "source": "gemini",
            "timestamp": "2025-12-16T10:30:08.000Z",
        },
        {
            "category": "lifecycle",
            "lifecycle_type": "turn_end",
            "session_id": codex_session,
            "status": "success",
            "stats": {
                "input_tokens": 150,
                "output_tokens": 200,
            },
            "source": "codex",
            "timestamp": "2025-12-16T10:30:08.100Z",
        },
        {
            "category": "lifecycle",
            "lifecycle_type": "session_end",
            "session_id": claude_session,
            "status": "success",
            "stats": {
                "duration_ms": 8200,
                "total_cost_usd": 0.30612,
                "input_tokens": 500,
                "output_tokens": 300,
            },
            "source": "claude",
            "timestamp": "2025-12-16T10:30:08.200Z",
        },
    ]

    return events


def generate_stress_test_events(count: int = 50) -> list[dict]:
    """生成压力测试事件。

    模拟高频事件流（用于测试性能和滚动）。
    """
    sources = ["gemini", "codex", "claude"]
    sessions = {
        "gemini": "stress-gemini-001",
        "codex": "stress-codex-001",
        "claude": "stress-claude-001",
    }

    events = []

    # 会话开始
    for src in sources:
        events.append({
            "category": "lifecycle",
            "lifecycle_type": "session_start",
            "session_id": sessions[src],
            "source": src,
        })

    # 随机事件
    for i in range(count):
        src = random.choice(sources)
        event_type = random.choice(["message", "operation"])

        if event_type == "message":
            events.append({
                "category": "message",
                "content_type": random.choice(["text", "reasoning"]),
                "role": "assistant",
                "text": f"[{src.upper()}] Event #{i}: " + "Sample text. " * random.randint(1, 5),
                "source": src,
                "session_id": sessions[src],
            })
        else:
            op_type = random.choice(["command", "file", "tool", "mcp"])
            events.append({
                "category": "operation",
                "operation_type": op_type,
                "name": f"{op_type}_operation",
                "operation_id": f"op-{i}",
                "status": random.choice(["running", "success", "success", "success"]),
                "input": f"input for {op_type}",
                "output": f"output #{i}" if random.random() > 0.3 else "",
                "source": src,
                "session_id": sessions[src],
            })

    return events


def run_demo(stress_test: bool = False) -> None:
    """运行多端 Demo。"""
    print("Starting CLI Agent Live Output (Multi Source Mode)")
    print("Features:")
    print("  - Source labels: [GEMINI] [CODEX] [CLAUDE]")
    print("  - Sidebar: Sessions grouped by source")
    print("  - Mixed event stream")
    print()

    if stress_test:
        events = generate_stress_test_events(100)
        print("Running stress test with 100 random events...")
        interval = 0.05
    else:
        events = generate_mixed_events()
        print("Pushing mixed events with 0.3s interval...")
        interval = 0.3

    # 创建查看器（多端模式）
    viewer = LiveViewer(
        title="CLI Agent Live Output",
        multi_source_mode=True,  # 多端模式！
    )

    # 启动事件推送线程
    def push_events():
        time.sleep(1)  # 等待窗口加载
        for event in events:
            viewer.push_event(event)
            time.sleep(interval)
        print(f"All {len(events)} events pushed!")

    threading.Thread(target=push_events, daemon=True).start()

    # 启动查看器（阻塞）
    viewer.start(blocking=True)


def main():
    stress_test = "--stress" in sys.argv or "-s" in sys.argv
    run_demo(stress_test=stress_test)


if __name__ == "__main__":
    main()
