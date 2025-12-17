#!/usr/bin/env python3
"""Claude CLI Output Collector - 收集 Claude Code CLI 输出样本。

使用方式:
    python collect_claude_samples.py [--prompt "custom prompt"]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 输出目录
SAMPLES_DIR = Path(__file__).parent / "samples" / "claude"

# 测试 prompts
TEST_PROMPTS = {
    "simple_greeting": "Say hello and introduce yourself briefly. Do not use any tools.",
    "list_files": "List the files in the current directory using the Bash tool.",
}


def run_claude(prompt: str, output_file: Path, timeout: int = 120) -> bool:
    """运行 Claude CLI 并捕获 JSON 输出。

    Args:
        prompt: 发送给 Claude 的 prompt
        output_file: 保存输出的路径
        timeout: 最大执行时间（秒）

    Returns:
        成功返回 True，否则 False
    """
    cmd = [
        "claude",
        "-p",
        prompt,
        "--output-format", "stream-json",
        "--verbose",  # Required for stream-json
        "--allowedTools", "Bash,Read",
        "--max-turns", "3",
    ]

    print(f"Running Claude: claude -p \"{prompt[:40]}...\"")
    print(f"  Full command: {' '.join(cmd[:6])}...")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=Path.cwd(),
        )

        # 创建输出目录
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # 解析 JSON lines
        events = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line:
                try:
                    event = json.loads(line)
                    events.append(event)
                except json.JSONDecodeError:
                    events.append({"_raw": line})

        # 保存
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump({
                "cli": "claude",
                "prompt": prompt,
                "timestamp": datetime.now().isoformat(),
                "returncode": result.returncode,
                "events": events,
                "stderr": result.stderr,
            }, f, indent=2, ensure_ascii=False)

        print(f"  Saved {len(events)} events to {output_file}")
        print(f"  Return code: {result.returncode}")
        if result.stderr:
            print(f"  Stderr: {result.stderr[:200]}...")
        return True

    except subprocess.TimeoutExpired:
        print(f"  Timeout after {timeout}s")
        return False
    except FileNotFoundError:
        print("  Claude CLI not found (is it installed?)")
        return False
    except Exception as e:
        print(f"  Error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Collect Claude CLI output samples")
    parser.add_argument("--prompt", type=str, help="Custom prompt to use")
    parser.add_argument("--scenario", type=str, choices=list(TEST_PROMPTS.keys()),
                        help="Use a predefined test scenario")
    parser.add_argument("--timeout", type=int, default=120, help="Timeout in seconds")
    args = parser.parse_args()

    # 确定 prompt
    if args.prompt:
        prompts = {"custom": args.prompt}
    elif args.scenario:
        prompts = {args.scenario: TEST_PROMPTS[args.scenario]}
    else:
        prompts = TEST_PROMPTS

    print(f"Output directory: {SAMPLES_DIR}")
    print()

    # 运行测试
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for scenario_name, prompt in prompts.items():
        print(f"\n=== Scenario: {scenario_name} ===")
        print(f"Prompt: {prompt[:60]}..." if len(prompt) > 60 else f"Prompt: {prompt}")

        output_file = SAMPLES_DIR / f"{scenario_name}_{timestamp}.json"
        run_claude(prompt, output_file, timeout=args.timeout)

    print("\n=== Collection complete ===")
    print(f"Samples saved to: {SAMPLES_DIR}")


if __name__ == "__main__":
    main()
