"""Command construction, allowlist, and SSH/local argv tests."""

from __future__ import annotations

import pytest

from herdr_grok_bridge.allowlist import (
    AllowlistError,
    assert_herdr_argv_allowed,
    build_agent_list_argv,
    build_agent_status_argv,
    build_pane_read_argv,
)
from herdr_grok_bridge.config import BridgeConfig
from herdr_grok_bridge.runner import build_transport_argv


def _cfg(**kwargs) -> BridgeConfig:
    base = dict(
        mode="local",
        herdr_bin="herdr",
        timeout_seconds=30.0,
        connect_timeout_seconds=10,
        max_lines=200,
        max_output_chars=100_000,
    )
    base.update(kwargs)
    return BridgeConfig(**base)  # type: ignore[arg-type]


def test_agent_list_argv_omits_format_by_default() -> None:
    assert build_agent_list_argv() == ["agent", "list"]
    assert build_agent_list_argv(with_format_json=True) == [
        "agent",
        "list",
        "--format",
        "json",
    ]


def test_agent_status_argv_omits_format_by_default() -> None:
    assert build_agent_status_argv("wF:p1") == ["agent", "get", "wF:p1"]
    assert build_agent_status_argv("wF:p1", with_format_json=True) == [
        "agent",
        "get",
        "wF:p1",
        "--format",
        "json",
    ]


def test_allowlist_accepts_both_format_shapes() -> None:
    assert_herdr_argv_allowed(["agent", "list"])
    assert_herdr_argv_allowed(["agent", "list", "--format", "json"])
    assert_herdr_argv_allowed(["agent", "get", "w1:p2"])
    assert_herdr_argv_allowed(["agent", "get", "w1:p2", "--format", "json"])


def test_pane_read_visible_omits_lines() -> None:
    argv = build_pane_read_argv("w1:p2", "visible", 40, max_lines=200)
    assert argv == ["pane", "read", "w1:p2", "--source", "visible"]
    assert "--lines" not in argv


def test_pane_read_detection_omits_lines() -> None:
    argv = build_pane_read_argv("w1:p2", "detection", 10, max_lines=200)
    assert "--lines" not in argv


def test_pane_read_recent_includes_capped_lines() -> None:
    argv = build_pane_read_argv("w1:p2", "recent-unwrapped", None, max_lines=200)
    assert argv == [
        "pane",
        "read",
        "w1:p2",
        "--source",
        "recent-unwrapped",
        "--lines",
        "80",
    ]


def test_local_transport_argv() -> None:
    cfg = _cfg(mode="local", herdr_bin="/usr/local/bin/herdr")
    full = build_transport_argv(cfg, build_agent_list_argv())
    assert full == ["/usr/local/bin/herdr", "agent", "list"]


def test_ssh_transport_argv_batchmode_and_strict() -> None:
    cfg = _cfg(
        mode="ssh",
        ssh_host="herdr-box",
        ssh_user="deploy",
        ssh_port=2222,
        ssh_identity_file="/home/user/.ssh/id_ed25519",
        connect_timeout_seconds=7,
    )
    full = build_transport_argv(cfg, build_agent_list_argv())
    assert full[0] == "ssh"
    assert "BatchMode=yes" in full
    assert "StrictHostKeyChecking=yes" in full
    assert "ConnectTimeout=7" in full
    assert "PasswordAuthentication=no" in full
    assert full[full.index("-p") + 1] == "2222"
    assert full[full.index("-i") + 1] == "/home/user/.ssh/id_ed25519"
    # Destination then -- then herdr argv
    assert "deploy@herdr-box" in full
    dash = full.index("--")
    assert full[dash:] == ["--", "herdr", "agent", "list"]


def test_mutation_routes_hard_denied() -> None:
    forbidden = [
        ["agent", "prompt", "w1:p1", "hello"],
        ["agent", "send-keys", "w1:p1", "enter"],
        ["agent", "focus", "w1:p1"],
        ["agent", "start", "--kind", "claude", "--pane", "w1:p1"],
        ["pane", "run", "w1:p1", "echo hi"],
        ["pane", "close", "w1:p1"],
        ["api", "snapshot"],
        ["shell", "ls"],
    ]
    for argv in forbidden:
        with pytest.raises(AllowlistError):
            assert_herdr_argv_allowed(argv)


def test_ssh_destination_not_in_herdr_allowlist_builder() -> None:
    # Tool-facing builders never take host/user.
    assert "ssh" not in build_agent_list_argv()
    assert "@" not in "".join(build_pane_read_argv("w1:p1", "visible", None, max_lines=50))
