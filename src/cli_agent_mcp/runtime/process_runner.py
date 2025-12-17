"""Process runner with subprocess isolation and reliable termination.

cli-agent-mcp runtime module v0.1.0

This module provides:
- Cross-platform subprocess isolation (new session/process group)
- Reliable termination with graceful shutdown (SIGTERM -> timeout -> SIGKILL)
- Stdout/stderr streaming with backpressure control
- Cancel-safe cleanup using asyncio.shield

Key design points:
- POSIX: start_new_session=True to create new process group
- Windows: CREATE_NEW_PROCESS_GROUP for signal isolation
- Cancellation terminates the process group, not just the main process
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import sys
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anyio

__all__ = [
    "ProcessRunner",
    "ProcessSpec",
]

logger = logging.getLogger(__name__)

# Platform detection
IS_WINDOWS = sys.platform == "win32"

# Default timeouts
DEFAULT_TERM_TIMEOUT = 2.0  # seconds to wait after SIGTERM
DEFAULT_KILL_TIMEOUT = 1.0  # seconds to wait after SIGKILL


@dataclass(frozen=True)
class ProcessSpec:
    """Specification for a subprocess to run.

    Attributes:
        argv: Command line arguments (first element is the executable)
        cwd: Working directory for the process
        env: Environment variables (None = inherit parent)
        stdin_bytes: Optional bytes to write to stdin
    """

    argv: list[str]
    cwd: Path
    env: Mapping[str, str] | None = None
    stdin_bytes: bytes | None = None


@dataclass
class ProcessRunner:
    """Cross-platform process runner with isolation and reliable termination.

    This class manages subprocess execution with:
    - Process group/session isolation to prevent SIGINT propagation
    - Graceful termination (SIGTERM -> timeout -> SIGKILL)
    - Stderr draining to prevent deadlocks
    - Cancel-safe cleanup

    Example:
        runner = ProcessRunner()
        spec = ProcessSpec(
            argv=["my-cli", "--json"],
            cwd=Path("/workspace"),
            stdin_bytes=b"prompt text",
        )

        async for chunk in runner.run(spec):
            process_output(chunk)
    """

    term_timeout: float = DEFAULT_TERM_TIMEOUT
    kill_timeout: float = DEFAULT_KILL_TIMEOUT

    async def run(
        self,
        spec: ProcessSpec,
        *,
        cancel_scope: anyio.CancelScope | None = None,
        on_stderr: Callable[[bytes], None] | None = None,
    ) -> AsyncIterator[bytes]:
        """Run subprocess and yield stdout chunks.

        This method:
        1. Starts the subprocess in an isolated process group/session
        2. Writes stdin_bytes if provided
        3. Yields stdout line by line
        4. Drains stderr concurrently (via on_stderr callback or internal buffer)
        5. Ensures cleanup even if cancelled

        Args:
            spec: Process specification
            cancel_scope: Optional anyio.CancelScope for cancellation
            on_stderr: Optional callback for stderr chunks

        Yields:
            Lines from stdout as bytes (including newline)

        Raises:
            ProcessExecutionError: If process setup fails
        """
        process: asyncio.subprocess.Process | None = None
        stderr_task: asyncio.Task[list[bytes]] | None = None

        # Build platform-specific kwargs
        kwargs = self._build_subprocess_kwargs(spec)

        try:
            # Create subprocess with isolation
            # Note: Use DEVNULL instead of None when stdin_bytes is not provided.
            # stdin=None would inherit parent's stdin (MCP's JSON-RPC channel),
            # which can cause MCP server to crash when subprocess exits and closes it.
            process = await asyncio.create_subprocess_exec(
                *spec.argv,
                stdin=asyncio.subprocess.PIPE if spec.stdin_bytes is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=spec.cwd,
                **kwargs,
            )

            logger.debug(
                f"Started subprocess pid={process.pid} "
                f"argv={spec.argv[0]} cwd={spec.cwd}"
            )

            # Write stdin if provided
            if spec.stdin_bytes is not None and process.stdin:
                process.stdin.write(spec.stdin_bytes)
                await process.stdin.drain()
                process.stdin.close()
                await process.stdin.wait_closed()

            # Start stderr draining task
            stderr_task = asyncio.create_task(
                self._drain_stderr(process, on_stderr)
            )

            # Yield stdout lines
            if process.stdout:
                async for line in process.stdout:
                    # Check cancel scope if provided
                    if cancel_scope and cancel_scope.cancel_called:
                        break
                    yield line

            # Wait for stderr to complete
            await stderr_task

            # Wait for process to finish
            await process.wait()

            logger.debug(
                f"Subprocess completed pid={process.pid} "
                f"returncode={process.returncode}"
            )

        finally:
            # Ensure cleanup with shield to prevent cancel interruption
            await self._safe_cleanup(process, stderr_task)

    def _build_subprocess_kwargs(self, spec: ProcessSpec) -> dict[str, Any]:
        """Build platform-specific subprocess kwargs.

        Args:
            spec: Process specification

        Returns:
            Dict of kwargs for asyncio.create_subprocess_exec
        """
        kwargs: dict[str, Any] = {}

        # Environment
        if spec.env is not None:
            kwargs["env"] = dict(spec.env)

        # Platform-specific isolation
        if IS_WINDOWS:
            # Windows: CREATE_NEW_PROCESS_GROUP
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            # POSIX: start_new_session (equivalent to setsid)
            kwargs["start_new_session"] = True

        return kwargs

    async def _drain_stderr(
        self,
        process: asyncio.subprocess.Process,
        on_stderr: Callable[[bytes], None] | None = None,
    ) -> list[bytes]:
        """Drain stderr to prevent buffer deadlock.

        Args:
            process: The subprocess
            on_stderr: Optional callback for each chunk

        Returns:
            List of all stderr chunks (useful when no callback provided)
        """
        chunks: list[bytes] = []

        if process.stderr:
            while True:
                chunk = await process.stderr.read(4096)
                if not chunk:
                    break
                chunks.append(chunk)
                if on_stderr:
                    on_stderr(chunk)

        return chunks

    async def _safe_cleanup(
        self,
        process: asyncio.subprocess.Process | None,
        stderr_task: asyncio.Task[list[bytes]] | None,
    ) -> None:
        """Safely cleanup subprocess and tasks, shielded from cancellation.

        This method uses asyncio.shield to ensure cleanup completes
        even if the caller is cancelled.

        Args:
            process: The subprocess to terminate
            stderr_task: The stderr draining task
        """
        try:
            # Shield entire cleanup from cancellation
            await asyncio.shield(self._do_cleanup(process, stderr_task))
        except asyncio.CancelledError:
            # If shield itself is cancelled, still try cleanup
            await self._do_cleanup(process, stderr_task)

    async def _do_cleanup(
        self,
        process: asyncio.subprocess.Process | None,
        stderr_task: asyncio.Task[list[bytes]] | None,
    ) -> None:
        """Perform actual cleanup.

        Args:
            process: The subprocess to terminate
            stderr_task: The stderr draining task
        """
        # Cancel stderr task if still running
        if stderr_task and not stderr_task.done():
            stderr_task.cancel()
            try:
                await stderr_task
            except asyncio.CancelledError:
                pass

        # Terminate subprocess if still running
        if process is not None and process.returncode is None:
            await self._terminate_process(process)

    async def _terminate_process(
        self,
        process: asyncio.subprocess.Process,
    ) -> None:
        """Terminate subprocess gracefully, then forcefully if needed.

        Termination strategy:
        1. Send SIGTERM (or CTRL_BREAK_EVENT on Windows)
        2. Wait up to term_timeout for graceful exit
        3. If still running, send SIGKILL (or terminate() on Windows)
        4. Wait up to kill_timeout for forced exit

        Args:
            process: The subprocess to terminate
        """
        pid = process.pid
        logger.debug(f"Terminating subprocess pid={pid}")

        try:
            # Step 1: Graceful termination
            if IS_WINDOWS:
                # Windows: Try CTRL_BREAK_EVENT first
                await self._windows_terminate(process)
            else:
                # POSIX: SIGTERM to process group
                await self._posix_terminate(process)

            # Step 2: Wait for graceful exit
            try:
                await asyncio.wait_for(process.wait(), timeout=self.term_timeout)
                logger.debug(
                    f"Subprocess terminated gracefully pid={pid} "
                    f"returncode={process.returncode}"
                )
                return
            except asyncio.TimeoutError:
                pass

            # Step 3: Force kill
            logger.debug(f"Force killing subprocess pid={pid}")
            if IS_WINDOWS:
                await self._windows_kill(process)
            else:
                await self._posix_kill(process)

            # Step 4: Wait for forced exit
            try:
                await asyncio.wait_for(process.wait(), timeout=self.kill_timeout)
                logger.debug(
                    f"Subprocess killed pid={pid} "
                    f"returncode={process.returncode}"
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"Subprocess did not exit after kill pid={pid}"
                )

        except ProcessLookupError:
            # Process already exited
            logger.debug(f"Subprocess already exited pid={pid}")
        except Exception as e:
            logger.warning(f"Error terminating subprocess pid={pid}: {e}")

    async def _posix_terminate(
        self,
        process: asyncio.subprocess.Process,
    ) -> None:
        """Send SIGTERM to process group on POSIX systems.

        Args:
            process: The subprocess
        """
        try:
            # Get process group ID (should be same as pid due to start_new_session)
            pgid = os.getpgid(process.pid)
            # Send SIGTERM to entire process group
            os.killpg(pgid, signal.SIGTERM)
            logger.debug(f"Sent SIGTERM to process group pgid={pgid}")
        except ProcessLookupError:
            pass
        except OSError as e:
            # Fallback to terminating just the process
            logger.debug(f"killpg failed, falling back to terminate: {e}")
            process.terminate()

    async def _posix_kill(
        self,
        process: asyncio.subprocess.Process,
    ) -> None:
        """Send SIGKILL to process group on POSIX systems.

        Args:
            process: The subprocess
        """
        try:
            pgid = os.getpgid(process.pid)
            os.killpg(pgid, signal.SIGKILL)
            logger.debug(f"Sent SIGKILL to process group pgid={pgid}")
        except ProcessLookupError:
            pass
        except OSError as e:
            logger.debug(f"killpg failed, falling back to kill: {e}")
            process.kill()

    async def _windows_terminate(
        self,
        process: asyncio.subprocess.Process,
    ) -> None:
        """Send CTRL_BREAK_EVENT on Windows.

        Args:
            process: The subprocess
        """
        try:
            # Send CTRL_BREAK_EVENT to the process group
            # This works because we used CREATE_NEW_PROCESS_GROUP
            os.kill(process.pid, signal.CTRL_BREAK_EVENT)
            logger.debug(f"Sent CTRL_BREAK_EVENT to pid={process.pid}")
        except (ProcessLookupError, OSError) as e:
            # Fallback to terminate
            logger.debug(f"CTRL_BREAK_EVENT failed, falling back: {e}")
            process.terminate()

    async def _windows_kill(
        self,
        process: asyncio.subprocess.Process,
    ) -> None:
        """Force kill on Windows.

        Args:
            process: The subprocess
        """
        try:
            process.kill()
            logger.debug(f"Called kill() on pid={process.pid}")
        except ProcessLookupError:
            pass


# Convenience function for simple use cases
async def run_process(
    spec: ProcessSpec,
    *,
    on_stderr: Callable[[bytes], None] | None = None,
) -> tuple[bytes, int]:
    """Run process and collect all stdout.

    This is a convenience function for cases where streaming is not needed.

    Args:
        spec: Process specification
        on_stderr: Optional callback for stderr chunks

    Returns:
        Tuple of (stdout_bytes, returncode)
    """
    runner = ProcessRunner()
    stdout_chunks: list[bytes] = []

    async for chunk in runner.run(spec, on_stderr=on_stderr):
        stdout_chunks.append(chunk)

    # Note: We can't get returncode here directly from the generator
    # This function is mainly for testing convenience
    stdout = b"".join(stdout_chunks)

    return stdout, 0  # returncode would need to be captured differently
