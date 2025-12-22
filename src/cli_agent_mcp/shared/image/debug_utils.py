"""Debug utilities for image API clients.

cli-agent-mcp shared/image v0.1.0
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable

EventCallback = Callable[[dict[str, Any]], None]


def sanitize_for_debug(data: Any) -> Any:
    """Sanitize data for debug output, replacing base64 strings with summaries."""
    if isinstance(data, dict):
        return {k: sanitize_for_debug(v) for k, v in data.items()}
    if isinstance(data, list):
        return [sanitize_for_debug(item) for item in data]
    if isinstance(data, str) and len(data) > 100:
        # Check if it looks like base64
        if re.match(r'^[A-Za-z0-9+/=]+$', data[:100]):
            return f"<base64:{len(data)} bytes>"
    return data


def sanitize_headers(headers: dict[str, str]) -> dict[str, str]:
    """Sanitize headers for debug output, masking auth tokens."""
    result = {}
    for k, v in headers.items():
        if k.lower() in ("authorization", "x-goog-api-key"):
            result[k] = "***"
        else:
            result[k] = v
    return result
