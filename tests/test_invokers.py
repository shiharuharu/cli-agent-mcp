"""CLI 调用器模块测试。

测试覆盖：
- 类型定义和参数转换
- 命令行构建
- 参数验证
- 工厂函数
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cli_agent_mcp.shared.invokers import (
    CLIType,
    ClaudeInvoker,
    ClaudeParams,
    CodexInvoker,
    CodexParams,
    CommonParams,
    ExecutionResult,
    GeminiInvoker,
    GeminiParams,
    GUIMetadata,
    Permission,
    PERMISSION_MAP_CLAUDE,
    PERMISSION_MAP_CODEX,
    create_invoker,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """创建临时工作目录。"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def temp_image(tmp_path: Path) -> Path:
    """创建临时图片文件。"""
    img = tmp_path / "test.png"
    img.write_bytes(b"fake image data")
    return img


# =============================================================================
# 类型定义测试
# =============================================================================


class TestPermission:
    """Permission 枚举测试。"""

    def test_permission_values(self):
        """测试权限枚举值。"""
        assert Permission.READ_ONLY.value == "read-only"
        assert Permission.WORKSPACE_WRITE.value == "workspace-write"
        assert Permission.UNLIMITED.value == "unlimited"

    def test_permission_from_string(self):
        """测试从字符串创建权限。"""
        assert Permission("read-only") == Permission.READ_ONLY
        assert Permission("workspace-write") == Permission.WORKSPACE_WRITE
        assert Permission("unlimited") == Permission.UNLIMITED


class TestCLIType:
    """CLIType 枚举测试。"""

    def test_cli_type_values(self):
        """测试 CLI 类型枚举值。"""
        assert CLIType.CODEX.value == "codex"
        assert CLIType.GEMINI.value == "gemini"
        assert CLIType.CLAUDE.value == "claude"


class TestPermissionMaps:
    """Permission 映射表测试。"""

    def test_codex_permission_map(self):
        """测试 Codex permission 映射。"""
        assert PERMISSION_MAP_CODEX[Permission.READ_ONLY] == "read-only"
        assert PERMISSION_MAP_CODEX[Permission.WORKSPACE_WRITE] == "workspace-write"
        assert PERMISSION_MAP_CODEX[Permission.UNLIMITED] == "danger-full-access"

    def test_claude_permission_map(self):
        """测试 Claude permission 映射。"""
        assert PERMISSION_MAP_CLAUDE[Permission.READ_ONLY] == "Read,Grep,Glob"
        assert PERMISSION_MAP_CLAUDE[Permission.WORKSPACE_WRITE] == "Read,Edit,Write,Bash"
        assert PERMISSION_MAP_CLAUDE[Permission.UNLIMITED] == "default"


class TestCommonParams:
    """CommonParams 测试。"""

    def test_required_params(self, temp_workspace: Path):
        """测试必需参数。"""
        params = CommonParams(prompt="test", workspace=temp_workspace)
        assert params.prompt == "test"
        assert params.workspace == temp_workspace
        assert params.permission == Permission.READ_ONLY  # 默认值

    def test_all_params(self, temp_workspace: Path):
        """测试所有参数。"""
        params = CommonParams(
            prompt="test prompt",
            workspace=temp_workspace,
            permission=Permission.WORKSPACE_WRITE,
            session_id="session-123",
            model="gpt-4",
            task_note="[Test] Unit test",
            task_tags=["test", "unit"],
        )
        assert params.permission == Permission.WORKSPACE_WRITE
        assert params.session_id == "session-123"
        assert params.model == "gpt-4"
        assert params.task_note == "[Test] Unit test"
        assert params.task_tags == ["test", "unit"]

    def test_workspace_string_conversion(self, temp_workspace: Path):
        """测试 workspace 字符串自动转换。"""
        params = CommonParams(prompt="test", workspace=str(temp_workspace))
        assert isinstance(params.workspace, Path)
        assert params.workspace == temp_workspace

    def test_permission_string_conversion(self, temp_workspace: Path):
        """测试 permission 字符串自动转换。"""
        params = CommonParams(
            prompt="test",
            workspace=temp_workspace,
            permission="workspace-write",  # type: ignore
        )
        assert params.permission == Permission.WORKSPACE_WRITE


