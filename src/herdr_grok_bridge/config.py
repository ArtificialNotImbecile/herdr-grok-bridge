"""Environment-driven bridge configuration.

SSH destinations and identity paths are process configuration only. They are
never accepted as MCP tool arguments.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

Mode = Literal["local", "ssh"]

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10
DEFAULT_MAX_LINES = 200
DEFAULT_MAX_OUTPUT_CHARS = 100_000
DEFAULT_HERDR_BIN = "herdr"


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


@dataclass(frozen=True, slots=True)
class BridgeConfig:
    """Resolved runtime settings for local or SSH Herdr access."""

    mode: Mode
    herdr_bin: str
    timeout_seconds: float
    connect_timeout_seconds: int
    max_lines: int
    max_output_chars: int
    ssh_host: str | None = None
    ssh_user: str | None = None
    ssh_port: int | None = None
    ssh_identity_file: str | None = None

    def public_dict(self) -> dict[str, object]:
        """Non-sensitive summary safe to return from tools or logs."""
        return {
            "mode": self.mode,
            "herdr_bin": self.herdr_bin,
            "timeout_seconds": self.timeout_seconds,
            "connect_timeout_seconds": self.connect_timeout_seconds,
            "max_lines": self.max_lines,
            "max_output_chars": self.max_output_chars,
            "ssh_configured": bool(self.ssh_host),
            # Never expose host, user, port, or identity paths.
        }


def load_config() -> BridgeConfig:
    """Load configuration from environment variables."""
    ssh_host = _env("HERDR_BRIDGE_SSH_HOST")
    mode_raw = (_env("HERDR_BRIDGE_MODE") or ("ssh" if ssh_host else "local")).lower()
    if mode_raw not in ("local", "ssh"):
        raise ValueError("HERDR_BRIDGE_MODE must be 'local' or 'ssh'")
    mode: Mode = mode_raw  # type: ignore[assignment]

    if mode == "ssh" and not ssh_host:
        raise ValueError(
            "HERDR_BRIDGE_MODE=ssh requires HERDR_BRIDGE_SSH_HOST "
            "(prefer an OpenSSH Host alias already present in known_hosts)"
        )

    ssh_port_raw = _env("HERDR_BRIDGE_SSH_PORT")
    ssh_port = int(ssh_port_raw) if ssh_port_raw else None
    if ssh_port is not None and not (1 <= ssh_port <= 65535):
        raise ValueError("HERDR_BRIDGE_SSH_PORT must be 1-65535")

    return BridgeConfig(
        mode=mode,
        herdr_bin=_env("HERDR_BRIDGE_HERDR_BIN", DEFAULT_HERDR_BIN) or DEFAULT_HERDR_BIN,
        timeout_seconds=_env_float(
            "HERDR_BRIDGE_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS
        ),
        connect_timeout_seconds=_env_int(
            "HERDR_BRIDGE_CONNECT_TIMEOUT_SECONDS", DEFAULT_CONNECT_TIMEOUT_SECONDS
        ),
        max_lines=_env_int("HERDR_BRIDGE_MAX_LINES", DEFAULT_MAX_LINES),
        max_output_chars=_env_int(
            "HERDR_BRIDGE_MAX_OUTPUT_CHARS", DEFAULT_MAX_OUTPUT_CHARS
        ),
        ssh_host=ssh_host,
        ssh_user=_env("HERDR_BRIDGE_SSH_USER"),
        ssh_port=ssh_port,
        ssh_identity_file=_env("HERDR_BRIDGE_SSH_IDENTITY_FILE"),
    )
