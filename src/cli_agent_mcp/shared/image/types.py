"""Image 模块类型定义。

cli-agent-mcp shared/image v0.1.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

__all__ = [
    "ImageInput",
    "ImageRequest",
    "ImageArtifact",
    "ImageResponse",
    "map_to_size",
]


# 参数映射：aspect_ratio + resolution -> size
SIZE_MAP = {
    # 1K resolution
    ("1:1", "1K"): "1024x1024",
    ("16:9", "1K"): "1792x1024",
    ("9:16", "1K"): "1024x1792",
    ("2:3", "1K"): "683x1024",
    ("3:2", "1K"): "1024x683",
    ("3:4", "1K"): "768x1024",
    ("4:3", "1K"): "1024x768",
    ("4:5", "1K"): "819x1024",
    ("5:4", "1K"): "1024x819",
    ("21:9", "1K"): "1792x768",
    # 2K resolution
    ("1:1", "2K"): "2048x2048",
    ("16:9", "2K"): "3584x2048",
    ("9:16", "2K"): "2048x3584",
    # 4K resolution
    ("1:1", "4K"): "4096x4096",
    ("16:9", "4K"): "7168x4096",
    ("9:16", "4K"): "4096x7168",
}


def map_to_size(aspect_ratio: str, resolution: str) -> str:
    """将 aspect_ratio + resolution 映射到 OpenAI size 格式。

    Args:
        aspect_ratio: 纵横比（如 "1:1", "16:9", "9:16"）
        resolution: 分辨率（如 "1K", "2K", "4K"）

    Returns:
        OpenAI size 格式（如 "1024x1024"）
    """
    key = (aspect_ratio, resolution.upper())
    return SIZE_MAP.get(key, "1024x1024")


@dataclass
class ImageInput:
    """图片输入。

    Attributes:
        source: 文件路径（绝对路径）
    """
    source: str


@dataclass
class ImageRequest:
    """Image API 请求。

    Attributes:
        prompt: 自然语言提示词
        model: 模型名称
        images: 输入图片列表
        output_dir: 输出目录（图片落盘位置）
        task_note: 任务备注（用于文件名前缀）
        aspect_ratio: 纵横比
        resolution: 分辨率（1K/2K/4K）
        quality: 图片质量（generations API）
        api_type: API 类型（空字符串时使用环境变量配置）
    """
    prompt: str
    model: str = ""
    images: list[ImageInput] = field(default_factory=list)
    output_dir: str = ""
    task_note: str = ""
    aspect_ratio: str = "1:1"
    resolution: str = "1K"
    quality: str = "standard"
    api_type: str = ""

    def get_size(self) -> str:
        """获取 OpenAI size 格式。"""
        return map_to_size(self.aspect_ratio, self.resolution)


@dataclass
class ImageArtifact:
    """图片 artifact。

    Attributes:
        id: artifact ID
        kind: 类型（固定为 image）
        mime_type: MIME 类型
        path: 落盘路径（绝对路径）
        sha256: 文件哈希
    """
    id: str
    kind: Literal["image"] = "image"
    mime_type: str = "image/png"
    path: str = ""
    sha256: str = ""


@dataclass
class ImageResponse:
    """Image API 响应。

    Attributes:
        request_id: 请求 ID
        model: 使用的模型
        text_content: 文本响应内容
        artifacts: 图片 artifact 列表
        success: 是否成功
        error: 错误信息
        api_url: 请求的 API 完整路径（用于 debug）
        auth_hint: 脱敏后的认证信息（用于 debug）
    """
    request_id: str
    model: str = ""
    text_content: str = ""
    artifacts: list[ImageArtifact] = field(default_factory=list)
    success: bool = True
    error: str = ""
    api_url: str = ""
    auth_hint: str = ""
