"""Strict validation for tool inputs.

Read targets must be live pane ids (for example ``w1:p2``), never bare agent
kinds such as ``claude``.
"""

from __future__ import annotations

import re
from typing import Literal

ReadSource = Literal["visible", "recent", "recent-unwrapped", "detection"]

ALLOWED_SOURCES: frozenset[str] = frozenset(
    {"visible", "recent", "recent-unwrapped", "detection"}
)

# Herdr pane ids look like "w1:p2" / "wF:p1". Require an explicit pane suffix.
PANE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}:p[0-9]{1,6}$")

# Common bare agent-kind labels that must never be accepted as targets.
BARE_KIND_RE = re.compile(
    r"^(claude|codex|gemini|gpt|opencode|aider|cursor|amp|goose)([_-].*)?$",
    re.IGNORECASE,
)

DEFAULT_RECENT_LINES = 80
MIN_LINES = 1


class ValidationError(ValueError):
    """Invalid tool input."""


def validate_pane_id(pane_id: str) -> str:
    """Return a sanitized live pane id or raise ValidationError."""
    if not isinstance(pane_id, str):
        raise ValidationError("pane_id must be a string")
    value = pane_id.strip()
    if not value:
        raise ValidationError("pane_id must not be empty")
    if any(ch.isspace() for ch in value):
        raise ValidationError("pane_id must not contain whitespace")
    if BARE_KIND_RE.match(value) or ":" not in value:
        raise ValidationError(
            "pane_id must be a live Herdr pane id (for example 'w1:p2'), "
            "not a bare agent kind or name"
        )
    if not PANE_ID_RE.match(value):
        raise ValidationError(
            "pane_id must match Herdr pane form like 'w1:p2' "
            "(workspace token + ':p' + digits)"
        )
    return value


def validate_source(source: str) -> ReadSource:
    """Validate a pane-read source."""
    if not isinstance(source, str):
        raise ValidationError("source must be a string")
    value = source.strip()
    if value not in ALLOWED_SOURCES:
        raise ValidationError(
            "source must be one of: visible, recent, recent-unwrapped, detection"
        )
    return value  # type: ignore[return-value]


def validate_lines(lines: int | None, *, max_lines: int) -> int | None:
    """Validate an optional line bound.

    Returns None when the caller should omit ``--lines`` (visible/detection
    compatibility path decides separately).
    """
    if lines is None:
        return None
    if not isinstance(lines, int) or isinstance(lines, bool):
        raise ValidationError("lines must be an integer")
    if lines < MIN_LINES:
        raise ValidationError(f"lines must be >= {MIN_LINES}")
    if lines > max_lines:
        raise ValidationError(f"lines must be <= {max_lines}")
    return lines


def resolve_read_lines(
    source: ReadSource,
    lines: int | None,
    *,
    max_lines: int,
) -> int | None:
    """Decide whether ``--lines`` should be passed for this source.

    Some Herdr versions reject ``--lines`` together with ``visible`` /
    ``detection``. For those sources we omit ``--lines`` entirely and truncate
    client-side after the read. For recent sources we always pass a capped
    ``--lines`` value.
    """
    validated = validate_lines(lines, max_lines=max_lines)
    if source in ("visible", "detection"):
        # Compatibility: never send --lines for these sources.
        return None
    return validated if validated is not None else min(DEFAULT_RECENT_LINES, max_lines)
