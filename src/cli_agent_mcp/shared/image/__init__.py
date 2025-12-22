"""Image 模块。

cli-agent-mcp shared/image v0.1.0

提供统一的图像生成 API 封装，支持多种 API 格式。
"""

from __future__ import annotations

from .client import ImageClient
from .config import (
    DEFAULT_MODEL,
    ApiType,
    ImageEnvConfig,
    get_image_config,
)
from .errors import (
    ImageAPIError,
    ImageConfigError,
    ImageError,
    ImageRetryableError,
)
from .types import (
    ImageArtifact,
    ImageInput,
    ImageRequest,
    ImageResponse,
    map_to_size,
)

__all__ = [
    # Client
    "ImageClient",
    # Config
    "DEFAULT_MODEL",
    "ApiType",
    "ImageEnvConfig",
    "get_image_config",
    # Errors
    "ImageError",
    "ImageConfigError",
    "ImageAPIError",
    "ImageRetryableError",
    # Types
    "ImageInput",
    "ImageRequest",
    "ImageArtifact",
    "ImageResponse",
    "map_to_size",
]
