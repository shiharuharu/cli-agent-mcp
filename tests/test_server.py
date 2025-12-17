"""Server 模块测试。

测试 MCP Server 相关功能。
注意：由于 server.py 使用相对导入，部分测试需要通过其他方式验证。
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

# 导入可以直接测试的模块
from cli_agent_mcp.config import Config, load_config, reload_config, SUPPORTED_TOOLS

# 导入 invokers 类型（用于验证参数构建逻辑）
from invokers import (
    CodexParams,
    GeminiParams,
    ClaudeParams,
    Permission,
)


class TestConfigIntegration:
    """测试 Config 与 Server 的集成。"""

    def test_tool_filtering_codex_only(self):
        """只允许 codex 时的过滤。"""
        with mock.patch.dict(os.environ, {"CAM_TOOLS": "codex"}, clear=False):
            config = reload_config()
            assert config.is_tool_allowed("codex")
            assert not config.is_tool_allowed("gemini")
            assert not config.is_tool_allowed("claude")

    def test_tool_filtering_multiple(self):
        """允许多个工具时的过滤。"""
        with mock.patch.dict(os.environ, {"CAM_TOOLS": "codex,claude"}, clear=False):
            config = reload_config()
            assert config.is_tool_allowed("codex")
            assert not config.is_tool_allowed("gemini")
            assert config.is_tool_allowed("claude")

    def test_all_tools_available_by_default(self):
        """默认所有工具可用。"""
        env = {k: v for k, v in os.environ.items() if k != "CAM_TOOLS"}
        with mock.patch.dict(os.environ, env, clear=True):
            config = reload_config()
            assert config.is_tool_allowed("codex")
            assert config.is_tool_allowed("gemini")
            assert config.is_tool_allowed("claude")


class TestParamsBuilding:
    """测试参数构建逻辑（不依赖 server.py 的导入）。"""

    def test_codex_params_structure(self, tmp_path: Path):
        """Codex 参数结构正确。"""
        params = CodexParams(
            prompt="test prompt",
            workspace=tmp_path,
            permission=Permission.READ_ONLY,
            image=[Path("/path/to/image.png")],
        )
        assert params.prompt == "test prompt"
        assert params.workspace == tmp_path
        assert params.permission == Permission.READ_ONLY
        assert len(params.image) == 1

    def test_gemini_params_structure(self, tmp_path: Path):
        """Gemini 参数结构正确。"""
        params = GeminiParams(
            prompt="test prompt",
            workspace=tmp_path,
            permission=Permission.WORKSPACE_WRITE,
        )
        assert params.prompt == "test prompt"
        assert params.permission == Permission.WORKSPACE_WRITE

    def test_claude_params_structure(self, tmp_path: Path):
        """Claude 参数结构正确。"""
        params = ClaudeParams(
            prompt="test prompt",
            workspace=tmp_path,
            system_prompt="custom system",
            append_system_prompt="extra instructions",
        )
        assert params.system_prompt == "custom system"
        assert params.append_system_prompt == "extra instructions"

    def test_params_with_task_metadata(self, tmp_path: Path):
        """参数包含任务元数据。"""
        params = GeminiParams(
            prompt="test",
            workspace=tmp_path,
            task_note="[Review] PR #123",
            task_tags=["review", "security"],
        )
        assert params.task_note == "[Review] PR #123"
        assert params.task_tags == ["review", "security"]

    def test_permission_string_conversion(self, tmp_path: Path):
        """Permission 字符串转换。"""
        params = CodexParams(
            prompt="test",
            workspace=tmp_path,
            permission="workspace-write",  # 字符串
        )
        assert params.permission == Permission.WORKSPACE_WRITE


class TestToolSchemaLogic:
    """测试工具 Schema 生成逻辑。"""

    def test_common_properties(self):
        """验证公共属性名称。"""
        # 这些是 MCP 工具应该有的公共属性
        expected_properties = [
            "prompt",
            "workspace",
            "permission",
            "session_id",
            "model",
            "full_output",
            "task_note",
            "task_tags",
        ]
        # 验证 CommonParams 有这些属性
        from invokers import CommonParams
        import dataclasses

        fields = {f.name for f in dataclasses.fields(CommonParams)}
        for prop in expected_properties:
            assert prop in fields, f"Missing property: {prop}"

    def test_codex_specific_properties(self):
        """Codex 特有属性。"""
        import dataclasses
        fields = {f.name for f in dataclasses.fields(CodexParams)}
        assert "image" in fields

    def test_claude_specific_properties(self):
        """Claude 特有属性。"""
        import dataclasses
        fields = {f.name for f in dataclasses.fields(ClaudeParams)}
        assert "system_prompt" in fields
        assert "append_system_prompt" in fields


class TestDebugMode:
    """测试 Debug 模式。"""

    def test_debug_mode_enabled(self):
        """Debug 模式启用。"""
        with mock.patch.dict(os.environ, {"CAM_DEBUG": "true"}, clear=False):
            config = reload_config()
            assert config.debug is True

    def test_debug_mode_disabled(self):
        """Debug 模式禁用。"""
        with mock.patch.dict(os.environ, {"CAM_DEBUG": "false"}, clear=False):
            config = reload_config()
            assert config.debug is False


class TestGUIConfig:
    """测试 GUI 配置。"""

    def test_gui_enabled_by_default(self):
        """GUI 默认启用。"""
        env = {k: v for k, v in os.environ.items() if k != "CAM_GUI"}
        with mock.patch.dict(os.environ, env, clear=True):
            config = reload_config()
            assert config.gui_enabled is True

    def test_gui_disabled(self):
        """GUI 可禁用。"""
        with mock.patch.dict(os.environ, {"CAM_GUI": "false"}, clear=False):
            config = reload_config()
            assert config.gui_enabled is False

    def test_gui_detail_mode(self):
        """GUI 详细模式。"""
        with mock.patch.dict(os.environ, {"CAM_GUI_DETAIL": "true"}, clear=False):
            config = reload_config()
            assert config.gui_detail is True
