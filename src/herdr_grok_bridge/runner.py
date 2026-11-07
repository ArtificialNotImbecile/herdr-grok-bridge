"""Structured argv construction and subprocess execution (never shell=True)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol

from .allowlist import assert_herdr_argv_allowed
from .config import BridgeConfig

log = logging.getLogger("herdr_grok_bridge.runner")


class RunnerError(RuntimeError):
    """Local/SSH herdr invocation failed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class CommandResult:
    argv: list[str]
    exit_code: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    async def run(self, herdr_argv: list[str], *, timeout: float) -> CommandResult: ...


def build_transport_argv(config: BridgeConfig, herdr_argv: list[str]) -> list[str]:
    """Build full local or SSH argv. SSH options are fixed, not tool-supplied."""
    assert_herdr_argv_allowed(herdr_argv)

    if config.mode == "local":
        return [config.herdr_bin, *herdr_argv]

    if not config.ssh_host:
        raise RunnerError("ssh_config", "ssh mode requires HERDR_BRIDGE_SSH_HOST")

    ssh_argv: list[str] = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"ConnectTimeout={config.connect_timeout_seconds}",
        "-o",
        "PasswordAuthentication=no",
        "-o",
        "KbdInteractiveAuthentication=no",
    ]
    if config.ssh_port is not None:
        ssh_argv.extend(["-p", str(config.ssh_port)])
    if config.ssh_identity_file:
        ssh_argv.extend(["-i", config.ssh_identity_file])

    destination = (
        f"{config.ssh_user}@{config.ssh_host}" if config.ssh_user else config.ssh_host
    )
    # Remote argv after "--": herdr + allowlisted args only.
    ssh_argv.extend([destination, "--", config.herdr_bin, *herdr_argv])
    return ssh_argv


class SubprocessRunner:
    """Default runner using asyncio.create_subprocess_exec."""

    def __init__(self, config: BridgeConfig) -> None:
        self._config = config

    async def run(self, herdr_argv: list[str], *, timeout: float) -> CommandResult:
        argv = build_transport_argv(self._config, herdr_argv)
        # Log only herdr subcommand tokens, never SSH destination.
        log.info("exec herdr %s (mode=%s)", " ".join(herdr_argv), self._config.mode)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise RunnerError(
                "executable_not_found",
                f"cannot execute {argv[0]!r}: {exc}",
            ) from exc

        try:
            out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RunnerError(
                "timeout",
                f"command exceeded {timeout:.0f}s",
            ) from None

        stdout = out_b.decode("utf-8", "replace")
        stderr = err_b.decode("utf-8", "replace")
        code = proc.returncode if proc.returncode is not None else -1
        if code != 0:
            detail = (stderr or stdout).strip() or f"exit {code}"
            # Avoid echoing potential hostnames from ssh errors into structured code.
            raise RunnerError("command_failed", detail[:2000])
        return CommandResult(argv=argv, exit_code=code, stdout=stdout, stderr=stderr)


class MockRunner:
    """Test double that records argv and returns canned output."""

    def __init__(
        self,
        *,
        stdout: str = "",
        stderr: str = "",
        exit_code: int = 0,
        delay: float = 0.0,
        error: Exception | None = None,
    ) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.delay = delay
        self.error = error
        self.calls: list[list[str]] = []

    async def run(self, herdr_argv: list[str], *, timeout: float) -> CommandResult:
        assert_herdr_argv_allowed(herdr_argv)
        self.calls.append(list(herdr_argv))
        if self.delay:
            await asyncio.sleep(self.delay)
            if self.delay > timeout:
                raise RunnerError("timeout", f"command exceeded {timeout:.0f}s")
        if self.error:
            raise self.error
        if self.exit_code != 0:
            raise RunnerError(
                "command_failed",
                (self.stderr or self.stdout or f"exit {self.exit_code}")[:2000],
            )
        return CommandResult(
            argv=list(herdr_argv),
            exit_code=self.exit_code,
            stdout=self.stdout,
            stderr=self.stderr,
        )
