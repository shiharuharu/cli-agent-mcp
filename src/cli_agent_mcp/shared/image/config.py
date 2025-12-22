"""Image 模块配置。

cli-agent-mcp shared/image v0.1.0

环境变量:
    IMAGE_AUTH_TOKEN: API 认证 token
    IMAGE_ENDPOINT: API 端点 URL（默认 OpenRouter）
    IMAGE_MODEL: 默认模型
    IMAGE_API_TYPE: API 类型（openrouter_chat/openai_images/openai_responses）
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

__all__ = [
    "DEFAULT_MODEL",
    "ApiType",
    "ImageEnvConfig",
    "get_image_config",
]

# 默认模型
DEFAULT_MODEL = "gpt-image-1"

# 默认 API 基础 URL
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

# API 类型
ApiType = Literal["openrouter_chat", "openai_images", "openai_responses"]


def _normalize_base_url(url: str) -> str:
    """规范化 BASE_URL，自动补全版本路径。"""
    url = url.rstrip("/")
    if url.endswith(("/v1", "/v1beta", "/v2")):
        return url
    return f"{url}/v1"


@dataclass
class ImageEnvConfig:
    """Image 环境配置。

    Attributes:
        base_url: API 基础 URL
        auth_token: API 认证 token
        model: 默认模型
        api_type: API 类型
    """
    base_url: str
    auth_token: str
    model: str
    api_type: ApiType

    @property
    def is_configured(self) -> bool:
        """检查是否已配置 API token。"""
        return bool(self.auth_token)


def _parse_api_type(value: str) -> ApiType:
    """解析 API 类型。"""
    value = value.lower().strip()
    if value in ("openrouter_chat", "openai_images", "openai_responses"):
        return value  # type: ignore
    return "openrouter_chat"


def get_image_config() -> ImageEnvConfig:
    """从环境变量加载配置。

    Returns:
        ImageEnvConfig 实例
    """
    auth_token = os.environ.get("IMAGE_AUTH_TOKEN", "")
    raw_url = os.environ.get("IMAGE_ENDPOINT", DEFAULT_BASE_URL)
    model = os.environ.get("IMAGE_MODEL", DEFAULT_MODEL)

    api_type_str = os.environ.get("IMAGE_API_TYPE", "openrouter_chat")
    api_type = _parse_api_type(api_type_str)

    return ImageEnvConfig(
        base_url=_normalize_base_url(raw_url),
        auth_token=auth_token,
        model=model,
        api_type=api_type,
    )
