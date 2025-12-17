#!/usr/bin/env python3
"""Fake CLI for integration testing.

This script simulates a long-running CLI agent that outputs JSONL events.
It properly responds to SIGINT/SIGTERM signals and exits gracefully.

Usage:
    python fake_cli.py [--duration SECONDS] [--interval SECONDS] [--fail] [--exit-code CODE]

Arguments:
    --duration: Total duration to run (default: 10 seconds)
    --interval: Interval between events (default: 0.5 seconds)
    --fail: Exit with non-zero code
    --exit-code: Specific exit code (default: 0, or 1 if --fail)

The script reads a prompt from stdin and outputs JSONL events to stdout.

Event format (compatible with Codex/Gemini/Claude parsers):
    {"type": "message", "role": "assistant", "content": "...", "session_id": "..."}
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from typing import NoReturn

# Flag to indicate if we should stop
_should_stop = False
_exit_code = 0


def signal_handler(signum: int, frame) -> None:
    """Handle SIGINT/SIGTERM signals."""
    global _should_stop, _exit_code
    signal_name = signal.Signals(signum).name
    # Output a system event indicating cancellation
    emit_event({
        "type": "system",
        "subtype": "cancelled",
        "message": f"Received {signal_name}, stopping gracefully",
        "severity": "warning",
    })
    _should_stop = True
    # Exit code 130 for SIGINT (128 + 2), 143 for SIGTERM (128 + 15)
    _exit_code = 128 + signum


def emit_event(data: dict) -> None:
    """Emit a JSONL event to stdout."""
    print(json.dumps(data, ensure_ascii=False), flush=True)


def main() -> NoReturn:
    """Main entry point."""
    global _exit_code

    parser = argparse.ArgumentParser(description="Fake CLI for testing")
    parser.add_argument("--duration", type=float, default=10.0, help="Duration in seconds")
    parser.add_argument("--interval", type=float, default=0.5, help="Interval between events")
    parser.add_argument("--fail", action="store_true", help="Exit with error")
    parser.add_argument("--exit-code", type=int, default=None, help="Specific exit code")
    parser.add_argument("--session-id", type=str, default="fake-session-123", help="Session ID")
    # Accept any positional arguments (for compatibility with CLI patterns)
    parser.add_argument("args", nargs="*", help="Additional arguments")

    args = parser.parse_args()

    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Read prompt from stdin (non-blocking for testing)
    prompt = ""
    if not sys.stdin.isatty():
        try:
            # Set a timeout for stdin read to avoid hanging
            import select
            if select.select([sys.stdin], [], [], 0.1)[0]:
                prompt = sys.stdin.read().strip()
        except Exception:
            pass

    # Emit session start event
    emit_event({
        "type": "session",
        "session_id": args.session_id,
        "status": "started",
    })

    # Emit initial system info
    emit_event({
        "type": "system",
        "subtype": "info",
        "message": f"Processing prompt: {prompt[:50]}..." if len(prompt) > 50 else f"Processing prompt: {prompt}",
        "model": "fake-model-1.0",
    })

    # Simulate long-running operation with periodic events
    start_time = time.time()
    event_count = 0
    total_response = ""

    while not _should_stop:
        elapsed = time.time() - start_time
        if elapsed >= args.duration:
            break

        # Emit progress events
        event_count += 1
        chunk = f"Processing step {event_count}... "
        total_response += chunk

        emit_event({
            "type": "message",
            "role": "assistant",
            "content": chunk,
            "is_delta": True,
            "session_id": args.session_id,
        })

        time.sleep(args.interval)

    # If not cancelled, emit final response
    if not _should_stop:
        final_message = f"Task completed successfully. Processed {event_count} steps."
        emit_event({
            "type": "message",
            "role": "assistant",
            "content": final_message,
            "is_delta": False,
            "session_id": args.session_id,
        })

        # Emit stats
        emit_event({
            "type": "stats",
            "stats": {
                "input_tokens": 100,
                "output_tokens": 200,
                "total_input_tokens": 100,
                "total_output_tokens": 200,
            },
            "model": "fake-model-1.0",
        })

        # Emit session end
        emit_event({
            "type": "session",
            "session_id": args.session_id,
            "status": "completed",
        })

    # Determine exit code
    if args.exit_code is not None:
        _exit_code = args.exit_code
    elif args.fail:
        _exit_code = 1

    sys.exit(_exit_code)


if __name__ == "__main__":
    main()
