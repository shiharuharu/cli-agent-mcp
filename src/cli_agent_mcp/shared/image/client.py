"""Image API 客户端。

cli-agent-mcp shared/image v0.1.0

统一的图片生成客户端，支持三种 API 格式：
1. OpenRouter chat/completions + modalities
2. OpenAI /images/generations
3. OpenAI /responses
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Callable

import aiohttp

from .config import ImageEnvConfig, get_image_config
from .errors import (
    ImageAPIError,
    ImageRetryableError,
)
from .providers import (
    OpenAIImagesProvider,
    OpenAIResponsesProvider,
    OpenRouterChatProvider,
)
from .types import ImageRequest, ImageResponse

__all__ = ["ImageClient"]

logger = logging.getLogger(__name__)

# 重试配置
MAX_RETRIES = 3
RETRY_DELAYS = [1.0, 2.0, 4.0]

# 事件回调类型
EventCallback = Callable[[dict[str, Any]], None]


class ImageClient:
    """Image API 客户端。

    统一的图片生成客户端，支持多种 API 格式。

    Example:
        client = ImageClient()
        response = await client.generate(ImageRequest(
            prompt="A beautiful sunset over mountains",
            aspect_ratio="16:9",
        ))
    """

    def __init__(
        self,
        config: ImageEnvConfig | None = None,
        event_callback: EventCallback | None = None,
    ) -> None:
        """初始化客户端。

        Args:
            config: 环境配置（可选，默认从环境变量加载）
            event_callback: 事件回调函数（用于 GUI 推送）
        """
        self._config = config or get_image_config()
        self._event_callback = event_callback
        self._session: aiohttp.ClientSession | None = None

        # 初始化 providers (pass event_callback)
        self._providers = {
            "openrouter_chat": OpenRouterChatProvider(self._config, event_callback),
            "openai_images": OpenAIImagesProvider(self._config, event_callback),
            "openai_responses": OpenAIResponsesProvider(self._config, event_callback),
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 HTTP 会话。"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """关闭 HTTP 会话。"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def _emit_event(self, event: dict[str, Any]) -> None:
        """发送事件到回调。"""
        if self._event_callback:
            self._event_callback(event)

    def _mask_token(self, token: str) -> str:
        """脱敏 token，只显示前4位和后4位。"""
        if not token:
            return "(empty)"
        clean = token.replace("Bearer ", "")
        if len(clean) <= 8:
            return clean[:2] + "***"
        return f"{clean[:4]}...{clean[-4:]}"

    def _get_api_type(self, request: ImageRequest) -> str:
        """获取要使用的 API 类型。"""
        if request.api_type:
            return request.api_type
        return self._config.api_type

    async def _generate_with_provider(
        self,
        api_type: str,
        request: ImageRequest,
        request_id: str,
        session: aiohttp.ClientSession,
    ) -> ImageResponse:
        """使用指定 provider 生成图像，带重试。"""
        provider = self._providers.get(api_type)
        if not provider:
            raise ImageAPIError(0, f"Unknown API type: {api_type}")

        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                self._emit_event({
                    "type": "api_call",
                    "request_id": request_id,
                    "api_type": api_type,
                    "attempt": attempt + 1,
                    "status": "started",
                })

                return await provider.generate(request, request_id, session)

            except ImageRetryableError as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = e.retry_after or RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                    logger.warning(
                        f"API error {e.status_code}, retrying in {delay}s: {e.message[:200]}"
                    )
                    self._emit_event({
                        "type": "api_retry",
                        "request_id": request_id,
                        "api_type": api_type,
                        "attempt": attempt + 1,
                        "status_code": e.status_code,
                        "delay": delay,
                    })
                    await asyncio.sleep(delay)
                    continue
                raise

            except aiohttp.ClientError as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                    logger.warning(f"Network error, retrying in {delay}s: {e}")
                    await asyncio.sleep(delay)
                    continue
                raise ImageAPIError(0, f"Network error: {e}")

        raise ImageAPIError(0, str(last_error) if last_error else "Unknown error")

    async def generate(self, request: ImageRequest) -> ImageResponse:
        """调用图像生成 API。

        根据配置的 api_type 选择调用哪个 API。

        Args:
            request: 请求对象

        Returns:
            ImageResponse 响应对象
        """
        request_id = str(uuid.uuid4())[:8]
        auth_hint = self._mask_token(self._config.auth_token)

        self._emit_event({
            "type": "generation_started",
            "request_id": request_id,
            "prompt": request.prompt[:100],
            "image_count": len(request.images),
        })

        if not self._config.is_configured:
            error_msg = "API key not configured. Set IMAGE_AUTH_TOKEN environment variable."
            self._emit_event({
                "type": "generation_failed",
                "request_id": request_id,
                "error": error_msg,
                "auth_hint": auth_hint,
            })
            return ImageResponse(
                request_id=request_id,
                success=False,
                error=error_msg,
                auth_hint=auth_hint,
            )

        session = await self._get_session()
        api_type = self._get_api_type(request)

        try:
            response = await self._generate_with_provider(
                api_type, request, request_id, session
            )
            # 填充 auth_hint
            response.auth_hint = auth_hint

            self._emit_event({
                "type": "generation_completed",
                "request_id": request_id,
                "artifact_count": len(response.artifacts),
                "success": True,
            })

            return response

        except (ImageAPIError, ImageRetryableError) as e:
            error_msg = self._build_error_message(e)
            api_url = getattr(e, 'api_url', '')
            self._emit_event({
                "type": "generation_failed",
                "request_id": request_id,
                "error": error_msg,
                "api_url": api_url,
                "auth_hint": auth_hint,
            })

            return ImageResponse(
                request_id=request_id,
                model=request.model or self._config.model,
                success=False,
                error=error_msg,
                api_url=api_url,
                auth_hint=auth_hint,
            )

    def _build_error_message(self, last_error: Exception | None) -> str:
        """构建用户友好的错误信息。"""
        if last_error is None:
            return "Image generation failed. Check your API key and endpoint configuration."

        base_msg = str(last_error)

        # 添加建议
        suggestions = []

        if isinstance(last_error, ImageAPIError):
            if last_error.status_code == 401:
                suggestions.append("Check your API key is valid and has sufficient permissions.")
            elif last_error.status_code == 403:
                suggestions.append("Your API key may not have access to image generation.")
            elif last_error.status_code == 429:
                suggestions.append("Rate limit exceeded. Wait and try again later.")

        if suggestions:
            return f"{base_msg}\n\nSuggestions:\n- " + "\n- ".join(suggestions)

        return base_msg
