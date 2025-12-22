"""Banana 模块类型定义。

cli-agent-mcp shared/banana v0.1.0
同步日期: 2025-12-21
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal

__all__ = [
    "AspectRatio",
    "ImageSize",
    "ImageRole",
    "ImageInput",
    "BananaConfig",
    "BananaRequest",
    "BananaPart",
    "BananaArtifact",
    "BananaResponse",
]


class AspectRatio(str, Enum):
    """输出图片宽高比。"""
    RATIO_1_1 = "1:1"
    RATIO_2_3 = "2:3"
    RATIO_3_2 = "3:2"
    RATIO_3_4 = "3:4"
    RATIO_4_3 = "4:3"
    RATIO_4_5 = "4:5"
    RATIO_5_4 = "5:4"
    RATIO_9_16 = "9:16"
    RATIO_16_9 = "16:9"
    RATIO_21_9 = "21:9"


class ImageSize(str, Enum):
    """输出图片分辨率。"""
    SIZE_1K = "1K"  # 最高 1024x1024
    SIZE_2K = "2K"  # 最高 2048x2048
    SIZE_4K = "4K"  # 最高 4096x4096


class ImageRole(str, Enum):
    """参考图片角色。"""
    EDIT_BASE = "edit_base"           # 被编辑的底图
    SUBJECT_REF = "subject_ref"       # 人物/角色参考
    STYLE_REF = "style_ref"           # 风格参考
    LAYOUT_REF = "layout_ref"         # 版式参考
    BACKGROUND_REF = "background_ref" # 背景参考
    OBJECT_REF = "object_ref"         # 物体参考


@dataclass
class ImageInput:
    """图片输入。

    Attributes:
        source: 文件路径（绝对路径）
        role: 可选角色标注
        label: 可选标签
    """
    source: str
    role: ImageRole | None = None
    label: str = ""


@dataclass
class BananaConfig:
    """生成配置。

    Attributes:
        aspect_ratio: 输出宽高比
        image_size: 输出分辨率
        use_search: 启用搜索 grounding
        include_thoughts: 返回思考过程
        temperature: 控制随机性 (0.0-2.0)
        top_p: Nucleus sampling (0.0-1.0)
        top_k: Top-k sampling (1-100)
        num_images: 生成数量 (1-4)
    """
    aspect_ratio: AspectRatio = AspectRatio.RATIO_1_1
    image_size: ImageSize = ImageSize.SIZE_1K
    use_search: bool = False
    include_thoughts: bool = False
    temperature: float = 1.0
    top_p: float = 0.95
    top_k: int = 40
    num_images: int = 1


@dataclass
class BananaRequest:
    """Banana API 请求。

    Attributes:
        prompt: 自然语言提示词
        images: 参考图片列表
        config: 生成配置
        output_dir: 输出目录（图片落盘位置）
        task_note: 任务备注（用于文件名前缀）
    """
    prompt: str
    images: list[ImageInput] = field(default_factory=list)
    config: BananaConfig = field(default_factory=BananaConfig)
    output_dir: str = ""
    task_note: str = ""


@dataclass
class BananaPart:
    """响应内容部分。

    Attributes:
        index: 部分索引
        kind: 内容类型 (text/image/thought)
        content: 文本内容（kind=text/thought 时）
        artifact_id: 图片 artifact ID（kind=image 时）
        candidate_index: 候选索引（用于多图生成）
    """
    index: int
    kind: Literal["text", "image", "thought"]
    content: str = ""
    artifact_id: str = ""
    candidate_index: int = 0


@dataclass
class BananaArtifact:
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
class BananaResponse:
    """Banana API 响应。

    Attributes:
        request_id: 请求 ID
        model: 使用的模型
        parts: 内容部分列表
        artifacts: 图片 artifact 列表
        grounding_html: 搜索来源 HTML（如果启用 use_search）
        success: 是否成功
        error: 错误信息
        api_url: 请求的 API 完整路径（用于 debug）
        auth_hint: 脱敏后的认证信息（用于 debug）
    """
    request_id: str
    model: str = ""  # 由 config.model 填充
    parts: list[BananaPart] = field(default_factory=list)
    artifacts: list[BananaArtifact] = field(default_factory=list)
    grounding_html: str = ""
    success: bool = True
    error: str = ""
    api_url: str = ""
    auth_hint: str = ""
