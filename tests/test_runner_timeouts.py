"""Timeout and error behavior with mock runner."""

from __future__ import annotations

import pytest

from herdr_grok_bridge.allowlist import build_agent_list_argv
from herdr_grok_bridge.runner import MockRunner, RunnerError


@pytest.mark.asyncio
async def test_mock_runner_records_argv() -> None:
    runner = MockRunner(stdout='{"result":{"type":"agent_list","agents":[]}}')
    result = await runner.run(build_agent_list_argv(), timeout=5)
    assert runner.calls == [["agent", "list"]]
    assert result.exit_code == 0


@pytest.mark.asyncio
async def test_mock_runner_timeout() -> None:
    runner = MockRunner(delay=0.05)
    with pytest.raises(RunnerError, match="timeout"):
        await runner.run(build_agent_list_argv(), timeout=0.01)


@pytest.mark.asyncio
async def test_mock_runner_nonzero_exit() -> None:
    runner = MockRunner(exit_code=1, stderr="boom")
    with pytest.raises(RunnerError, match="command_failed"):
        await runner.run(build_agent_list_argv(), timeout=5)


@pytest.mark.asyncio
async def test_mock_runner_rejects_mutation_before_exec() -> None:
    runner = MockRunner(stdout="should-not-run")
    with pytest.raises(Exception):
        await runner.run(["agent", "prompt", "w1:p1", "hi"], timeout=5)
    assert runner.calls == []
