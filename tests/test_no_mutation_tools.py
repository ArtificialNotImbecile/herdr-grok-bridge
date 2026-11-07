"""Ensure the MCP surface exposes only read-only tools."""

from __future__ import annotations

import pytest
from mcp import Client

from herdr_grok_bridge import server as bridge_server
from herdr_grok_bridge.config import BridgeConfig
from herdr_grok_bridge.runner import MockRunner


MUTATING_NAMES = {
    "agent_prompt",
    "prompt",
    "send_keys",
    "send_text",
    "pane_run",
    "pane_close",
    "focus",
    "agent_focus",
    "start_agent",
    "herdr_rpc",
    "shell",
    "exec",
}


@pytest.fixture
def configured_server():
    cfg = BridgeConfig(
        mode="local",
        herdr_bin="herdr",
        timeout_seconds=5.0,
        connect_timeout_seconds=2,
        max_lines=100,
        max_output_chars=10_000,
    )
    runner = MockRunner(
        stdout=(
            '{"id":"cli:agent:list","result":{"type":"agent_list","agents":'
            '[{"agent":"claude","agent_status":"working","pane_id":"wF:p1","cwd":"/tmp"}]}}'
        )
    )
    bridge_server.configure(cfg, runner)
    return bridge_server.server, runner


@pytest.mark.asyncio
async def test_only_readonly_tools_registered(configured_server) -> None:
    mcp_server, _runner = configured_server
    async with Client(mcp_server) as client:
        listed = await client.list_tools()
        names = {t.name for t in listed.tools}
        assert names == {"bridge_info", "list_agents", "get_agent_status", "read_pane"}
        assert names.isdisjoint(MUTATING_NAMES)
        for tool in listed.tools:
            assert tool.annotations is not None
            assert tool.annotations.read_only_hint is True
            assert tool.annotations.destructive_hint is False
