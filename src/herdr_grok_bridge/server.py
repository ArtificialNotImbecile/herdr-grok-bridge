"""Read-only MCP server: list agents, agent status, bounded pane reads.

This is an unofficial community bridge. It exposes MCP *tools* over stdio —
not an embedded Herdr UI, Canvas, or refresh button.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from . import __version__
from .allowlist import (
    AllowlistError,
    build_agent_list_argv,
    build_agent_status_argv,
    build_pane_read_argv,
)
from .config import BridgeConfig, load_config
from .decode import (
    HerdrDecodeError,
    decode_agent_list,
    decode_agent_status,
    decode_pane_text,
)
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
"""

_config: BridgeConfig | None = None
_runner: CommandRunner | None = None

server = MCPServer(
    name="herdr-grok-bridge",
    title="Herdr Grok Bridge (read-only)",
    version=__version__,
    instructions=INSTRUCTIONS,
)


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


def _tool_error(exc: Exception) -> ToolError:
    if isinstance(exc, (ValidationError, AllowlistError, HerdrDecodeError, RunnerError)):
        return ToolError(str(exc))
    return ToolError(f"internal_error: {exc}")


async def _run_herdr(herdr_argv: list[str]) -> str:
    config, runner = _require()
    try:
        result = await runner.run(herdr_argv, timeout=config.timeout_seconds)
    except (RunnerError, AllowlistError, ValidationError) as exc:
        raise _tool_error(exc) from exc
    return result.stdout


@server.tool(annotations=READ)
async def bridge_info() -> dict[str, Any]:
    """Non-sensitive bridge configuration (mode, timeouts, limits). Never returns SSH host or credentials."""
    config, _runner = _require()
    return {
        "name": "herdr-grok-bridge",
        "version": __version__,
        "unofficial": True,
        "read_only": True,
        "ui": False,
        "note": "MCP tools only — not an embedded Herdr UI/Canvas refresh button.",
        "config": config.public_dict(),
        "tools": ["list_agents", "get_agent_status", "read_pane", "bridge_info"],
    }


@server.tool(annotations=READ)
async def list_agents() -> dict[str, Any]:
    """List active Herdr agents with status and pane_id targets for later reads."""
    try:
        stdout = await _run_herdr(build_agent_list_argv())
        return decode_agent_list(stdout)
    except (HerdrDecodeError, ToolError) as exc:
        if isinstance(exc, ToolError):
            raise
        raise _tool_error(exc) from exc


@server.tool(annotations=READ)
async def get_agent_status(pane_id: str) -> dict[str, Any]:
    """Get status for one live agent by pane_id (required; not a bare kind like "claude")."""
    try:
        argv = build_agent_status_argv(pane_id)
        stdout = await _run_herdr(argv)
        return decode_agent_status(stdout)
    except (ValidationError, AllowlistError, HerdrDecodeError, ToolError) as exc:
        if isinstance(exc, ToolError):
            raise
        raise _tool_error(exc) from exc


@server.tool(annotations=READ)
async def read_pane(
    pane_id: str,
    source: Literal["visible", "recent", "recent-unwrapped", "detection"] = "visible",
    lines: int | None = None,
) -> dict[str, Any]:
    """Read bounded output from a live pane_id.

    For ``visible`` / ``detection``, ``--lines`` is omitted for Herdr version
    compatibility; output is still truncated client-side. For recent sources,
    a capped ``--lines`` is sent (default 80). Secrets in terminal text are
    redacted best-effort.
    """
    config, _ = _require()
    try:
        argv = build_pane_read_argv(
            pane_id, source, lines, max_lines=config.max_lines
        )
        stdout = await _run_herdr(argv)
        text = decode_pane_text(stdout)
        text = redact_secrets(text)
        # Client-side line trim for visible/detection when caller asked for lines.
        if source in ("visible", "detection") and lines is not None and lines > 0:
            parts = text.splitlines()
            if len(parts) > lines:
                text = "\n".join(parts[-lines:])
        text, truncated = bound_text(text, config.max_output_chars)
        return {
            "pane_id": pane_id.strip(),
            "source": source,
            "lines_requested": lines,
            "truncated": truncated,
            "text": text,
        }
    except (ValidationError, AllowlistError, HerdrDecodeError, ToolError) as exc:
        if isinstance(exc, ToolError):
            raise
        raise _tool_error(exc) from exc


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
