"""图像生成工具处理器。

处理 banana 和 image 工具调用。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mcp.types import TextContent

from .base import ToolContext, ToolHandler
from ..shared.invokers import BananaInvoker, BananaParams, ImageInvoker, ImageParams
from ..shared.response_formatter import ResponseData, get_formatter, format_error_response
from ..tool_schema import create_tool_schema

__all__ = ["BananaHandler", "ImageHandler"]

logger = logging.getLogger(__name__)


class BananaHandler(ToolHandler):
    """Banana 图像生成工具处理器。"""

    @property
    def name(self) -> str:
        return "banana"

    @property
    def description(self) -> str:
        return """Generate images using Nano Banana Pro (Gemini 3 Pro Image).

CAPABILITIES:
- Text-to-image generation with high quality output
- Image editing and transformation with reference images
- Multiple aspect ratios and resolutions (1K/2K/4K)
- Style transfer and multi-image fusion
- Optional search grounding for factual content

RESPONSE FORMAT:
- Returns XML with file paths to generated images
- Images are saved to disk (no base64 in response)
- Includes text descriptions and optional thinking process

BEST PRACTICES:
- Be descriptive: describe scenes, not just keywords
- Use negative constraints in prompt: "no text", "no watermark"
- For editing: provide reference image and specify what to keep
- For style transfer: provide style reference image

Supports: reference images with roles (edit_base, style_ref, etc.)."""

    def get_input_schema(self) -> dict[str, Any]:
        return create_tool_schema("banana")

    def validate(self, arguments: dict[str, Any]) -> str | None:
        if not arguments.get("prompt"):
            return "Missing required argument: 'prompt'"
        if not arguments.get("save_path"):
            return "Missing required argument: 'save_path'"
        if not arguments.get("task_note"):
            return "Missing required argument: 'task_note'"
        return None

    async def handle(
        self,
        arguments: dict[str, Any],
        ctx: ToolContext,
    ) -> list[TextContent]:
        error = self.validate(arguments)
        if error:
            return format_error_response(error)

        prompt = arguments.get("prompt", "")
        task_note = arguments.get("task_note", "")

        # 推送用户 prompt 到 GUI
        ctx.push_user_prompt("banana", prompt, task_note)

        # 创建事件回调
        def event_callback(event: Any) -> None:
            if ctx.gui_manager and ctx.gui_manager.is_running:
                event_dict = event.model_dump() if hasattr(event, "model_dump") else dict(event.__dict__)
                event_dict["source"] = "banana"
                ctx.gui_manager.push_event(event_dict)

        # 创建 invoker 并执行
        invoker = BananaInvoker(event_callback=event_callback)

        params = BananaParams(
            prompt=prompt,
            images=arguments.get("images", []),
            aspect_ratio=arguments.get("aspect_ratio", "1:1"),
            resolution=arguments.get("resolution", "4K"),
            use_search=arguments.get("use_search", False),
            include_thoughts=arguments.get("include_thoughts", False),
            temperature=arguments.get("temperature", 1.0),
            top_p=arguments.get("top_p", 0.95),
            top_k=arguments.get("top_k", 40),
            num_images=arguments.get("num_images", 1),
            # DESIGN: save_path 在 permission='read-only' 下允许写入是特性（用于保存生成结果），不是风险或越权。
            save_path=arguments.get("save_path", ""),
            task_note=task_note,
        )

        try:
            result = await invoker.execute(params)

            if result.success:
                response = result.response_xml

                # 添加 debug_info（仅当 debug 开启时）
                debug_enabled = ctx.resolve_debug(arguments)
                if debug_enabled and result.artifacts:
                    response += (
                        f"\n<debug_info>"
                        f"\n  <image_count>{len(result.artifacts)}</image_count>"
                        f"\n  <duration_sec>{result.duration_sec:.3f}</duration_sec>"
                        f"\n  <model>{result.model}</model>"
                        f"\n  <api_endpoint>{result.api_endpoint}</api_endpoint>"
                        f"\n  <auth_token>{result.auth_token_masked}</auth_token>"
                        f"\n</debug_info>"
                    )

                # 推送结果到 GUI
                gui_metadata: dict[str, Any] = {
                    "artifacts": result.artifacts,
                    "task_note": task_note,
                }
                if debug_enabled:
                    gui_metadata["debug"] = {
                        "image_count": len(result.artifacts),
                        "duration_sec": result.duration_sec,
                        "model": result.model,
                        "api_endpoint": result.api_endpoint,
                        "auth_token": result.auth_token_masked,
                    }
                ctx.push_to_gui({
                    "category": "operation",
                    "operation_type": "tool_call",
                    "source": "banana",
                    "session_id": f"banana_{result.request_id}",
                    "name": "banana",
                    "status": "success",
                    "output": response,
                    "metadata": gui_metadata,
                })

                return [TextContent(type="text", text=response)]
            else:
                return format_error_response(result.error or "Unknown error")

        except asyncio.CancelledError:
            raise

        except Exception as e:
            logger.exception(f"Banana tool error: {e}")
            return format_error_response(str(e))


class ImageHandler(ToolHandler):
    """Image 图像生成工具处理器。"""

    @property
    def name(self) -> str:
        return "image"

    @property
    def description(self) -> str:
        return """Generate images via OpenRouter-compatible or OpenAI-compatible endpoints.

