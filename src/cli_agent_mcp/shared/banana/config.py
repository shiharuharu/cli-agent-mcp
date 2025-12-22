"""Banana 模块配置。

cli-agent-mcp shared/banana v0.1.0
同步日期: 2025-12-21

环境变量:
    BANANA_ENDPOINT: API 端点 URL（默认 Google AI Studio）
    BANANA_AUTH_TOKEN: API 认证 token（即 GOOGLE_API_KEY）
    BANANA_MODEL: 默认模型 ID
"""

from __future__ import annotations

import os
from dataclasses import dataclass

__all__ = [
    "DEFAULT_MODEL",
    "BananaEnvConfig",
    "get_banana_config",
]

# 默认模型 ID
DEFAULT_MODEL = "gemini-3-pro-image-preview"

# 默认 API 端点 URL
DEFAULT_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta"


def _normalize_endpoint(url: str) -> str:
    """规范化端点 URL，自动补全版本路径。"""
    url = url.rstrip("/")
    # 已有版本路径则不处理
    if url.endswith(("/v1beta", "/v1", "/v2")):
        return url
    # Google AI 默认使用 v1beta
    return f"{url}/v1beta"


@dataclass
class BananaEnvConfig:
    """Banana 环境配置。

    Attributes:
        base_url: API 端点 URL
        auth_token: API 认证 token
        model: 默认模型 ID
    """
    base_url: str
    auth_token: str
    model: str

    @property
    def is_configured(self) -> bool:
        """检查是否已配置 API token。"""
        return bool(self.auth_token)


def get_banana_config() -> BananaEnvConfig:
    """从环境变量加载配置。

    Returns:
        BananaEnvConfig 实例
    """
    # 优先使用 BANANA_AUTH_TOKEN，回退到 GOOGLE_API_KEY
    auth_token = os.environ.get("BANANA_AUTH_TOKEN") or os.environ.get("GOOGLE_API_KEY", "")

    # 模型：优先使用环境变量，否则使用默认值
    model = os.environ.get("BANANA_MODEL", DEFAULT_MODEL)

    # 端点 URL：自动补全版本路径
    raw_url = os.environ.get("BANANA_ENDPOINT", DEFAULT_ENDPOINT)

    return BananaEnvConfig(
        base_url=_normalize_endpoint(raw_url),
        auth_token=auth_token,
        model=model,
    )
