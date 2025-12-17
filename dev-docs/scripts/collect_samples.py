#!/usr/bin/env python3
"""CLI Output Collector - Collect CLI outputs for testing.

This script runs Codex and Gemini CLI with test prompts and saves
the JSON stream output as test samples.

Usage:
    python collect_samples.py [--codex-only | --gemini-only] [--prompt "custom prompt"]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Test prompts for different scenarios
TEST_PROMPTS = {
    "simple_greeting": "Say hello and introduce yourself briefly.",
    "code_analysis": "List the files in the current directory and describe what you see.",
    "file_read": "Read the README.md file if it exists, or list what files are available.",
}

# Output directory
SAMPLES_DIR = Path(__file__).parent.parent / "samples"


def run_codex(prompt: str, output_file: Path, timeout: int = 60) -> bool:
    """Run Codex CLI and capture JSON output.

    Args:
        prompt: The prompt to send to Codex
        output_file: Path to save the output
        timeout: Maximum execution time in seconds

    Returns:
        True if successful, False otherwise
    """
    cmd = [
        "codex", "exec",
        "--sandbox", "read-only",
        "--skip-git-repo-check",
        "--json",
        "--", prompt
    ]

    print(f"Running Codex: {' '.join(cmd[:6])}...")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=Path.cwd(),
        )

        # Save raw output
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # Parse and save JSON lines
        events = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line:
                try:
                    event = json.loads(line)
                    events.append(event)
                except json.JSONDecodeError:
                    events.append({"_raw": line})

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump({
                "cli": "codex",
                "prompt": prompt,
                "timestamp": datetime.now().isoformat(),
                "returncode": result.returncode,
                "events": events,
                "stderr": result.stderr,
            }, f, indent=2, ensure_ascii=False)

        print(f"  Saved {len(events)} events to {output_file}")
        return True

    except subprocess.TimeoutExpired:
        print(f"  Timeout after {timeout}s")
        return False
    except FileNotFoundError:
        print("  Codex CLI not found")
        return False
    except Exception as e:
        print(f"  Error: {e}")
        return False


def run_gemini(prompt: str, output_file: Path, timeout: int = 60) -> bool:
    """Run Gemini CLI and capture JSON stream output.

    Args:
        prompt: The prompt to send to Gemini
        output_file: Path to save the output
        timeout: Maximum execution time in seconds

    Returns:
        True if successful, False otherwise
    """
    cmd = [
        "gemini",
        "-o", "stream-json",
        prompt
    ]

    print(f"Running Gemini: {' '.join(cmd[:3])}...")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=Path.cwd(),
        )

        # Save raw output
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # Parse and save JSON lines
        events = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line:
                try:
                    event = json.loads(line)
                    events.append(event)
                except json.JSONDecodeError:
                    events.append({"_raw": line})

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump({
                "cli": "gemini",
                "prompt": prompt,
                "timestamp": datetime.now().isoformat(),
                "returncode": result.returncode,
                "events": events,
                "stderr": result.stderr,
            }, f, indent=2, ensure_ascii=False)

        print(f"  Saved {len(events)} events to {output_file}")
        return True

    except subprocess.TimeoutExpired:
        print(f"  Timeout after {timeout}s")
        return False
    except FileNotFoundError:
        print("  Gemini CLI not found")
        return False
    except Exception as e:
        print(f"  Error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Collect CLI output samples")
    parser.add_argument("--codex-only", action="store_true", help="Only run Codex CLI")
    parser.add_argument("--gemini-only", action="store_true", help="Only run Gemini CLI")
    parser.add_argument("--prompt", type=str, help="Custom prompt to use")
    parser.add_argument("--timeout", type=int, default=120, help="Timeout in seconds")
    parser.add_argument("--scenario", type=str, choices=list(TEST_PROMPTS.keys()),
                        help="Use a predefined test scenario")
    args = parser.parse_args()

    # Determine which CLIs to run
    run_codex_cli = not args.gemini_only
    run_gemini_cli = not args.codex_only

    # Determine prompt
    if args.prompt:
        prompts = {"custom": args.prompt}
    elif args.scenario:
        prompts = {args.scenario: TEST_PROMPTS[args.scenario]}
    else:
        prompts = TEST_PROMPTS

    print(f"Output directory: {SAMPLES_DIR}")
    print(f"Running: {'Codex' if run_codex_cli else ''} {'Gemini' if run_gemini_cli else ''}")
    print()

    # Run tests
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for scenario_name, prompt in prompts.items():
        print(f"\n=== Scenario: {scenario_name} ===")
        print(f"Prompt: {prompt[:50]}..." if len(prompt) > 50 else f"Prompt: {prompt}")

        if run_codex_cli:
            output_file = SAMPLES_DIR / "codex" / f"{scenario_name}_{timestamp}.json"
            run_codex(prompt, output_file, timeout=args.timeout)

        if run_gemini_cli:
            output_file = SAMPLES_DIR / "gemini" / f"{scenario_name}_{timestamp}.json"
            run_gemini(prompt, output_file, timeout=args.timeout)

    print("\n=== Collection complete ===")
    print(f"Samples saved to: {SAMPLES_DIR}")


if __name__ == "__main__":
    main()
