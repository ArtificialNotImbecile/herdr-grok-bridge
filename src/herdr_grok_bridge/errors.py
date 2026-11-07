"""MCP tool result helpers.

Failures must set ``CallToolResult.is_error=True`` (wire field ``isError: true``).
Returning an error-shaped JSON object with ``is_error=False`` is treated as
success by clients and is not allowed for validation/backend failures.
"""

from __future__ import annotations

import json
from typing import Any

from mcp_types import CallToolResult, TextContent


def tool_error_result(message: str) -> CallToolResult:
    """Build an MCP tool failure result (``isError: true`` on the wire)."""
    text = str(message).strip() or "tool_error"
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        is_error=True,
    )


def tool_success_result(payload: dict[str, Any]) -> CallToolResult:
    """Build a successful tool result (``isError: false``) with JSON text."""
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=payload,
        is_error=False,
    )
