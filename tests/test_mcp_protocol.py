"""MCP initialization / list_tools / call_tool smoke tests (in-memory)."""

from __future__ import annotations

import json

import pytest
from mcp import Client

from herdr_grok_bridge import server as bridge_server
from herdr_grok_bridge.config import BridgeConfig
from herdr_grok_bridge.runner import MockRunner


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
async def test_list_and_call_list_agents() -> None:
    runner = MockRunner(
        stdout=json.dumps(
            {
                "id": "cli:agent:list",
                "result": {
                    "type": "agent_list",
                    "agents": [
                        {
                            "agent": "claude",
                            "agent_status": "working",
                            "cwd": "/tmp/demo",
                            "pane_id": "wF:p1",
                        }
                    ],
                },
            }
        )
    )
    bridge_server.configure(_config(), runner)

    async with Client(bridge_server.server) as client:
        assert client.server_info is not None
        tools = await client.list_tools()
        names = [t.name for t in tools.tools]
        assert "list_agents" in names

        result = await client.call_tool("list_agents", {})
        assert result.is_error is False
        # Structured JSON is returned as text content by the SDK.
        text = result.content[0].text  # type: ignore[index]
        payload = json.loads(text)
        assert payload["agents"][0]["pane_id"] == "wF:p1"
        assert runner.calls == [["agent", "list", "--format", "json"]]


@pytest.mark.asyncio
async def test_call_read_pane_and_status() -> None:
    # Runner returns different payloads based on call order.
    class SeqRunner(MockRunner):
        async def run(self, herdr_argv, *, timeout: float):  # type: ignore[no-untyped-def]
            from herdr_grok_bridge.allowlist import assert_herdr_argv_allowed
            from herdr_grok_bridge.runner import CommandResult

            assert_herdr_argv_allowed(herdr_argv)
            self.calls.append(list(herdr_argv))
            if herdr_argv[:2] == ["agent", "get"]:
                stdout = json.dumps(
                    {
                        "result": {
                            "pane_id": "wF:p1",
                            "agent": "claude",
                            "agent_status": "idle",
                        }
                    }
                )
            else:
                stdout = "TOKEN=sk-abcdefghijklmnopqrstuvwxyz012345\nhello"
            return CommandResult(
                argv=list(herdr_argv), exit_code=0, stdout=stdout, stderr=""
            )

    runner = SeqRunner()
    bridge_server.configure(_config(), runner)

    async with Client(bridge_server.server) as client:
        status = await client.call_tool("get_agent_status", {"pane_id": "wF:p1"})
        assert status.is_error is False
        status_payload = json.loads(status.content[0].text)  # type: ignore[index]
        assert status_payload["agent_status"] == "idle"

        read = await client.call_tool(
            "read_pane",
            {"pane_id": "wF:p1", "source": "visible", "lines": 20},
        )
        assert read.is_error is False
        read_payload = json.loads(read.content[0].text)  # type: ignore[index]
        assert "sk-abcdefghijklmnopqrstuvwxyz012345" not in read_payload["text"]
        assert "hello" in read_payload["text"]
        # visible must not pass --lines to herdr
        assert runner.calls[-1] == [
            "pane",
            "read",
            "wF:p1",
            "--source",
            "visible",
        ]


@pytest.mark.asyncio
async def test_rejects_bare_kind_via_tool() -> None:
    bridge_server.configure(_config(), MockRunner(stdout="{}"))
    async with Client(bridge_server.server) as client:
        result = await client.call_tool("get_agent_status", {"pane_id": "claude"})
        assert result.is_error is True


@pytest.mark.asyncio
async def test_bridge_info_hides_ssh_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERDR_BRIDGE_MODE", "ssh")
    monkeypatch.setenv("HERDR_BRIDGE_SSH_HOST", "should-not-leak.example")
    from herdr_grok_bridge.config import load_config

    cfg = load_config()
    bridge_server.configure(cfg, MockRunner())
    async with Client(bridge_server.server) as client:
        info = await client.call_tool("bridge_info", {})
        payload = json.loads(info.content[0].text)  # type: ignore[index]
        blob = json.dumps(payload)
        assert "should-not-leak.example" not in blob
        assert payload["config"]["mode"] == "ssh"
        assert payload["config"]["ssh_configured"] is True
        assert payload["ui"] is False