CAPABILITIES:
- Text-to-image generation with multiple providers
- Image editing and transformation with reference images
- Multiple aspect ratios and resolutions (1K/2K/4K)

RESPONSE FORMAT:
- Returns XML with file paths to generated images
- Images saved to disk (no base64 in response)
- Includes text descriptions when available

BEST PRACTICES:
- Be descriptive: describe scenes, lighting, style, composition
- Use negative constraints in prompt: "no text", "no watermark", "no blur"
- For editing: provide reference image and specify what to keep

Supports: reference images for editing."""

    def get_input_schema(self) -> dict[str, Any]:
        return create_tool_schema("image")

    def validate(self, arguments: dict[str, Any]) -> str | None:
        if not arguments.get("prompt"):
            return "Missing required argument: 'prompt'"
        if not arguments.get("save_path"):
            return "Missing required argument: 'save_path'"
        if not arguments.get("task_note"):
            return "Missing required argument: 'task_note'"
        return None

    async def handle(
        self,
        arguments: dict[str, Any],
        ctx: ToolContext,
    ) -> list[TextContent]:
        error = self.validate(arguments)
        if error:
            return format_error_response(error)

        prompt = arguments.get("prompt", "")
        task_note = arguments.get("task_note", "")

        # 推送用户 prompt 到 GUI
        ctx.push_user_prompt("image", prompt, task_note)

        # 创建事件回调
        def event_callback(event: Any) -> None:
            if ctx.gui_manager and ctx.gui_manager.is_running:
                event_dict = event.model_dump() if hasattr(event, "model_dump") else dict(event.__dict__)
                event_dict["source"] = "image"
                ctx.gui_manager.push_event(event_dict)

        # 创建 invoker 并执行
        invoker = ImageInvoker(event_callback=event_callback)

        params = ImageParams(
            prompt=prompt,
            model=arguments.get("model", ""),
            images=arguments.get("images", []),
            # DESIGN: save_path 在 permission='read-only' 下允许写入是特性（用于保存生成结果），不是风险或越权。
            save_path=arguments.get("save_path", ""),
            task_note=task_note,
            aspect_ratio=arguments.get("aspect_ratio", "1:1"),
            resolution=arguments.get("resolution", "1K"),
            quality=arguments.get("quality", "standard"),
            api_type=arguments.get("api_type", ""),
        )

        try:
            result = await invoker.execute(params)

            if result.success:
                response = result.response_xml

                # 添加 debug_info（仅当 debug 开启时）
                debug_enabled = ctx.resolve_debug(arguments)
                if debug_enabled:
                    response += (
                        f"\n<debug_info>"
                        f"\n  <image_count>{len(result.artifacts) if result.artifacts else 0}</image_count>"
                        f"\n  <duration_sec>{result.duration_sec:.3f}</duration_sec>"
                        f"\n  <model>{params.model or 'env:IMAGE_MODEL'}</model>"
                        f"\n  <api_type>{params.api_type or 'env:IMAGE_API_TYPE'}</api_type>"
                        f"\n</debug_info>"
                    )

                # 推送结果到 GUI
                gui_metadata: dict[str, Any] = {
                    "artifacts": result.artifacts,
                    "task_note": task_note,
                }
                if debug_enabled:
                    gui_metadata["debug"] = {
                        "image_count": len(result.artifacts) if result.artifacts else 0,
                        "duration_sec": result.duration_sec,
                        "model": params.model or "env:IMAGE_MODEL",
                        "api_type": params.api_type or "env:IMAGE_API_TYPE",
                    }
                ctx.push_to_gui({
                    "category": "operation",
                    "operation_type": "tool_call",
                    "source": "image",
                    "session_id": f"image_{result.request_id}",
                    "name": "image",
                    "status": "success",
                    "output": response,
                    "metadata": gui_metadata,
                })

                return [TextContent(type="text", text=response)]
            else:
                return format_error_response(result.error or "Unknown error")

        except asyncio.CancelledError:
            raise

        except Exception as e:
            logger.exception(f"Image tool error: {e}")
            return format_error_response(str(e))
