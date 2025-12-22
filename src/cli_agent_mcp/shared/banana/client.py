"""Nano Banana Pro API 客户端。

cli-agent-mcp shared/banana v0.1.0
同步日期: 2025-12-21

使用 aiohttp 异步调用 Gemini 3 Pro Image API。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Callable

import aiohttp


def _sanitize_for_debug(data: Any) -> Any:
    """Sanitize data for debug output, replacing base64 strings with summaries."""
    if isinstance(data, dict):
        return {k: _sanitize_for_debug(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_sanitize_for_debug(item) for item in data]
    if isinstance(data, str) and len(data) > 100:
        # Check if it looks like base64
        if re.match(r'^[A-Za-z0-9+/=]+$', data[:100]):
            return f"<base64:{len(data)} bytes>"
    return data

from .config import DEFAULT_MODEL, BananaEnvConfig, get_banana_config
from .errors import BananaAPIError, BananaConfigError, BananaRetryableError
from .image_codec import encode_image_to_base64
from .types import (
    BananaArtifact,
    BananaPart,
    BananaRequest,
    BananaResponse,
    ImageInput,
)

__all__ = ["NanoBananaProClient"]

logger = logging.getLogger(__name__)

# 重试配置
MAX_RETRIES = 3
RETRY_DELAYS = [1.0, 2.0, 4.0]  # 指数退避

# 事件回调类型
EventCallback = Callable[[dict[str, Any]], None]


class NanoBananaProClient:
    """Nano Banana Pro API 客户端。

    使用 aiohttp 异步调用 Gemini 3 Pro Image API。

    Example:
        client = NanoBananaProClient()
        response = await client.generate(BananaRequest(
            prompt="Create a cute cat",
            config=BananaConfig(aspect_ratio=AspectRatio.RATIO_16_9),
        ))
    """

    def __init__(
        self,
        config: BananaEnvConfig | None = None,
        event_callback: EventCallback | None = None,
    ) -> None:
        """初始化客户端。

        Args:
            config: 环境配置（可选，默认从环境变量加载）
            event_callback: 事件回调函数（用于 GUI 推送）
        """
        self._config = config or get_banana_config()
        self._event_callback = event_callback
        self._session: aiohttp.ClientSession | None = None

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
        # 移除 Bearer 前缀
        clean = token.replace("Bearer ", "")
        if len(clean) <= 8:
            return clean[:2] + "***"
        return f"{clean[:4]}...{clean[-4:]}"

    def _sanitize_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """Sanitize headers for debug output, masking auth tokens."""
        result = {}
        for k, v in headers.items():
            if k.lower() in ("authorization", "x-goog-api-key"):
                result[k] = "***"
            else:
                result[k] = v
        return result

    def _build_image_metadata_prefix(self, images: list[ImageInput]) -> str:
        """Build metadata prefix from images with role/label."""
        lines = []
        for i, img in enumerate(images, 1):
            if img.role or img.label:
                role_str = img.role.value if img.role else "input"
                label_str = f' label="{img.label}"' if img.label else ""
                lines.append(f"Image {i}: role={role_str}{label_str}")
        return "\n".join(lines) + "\n\n" if lines else ""

    def _build_request_body(self, request: BananaRequest) -> dict[str, Any]:
        """构建 API 请求体。"""
        # 构建 contents
        parts: list[dict[str, Any]] = []

        # 添加参考图片
        for img in request.images:
            try:
                data, mime_type = encode_image_to_base64(img.source)
                parts.append({
                    "inline_data": {
                        "mime_type": mime_type,
                        "data": data,
                    }
                })
            except Exception as e:
                logger.warning(f"Failed to encode image {img.source}: {e}")

        # Build prompt with metadata prefix if images have role/label
        metadata_prefix = self._build_image_metadata_prefix(request.images)
        final_prompt = metadata_prefix + request.prompt if metadata_prefix else request.prompt

        # 添加文本提示词
        parts.append({"text": final_prompt})

        # 构建 generationConfig
        config = request.config
        generation_config: dict[str, Any] = {
            # 如果 use_search 或 include_thoughts，需要包含 TEXT
            "responseModalities": ["TEXT", "IMAGE"] if config.use_search or config.include_thoughts else ["IMAGE"],
            "temperature": config.temperature,
            "topP": config.top_p,
            "topK": config.top_k,
        }

        # 多图生成
        if config.num_images > 1:
            generation_config["candidateCount"] = config.num_images

        # 图片配置
        image_config: dict[str, Any] = {}
        if config.aspect_ratio:
            image_config["aspectRatio"] = config.aspect_ratio.value
        if config.image_size:
            image_config["imageSize"] = config.image_size.value
        if image_config:
            generation_config["imageConfig"] = image_config

        body: dict[str, Any] = {
            "contents": [{"parts": parts}],
            "generationConfig": generation_config,
        }

        # 思考配置（放在 generationConfig 内部）
        if config.include_thoughts:
            generation_config["thinkingConfig"] = {"includeThoughts": True}

        # 搜索工具
        if config.use_search:
            body["tools"] = [{"google_search": {}}]

        return body

    async def _call_api(
        self,
        request: BananaRequest,
        request_id: str,
    ) -> tuple[dict[str, Any], str]:
        """调用 API 并处理重试。

        Returns:
            (api_response, api_url) 元组
        """
        if not self._config.is_configured:
            raise BananaConfigError(
                "API token not configured. Set BANANA_AUTH_TOKEN or GOOGLE_API_KEY."
            )

        url = f"{self._config.base_url}/models/{self._config.model}:generateContent"

        # 支持 Bearer token 和 API key 两种认证方式
        auth_token = self._config.auth_token
        if auth_token.startswith("Bearer "):
            headers = {
                "Content-Type": "application/json",
                "Authorization": auth_token,
            }
        else:
            headers = {
                "Content-Type": "application/json",
                "x-goog-api-key": auth_token,
            }
        body = self._build_request_body(request)

        session = await self._get_session()

        for attempt in range(MAX_RETRIES):
            try:
                self._emit_event({
                    "type": "api_call",
                    "request_id": request_id,
                    "attempt": attempt + 1,
                    "status": "started",
                })

                # Emit api_request event with sanitized body
                self._emit_event({
                    "type": "api_request",
                    "request_id": request_id,
                    "url": url,
                    "method": "POST",
                    "headers": self._sanitize_headers(headers),
                    "body": _sanitize_for_debug(body),
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
                            "body": _sanitize_for_debug(api_response),
                        })
                        return api_response, url

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

                    # 可重试错误
                    if resp.status in (429, 500, 502, 503, 504):
                        retry_after = resp.headers.get("Retry-After")
                        delay = (
                            float(retry_after)
                            if retry_after
                            else RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                        )

                        if attempt < MAX_RETRIES - 1:
                            logger.warning(
                                f"API error {resp.status}, retrying in {delay}s: {error_text[:200]}"
                            )
                            self._emit_event({
                                "type": "api_retry",
                                "request_id": request_id,
                                "attempt": attempt + 1,
                                "status_code": resp.status,
                                "delay": delay,
                            })
                            await asyncio.sleep(delay)
                            continue

                        raise BananaRetryableError(resp.status, error_text, delay)

                    # 不可重试错误
                    raise BananaAPIError(resp.status, error_text)

            except aiohttp.ClientError as e:
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                    logger.warning(f"Network error, retrying in {delay}s: {e}")
                    await asyncio.sleep(delay)
                    continue
                raise BananaRetryableError(0, str(e))

        # 不应该到达这里
        raise BananaAPIError(0, "Max retries exceeded")

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
        """保存图片到文件。

        Returns:
            (file_path, sha256) 元组
        """
        ext_map = {"image/png": "png", "image/jpeg": "jpeg", "image/webp": "webp"}
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
        request: BananaRequest,
        request_id: str,
        api_url: str = "",
        auth_hint: str = "",
    ) -> BananaResponse:
        """解析 API 响应。"""
        if not request.output_dir:
            raise BananaConfigError("output_dir is required")
        output_dir = Path(request.output_dir)

        # task_note 用于文件名前缀，如果为空则使用 request_id
        task_note = request.task_note or request_id

        parts: list[BananaPart] = []
        artifacts: list[BananaArtifact] = []
        grounding_html = ""

        candidates = api_response.get("candidates", [])
        for c_idx, candidate in enumerate(candidates):
            content = candidate.get("content", {})
            for p_idx, part in enumerate(content.get("parts", [])):
                # 文本内容
                if "text" in part:
                    parts.append(BananaPart(
                        index=p_idx,
                        kind="text",
                        content=part["text"],
                        candidate_index=c_idx,
                    ))

                # 思考内容
                if "thought" in part:
                    parts.append(BananaPart(
                        index=p_idx,
                        kind="thought",
                        content=part["thought"],
                        candidate_index=c_idx,
                    ))

                # 图片内容（兼容 inlineData 和 inline_data）
                inline_data = part.get("inlineData") or part.get("inline_data")
                if inline_data:
                    mime_type = inline_data.get("mimeType") or inline_data.get("mime_type", "image/png")
                    b64_data = inline_data.get("data", "")

                    if b64_data:
                        image_bytes = base64.b64decode(b64_data)
                        file_path, sha256 = self._save_image(
                            image_bytes,
                            output_dir,
                            task_note,
                            mime_type,
                        )

                        artifact_id = f"img-{c_idx}-{p_idx}"
                        artifacts.append(BananaArtifact(
                            id=artifact_id,
                            mime_type=mime_type,
                            path=file_path,
                            sha256=sha256,
                        ))

                        parts.append(BananaPart(
                            index=p_idx,
                            kind="image",
                            artifact_id=artifact_id,
                            candidate_index=c_idx,
                        ))

            # Grounding 元数据
            grounding_meta = candidate.get("groundingMetadata", {})
            search_entry = grounding_meta.get("searchEntryPoint", {})
            if "renderedContent" in search_entry:
                grounding_html = search_entry["renderedContent"]

        return BananaResponse(
            request_id=request_id,
            model=self._config.model,
            parts=parts,
            artifacts=artifacts,
            grounding_html=grounding_html,
            success=True,
            api_url=api_url,
            auth_hint=auth_hint,
        )

    async def generate(self, request: BananaRequest) -> BananaResponse:
        """生成图片。

        Args:
            request: 生成请求

        Returns:
            BananaResponse 响应对象
        """
        request_id = str(uuid.uuid4())[:8]
        # 预先构建 debug 信息
        api_url = f"{self._config.base_url}/models/{self._config.model}:generateContent"
        auth_hint = self._mask_token(self._config.auth_token)

        self._emit_event({
            "type": "generation_started",
            "request_id": request_id,
            "prompt": request.prompt[:100],
            "image_count": len(request.images),
        })

        try:
            api_response, api_url = await self._call_api(request, request_id)
            response = self._parse_response(api_response, request, request_id, api_url, auth_hint)

            self._emit_event({
                "type": "generation_completed",
                "request_id": request_id,
                "artifact_count": len(response.artifacts),
                "success": True,
            })

            return response

        except (BananaAPIError, BananaRetryableError, BananaConfigError) as e:
            self._emit_event({
                "type": "generation_failed",
                "request_id": request_id,
                "error": str(e),
                "api_url": api_url,
                "auth_hint": auth_hint,
            })
            return BananaResponse(
                request_id=request_id,
                model=self._config.model,
                success=False,
                error=str(e),
                api_url=api_url,
                auth_hint=auth_hint,
            )

        except asyncio.CancelledError:
            # 取消错误必须 re-raise，不能被吞掉
            self._emit_event({
                "type": "generation_cancelled",
                "request_id": request_id,
            })
            raise

        except Exception as e:
            logger.exception(f"Unexpected error in generate: {e}")
            self._emit_event({
                "type": "generation_failed",
                "request_id": request_id,
                "error": str(e),
                "api_url": api_url,
                "auth_hint": auth_hint,
            })
            return BananaResponse(
                request_id=request_id,
                model=self._config.model,
                success=False,
                error=f"Unexpected error: {e}",
                api_url=api_url,
                auth_hint=auth_hint,
            )
