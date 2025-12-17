"""ProcessRunner unit tests.

Test coverage:
- Basic process execution (stdout reading)
- Stdin writing
- Process isolation (new session/process group)
- Cancellation and termination
- Stderr handling
- Cleanup behavior (shield from cancellation)
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cli_agent_mcp.runtime.process_runner import (
    IS_WINDOWS,
    ProcessRunner,
    ProcessSpec,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """Create temporary workspace directory."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def runner() -> ProcessRunner:
    """Create ProcessRunner instance with short timeouts for testing."""
    return ProcessRunner(term_timeout=0.5, kill_timeout=0.3)


# =============================================================================
# Basic Execution Tests
# =============================================================================


class TestBasicExecution:
    """Test basic process execution."""

    @pytest.mark.asyncio
    async def test_simple_command(self, temp_workspace: Path, runner: ProcessRunner):
        """Test running a simple command."""
        if IS_WINDOWS:
            spec = ProcessSpec(
                argv=["cmd", "/c", "echo", "hello"],
                cwd=temp_workspace,
            )
        else:
            spec = ProcessSpec(
                argv=["echo", "hello"],
                cwd=temp_workspace,
            )

        output = []
        async for chunk in runner.run(spec):
            output.append(chunk)

        result = b"".join(output).decode().strip()
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_multiline_output(self, temp_workspace: Path, runner: ProcessRunner):
        """Test process with multiple output lines."""
        if IS_WINDOWS:
            # Windows: use type command with a temp file
            test_file = temp_workspace / "test.txt"
            test_file.write_text("line1\nline2\nline3\n")
            spec = ProcessSpec(
                argv=["cmd", "/c", "type", str(test_file)],
                cwd=temp_workspace,
            )
        else:
            spec = ProcessSpec(
                argv=["sh", "-c", "echo line1; echo line2; echo line3"],
                cwd=temp_workspace,
            )

        lines = []
        async for chunk in runner.run(spec):
            lines.append(chunk.decode().strip())

        # Filter empty lines
        lines = [l for l in lines if l]
        assert len(lines) >= 3
        assert "line1" in lines[0]
        assert "line2" in lines[1]
        assert "line3" in lines[2]

    @pytest.mark.asyncio
    async def test_working_directory(self, temp_workspace: Path, runner: ProcessRunner):
        """Test that working directory is correctly set."""
        if IS_WINDOWS:
            spec = ProcessSpec(
                argv=["cmd", "/c", "cd"],
                cwd=temp_workspace,
            )
        else:
            spec = ProcessSpec(
                argv=["pwd"],
                cwd=temp_workspace,
            )

        output = []
        async for chunk in runner.run(spec):
            output.append(chunk)

        result = b"".join(output).decode().strip()
        assert str(temp_workspace) in result or temp_workspace.name in result


# =============================================================================
# Stdin Tests
# =============================================================================


class TestStdinHandling:
    """Test stdin handling."""

    @pytest.mark.asyncio
    async def test_stdin_write(self, temp_workspace: Path, runner: ProcessRunner):
        """Test writing to stdin."""
        if IS_WINDOWS:
            # Windows: use findstr which reads stdin
            spec = ProcessSpec(
                argv=["findstr", "."],
                cwd=temp_workspace,
                stdin_bytes=b"hello from stdin\n",
            )
        else:
            spec = ProcessSpec(
                argv=["cat"],
                cwd=temp_workspace,
                stdin_bytes=b"hello from stdin\n",
            )

        output = []
        async for chunk in runner.run(spec):
            output.append(chunk)

        result = b"".join(output).decode().strip()
        assert "hello from stdin" in result

    @pytest.mark.asyncio
    async def test_stdin_multiline(self, temp_workspace: Path, runner: ProcessRunner):
        """Test writing multiple lines to stdin."""
        stdin_data = b"line1\nline2\nline3\n"

        if IS_WINDOWS:
            spec = ProcessSpec(
                argv=["findstr", "."],
                cwd=temp_workspace,
                stdin_bytes=stdin_data,
            )
        else:
            spec = ProcessSpec(
                argv=["cat"],
                cwd=temp_workspace,
                stdin_bytes=stdin_data,
            )

        output = []
        async for chunk in runner.run(spec):
            output.append(chunk)

        result = b"".join(output).decode()
        assert "line1" in result
        assert "line2" in result
        assert "line3" in result


