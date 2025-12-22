"""图片编解码工具。

cli-agent-mcp shared/banana v0.1.0
同步日期: 2025-12-21

仅用于读取参考图片并编码为 base64。
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

__all__ = [
    "encode_image_to_base64",
    "get_mime_type",
]


def get_mime_type(file_path: str | Path) -> str:
    """获取文件的 MIME 类型。

    Args:
        file_path: 文件路径

    Returns:
        MIME 类型字符串，默认 image/png
    """
    path = Path(file_path)
    mime_type, _ = mimetypes.guess_type(str(path))
    return mime_type or "image/png"


def encode_image_to_base64(file_path: str | Path) -> tuple[str, str]:
    """读取图片文件并编码为 base64。

    Args:
        file_path: 图片文件路径

    Returns:
        (base64_data, mime_type) 元组

    Raises:
        FileNotFoundError: 文件不存在
        IOError: 读取失败
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {path}")

    mime_type = get_mime_type(path)
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")

    return data, mime_type
