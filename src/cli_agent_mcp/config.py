"""CAM 环境变量配置管理。

环境变量:
    CAM_ENABLE: 启用的工具列表
        - 空/未设置 = 全部可用 (codex, gemini, claude, opencode, banana, image)
        - 逗号分割，忽略大小写
        - 例: "codex,gemini" 或 "CODEX, Gemini"

    CAM_DISABLE: 禁用的工具列表（从 enable 中减去）
        - 逗号分割，忽略大小写
        - 例: "banana,image" 禁用图片生成工具

    CAM_GUI: 是否启动 GUI 窗口
        - true/1/yes = 启动 (默认)
        - false/0/no = 不启动

    CAM_GUI_DETAIL: GUI 详细模式
        - true/1/yes = 开启 (事件默认不折叠)
        - false/0/no = 关闭 (默认，事件默认折叠)

    CAM_KEEP_UI: 主进程退出时是否保留 GUI 窗口
        - true/1/yes = 保留 (GUI 继续运行)
        - false/0/no = 关闭 (默认，随主进程退出)

    CAM_DEBUG: 调试模式
        - true/1/yes = 开启 (MCP 响应包含统计信息)
        - false/0/no = 关闭 (默认)

    CAM_LOG_DEBUG: 日志调试模式
        - true/1/yes = 开启 (日志输出到临时文件)
        - false/0/no = 关闭 (默认，日志输出到 stderr)

    CAM_SIGINT_MODE: SIGINT (Ctrl+C) 处理模式
        - cancel = 取消活动请求（无活动请求则退出）(默认)
        - exit = 直接退出进程
        - cancel_then_exit = 先取消请求，第二次才退出

    CAM_SIGINT_DOUBLE_TAP_WINDOW: 双击退出窗口时间（秒）
        - 默认 1.0 秒
        - 在此时间窗口内第二次 Ctrl+C 将强制退出
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal

__all__ = ["Config", "load_config", "SigintMode"]


class SigintMode(Enum):
    """SIGINT 处理模式。

    - CANCEL: 只取消活动请求，不退出（如果没有活动请求则退出）
    - EXIT: 直接退出进程（传统行为）
    - CANCEL_THEN_EXIT: 先取消请求，第二次 SIGINT 才退出
    """

    CANCEL = "cancel"
    EXIT = "exit"
    CANCEL_THEN_EXIT = "cancel_then_exit"

    @classmethod
    def from_string(cls, value: str) -> "SigintMode":
        """从字符串解析模式。

        Args:
            value: 模式字符串 (cancel/exit/cancel_then_exit)

        Returns:
            对应的 SigintMode 枚举值，无效值返回 CANCEL
        """
        value = value.lower().strip()
        for mode in cls:
            if mode.value == value:
                return mode
        return cls.CANCEL  # 默认值

# 支持的 CLI 类型
SUPPORTED_TOOLS = frozenset({"codex", "gemini", "claude", "opencode", "banana", "image"})


def _parse_bool(value: str | None, default: bool = False) -> bool:
    """解析布尔值环境变量。"""
    if value is None:
        return default
    return value.lower() in ("true", "1", "yes", "on")


def _parse_tool_list(value: str | None) -> set[str]:
    """解析工具列表环境变量。

    Args:
        value: 环境变量值，逗号分割，忽略大小写

    Returns:
        工具集合
    """
    if not value or not value.strip():
        return set()

    tools = set()
    for item in value.split(","):
        tool = item.strip().lower()
        if tool and tool in SUPPORTED_TOOLS:
            tools.add(tool)

    return tools


def _compute_enabled_tools(enable: str | None, disable: str | None) -> set[str]:
    """计算最终启用的工具列表。

    Args:
        enable: CAM_ENABLE 环境变量值
        disable: CAM_DISABLE 环境变量值

    Returns:
        最终启用的工具集合，空集合表示全部可用
    """
    enabled = _parse_tool_list(enable)
    disabled = _parse_tool_list(disable)

    # enable 为空时默认全开
    if not enabled:
        enabled = set(SUPPORTED_TOOLS)

    # 从 enable 中减去 disable
    return enabled - disabled


@dataclass
class Config:
    """CAM 配置。

    Attributes:
        tools: 允许的工具集合，空集合表示全部可用
        gui_enabled: 是否启动 GUI
        gui_detail: GUI 详细模式（不折叠）
        gui_keep: 主进程退出时是否保留 GUI
        debug: 调试模式（响应包含统计信息）
        log_debug: 日志调试模式（输出到临时文件）
        log_file: 日志文件路径（当 log_debug=True 时自动设置）
        sigint_mode: SIGINT 处理模式
        sigint_double_tap_window: 双击退出窗口时间（秒）
    """

    tools: set[str] = field(default_factory=set)
    gui_enabled: bool = True
    gui_detail: bool = False
    gui_keep: bool = False
    debug: bool = False
    log_debug: bool = False
    log_file: str | None = None
    sigint_mode: SigintMode = SigintMode.CANCEL
    sigint_double_tap_window: float = 1.0

    @property
    def allowed_tools(self) -> set[str]:
        """获取实际允许的工具列表。"""
        return self.tools

    def is_tool_allowed(self, tool: str) -> bool:
        """检查工具是否允许使用。"""
        return tool.lower() in self.tools

    def __repr__(self) -> str:
        tools_str = ",".join(sorted(self.allowed_tools)) or "all"
        return (
            f"Config(tools={tools_str}, "
            f"gui_enabled={self.gui_enabled}, "
            f"gui_detail={self.gui_detail}, "
            f"gui_keep={self.gui_keep}, "
            f"debug={self.debug}, "
            f"log_debug={self.log_debug}, "
            f"log_file={self.log_file}, "
            f"sigint_mode={self.sigint_mode.value}, "
            f"sigint_double_tap_window={self.sigint_double_tap_window})"
        )


def _generate_log_file_path() -> str:
    """生成日志文件路径。

    Returns:
        临时目录下的日志文件绝对路径
    """
    # 使用系统临时目录下的 cli-agent-mcp 子目录
    log_dir = Path(tempfile.gettempdir()) / "cli-agent-mcp"
    log_dir.mkdir(parents=True, exist_ok=True)

    # 生成带时间戳的文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"cam_debug_{timestamp}.log"

    return str(log_file.resolve())


def _parse_sigint_mode(value: str | None) -> SigintMode:
    """解析 SIGINT 模式环境变量。"""
    if not value:
        return SigintMode.CANCEL
    return SigintMode.from_string(value)


def _parse_double_tap_window(value: str | None) -> float:
    """解析双击窗口时间环境变量。"""
    if not value:
        return 1.0
    try:
        window = float(value)
        return max(0.1, min(window, 10.0))  # 限制在 0.1-10 秒范围
    except ValueError:
        return 1.0


def load_config() -> Config:
    """从环境变量加载配置。"""
    log_debug = _parse_bool(os.environ.get("CAM_LOG_DEBUG"), default=False)
    log_file = _generate_log_file_path() if log_debug else None

    return Config(
        tools=_compute_enabled_tools(
            os.environ.get("CAM_ENABLE"),
            os.environ.get("CAM_DISABLE"),
        ),
        gui_enabled=_parse_bool(os.environ.get("CAM_GUI"), default=True),
        gui_detail=_parse_bool(os.environ.get("CAM_GUI_DETAIL"), default=False),
        gui_keep=_parse_bool(os.environ.get("CAM_KEEP_UI"), default=False),
        debug=_parse_bool(os.environ.get("CAM_DEBUG"), default=False),
        log_debug=log_debug,
        log_file=log_file,
        sigint_mode=_parse_sigint_mode(os.environ.get("CAM_SIGINT_MODE")),
        sigint_double_tap_window=_parse_double_tap_window(
            os.environ.get("CAM_SIGINT_DOUBLE_TAP_WINDOW")
        ),
    )


# 全局配置实例（延迟加载）
_config: Config | None = None


def get_config() -> Config:
    """获取全局配置实例。"""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config() -> Config:
    """重新加载配置（用于测试）。"""
    global _config
    _config = load_config()
    return _config
