"""Read-only MCP server: list agents, agent status, bounded pane reads.

This is an unofficial community bridge. It exposes MCP *tools* over stdio —
not an embedded Herdr UI, Canvas, or refresh button.

Tool failures return ``CallToolResult(is_error=True)`` (JSON ``isError: true``).
Do not treat plain text that happens to mention an error as a substitute for
that flag. Unknown tool names are handled by the MCP SDK: they yield
``isError: true`` with an ``Unknown tool: …`` message and never reach our
runner (so no Herdr/SSH side effects).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Literal

from mcp.server import MCPServer
from mcp_types import CallToolResult, ToolAnnotations

from . import __version__
from .allowlist import (
    AllowlistError,
    build_agent_list_argv,
    build_agent_status_argv,
    build_pane_read_argv,
)
from .compat import run_agent_json_compatible
from .config import BridgeConfig, load_config
from .decode import (
    HerdrDecodeError,
    decode_agent_list,
    decode_agent_status,
    decode_pane_text,
)
from .errors import tool_error_result, tool_success_result
from .redaction import bound_text, redact_secrets
from .runner import CommandRunner, RunnerError, SubprocessRunner
from .validation import ValidationError

log = logging.getLogger("herdr_grok_bridge")

READ = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

INSTRUCTIONS = """\
Unofficial READ-ONLY Herdr bridge. You can list live agents, fetch one agent's
status, and read bounded pane output. Targets must be live pane_id values from
list_agents (for example w1:p2) — never bare kinds like "claude".

This server cannot prompt agents, send keys, focus panes, restart Herdr, or run
arbitrary commands. Reading a pane can expose secrets that appeared in that
terminal; treat output as sensitive. This is MCP tools only — not a native
Herdr UI or Canvas refresh control.

Failures set CallToolResult.isError=true. Do not infer failure from text alone.
"""

_config: BridgeConfig | None = None
_runner: CommandRunner | None = None

server = MCPServer(
    name="herdr-grok-bridge",
    title="Herdr Grok Bridge (read-only)",
    version=__version__,
    instructions=INSTRUCTIONS,
)

_FAIL_TYPES = (ValidationError, AllowlistError, HerdrDecodeError, RunnerError, ValueError)


def configure(
    config: BridgeConfig | None = None,
    runner: CommandRunner | None = None,
) -> None:
    """Wire config/runner (tests inject a mock runner)."""
    global _config, _runner
    _config = config or load_config()
    _runner = runner or SubprocessRunner(_config)


def _require() -> tuple[BridgeConfig, CommandRunner]:
    if _config is None or _runner is None:
        configure()
    assert _config is not None and _runner is not None
    return _config, _runner


def _fail(exc: BaseException) -> CallToolResult:
    """Map domain failures to an MCP tool error result (isError=true)."""
    if isinstance(exc, RunnerError):
        return tool_error_result(f"{exc.code}: {exc.message}")
    return tool_error_result(str(exc))


async def _run_herdr_raw(herdr_argv: list[str]) -> str:
    """Invoke allowlisted herdr argv; preserve RunnerError for compat retries."""
    config, runner = _require()
    result = await runner.run(herdr_argv, timeout=config.timeout_seconds)
    return result.stdout


@server.tool(annotations=READ)
async def bridge_info() -> CallToolResult:
    """Non-sensitive bridge configuration (mode, timeouts, limits). Never returns SSH host or credentials."""
    config, _ignored = _require()
    return tool_success_result(
        {
            "name": "herdr-grok-bridge",
            "version": __version__,
            "unofficial": True,
            "read_only": True,
            "ui": False,
            "note": "MCP tools only — not an embedded Herdr UI/Canvas refresh button.",
            "error_signaling": (
                "Tool failures use CallToolResult.isError=true (wire isError). "
                "Unknown tools are rejected by the MCP SDK with isError=true and "
                "never invoke Herdr."
            ),
            "config": config.public_dict(),
            "tools": ["list_agents", "get_agent_status", "read_pane", "bridge_info"],
        }
    )


@server.tool(annotations=READ)
async def list_agents() -> CallToolResult:
    """List active Herdr agents with status and pane_id targets for later reads.

    Uses ``herdr agent list`` without ``--format json`` first (Herdr 0.8.0
    default JSON; that release rejects the flag). Retries with the flag only
    if the default path fails with a CLI/JSON error.
    """
    try:
        payload = await run_agent_json_compatible(
            _run_herdr_raw,
            without_format=build_agent_list_argv(with_format_json=False),
            with_format=build_agent_list_argv(with_format_json=True),
            decode=decode_agent_list,
        )
        return tool_success_result(payload)
    except _FAIL_TYPES as exc:
        return _fail(exc)


@server.tool(annotations=READ)
async def get_agent_status(pane_id: str) -> CallToolResult:
    """Get status for one live agent by pane_id (required; not a bare kind like "claude").

    Same ``--format json`` compatibility policy as ``list_agents``.
    Failures return ``isError: true`` (invalid pane_id, CLI/SSH/timeout errors).
    """
    try:
        payload = await run_agent_json_compatible(
            _run_herdr_raw,
            without_format=build_agent_status_argv(pane_id, with_format_json=False),
            with_format=build_agent_status_argv(pane_id, with_format_json=True),
            decode=decode_agent_status,
        )
        return tool_success_result(payload)
    except _FAIL_TYPES as exc:
        return _fail(exc)


@server.tool(annotations=READ)
async def read_pane(
    pane_id: str,
    source: Literal["visible", "recent", "recent-unwrapped", "detection"] = "visible",
    lines: int | None = None,
) -> CallToolResult:
    """Read bounded output from a live pane_id.

    For ``visible`` / ``detection``, ``--lines`` is omitted for Herdr version
    compatibility; output is still truncated client-side. For recent sources,
    a capped ``--lines`` is sent (default 80). Secrets in terminal text are
    redacted best-effort.

    Validation, Herdr CLI, timeout, and transport failures return
    ``isError: true`` — never a successful result whose text merely describes
    the error.
    """
    config, _ = _require()
    try:
        argv = build_pane_read_argv(
            pane_id, source, lines, max_lines=config.max_lines
        )
        stdout = await _run_herdr_raw(argv)
        text = decode_pane_text(stdout)
        text = redact_secrets(text)
        # Client-side line trim for visible/detection when caller asked for lines.
        if source in ("visible", "detection") and lines is not None and lines > 0:
            parts = text.splitlines()
            if len(parts) > lines:
                text = "\n".join(parts[-lines:])
        text, truncated = bound_text(text, config.max_output_chars)
        return tool_success_result(
            {
                "pane_id": pane_id.strip(),
                "source": source,
                "lines_requested": lines,
                "truncated": truncated,
                "text": text,
            }
        )
    except _FAIL_TYPES as exc:
        return _fail(exc)


def main(argv: list[str] | None = None) -> None:
    """CLI entry: stdio MCP server."""
    parser = argparse.ArgumentParser(
        prog="herdr-grok-bridge",
        description=(
            "Unofficial read-only Herdr MCP bridge for Grok Bot (stdio). "
            "SSH/local transport is configured via environment variables only."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"herdr-grok-bridge {__version__}",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("HERDR_BRIDGE_LOG_LEVEL", "INFO"),
        help="Logging level for stderr (default INFO)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    try:
        configure()
    except ValueError as exc:
        log.error("configuration error: %s", exc)
        raise SystemExit(2) from exc

    config, _ = _require()
    log.info(
        "starting herdr-grok-bridge %s mode=%s read_only=true",
        __version__,
        config.mode,
    )
    server.run()  # stdio


if __name__ == "__main__":
    main()