class TestCodexParams:
    """CodexParams 测试。"""

    def test_image_param(self, temp_workspace: Path, temp_image: Path):
        """测试 image 参数。"""
        params = CodexParams(
            prompt="test",
            workspace=temp_workspace,
            image=[temp_image],
        )
        assert len(params.image) == 1
        assert params.image[0] == temp_image

    def test_image_string_conversion(self, temp_workspace: Path, temp_image: Path):
        """测试 image 字符串自动转换。"""
        params = CodexParams(
            prompt="test",
            workspace=temp_workspace,
            image=[str(temp_image)],  # type: ignore
        )
        assert isinstance(params.image[0], Path)


class TestClaudeParams:
    """ClaudeParams 测试。"""

    def test_system_prompt(self, temp_workspace: Path):
        """测试 system_prompt 参数。"""
        params = ClaudeParams(
            prompt="test",
            workspace=temp_workspace,
            system_prompt="You are a helpful assistant.",
        )
        assert params.system_prompt == "You are a helpful assistant."
        assert params.append_system_prompt == ""

    def test_append_system_prompt(self, temp_workspace: Path):
        """测试 append_system_prompt 参数。"""
        params = ClaudeParams(
            prompt="test",
            workspace=temp_workspace,
            append_system_prompt="Focus on security.",
        )
        assert params.system_prompt == ""
        assert params.append_system_prompt == "Focus on security."


