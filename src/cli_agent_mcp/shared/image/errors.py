"""Image 模块异常类。

cli-agent-mcp shared/image v0.1.0
"""

from __future__ import annotations

__all__ = [
    "ImageError",
    "ImageConfigError",
    "ImageAPIError",
    "ImageRetryableError",
]


class ImageError(Exception):
    """Image 模块基础异常。"""
    pass


class ImageConfigError(ImageError):
    """配置错误（如缺少 API key）。"""
    pass


class ImageAPIError(ImageError):
    """API 调用错误（不可重试）。

    Attributes:
        status_code: HTTP 状态码
        message: 错误消息
        api_url: 请求的 API 完整路径
    """

    def __init__(self, status_code: int, message: str, api_url: str = "") -> None:
        self.status_code = status_code
        self.message = message
        self.api_url = api_url
        super().__init__(f"[{status_code}] {message}")


class ImageRetryableError(ImageError):
    """可重试的 API 错误（429/5xx）。

    Attributes:
        status_code: HTTP 状态码
        message: 错误消息
        retry_after: 建议重试等待时间（秒）
        api_url: 请求的 API 完整路径
    """

    def __init__(
        self,
        status_code: int,
        message: str,
        retry_after: float | None = None,
        api_url: str = "",
    ) -> None:
        self.status_code = status_code
        self.message = message
        self.retry_after = retry_after
        self.api_url = api_url
        super().__init__(f"[{status_code}] {message}")
