"""Config 模块测试。

测试 CAM_* 环境变量解析和配置管理。
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from cli_agent_mcp.config import Config, load_config, get_config, reload_config, SUPPORTED_TOOLS


class TestParseTools:
    """测试工具列表解析。"""

    def test_empty_tools_means_all(self):
        """空工具列表表示全部可用。"""
        with mock.patch.dict(os.environ, {"CAM_ENABLE": ""}, clear=False):
            config = load_config()
            assert config.allowed_tools == SUPPORTED_TOOLS

    def test_unset_tools_means_all(self):
        """未设置工具列表表示全部可用。"""
        env = {k: v for k, v in os.environ.items() if k not in ("CAM_ENABLE", "CAM_DISABLE")}
        with mock.patch.dict(os.environ, env, clear=True):
            config = load_config()
            assert config.allowed_tools == SUPPORTED_TOOLS

    def test_single_tool(self):
        """单个工具。"""
        with mock.patch.dict(os.environ, {"CAM_ENABLE": "codex"}, clear=False):
            config = load_config()
            assert config.allowed_tools == {"codex"}

    def test_multiple_tools(self):
        """多个工具，逗号分隔。"""
        with mock.patch.dict(os.environ, {"CAM_ENABLE": "codex,gemini"}, clear=False):
            config = load_config()
            assert config.allowed_tools == {"codex", "gemini"}

    def test_case_insensitive(self):
        """大小写不敏感。"""
        with mock.patch.dict(os.environ, {"CAM_ENABLE": "CODEX,Gemini,CLAUDE"}, clear=False):
            config = load_config()
            assert config.allowed_tools == {"codex", "gemini", "claude"}

    def test_whitespace_handling(self):
        """处理空格。"""
        with mock.patch.dict(os.environ, {"CAM_ENABLE": " codex , gemini "}, clear=False):
            config = load_config()
            assert config.allowed_tools == {"codex", "gemini"}

    def test_invalid_tools_ignored(self):
        """无效工具被忽略。"""
        with mock.patch.dict(os.environ, {"CAM_ENABLE": "codex,invalid,gemini"}, clear=False):
            config = load_config()
            assert config.allowed_tools == {"codex", "gemini"}

    def test_all_invalid_means_all(self):
        """全部无效时返回全部可用（因为 enable 解析为空）。"""
        with mock.patch.dict(os.environ, {"CAM_ENABLE": "invalid1,invalid2"}, clear=False):
            config = load_config()
            # 无效工具被忽略，enable 为空，所以全部可用
            assert config.allowed_tools == SUPPORTED_TOOLS


class TestParseBool:
    """测试布尔值解析。"""

    @pytest.mark.parametrize("value", ["true", "True", "TRUE", "1", "yes", "Yes", "on"])
    def test_truthy_values(self, value: str):
        """真值。"""
        with mock.patch.dict(os.environ, {"CAM_GUI": value}, clear=False):
            config = load_config()
            assert config.gui_enabled is True

    @pytest.mark.parametrize("value", ["false", "False", "FALSE", "0", "no", "No", "off", ""])
    def test_falsy_values(self, value: str):
        """假值。"""
        with mock.patch.dict(os.environ, {"CAM_GUI": value}, clear=False):
            config = load_config()
            assert config.gui_enabled is False

    def test_gui_default_true(self):
        """GUI 默认启用。"""
        env = {k: v for k, v in os.environ.items() if k != "CAM_GUI"}
        with mock.patch.dict(os.environ, env, clear=True):
            config = load_config()
            assert config.gui_enabled is True

    def test_gui_detail_default_false(self):
        """GUI 详细模式默认关闭。"""
        env = {k: v for k, v in os.environ.items() if k != "CAM_GUI_DETAIL"}
        with mock.patch.dict(os.environ, env, clear=True):
            config = load_config()
            assert config.gui_detail is False

    def test_debug_default_false(self):
        """Debug 模式默认关闭。"""
        env = {k: v for k, v in os.environ.items() if k != "CAM_DEBUG"}
        with mock.patch.dict(os.environ, env, clear=True):
            config = load_config()
            assert config.debug is False


class TestConfigMethods:
    """测试 Config 类方法。"""

    def test_is_tool_allowed_when_all(self):
        """全部工具可用时检查。"""
        config = Config(tools=SUPPORTED_TOOLS)  # 全部工具
        assert config.is_tool_allowed("codex") is True
        assert config.is_tool_allowed("gemini") is True
        assert config.is_tool_allowed("claude") is True
        assert config.is_tool_allowed("opencode") is True
        assert config.is_tool_allowed("banana") is True
        assert config.is_tool_allowed("image") is True

    def test_is_tool_allowed_when_restricted(self):
        """限制工具时检查。"""
        config = Config(tools={"codex"})
        assert config.is_tool_allowed("codex") is True
        assert config.is_tool_allowed("gemini") is False
        assert config.is_tool_allowed("claude") is False

    def test_is_tool_allowed_case_insensitive(self):
        """工具检查大小写不敏感。"""
        config = Config(tools={"codex"})
        assert config.is_tool_allowed("CODEX") is True
        assert config.is_tool_allowed("Codex") is True

    def test_repr(self):
        """字符串表示。"""
        config = Config(tools={"codex"}, gui_enabled=True, gui_detail=False, debug=True)
        repr_str = repr(config)
        assert "codex" in repr_str
        assert "gui_enabled=True" in repr_str
        assert "debug=True" in repr_str


class TestGlobalConfig:
    """测试全局配置实例。"""

    def test_get_config_returns_same_instance(self):
        """get_config 返回相同实例。"""
        # 先 reload 确保干净状态
        reload_config()
        config1 = get_config()
        config2 = get_config()
        assert config1 is config2

    def test_reload_config_creates_new_instance(self):
        """reload_config 创建新实例。"""
        config1 = get_config()
        config2 = reload_config()
        # reload 后应该是不同的实例
        assert config1 is not config2


class TestFullConfig:
    """完整配置测试。"""

    def test_full_config(self):
        """完整配置加载。"""
        with mock.patch.dict(
            os.environ,
            {
                "CAM_ENABLE": "codex,claude",
                "CAM_GUI": "true",
                "CAM_GUI_DETAIL": "true",
                "CAM_DEBUG": "true",
            },
            clear=False,
        ):
            config = load_config()
            assert config.allowed_tools == {"codex", "claude"}
            assert config.gui_enabled is True
            assert config.gui_detail is True
            assert config.debug is True
