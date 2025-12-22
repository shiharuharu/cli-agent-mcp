"""Banana 模块异常类。

cli-agent-mcp shared/banana v0.1.0
同步日期: 2025-12-21
"""

from __future__ import annotations

__all__ = [
    "BananaError",
    "BananaConfigError",
    "BananaAPIError",
    "BananaRetryableError",
]


class BananaError(Exception):
    """Banana 模块基础异常。"""
    pass


class BananaConfigError(BananaError):
    """配置错误（如缺少 API key）。"""
    pass


class BananaAPIError(BananaError):
    """API 调用错误（不可重试）。

    Attributes:
        status_code: HTTP 状态码
        message: 错误消息
    """

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"[{status_code}] {message}")


class BananaRetryableError(BananaError):
    """可重试的 API 错误（429/5xx）。

    Attributes:
        status_code: HTTP 状态码
        message: 错误消息
        retry_after: 建议重试等待时间（秒）
    """

    def __init__(
        self,
        status_code: int,
        message: str,
        retry_after: float | None = None,
    ) -> None:
        self.status_code = status_code
        self.message = message
        self.retry_after = retry_after
        super().__init__(f"[{status_code}] {message}")