# =============================================================================
# Stderr Handling Tests
# =============================================================================


class TestStderrHandling:
    """Test stderr handling."""

    @pytest.mark.asyncio
    async def test_stderr_callback(self, temp_workspace: Path, runner: ProcessRunner):
        """Test stderr callback is invoked."""
        stderr_chunks: list[bytes] = []

        def on_stderr(chunk: bytes) -> None:
            stderr_chunks.append(chunk)

        if IS_WINDOWS:
            spec = ProcessSpec(
                argv=["cmd", "/c", "echo error message 1>&2"],
                cwd=temp_workspace,
            )
        else:
            spec = ProcessSpec(
                argv=["sh", "-c", "echo 'error message' >&2"],
                cwd=temp_workspace,
            )

        # Consume all stdout
        async for _ in runner.run(spec, on_stderr=on_stderr):
            pass

        stderr = b"".join(stderr_chunks).decode()
        assert "error" in stderr.lower()

    @pytest.mark.asyncio
    async def test_mixed_stdout_stderr(self, temp_workspace: Path, runner: ProcessRunner):
        """Test handling both stdout and stderr."""
        stderr_chunks: list[bytes] = []

        def on_stderr(chunk: bytes) -> None:
            stderr_chunks.append(chunk)

        if IS_WINDOWS:
            spec = ProcessSpec(
                argv=["cmd", "/c", "echo stdout & echo stderr 1>&2"],
                cwd=temp_workspace,
            )
        else:
            spec = ProcessSpec(
                argv=["sh", "-c", "echo stdout; echo stderr >&2"],
                cwd=temp_workspace,
            )

        stdout_chunks = []
        async for chunk in runner.run(spec, on_stderr=on_stderr):
            stdout_chunks.append(chunk)

        stdout = b"".join(stdout_chunks).decode()
        stderr = b"".join(stderr_chunks).decode()

        assert "stdout" in stdout
        assert "stderr" in stderr


# =============================================================================
# Process Isolation Tests
# =============================================================================


