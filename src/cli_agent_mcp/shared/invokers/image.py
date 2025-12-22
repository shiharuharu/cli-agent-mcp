"""Image Invoker - 图像生成调用器。

cli-agent-mcp shared/invokers v0.1.0

封装 Image API 调用，提供与其他 CLI Invoker 一致的接口。
"""

from __future__ import annotations

import asyncio
import html
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..image import (
    ImageClient,
    ImageInput,
    ImageRequest,
    ImageResponse,
)
from ..parsers import CLISource, make_fallback_event
from .utils import sanitize_task_note, escape_xml

__all__ = ["ImageInvoker", "ImageParams", "ImageExecutionResult"]

logger = logging.getLogger(__name__)


@dataclass
class ImageParams:
    """Image 调用参数。

    Attributes:
        prompt: 提示词
        model: 模型名称（可选，默认从 ENV 读取）
        images: 输入图片列表（必须是绝对路径）
        save_path: 输出目录（可选，默认使用临时目录）
        task_note: 任务备注（用于子目录名称，建议英文）
        aspect_ratio: 纵横比
        resolution: 分辨率（1K/2K/4K）
        quality: 图片质量（generations API）
        api_type: API 类型（空字符串时使用环境变量配置）
    """
    prompt: str
    model: str = ""
    images: list[dict[str, Any]] = field(default_factory=list)
    save_path: str = ""
    task_note: str = ""
    aspect_ratio: str = "1:1"
    resolution: str = "1K"
    quality: str = "standard"
    api_type: str = ""


@dataclass
class ImageExecutionResult:
    """Image 执行结果。

    Attributes:
        success: 是否成功
        request_id: 请求 ID
        response_xml: XML 格式响应（只包含路径，不包含 base64）
        error: 错误信息
        artifacts: 生成的图片路径列表
        duration_sec: 执行时长
    """
    success: bool
    request_id: str = ""
    response_xml: str = ""
    error: str | None = None
    artifacts: list[str] = field(default_factory=list)
    duration_sec: float = 0.0


EventCallback = Any


class ImageInvoker:
    """Image 调用器。

    封装 Image API，提供与 CLI Invoker 一致的接口。

    Example:
        invoker = ImageInvoker()
        result = await invoker.execute(ImageParams(
            prompt="A beautiful sunset",
            task_note="sunset-wallpaper",
        ))
    """

    def __init__(
        self,
        event_callback: EventCallback | None = None,
    ) -> None:
        self._event_callback = event_callback
        self._client: ImageClient | None = None

    @property
    def cli_type(self) -> str:
        return "image"

    @property
    def cli_name(self) -> str:
        return "image"

    def _get_client(self) -> ImageClient:
        if self._client is None:
            self._client = ImageClient(
                event_callback=self._on_client_event,
            )
        return self._client

    def _on_client_event(self, event: dict[str, Any]) -> None:
        if not self._event_callback:
            return

        event_type = event.get("type", "")

        if event_type == "generation_started":
            unified = make_fallback_event(
                CLISource.UNKNOWN,
                {
                    "type": "system",
                    "subtype": "info",
                    "message": f"Processing: {event.get('prompt', '')[:50]}...",
                    "source": "image",
                },
            )
        elif event_type == "generation_completed":
            unified = make_fallback_event(
                CLISource.UNKNOWN,
                {
                    "type": "system",
                    "subtype": "info",
                    "message": f"Generated {event.get('artifact_count', 0)} image(s)",
                    "source": "image",
                },
            )
        elif event_type == "generation_failed":
            unified = make_fallback_event(
                CLISource.UNKNOWN,
                {
                    "type": "system",
                    "subtype": "error",
                    "severity": "error",
                    "message": f"Failed: {event.get('error', 'Unknown error')}",
                    "source": "image",
                },
            )
        elif event_type == "api_retry":
            unified = make_fallback_event(
                CLISource.UNKNOWN,
                {
                    "type": "system",
                    "subtype": "warning",
                    "severity": "warning",
                    "message": f"API error {event.get('status_code')}, retrying in {event.get('delay')}s...",
                    "source": "image",
                },
            )
        else:
            return

        self._event_callback(unified)

    def _parse_images(self, images: list[dict[str, Any]]) -> list[ImageInput]:
        """解析图片输入列表。

        图片路径必须是绝对路径且存在。
        """
        result = []

        for img in images:
            source = img.get("source", "")
            if not source:
                continue

            source_path = Path(source)
            if not source_path.is_absolute():
                logger.warning(f"Skipping non-absolute image path: {source}")
                continue

            # Resolve to real path (follows symlinks)
            try:
                resolved_path = source_path.resolve()
            except (OSError, ValueError) as e:
                logger.warning(f"Skipping invalid image path {source}: {e}")
                continue

            if not resolved_path.exists():
                logger.warning(f"Skipping non-existent image: {resolved_path}")
                continue

            result.append(ImageInput(source=str(resolved_path)))

        return result

    def _build_response_xml(self, response: ImageResponse) -> str:
        request_id = html.escape(response.request_id, quote=True)
        model = html.escape(response.model, quote=True)

        lines = [
            f'<image-response request_id="{request_id}" model="{model}">'
        ]

        if response.text_content:
            lines.append(f'  <text>{_escape_xml(response.text_content)}</text>')

        for artifact in response.artifacts:
            artifact_id = html.escape(artifact.id, quote=True)
            kind = html.escape(artifact.kind, quote=True)
            mime_type = html.escape(artifact.mime_type, quote=True)
            path = html.escape(artifact.path, quote=True)
            sha256 = html.escape(artifact.sha256, quote=True)
            lines.append(
                f'  <artifact id="{artifact_id}" kind="{kind}" '
                f'mime_type="{mime_type}" path="{path}" '
                f'sha256="{sha256}"/>'
            )

        lines.append('</image-response>')
        return '\n'.join(lines)

    async def execute(self, params: ImageParams) -> ImageExecutionResult:
        start_time = time.time()

        if not params.prompt:
            return ImageExecutionResult(
                success=False,
                error="prompt is required",
            )

        # 处理 save_path（不再创建子目录）
        output_dir = params.save_path

        # 清理 task_note 用于文件名前缀
        task_note = sanitize_task_note(params.task_note)

        request = ImageRequest(
            prompt=params.prompt,
            model=params.model,
            images=self._parse_images(params.images),
            output_dir=output_dir,
            task_note=task_note,
            aspect_ratio=params.aspect_ratio,
            resolution=params.resolution,
            quality=params.quality,
            api_type=params.api_type,
        )

        client = self._get_client()
        try:
            response = await client.generate(request)

            duration = time.time() - start_time

            if not response.success:
                return ImageExecutionResult(
                    success=False,
                    request_id=response.request_id,
                    error=response.error,
                    duration_sec=duration,
                )

            response_xml = self._build_response_xml(response)

            return ImageExecutionResult(
                success=True,
                request_id=response.request_id,
                response_xml=response_xml,
                artifacts=[a.path for a in response.artifacts],
                duration_sec=duration,
            )

        except asyncio.CancelledError:
            raise

        except Exception as e:
            logger.exception(f"Image execution failed: {e}")
            return ImageExecutionResult(
                success=False,
                error=str(e),
                duration_sec=time.time() - start_time,
            )

        finally:
            if self._client:
                await self._client.close()
                self._client = None
