"""Nano Banana Pro (Gemini 3 Pro Image) 模块。

cli-agent-mcp shared/banana v0.1.0
同步日期: 2025-12-21

提供图像生成和编辑功能的 API 客户端。
"""

from __future__ import annotations

__version__ = "0.1.0"

from .types import (
    AspectRatio,
    ImageSize,
    ImageRole,
    ImageInput,
    BananaConfig,
    BananaRequest,
    BananaPart,
    BananaArtifact,
    BananaResponse,
)
from .config import get_banana_config
from .errors import (
    BananaError,
    BananaConfigError,
    BananaAPIError,
    BananaRetryableError,
)
from .client import NanoBananaProClient

__all__ = [
    "__version__",
    # Types
    "AspectRatio",
    "ImageSize",
    "ImageRole",
    "ImageInput",
    "BananaConfig",
    "BananaRequest",
    "BananaPart",
    "BananaArtifact",
    "BananaResponse",
    # Config
    "get_banana_config",
    # Errors
    "BananaError",
    "BananaConfigError",
    "BananaAPIError",
    "BananaRetryableError",
    # Client
    "NanoBananaProClient",
]