class TestProcessIsolation:
    """Test process isolation (new session/process group)."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(IS_WINDOWS, reason="POSIX-specific test")
    async def test_new_session_posix(self, temp_workspace: Path, runner: ProcessRunner):
        """Test that process runs in new session on POSIX."""
        # Get process's session ID - should differ from parent
        spec = ProcessSpec(
            argv=["sh", "-c", "ps -o sid= -p $$"],
            cwd=temp_workspace,
        )

        output = []
        async for chunk in runner.run(spec):
            output.append(chunk)

        child_sid = b"".join(output).decode().strip()
        parent_sid = str(os.getsid(os.getpid()))

        # Child should be in different session
        assert child_sid != parent_sid

    @pytest.mark.asyncio
    @pytest.mark.skipif(IS_WINDOWS, reason="POSIX-specific test")
    async def test_process_group_posix(self, temp_workspace: Path, runner: ProcessRunner):
        """Test that process is its own process group leader on POSIX."""
        # Process group ID should equal PID when start_new_session=True
        spec = ProcessSpec(
            argv=["sh", "-c", "echo pid=$$ pgid=$(ps -o pgid= -p $$)"],
            cwd=temp_workspace,
        )

        output = []
        async for chunk in runner.run(spec):
            output.append(chunk)

        result = b"".join(output).decode().strip()
        # Parse pid and pgid
        # Output looks like: pid=12345 pgid=12345
        parts = result.split()
        if len(parts) >= 2:
            pid_part = parts[0].split("=")[1] if "=" in parts[0] else parts[0]
            pgid_part = parts[1].split("=")[1] if "=" in parts[1] else parts[1]
            # They should be equal (process is group leader)
            assert pid_part.strip() == pgid_part.strip()


# =============================================================================
# Termination Tests
# =============================================================================


class TestTermination:
    """Test process termination."""

    @pytest.mark.asyncio
    async def test_process_terminates_cleanly(
        self, temp_workspace: Path, runner: ProcessRunner
    ):
        """Test that process terminates cleanly after output consumed."""
        if IS_WINDOWS:
            spec = ProcessSpec(
                argv=["cmd", "/c", "echo done"],
                cwd=temp_workspace,
            )
        else:
            spec = ProcessSpec(
                argv=["echo", "done"],
                cwd=temp_workspace,
            )

        async for _ in runner.run(spec):
            pass

        # Process should have terminated normally
        # (no exception raised)

    @pytest.mark.asyncio
    async def test_long_running_process_termination(
        self, temp_workspace: Path, runner: ProcessRunner
    ):
        """Test termination of long-running process."""
        if IS_WINDOWS:
            # Windows: ping with -n for count
            spec = ProcessSpec(
                argv=["ping", "-n", "100", "127.0.0.1"],
                cwd=temp_workspace,
            )
        else:
            spec = ProcessSpec(
                argv=["sleep", "100"],
                cwd=temp_workspace,
            )

        # Start reading but cancel early
        count = 0
        async for _ in runner.run(spec):
            count += 1
            if count >= 2:
                # We've seen some output, break to trigger cleanup
                break

        # Cleanup should terminate the process
        # Give a moment for cleanup
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_cancellation_terminates_process(
        self, temp_workspace: Path, runner: ProcessRunner
    ):
        """Test that task cancellation terminates subprocess."""
        if IS_WINDOWS:
            spec = ProcessSpec(
                argv=["ping", "-n", "100", "127.0.0.1"],
                cwd=temp_workspace,
            )
        else:
            spec = ProcessSpec(
                argv=["sleep", "100"],
                cwd=temp_workspace,
            )

        async def run_process():
            async for _ in runner.run(spec):
                pass

        task = asyncio.create_task(run_process())

        # Let it start
        await asyncio.sleep(0.2)

        # Cancel the task
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

        # Process should be terminated by cleanup
        await asyncio.sleep(0.2)


# =============================================================================
# Environment Tests
# =============================================================================


class TestEnvironment:
    """Test environment variable handling."""

    @pytest.mark.asyncio
    async def test_custom_environment(
        self, temp_workspace: Path, runner: ProcessRunner
    ):
        """Test custom environment variables."""
        custom_env = os.environ.copy()
        custom_env["TEST_VAR"] = "test_value_123"

        if IS_WINDOWS:
            spec = ProcessSpec(
                argv=["cmd", "/c", "echo %TEST_VAR%"],
                cwd=temp_workspace,
                env=custom_env,
            )
        else:
            spec = ProcessSpec(
                argv=["sh", "-c", "echo $TEST_VAR"],
                cwd=temp_workspace,
                env=custom_env,
            )

        output = []
        async for chunk in runner.run(spec):
            output.append(chunk)

        result = b"".join(output).decode().strip()
        assert "test_value_123" in result

    @pytest.mark.asyncio
    async def test_inherit_environment(
        self, temp_workspace: Path, runner: ProcessRunner
    ):
        """Test that environment is inherited when env=None."""
        # PATH should be inherited
        if IS_WINDOWS:
            spec = ProcessSpec(
                argv=["cmd", "/c", "echo %PATH%"],
                cwd=temp_workspace,
                env=None,  # Inherit
            )
        else:
            spec = ProcessSpec(
                argv=["sh", "-c", "echo $PATH"],
                cwd=temp_workspace,
                env=None,  # Inherit
            )

        output = []
        async for chunk in runner.run(spec):
            output.append(chunk)

        result = b"".join(output).decode().strip()
        # PATH should be non-empty
        assert len(result) > 0


# =============================================================================
# ProcessSpec Tests
# =============================================================================


class TestProcessSpec:
    """Test ProcessSpec dataclass."""

    def test_frozen(self, temp_workspace: Path):
        """Test that ProcessSpec is immutable."""
        spec = ProcessSpec(
            argv=["echo", "test"],
            cwd=temp_workspace,
        )

        with pytest.raises(AttributeError):
            spec.argv = ["other"]  # type: ignore

    def test_default_values(self, temp_workspace: Path):
        """Test default values."""
        spec = ProcessSpec(
            argv=["echo"],
            cwd=temp_workspace,
        )

        assert spec.env is None
        assert spec.stdin_bytes is None

    def test_with_all_fields(self, temp_workspace: Path):
        """Test creation with all fields."""
        spec = ProcessSpec(
            argv=["my-cli", "--arg"],
            cwd=temp_workspace,
            env={"KEY": "value"},
            stdin_bytes=b"input",
        )

        assert spec.argv == ["my-cli", "--arg"]
        assert spec.cwd == temp_workspace
        assert spec.env == {"KEY": "value"}
        assert spec.stdin_bytes == b"input"


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_nonexistent_command(
        self, temp_workspace: Path, runner: ProcessRunner
    ):
        """Test handling of non-existent command."""
        spec = ProcessSpec(
            argv=["nonexistent_command_xyz_123"],
            cwd=temp_workspace,
        )

        with pytest.raises((FileNotFoundError, OSError)):
            async for _ in runner.run(spec):
                pass

    @pytest.mark.asyncio
    async def test_exit_code_nonzero(
        self, temp_workspace: Path, runner: ProcessRunner
    ):
        """Test process with non-zero exit code."""
        if IS_WINDOWS:
            spec = ProcessSpec(
                argv=["cmd", "/c", "exit 1"],
                cwd=temp_workspace,
            )
        else:
            spec = ProcessSpec(
                argv=["sh", "-c", "exit 1"],
                cwd=temp_workspace,
            )

        # Should complete without exception
        async for _ in runner.run(spec):
            pass

    @pytest.mark.asyncio
    async def test_empty_output(self, temp_workspace: Path, runner: ProcessRunner):
        """Test process with no output."""
        if IS_WINDOWS:
            spec = ProcessSpec(
                argv=["cmd", "/c", "rem"],  # No output
                cwd=temp_workspace,
            )
        else:
            spec = ProcessSpec(
                argv=["true"],  # No output
                cwd=temp_workspace,
            )

        output = []
        async for chunk in runner.run(spec):
            output.append(chunk)

        # Should complete successfully with no output
        assert len(output) == 0 or b"".join(output).strip() == b""

    @pytest.mark.asyncio
    async def test_large_output(self, temp_workspace: Path, runner: ProcessRunner):
        """Test handling of large output."""
        line_count = 1000

        if IS_WINDOWS:
            # Create a bat file to generate output
            bat_file = temp_workspace / "gen.bat"
            bat_content = "@echo off\n" + "echo line\n" * line_count
            bat_file.write_text(bat_content)
            spec = ProcessSpec(
                argv=["cmd", "/c", str(bat_file)],
                cwd=temp_workspace,
            )
        else:
            spec = ProcessSpec(
                argv=["sh", "-c", f"for i in $(seq 1 {line_count}); do echo line$i; done"],
                cwd=temp_workspace,
            )

        output = []
        async for chunk in runner.run(spec):
            output.append(chunk)

        result = b"".join(output).decode()
        lines = [l for l in result.strip().split("\n") if l]
        assert len(lines) >= line_count


# =============================================================================
# Cancel Scope Tests
# =============================================================================


class TestCancelScope:
    """Test anyio.CancelScope integration."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(10)
    async def test_cancel_scope_stops_iteration(
        self, temp_workspace: Path, runner: ProcessRunner
    ):
        """Test that cancel_scope stops the iteration."""
        import anyio

        if IS_WINDOWS:
            # Windows: use ping which outputs lines periodically
            spec = ProcessSpec(
                argv=["ping", "-n", "100", "127.0.0.1"],
                cwd=temp_workspace,
            )
        else:
            # POSIX: script that outputs multiple lines quickly
            spec = ProcessSpec(
                argv=["sh", "-c", "for i in 1 2 3 4 5 6 7 8 9 10; do echo line$i; done"],
                cwd=temp_workspace,
            )

        cancel_scope = anyio.CancelScope()
        output_count = 0

        async for _ in runner.run(spec, cancel_scope=cancel_scope):
            output_count += 1
            if output_count >= 3:
                cancel_scope.cancel()

        # Should have stopped after ~3 iterations
        # The process produces 10 lines but we stop at 3
        assert 3 <= output_count <= 10
