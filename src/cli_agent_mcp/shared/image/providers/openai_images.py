"""OpenAI Images Provider - 使用 /images/generations API 生成图像。

cli-agent-mcp shared/image/providers v0.1.0

适用于 OpenAI DALL-E 和 gpt-image-1 等模型。
"""

from __future__ import annotations

import base64
import hashlib
import logging
import time
from pathlib import Path
from typing import Any, Callable

import aiohttp

from ..config import ImageEnvConfig
from ..debug_utils import sanitize_for_debug, sanitize_headers, EventCallback
from ..errors import ImageAPIError, ImageRetryableError
from ..types import ImageArtifact, ImageRequest, ImageResponse

__all__ = ["OpenAIImagesProvider"]

logger = logging.getLogger(__name__)


class OpenAIImagesProvider:
    """OpenAI Images Provider。

    使用 /images/generations API 生成图像。
    """

    def __init__(self, config: ImageEnvConfig, event_callback: EventCallback | None = None) -> None:
        self._config = config
        self._event_callback = event_callback

    def _emit_event(self, event: dict[str, Any]) -> None:
        """发送事件到回调。"""
        if self._event_callback:
            self._event_callback(event)

    def _build_request_body(self, request: ImageRequest) -> dict[str, Any]:
        """构建请求体。"""
        model = request.model or self._config.model
        return {
            "model": model,
            "prompt": request.prompt,
            "size": request.get_size(),
            "quality": request.quality,
            "response_format": "b64_json",
        }

    def _find_next_seq(self, output_dir: Path, base_name: str, ext: str) -> int:
        """找到下一个可用的序号。"""
        seq = 0
        while (output_dir / f"{base_name}_{seq}.{ext}").exists():
            seq += 1
        return seq

    def _save_image(
        self,
        data: bytes,
        output_dir: Path,
        task_note: str,
        mime_type: str,
    ) -> tuple[str, str]:
        """保存图片到文件。"""
        ext_map = {
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/webp": "webp",
        }
        ext = ext_map.get(mime_type, "png")

        output_dir.mkdir(parents=True, exist_ok=True)

        seq = self._find_next_seq(output_dir, task_note, ext)
        filename = f"{task_note}_{seq}.{ext}"
        file_path = output_dir / filename

        file_path.write_bytes(data)
        sha256 = hashlib.sha256(data).hexdigest()

        return str(file_path.absolute()), sha256

    def _parse_response(
        self,
        api_response: dict[str, Any],
        request: ImageRequest,
        request_id: str,
        output_dir: Path,
        api_url: str = "",
    ) -> ImageResponse:
        """解析 API 响应。"""
        artifacts: list[ImageArtifact] = []
        text_parts: list[str] = []
        model = request.model or self._config.model

        # task_note 用于文件名前缀，如果为空则使用 request_id
        task_note = request.task_note or request_id

        data_list = api_response.get("data", [])
        for item in data_list:
            b64_json = item.get("b64_json", "")
            revised_prompt = item.get("revised_prompt", "")

            if revised_prompt:
                text_parts.append(f"Revised prompt: {revised_prompt}")

            if b64_json:
                try:
                    image_bytes = base64.b64decode(b64_json)
                    mime_type = "image/png"

                    file_path, sha256 = self._save_image(
                        image_bytes,
                        output_dir,
                        task_note,
                        mime_type,
                    )

                    filename = Path(file_path).name
                    artifacts.append(ImageArtifact(
                        id=f"img-{filename}",
                        mime_type=mime_type,
                        path=file_path,
                        sha256=sha256,
                    ))
                except Exception as e:
                    logger.warning(f"Failed to parse generations image output: {e}")

        return ImageResponse(
            request_id=request_id,
            model=model,
            text_content="\n".join(text_parts),
            artifacts=artifacts,
            success=True,
            api_url=api_url,
        )

    async def generate(
        self,
        request: ImageRequest,
        request_id: str,
        session: aiohttp.ClientSession,
    ) -> ImageResponse:
        """生成图像。"""
        base_url = self._config.base_url.rstrip("/")
        url = f"{base_url}/images/generations"

        # Validate: /images/generations doesn't support input images
        if request.images:
            raise ImageAPIError(
                400,
                "OpenAI /images/generations API does not support input images. "
                "Use openai_responses or openrouter_chat format for image editing.",
                url,
            )

        auth_token = self._config.auth_token
        if auth_token.startswith("Bearer "):
            auth_header = auth_token
        else:
            auth_header = f"Bearer {auth_token}"

        headers = {
            "Content-Type": "application/json",
            "Authorization": auth_header,
        }
        body = self._build_request_body(request)

        # Emit api_request event with sanitized body
        self._emit_event({
            "type": "api_request",
            "request_id": request_id,
            "url": url,
            "method": "POST",
            "headers": sanitize_headers(headers),
            "body": sanitize_for_debug(body),
        })

        start_time = time.time()
        async with session.post(url, json=body, headers=headers) as resp:
            duration_ms = int((time.time() - start_time) * 1000)
            resp_headers = dict(resp.headers)

            if resp.status == 200:
                api_response = await resp.json()
                # Emit api_response event with sanitized body
                self._emit_event({
                    "type": "api_response",
                    "request_id": request_id,
                    "status_code": resp.status,
                    "duration_ms": duration_ms,
                    "headers": resp_headers,
                    "body": sanitize_for_debug(api_response),
                })
                output_dir = Path(request.output_dir) if request.output_dir else Path("/tmp/image-gen")
                return self._parse_response(api_response, request, request_id, output_dir, url)

            error_text = await resp.text()

            # Emit api_response event for errors
            self._emit_event({
                "type": "api_response",
                "request_id": request_id,
                "status_code": resp.status,
                "duration_ms": duration_ms,
                "headers": resp_headers,
                "body": error_text[:2000],
            })

            if resp.status in (429, 500, 502, 503, 504):
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else None
                raise ImageRetryableError(resp.status, error_text, delay, url)

            raise ImageAPIError(resp.status, error_text, url)
