"""Banana Invoker - 图像生成调用器。

cli-agent-mcp shared/invokers v0.1.0
同步日期: 2025-12-21

封装 Nano Banana Pro API 调用，提供与其他 CLI Invoker 一致的接口。
"""

from __future__ import annotations

import asyncio
import html
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

from ..banana import (
    BananaConfig,
    BananaRequest,
    BananaResponse,
    ImageInput,
    ImageRole,
    NanoBananaProClient,
    AspectRatio,
    ImageSize,
)
from ..parsers import CLISource, EventCategory, make_fallback_event, UnifiedEvent
from .utils import sanitize_task_note, escape_xml

__all__ = ["BananaInvoker", "BananaParams"]

logger = logging.getLogger(__name__)


@dataclass
class BananaParams:
    """Banana 调用参数。

    Attributes:
        prompt: 图像生成提示词
        images: 参考图片列表
        aspect_ratio: 输出宽高比
        resolution: 输出分辨率
        use_search: 启用搜索 grounding
        include_thoughts: 返回思考过程
        temperature: 控制随机性 (0.0-2.0)
        top_p: Nucleus sampling (0.0-1.0)
        top_k: Top-k sampling (1-100)
        num_images: 生成数量 (1-4)
        save_path: 输出目录
        task_note: 任务备注（用于 GUI 显示和子目录名）
    """
    prompt: str
    images: list[dict[str, Any]] = field(default_factory=list)
    aspect_ratio: str = "1:1"
    resolution: str = "1K"
    use_search: bool = False
    include_thoughts: bool = False
    temperature: float = 1.0
    top_p: float = 0.95
    top_k: int = 40
    num_images: int = 1
    save_path: str = ""
    task_note: str = ""


@dataclass
class BananaExecutionResult:
    """Banana 执行结果。

    Attributes:
        success: 是否成功
        request_id: 请求 ID
        response_xml: XML 格式响应（只包含路径，不包含 base64）
        error: 错误信息
        artifacts: 生成的图片路径列表
        duration_sec: 执行时长
        model: 使用的模型
        api_endpoint: API 端点 URL
        auth_token_masked: 脱敏后的 auth token
    """
    success: bool
    request_id: str = ""
    response_xml: str = ""
    error: str | None = None
    artifacts: list[str] = field(default_factory=list)
    duration_sec: float = 0.0
    model: str = ""
    api_endpoint: str = ""
    auth_token_masked: str = ""


# 事件回调类型
EventCallback = Any  # Callable[[UnifiedEvent], None]


