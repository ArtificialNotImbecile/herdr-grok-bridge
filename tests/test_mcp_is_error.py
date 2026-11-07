"""Protocol-level isError assertions for tool failures.

Acceptance harnesses must use CallToolResult.is_error / wire ``isError``,
not text parsing. These tests pin that contract.
"""

from __future__ import annotations

import json

import pytest
from mcp import Client

from herdr_grok_bridge import server as bridge_server
from herdr_grok_bridge.config import BridgeConfig
from herdr_grok_bridge.runner import MockRunner, RunnerError


def _config() -> BridgeConfig:
    return BridgeConfig(
        mode="local",
        herdr_bin="herdr",
        timeout_seconds=5.0,
        connect_timeout_seconds=2,
        max_lines=100,
        max_output_chars=5_000,
    )


def _assert_tool_error(result) -> str:
    assert result.is_error is True, (
        f"expected is_error=True, got False; content={result.content!r}"
    )
    wire = result.model_dump(by_alias=True)
    assert wire.get("isError") is True
    assert result.content, "error results must include text content"
    text = result.content[0].text
    assert text
    # Must not look like a successful JSON tool payload with isError false.
    assert wire.get("isError") is not False
    return text


def _assert_tool_ok(result) -> dict:
    assert result.is_error is False
    wire = result.model_dump(by_alias=True)
    assert wire.get("isError") is False
    return json.loads(result.content[0].text)


@pytest.mark.asyncio
async def test_bad_pane_id_sets_is_error() -> None:
    runner = MockRunner(stdout="should-not-run")
    bridge_server.configure(_config(), runner)
    async with Client(bridge_server.server) as client:
        for tool, args in [
            ("get_agent_status", {"pane_id": "claude"}),
            ("read_pane", {"pane_id": "not-a-pane", "source": "visible"}),
            ("get_agent_status", {"pane_id": "w1"}),
            ("read_pane", {"pane_id": "codex", "source": "recent"}),
        ]:
            result = await client.call_tool(tool, args)
            text = _assert_tool_error(result)
            assert "pane" in text.lower() or "kind" in text.lower()
    assert runner.calls == [], "invalid pane_id must not invoke herdr/ssh"


@pytest.mark.asyncio
async def test_line_validation_sets_is_error() -> None:
    runner = MockRunner(stdout="should-not-run")
    bridge_server.configure(_config(), runner)
    async with Client(bridge_server.server) as client:
        too_many = await client.call_tool(
            "read_pane",
            {"pane_id": "w1:p1", "source": "recent", "lines": 99999},
        )
        text = _assert_tool_error(too_many)
        assert "lines" in text.lower()

        zero = await client.call_tool(
            "read_pane",
            {"pane_id": "w1:p1", "source": "recent", "lines": 0},
        )
        _assert_tool_error(zero)

        # Schema-level rejection (wrong type / enum) — also isError via SDK.
        bad_source = await client.call_tool(
            "read_pane",
            {"pane_id": "w1:p1", "source": "nope"},
        )
        _assert_tool_error(bad_source)
    assert runner.calls == []


@pytest.mark.asyncio
async def test_backend_cli_failure_sets_is_error() -> None:
    runner = MockRunner(exit_code=1, stderr="herdr: pane not found")
    bridge_server.configure(_config(), runner)
    async with Client(bridge_server.server) as client:
        result = await client.call_tool(
            "read_pane", {"pane_id": "w1:p1", "source": "visible"}
        )
        text = _assert_tool_error(result)
        assert "command_failed" in text or "pane not found" in text.lower()


@pytest.mark.asyncio
async def test_timeout_sets_is_error() -> None:
    runner = MockRunner(error=RunnerError("timeout", "command exceeded 5s"))
    bridge_server.configure(_config(), runner)
    async with Client(bridge_server.server) as client:
        result = await client.call_tool("list_agents", {})
        text = _assert_tool_error(result)
        assert "timeout" in text.lower()


@pytest.mark.asyncio
async def test_ssh_network_failure_sets_is_error() -> None:
    runner = MockRunner(
        error=RunnerError("command_failed", "ssh: connect to host timed out")
    )
    bridge_server.configure(_config(), runner)
    async with Client(bridge_server.server) as client:
        listed = await client.call_tool("list_agents", {})
        text = _assert_tool_error(listed)
        assert "command_failed" in text or "timed out" in text.lower()

        status = await client.call_tool(
            "get_agent_status", {"pane_id": "wF:p1"}
        )
        _assert_tool_error(status)


@pytest.mark.asyncio
async def test_herdr_json_error_envelope_sets_is_error() -> None:
    runner = MockRunner(
        stdout=json.dumps(
            {"error": {"code": "not_found", "message": "no such pane"}}
        )
    )
    bridge_server.configure(_config(), runner)
    async with Client(bridge_server.server) as client:
        result = await client.call_tool(
            "get_agent_status", {"pane_id": "w9:p9"}
        )
        text = _assert_tool_error(result)
        assert "not_found" in text or "no such pane" in text


@pytest.mark.asyncio
async def test_success_clears_is_error() -> None:
    runner = MockRunner(
        stdout=json.dumps(
            {
                "id": "cli:agent:list",
                "result": {
                    "type": "agent_list",
                    "agents": [
                        {
                            "agent": "claude",
                            "agent_status": "idle",
                            "pane_id": "wF:p1",
                            "cwd": "/tmp",
                        }
                    ],
                },
            }
        )
    )
    bridge_server.configure(_config(), runner)
    async with Client(bridge_server.server) as client:
        result = await client.call_tool("list_agents", {})
        payload = _assert_tool_ok(result)
        assert payload["agents"][0]["pane_id"] == "wF:p1"


@pytest.mark.asyncio
async def test_unknown_and_mutation_tools_sdk_is_error_no_side_effects() -> None:
    """Unknown tool names are SDK-defined: isError=true, no runner calls.

    Mutating names (agent_prompt, pane_run, …) are not registered, so they
    take this path and cannot execute Herdr commands.
    """
    runner = MockRunner(stdout="should-not-run")
    bridge_server.configure(_config(), runner)
    async with Client(bridge_server.server) as client:
        listed = await client.list_tools()
        names = {t.name for t in listed.tools}
        assert "agent_prompt" not in names
        assert "pane_run" not in names
        assert "send_keys" not in names

        for name in (
            "agent_prompt",
            "pane_run",
            "pane_close",
            "send_keys",
            "herdr_rpc",
            "not_a_real_tool",
        ):
            result = await client.call_tool(name, {"pane_id": "w1:p1"})
            text = _assert_tool_error(result)
            assert "unknown tool" in text.lower()
    assert runner.calls == []
