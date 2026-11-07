"""Conservative secrets redaction for pane text returned to MCP clients."""

from __future__ import annotations

import re

# Patterns intentionally broad; false positives are preferred over leaks.
# Order matters: match full Bearer / key lines before shorter key=value clips.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*"),
        "Bearer [REDACTED]",
    ),
    (
        re.compile(
            r"(?i)\b(authorization|api[_-]?key|secret|token|password|passwd|credential)s?\b\s*[:=]\s*\S+"
        ),
        r"\1=[REDACTED]",
    ),
    (
        re.compile(r"\b(sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})\b"),
        "[REDACTED_TOKEN]",
    ),
    (
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "[REDACTED_AWS_KEY]",
    ),
    (
        re.compile(
            r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
]


def redact_secrets(text: str) -> str:
    """Return text with common credential shapes replaced."""
    if not text:
        return text
    out = text
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return out


def bound_text(text: str, max_chars: int) -> tuple[str, bool]:
    """Truncate text to max_chars. Returns (text, truncated)."""
    if max_chars <= 0:
        return "", True
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars] + "\n…[truncated]", True
