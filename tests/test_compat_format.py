"""Herdr 0.8.0 vs newer CLI --format json compatibility."""

from __future__ import annotations

import json

import pytest
from mcp import Client

from herdr_grok_bridge import server as bridge_server
from herdr_grok_bridge.compat import run_agent_json_compatible
from herdr_grok_bridge.config import BridgeConfig
from herdr_grok_bridge.decode import decode_agent_list
from herdr_grok_bridge.runner import CommandResult, MockRunner, RunnerError


SAMPLE = {
    "id": "cli:agent:list",
    "result": {
        "type": "agent_list",
        "agents": [
            {
                "agent": "claude",
                "agent_status": "working",
                "pane_id": "wF:p1",
                "cwd": "/tmp",
            }
        ],
    },
}


def _config() -> BridgeConfig:
    return BridgeConfig(
        mode="local",
        herdr_bin="herdr",
        timeout_seconds=5.0,
        connect_timeout_seconds=2,
        max_lines=100,
        max_output_chars=5_000,
    )


@pytest.mark.asyncio
async def test_prefers_without_format_when_json_default() -> None:
    calls: list[list[str]] = []

    async def run(argv: list[str]) -> str:
        calls.append(list(argv))
        assert argv == ["agent", "list"]
        return json.dumps(SAMPLE)

    out = await run_agent_json_compatible(
        run,
        without_format=["agent", "list"],
        with_format=["agent", "list", "--format", "json"],
        decode=decode_agent_list,
    )
    assert out["agents"][0]["pane_id"] == "wF:p1"
    assert calls == [["agent", "list"]]


@pytest.mark.asyncio
async def test_retries_with_format_after_usage_error() -> None:
    calls: list[list[str]] = []

    async def run(argv: list[str]) -> str:
        calls.append(list(argv))
        if argv == ["agent", "list"]:
            # Simulate a newer CLI that refuses to emit JSON without the flag.
            raise RunnerError(
                "command_failed",
                "error: JSON output requires --format json",
            )
        assert argv == ["agent", "list", "--format", "json"]
        return json.dumps(SAMPLE)

    out = await run_agent_json_compatible(
        run,
        without_format=["agent", "list"],
        with_format=["agent", "list", "--format", "json"],
        decode=decode_agent_list,
    )
    assert out["count"] == 1
    assert calls == [
        ["agent", "list"],
        ["agent", "list", "--format", "json"],
    ]


@pytest.mark.asyncio
async def test_retries_with_format_after_non_json_stdout() -> None:
    calls: list[list[str]] = []

    async def run(argv: list[str]) -> str:
        calls.append(list(argv))
        if "--format" not in argv:
            return "Agents:\n  claude working"
        return json.dumps(SAMPLE)

    out = await run_agent_json_compatible(
        run,
        without_format=["agent", "list"],
        with_format=["agent", "list", "--format", "json"],
        decode=decode_agent_list,
    )
    assert out["agents"][0]["agent"] == "claude"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_does_not_retry_timeouts() -> None:
    calls: list[list[str]] = []

    async def run(argv: list[str]) -> str:
        calls.append(list(argv))
        raise RunnerError("timeout", "command exceeded 5s")

    with pytest.raises(RunnerError, match="timeout"):
        await run_agent_json_compatible(
            run,
            without_format=["agent", "list"],
            with_format=["agent", "list", "--format", "json"],
            decode=decode_agent_list,
        )
    assert calls == [["agent", "list"]]


@pytest.mark.asyncio
async def test_list_agents_tool_omits_format_on_08() -> None:
    class Herdr08Runner(MockRunner):
        async def run(self, herdr_argv, *, timeout: float):  # type: ignore[no-untyped-def]
            from herdr_grok_bridge.allowlist import assert_herdr_argv_allowed

            assert_herdr_argv_allowed(herdr_argv)
            self.calls.append(list(herdr_argv))
            if herdr_argv == ["agent", "list", "--format", "json"]:
                raise RunnerError(
                    "command_failed",
                    "unexpected argument --format",
                )
            if herdr_argv == ["agent", "list"]:
                return CommandResult(
                    argv=list(herdr_argv),
                    exit_code=0,
                    stdout=json.dumps(SAMPLE),
                    stderr="",
                )
            raise AssertionError(f"unexpected argv {herdr_argv}")

    runner = Herdr08Runner()
    bridge_server.configure(_config(), runner)
    async with Client(bridge_server.server) as client:
        result = await client.call_tool("list_agents", {})
        assert result.is_error is False
        payload = json.loads(result.content[0].text)  # type: ignore[index]
        assert payload["agents"][0]["pane_id"] == "wF:p1"
    assert runner.calls == [["agent", "list"]]
