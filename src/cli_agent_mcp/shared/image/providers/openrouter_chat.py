"""OpenRouter Chat Provider - 使用 chat/completions + modalities 生成图像。

cli-agent-mcp shared/image/providers v0.1.0

适用于 OpenRouter 和支持 modalities 的 API。
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import aiohttp

from ..config import ImageEnvConfig
from ..debug_utils import sanitize_for_debug, sanitize_headers, EventCallback
from ..errors import ImageAPIError, ImageRetryableError
from ..types import ImageArtifact, ImageRequest, ImageResponse

# 复用 banana 的图片编解码
from ...banana.image_codec import encode_image_to_base64

__all__ = ["OpenRouterChatProvider"]

logger = logging.getLogger(__name__)


class OpenRouterChatProvider:
    """OpenRouter Chat Provider。

    使用 chat/completions API + modalities 参数生成图像。
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
        content: list[dict[str, Any]] = []

        # 添加输入图片
        for img in request.images:
            try:
                data, mime_type = encode_image_to_base64(img.source)
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{data}",
                    },
                })
            except Exception as e:
                logger.warning(f"Failed to encode image {img.source}: {e}")

        # 添加文本提示词
        content.append({
            "type": "text",
            "text": request.prompt,
        })

        model = request.model or self._config.model

        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": content,
                }
            ],
            "modalities": ["text", "image"],
        }

        # 添加 image_config（aspect_ratio/resolution）
        image_config: dict[str, Any] = {}
        if request.aspect_ratio and request.aspect_ratio != "1:1":
            image_config["aspect_ratio"] = request.aspect_ratio
        if request.resolution and request.resolution != "1K":
            image_config["image_size"] = request.resolution
        if image_config:
            body["image_config"] = image_config

        return body

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

    async def _download_image(
        self,
        url: str,
        session: aiohttp.ClientSession,
        output_dir: Path,
        task_note: str,
    ) -> ImageArtifact | None:
        """下载 CDN URL 图片并保存到本地。"""
        try:
            logger.info(f"Downloading image from CDN: {url}")
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status != 200:
                    logger.warning(f"Failed to download image: HTTP {resp.status}")
                    return None

                content_type = resp.headers.get("Content-Type", "image/png")
                mime_type = content_type.split(";")[0].strip()
                image_bytes = await resp.read()

                file_path, sha256 = self._save_image(
                    image_bytes,
                    output_dir,
                    task_note,
                    mime_type,
                )

                logger.info(f"Downloaded image: {len(image_bytes)} bytes -> {file_path}")

                # Extract seq from filename for artifact id
                filename = Path(file_path).name
                artifact_id = f"img-{filename}"

                return ImageArtifact(
                    id=artifact_id,
                    mime_type=mime_type,
                    path=file_path,
                    sha256=sha256,
                )
        except Exception as e:
            logger.warning(f"Failed to download image from {url}: {e}")
            return None

    def _extract_urls_from_text(self, text: str) -> list[str]:
        """从文本中提取图片 URL。"""
        # 匹配 markdown 图片语法: ![alt](url)
        md_pattern = r'!\[.*?\]\((https?://[^\s\)]+)\)'
        md_urls = re.findall(md_pattern, text)

        # 匹配直接的图片 URL
        direct_pattern = r'(https?://[^\s<>"\']+\.(?:png|jpg|jpeg|webp|gif))'
        direct_urls = re.findall(direct_pattern, text, re.IGNORECASE)

        # 合并并去重
        all_urls = list(dict.fromkeys(md_urls + direct_urls))
        return all_urls

    async def _parse_response(
        self,
        api_response: dict[str, Any],
        request: ImageRequest,
        request_id: str,
        output_dir: Path,
        session: aiohttp.ClientSession,
        api_url: str = "",
    ) -> ImageResponse:
        """解析 API 响应。"""
        text_parts: list[str] = []
        artifacts: list[ImageArtifact] = []
        cdn_urls_to_download: list[str] = []
        model = api_response.get("model", request.model or self._config.model)

        # task_note 用于文件名前缀，如果为空则使用 request_id
        task_note = request.task_note or request_id

        # 解析 choices
        choices = api_response.get("choices", [])

        for choice in choices:
            message = choice.get("message", {})

            # 优先检查 message.images[] (新格式)
            images = message.get("images", [])
            for img_item in images:
                image_url = img_item.get("image_url", {})
                url = image_url.get("url", "") if isinstance(image_url, dict) else ""
                if url.startswith("data:"):
                    try:
                        header, b64_data = url.split(",", 1)
                        mime_type = header.split(":")[1].split(";")[0]
                        image_bytes = base64.b64decode(b64_data)

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
                        logger.warning(f"Failed to parse image from images[]: {e}")
                elif url.startswith("http"):
                    # CDN URL - 稍后下载
                    cdn_urls_to_download.append(url)

            # 解析 message.content (兼容旧格式)
            content = message.get("content", [])

            if isinstance(content, str):
                text_parts.append(content)
                # 从文本中提取 CDN URL
                extracted_urls = self._extract_urls_from_text(content)
                cdn_urls_to_download.extend(extracted_urls)
                continue

            for item in content:
                item_type = item.get("type", "")

                if item_type == "text":
                    text_content = item.get("text", "")
                    text_parts.append(text_content)
                    # 从文本中提取 CDN URL
                    extracted_urls = self._extract_urls_from_text(text_content)
                    cdn_urls_to_download.extend(extracted_urls)

                elif item_type == "image_url":
                    image_url = item.get("image_url", {})
                    url = image_url.get("url", "") if isinstance(image_url, dict) else image_url

                    if url.startswith("data:"):
                        try:
                            header, b64_data = url.split(",", 1)
                            mime_type = header.split(":")[1].split(";")[0]
                            image_bytes = base64.b64decode(b64_data)

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
                            logger.warning(f"Failed to parse image output: {e}")
                    elif url.startswith("http"):
                        # CDN URL - 稍后下载
                        cdn_urls_to_download.append(url)

        # 下载 CDN URL 图片
        cdn_urls_to_download = list(dict.fromkeys(cdn_urls_to_download))  # 去重
        for url in cdn_urls_to_download:
            artifact = await self._download_image(
                url, session, output_dir, task_note
            )
            if artifact:
                artifacts.append(artifact)

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
        url = f"{base_url}/chat/completions"

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
                return await self._parse_response(api_response, request, request_id, output_dir, session, url)

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