class TestExecutionResult:
    """ExecutionResult 测试。"""

    def test_success_result(self):
        """测试成功结果。"""
        result = ExecutionResult(
            success=True,
            session_id="session-123",
            agent_messages="Task completed.",
        )
        assert result.success is True
        assert result.error is None

    def test_error_result(self):
        """测试错误结果。"""
        result = ExecutionResult(
            success=False,
            error="Something went wrong",
        )
        assert result.success is False
        assert result.error == "Something went wrong"

    def test_to_dict(self):
        """测试转换为字典。"""
        result = ExecutionResult(
            success=True,
            session_id="session-123",
            agent_messages="Done",
            gui_metadata=GUIMetadata(
                task_note="[Test]",
                task_tags=["test"],
                source="codex",
                start_time=1000.0,
                end_time=1001.0,
            ),
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["session_id"] == "session-123"
        assert d["agent_messages"] == "Done"
        assert "error" not in d  # 成功时不包含 error
        assert d["gui_metadata"]["source"] == "codex"


# =============================================================================
# 命令构建测试
# =============================================================================


class TestCodexInvokerCommand:
    """Codex 命令构建测试。"""

    def test_basic_command(self, temp_workspace: Path):
        """测试基础命令构建。"""
        invoker = CodexInvoker()
        params = CodexParams(prompt="hello", workspace=temp_workspace)
        cmd = invoker.build_command(params)

        assert cmd[0] == "codex"
        assert cmd[1] == "exec"
        assert "--cd" in cmd
        assert str(temp_workspace.absolute()) in cmd
        assert "--sandbox" in cmd
        assert "read-only" in cmd  # 默认权限
        assert "--skip-git-repo-check" in cmd
        assert "--json" in cmd
        # prompt 通过 stdin 传递，不在 cmd 中

    def test_permission_mapping(self, temp_workspace: Path):
        """测试权限映射。"""
        invoker = CodexInvoker()

        # workspace-write
        params = CodexParams(
            prompt="test",
            workspace=temp_workspace,
            permission=Permission.WORKSPACE_WRITE,
        )
        cmd = invoker.build_command(params)
        sandbox_idx = cmd.index("--sandbox")
        assert cmd[sandbox_idx + 1] == "workspace-write"

        # unlimited
        params = CodexParams(
            prompt="test",
            workspace=temp_workspace,
            permission=Permission.UNLIMITED,
        )
        cmd = invoker.build_command(params)
        sandbox_idx = cmd.index("--sandbox")
        assert cmd[sandbox_idx + 1] == "danger-full-access"

    def test_with_model(self, temp_workspace: Path):
        """测试模型参数。"""
        invoker = CodexInvoker()
        params = CodexParams(
            prompt="test",
            workspace=temp_workspace,
            model="o3",
        )
        cmd = invoker.build_command(params)
        assert "--model" in cmd
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "o3"

    def test_with_image(self, temp_workspace: Path, temp_image: Path):
        """测试图片参数。"""
        invoker = CodexInvoker()
        params = CodexParams(
            prompt="test",
            workspace=temp_workspace,
            image=[temp_image],
        )
        cmd = invoker.build_command(params)
        assert "--image" in cmd
        image_idx = cmd.index("--image")
        assert cmd[image_idx + 1] == str(temp_image.absolute())

    def test_with_session_id(self, temp_workspace: Path):
        """测试会话恢复。"""
        invoker = CodexInvoker()
        params = CodexParams(
            prompt="continue",
            workspace=temp_workspace,
            session_id="thread-abc",
        )
        cmd = invoker.build_command(params)
        assert "resume" in cmd
        resume_idx = cmd.index("resume")
        assert cmd[resume_idx + 1] == "thread-abc"


class TestGeminiInvokerCommand:
    """Gemini 命令构建测试。"""

    def test_basic_command(self, temp_workspace: Path):
        """测试基础命令构建。"""
        invoker = GeminiInvoker()
        params = GeminiParams(prompt="hello", workspace=temp_workspace)
        cmd = invoker.build_command(params)

        assert cmd[0] == "gemini"
        assert "-o" in cmd
        assert "stream-json" in cmd
        assert "--include-directories" in cmd
        assert str(temp_workspace.absolute()) in cmd
        assert "--sandbox" in cmd  # 默认 read-only，启用 sandbox
        # prompt 通过 stdin 传递，不在 cmd 中

    def test_unlimited_no_sandbox(self, temp_workspace: Path):
        """测试 unlimited 权限不启用 sandbox。"""
        invoker = GeminiInvoker()
        params = GeminiParams(
            prompt="test",
            workspace=temp_workspace,
            permission=Permission.UNLIMITED,
        )
        cmd = invoker.build_command(params)
        assert "--sandbox" not in cmd

    def test_with_session_id(self, temp_workspace: Path):
        """测试会话恢复。"""
        invoker = GeminiInvoker()
        params = GeminiParams(
            prompt="continue",
            workspace=temp_workspace,
            session_id="session-xyz",
        )
        cmd = invoker.build_command(params)
        assert "--resume" in cmd
        resume_idx = cmd.index("--resume")
        assert cmd[resume_idx + 1] == "session-xyz"


class TestClaudeInvokerCommand:
    """Claude 命令构建测试。"""

    def test_basic_command(self, temp_workspace: Path):
        """测试基础命令构建。"""
        invoker = ClaudeInvoker()
        params = ClaudeParams(prompt="hello", workspace=temp_workspace)
        cmd = invoker.build_command(params)

        assert cmd[0] == "claude"
        assert "-p" in cmd
        assert "--output-format" in cmd
        assert "stream-json" in cmd
        assert "--add-dir" in cmd
        assert str(temp_workspace.absolute()) in cmd
        assert "--tools" in cmd
        assert "Read,Grep,Glob" in cmd  # 默认 read-only
        # prompt 通过 stdin 传递，不在 cmd 中

    def test_permission_mapping(self, temp_workspace: Path):
        """测试权限映射。"""
        invoker = ClaudeInvoker()

        # workspace-write
        params = ClaudeParams(
            prompt="test",
            workspace=temp_workspace,
            permission=Permission.WORKSPACE_WRITE,
        )
        cmd = invoker.build_command(params)
        tools_idx = cmd.index("--tools")
        assert cmd[tools_idx + 1] == "Read,Edit,Write,Bash"

        # unlimited
        params = ClaudeParams(
            prompt="test",
            workspace=temp_workspace,
            permission=Permission.UNLIMITED,
        )
        cmd = invoker.build_command(params)
        tools_idx = cmd.index("--tools")
        assert cmd[tools_idx + 1] == "default"

    def test_with_system_prompt(self, temp_workspace: Path):
        """测试系统提示词覆盖。"""
        invoker = ClaudeInvoker()
        params = ClaudeParams(
            prompt="test",
            workspace=temp_workspace,
            system_prompt="You are a code reviewer.",
        )
        cmd = invoker.build_command(params)
        assert "--system-prompt" in cmd
        sp_idx = cmd.index("--system-prompt")
        assert cmd[sp_idx + 1] == "You are a code reviewer."

    def test_with_append_system_prompt(self, temp_workspace: Path):
        """测试系统提示词追加。"""
        invoker = ClaudeInvoker()
        params = ClaudeParams(
            prompt="test",
            workspace=temp_workspace,
            append_system_prompt="Focus on security.",
        )
        cmd = invoker.build_command(params)
        assert "--append-system-prompt" in cmd
        asp_idx = cmd.index("--append-system-prompt")
        assert cmd[asp_idx + 1] == "Focus on security."

    def test_with_session_id(self, temp_workspace: Path):
        """测试会话恢复。"""
        invoker = ClaudeInvoker()
        params = ClaudeParams(
            prompt="continue",
            workspace=temp_workspace,
            session_id="conv-123",
        )
        cmd = invoker.build_command(params)
        assert "--resume" in cmd
        resume_idx = cmd.index("--resume")
        assert cmd[resume_idx + 1] == "conv-123"


# =============================================================================
# 参数验证测试
# =============================================================================


class TestParamValidation:
    """参数验证测试。"""

    def test_empty_prompt(self, temp_workspace: Path):
        """测试空 prompt 验证。"""
        invoker = CodexInvoker()
        params = CodexParams(prompt="", workspace=temp_workspace)
        with pytest.raises(ValueError, match="prompt is required"):
            invoker.validate_params(params)

    def test_nonexistent_workspace(self, tmp_path: Path):
        """测试不存在的 workspace 验证。"""
        invoker = GeminiInvoker()
        params = GeminiParams(
            prompt="test",
            workspace=tmp_path / "nonexistent",
        )
        with pytest.raises(ValueError, match="does not exist"):
            invoker.validate_params(params)

    def test_workspace_is_file(self, tmp_path: Path):
        """测试 workspace 是文件的验证。"""
        file_path = tmp_path / "file.txt"
        file_path.write_text("content")
        invoker = ClaudeInvoker()
        params = ClaudeParams(prompt="test", workspace=file_path)
        with pytest.raises(ValueError, match="not a directory"):
            invoker.validate_params(params)

    def test_nonexistent_image(self, temp_workspace: Path):
        """测试不存在的图片验证。"""
        invoker = CodexInvoker()
        params = CodexParams(
            prompt="test",
            workspace=temp_workspace,
            image=[Path("/nonexistent/image.png")],
        )
        with pytest.raises(ValueError, match="Image file does not exist"):
            invoker.validate_params(params)

    def test_both_system_prompts(self, temp_workspace: Path):
        """测试同时指定两种系统提示词。"""
        invoker = ClaudeInvoker()
        params = ClaudeParams(
            prompt="test",
            workspace=temp_workspace,
            system_prompt="override",
            append_system_prompt="append",
        )
        with pytest.raises(ValueError, match="Cannot specify both"):
            invoker.validate_params(params)


# =============================================================================
# 工厂函数测试
# =============================================================================


class TestCreateInvoker:
    """工厂函数测试。"""

    def test_create_codex(self):
        """测试创建 Codex 调用器。"""
        invoker = create_invoker(CLIType.CODEX)
        assert isinstance(invoker, CodexInvoker)
        assert invoker.cli_type == CLIType.CODEX

    def test_create_gemini(self):
        """测试创建 Gemini 调用器。"""
        invoker = create_invoker(CLIType.GEMINI)
        assert isinstance(invoker, GeminiInvoker)
        assert invoker.cli_type == CLIType.GEMINI

    def test_create_claude(self):
        """测试创建 Claude 调用器。"""
        invoker = create_invoker(CLIType.CLAUDE)
        assert isinstance(invoker, ClaudeInvoker)
        assert invoker.cli_type == CLIType.CLAUDE

    def test_create_from_string(self):
        """测试从字符串创建。"""
        invoker = create_invoker("codex")
        assert isinstance(invoker, CodexInvoker)

        invoker = create_invoker("GEMINI")  # 大小写不敏感
        assert isinstance(invoker, GeminiInvoker)

    def test_create_with_callback(self):
        """测试带回调创建。"""
        callback_called = []

        def callback(event):
            callback_called.append(event)

        invoker = create_invoker(CLIType.CODEX, event_callback=callback)
        assert invoker._event_callback is callback

    def test_invalid_type(self):
        """测试无效类型。"""
        with pytest.raises(ValueError):
            create_invoker("invalid")


# =============================================================================
# CLI 属性测试
# =============================================================================


class TestCLIProperties:
    """CLI 属性测试。"""

    def test_cli_name(self):
        """测试 cli_name 属性。"""
        assert CodexInvoker().cli_name == "codex"
        assert GeminiInvoker().cli_name == "gemini"
        assert ClaudeInvoker().cli_name == "claude"

    def test_custom_path(self):
        """测试自定义可执行文件路径。"""
        invoker = CodexInvoker(codex_path="/custom/codex")
        assert invoker._codex_path == "/custom/codex"

        invoker = GeminiInvoker(gemini_path="/custom/gemini")
        assert invoker._gemini_path == "/custom/gemini"

        invoker = ClaudeInvoker(claude_path="/custom/claude")
        assert invoker._claude_path == "/custom/claude"
