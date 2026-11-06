"""Hard allowlist for Herdr argv sequences.

Only three read operations are constructible. Everything else — including
generic RPC, shell, prompts, focus, and pane mutation — is refused.
"""

from __future__ import annotations

from .validation import (
    ReadSource,
    resolve_read_lines,
    validate_pane_id,
    validate_source,
)

# Tokens that must never appear in constructed Herdr argv (defense in depth).
FORBIDDEN_TOKENS = frozenset(
    {
        "prompt",
        "send-keys",
        "send-text",
        "send_keys",
        "send_text",
        "start",
        "attach",
        "focus",
        "rename",
        "close",
        "split",
        "swap",
        "move",
        "resize",
        "zoom",
        "input",
        "run",
        "create",
        "api",
        "rpc",
        "shell",
        "exec",
        "machine",
        "wait",
        "wait-output",
        "subscribe",
        "notification",
        "worktree",
        "--",  # never pass a raw "--" that could inject agent args
    }
)


class AllowlistError(PermissionError):
    """Attempted command is outside the read-only allowlist."""


def _assert_safe_tokens(argv: list[str]) -> None:
    for token in argv:
        lowered = token.lower()
        # Allow pane ids / sources / numeric flags; reject known mutators.
        if lowered in FORBIDDEN_TOKENS:
            raise AllowlistError(f"refusing forbidden herdr token: {token}")
        if lowered.startswith("-") and lowered not in {
            "--format",
            "--source",
            "--lines",
        }:
            # Only the few read flags we emit are permitted.
            raise AllowlistError(f"refusing unexpected flag: {token}")


def build_agent_list_argv() -> list[str]:
    """``herdr agent list --format json``."""
    argv = ["agent", "list", "--format", "json"]
    _assert_safe_tokens(argv)
    return argv


def build_agent_status_argv(pane_id: str) -> list[str]:
    """``herdr agent get <pane_id> --format json``."""
    pid = validate_pane_id(pane_id)
    argv = ["agent", "get", pid, "--format", "json"]
    _assert_safe_tokens(argv)
    return argv


def build_pane_read_argv(
    pane_id: str,
    source: str,
    lines: int | None,
    *,
    max_lines: int,
) -> list[str]:
    """``herdr pane read <pane_id> --source ... [--lines N]`` (no mutation)."""
    pid = validate_pane_id(pane_id)
    src: ReadSource = validate_source(source)
    resolved_lines = resolve_read_lines(src, lines, max_lines=max_lines)
    argv = ["pane", "read", pid, "--source", src]
    if resolved_lines is not None:
        argv.extend(["--lines", str(resolved_lines)])
    _assert_safe_tokens(argv)
    return argv


def assert_herdr_argv_allowed(herdr_argv: list[str]) -> None:
    """Final gate: only the three known read shapes may run."""
    if not herdr_argv:
        raise AllowlistError("empty herdr argv")
    _assert_safe_tokens(herdr_argv)

    if herdr_argv == ["agent", "list", "--format", "json"]:
        return

    if (
        len(herdr_argv) == 5
        and herdr_argv[:2] == ["agent", "get"]
        and herdr_argv[3:] == ["--format", "json"]
    ):
        validate_pane_id(herdr_argv[2])
        return

    if (
        len(herdr_argv) in (5, 7)
        and herdr_argv[:2] == ["pane", "read"]
        and herdr_argv[3] == "--source"
    ):
        validate_pane_id(herdr_argv[2])
        validate_source(herdr_argv[4])
        if len(herdr_argv) == 7:
            if herdr_argv[5] != "--lines":
                raise AllowlistError("unexpected pane read argv shape")
            if not herdr_argv[6].isdigit():
                raise AllowlistError("lines must be digits")
        return

    raise AllowlistError(f"herdr argv not on read-only allowlist: {herdr_argv!r}")
