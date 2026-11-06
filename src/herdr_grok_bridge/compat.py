"""Version-tolerant helpers for Herdr CLI differences across releases."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from .decode import HerdrDecodeError
from .runner import RunnerError

log = logging.getLogger("herdr_grok_bridge.compat")

T = TypeVar("T")
RunFn = Callable[[list[str]], Awaitable[str]]
DecodeFn = Callable[[str], T]


def _is_retryable_cli_failure(exc: BaseException) -> bool:
    """Retry with ``--format json`` only for ordinary CLI failures / bad JSON."""
    if isinstance(exc, HerdrDecodeError):
        return True
    if isinstance(exc, RunnerError) and exc.code == "command_failed":
        return True
    return False


async def run_agent_json_compatible(
    run: RunFn,
    *,
    without_format: list[str],
    with_format: list[str],
    decode: DecodeFn[T],
) -> T:
    """Run an agent read that should return JSON.

    Prefer argv *without* ``--format json`` (Herdr 0.8.0 returns JSON by
    default and rejects the flag). If that attempt fails with a CLI usage /
    non-JSON decode error, retry once *with* ``--format json`` for newer CLIs.
    """
    first_error: BaseException | None = None
    try:
        stdout = await run(without_format)
        return decode(stdout)
    except Exception as exc:  # noqa: BLE001 — narrow via _is_retryable_cli_failure
        if not _is_retryable_cli_failure(exc):
            raise
        first_error = exc
        log.info(
            "agent json without --format failed (%s); retrying with --format json",
            exc,
        )

    try:
        stdout = await run(with_format)
        return decode(stdout)
    except Exception as second:  # noqa: BLE001
        assert first_error is not None
        raise first_error from second