class BananaInvoker:
    """Banana 图像生成调用器。

    封装 Nano Banana Pro API，提供与 CLI Invoker 一致的接口。

    Example:
        invoker = BananaInvoker()
        result = await invoker.execute(BananaParams(
            prompt="Create a cute cat",
        ))
    """

    def __init__(
        self,
        event_callback: EventCallback | None = None,
    ) -> None:
        """初始化调用器。

        Args:
            event_callback: 事件回调函数（用于 GUI 推送）
        """
        self._event_callback = event_callback
        self._client: NanoBananaProClient | None = None

    @property
    def cli_type(self) -> str:
        return "banana"

    @property
    def cli_name(self) -> str:
        return "banana"

    def _get_client(self) -> NanoBananaProClient:
        """获取或创建 API 客户端。"""
        if self._client is None:
            self._client = NanoBananaProClient(
                event_callback=self._on_client_event,
            )
        return self._client

    def _on_client_event(self, event: dict[str, Any]) -> None:
        """处理客户端事件并转发到 GUI。"""
        if not self._event_callback:
            return

        # 转换为 UnifiedEvent
        event_type = event.get("type", "")

        if event_type == "generation_started":
            unified = make_fallback_event(
                CLISource.UNKNOWN,
                {
                    "type": "system",
                    "subtype": "info",
                    "message": f"Generating image: {event.get('prompt', '')[:50]}...",
                    "source": "banana",
                },
            )
        elif event_type == "generation_completed":
            unified = make_fallback_event(
                CLISource.UNKNOWN,
                {
                    "type": "system",
                    "subtype": "info",
                    "message": f"Generated {event.get('artifact_count', 0)} image(s)",
                    "source": "banana",
                },
            )
        elif event_type == "generation_failed":
            unified = make_fallback_event(
                CLISource.UNKNOWN,
                {
                    "type": "system",
                    "subtype": "error",
                    "severity": "error",
                    "message": f"Generation failed: {event.get('error', 'Unknown error')}",
                    "source": "banana",
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
                    "source": "banana",
                },
            )
        else:
            return  # 忽略其他事件

        self._event_callback(unified)

    def _parse_images(self, images: list[dict[str, Any]]) -> list[ImageInput]:
        """解析图片输入列表。"""
        result = []
        for img in images:
            source = img.get("source", "")
            if not source:
                continue

            source_path = Path(source)
            if not source_path.is_absolute():
                logger.warning(f"Skipping non-absolute image path: {source}")
                continue

            if not source_path.exists():
                logger.warning(f"Skipping non-existent image: {source_path}")
                continue

            # 解析角色
            role_str = img.get("role", "")
            role = None
            if role_str:
                try:
                    role = ImageRole(role_str)
                except ValueError:
                    pass

            result.append(ImageInput(
                source=str(source_path),
                role=role,
                label=img.get("label", ""),
            ))

        return result

    def _build_response_xml(self, response: BananaResponse) -> str:
        """构建 XML 格式响应（不包含 base64）。"""
        request_id = html.escape(response.request_id, quote=True)
        model = html.escape(response.model, quote=True)

        # 构建 artifact_id -> path 映射
        artifact_paths = {a.id: a.path for a in response.artifacts}

        lines = [
            f'<nano-banana-response request_id="{request_id}" model="{model}">'
        ]

        # 按 candidate_index 分组 parts
        from itertools import groupby
        sorted_parts = sorted(response.parts, key=lambda p: p.candidate_index)
        for c_idx, group in groupby(sorted_parts, key=lambda p: p.candidate_index):
            lines.append(f'  <candidate index="{c_idx}">')
            for part in group:
                if part.kind == "text":
                    lines.append(f'    <part index="{part.index}" kind="text">{_escape_xml(part.content)}</part>')
                elif part.kind == "thought":
                    lines.append(f'    <part index="{part.index}" kind="thought">{_escape_xml(part.content)}</part>')
                elif part.kind == "image":
                    # 直接输出路径，减少 token 消耗
                    path = html.escape(artifact_paths.get(part.artifact_id, ""), quote=True)
                    lines.append(f'    <part index="{part.index}" kind="image" path="{path}"/>')
            lines.append('  </candidate>')

        # Grounding
        if response.grounding_html:
            lines.append('  <grounding>')
            lines.append(f'    <html><![CDATA[{response.grounding_html}]]></html>')
            lines.append('  </grounding>')

        lines.append('</nano-banana-response>')
        return '\n'.join(lines)

    async def execute(self, params: BananaParams) -> BananaExecutionResult:
        """执行图像生成。

        Args:
            params: 调用参数

        Returns:
            执行结果
        """
        start_time = time.time()

        # 验证参数
        if not params.prompt:
            return BananaExecutionResult(
                success=False,
                error="prompt is required",
            )

        # 处理 save_path（不再创建子目录）
        output_dir = params.save_path

        # 清理 task_note 用于文件名前缀
        task_note = sanitize_task_note(params.task_note)

        # 解析宽高比
        try:
            aspect_ratio = AspectRatio(params.aspect_ratio)
        except ValueError:
            aspect_ratio = AspectRatio.RATIO_1_1

        # 解析分辨率
        try:
            image_size = ImageSize(params.resolution)
        except ValueError:
            image_size = ImageSize.SIZE_1K

        # 构建请求
        request = BananaRequest(
            prompt=params.prompt,
            images=self._parse_images(params.images),
            config=BananaConfig(
                aspect_ratio=aspect_ratio,
                image_size=image_size,
                use_search=params.use_search,
                include_thoughts=params.include_thoughts,
                temperature=params.temperature,
                top_p=params.top_p,
                top_k=params.top_k,
                num_images=params.num_images,
            ),
            output_dir=output_dir,
            task_note=task_note,
        )

        # 执行生成
        client = self._get_client()
        try:
            response = await client.generate(request)

            duration = time.time() - start_time

            if not response.success:
                return BananaExecutionResult(
                    success=False,
                    request_id=response.request_id,
                    error=response.error,
                    duration_sec=duration,
                    model=response.model,
                    api_endpoint=response.api_url,
                    auth_token_masked=response.auth_hint,
                )

            # 构建 XML 响应
            response_xml = self._build_response_xml(response)

            return BananaExecutionResult(
                success=True,
                request_id=response.request_id,
                response_xml=response_xml,
                artifacts=[a.path for a in response.artifacts],
                duration_sec=duration,
                model=response.model,
                api_endpoint=response.api_url,
                auth_token_masked=response.auth_hint,
            )

        except asyncio.CancelledError:
            # 取消错误必须 re-raise，不能被吞掉
            raise

        except Exception as e:
            logger.exception(f"Banana execution failed: {e}")
            return BananaExecutionResult(
                success=False,
                error=str(e),
                duration_sec=time.time() - start_time,
            )

        finally:
            # 关闭客户端
            if self._client:
                await self._client.close()
                self._client = None
