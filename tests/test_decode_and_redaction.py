"""Herdr JSON decoding and secrets redaction."""

from __future__ import annotations

import json

import pytest

from herdr_grok_bridge.decode import (
    HerdrDecodeError,
    decode_agent_list,
    decode_agent_status,
    decode_pane_text,
)
from herdr_grok_bridge.redaction import bound_text, redact_secrets


SAMPLE_LIST = {
    "id": "cli:agent:list",
    "result": {
        "type": "agent_list",
        "agents": [
            {
                "agent": "claude",
                "agent_status": "working",
                "cwd": "/home/user/proj",
                "pane_id": "wF:p1",
                "name": "reviewer",
            }
        ],
    },
}


def test_decode_agent_list_envelope() -> None:
    out = decode_agent_list(json.dumps(SAMPLE_LIST))
    assert out["count"] == 1
    assert out["agents"][0]["pane_id"] == "wF:p1"
    assert out["agents"][0]["agent_status"] == "working"
    assert out["agents"][0]["agent"] == "claude"


def test_decode_agent_list_error() -> None:
    payload = {"error": {"code": "not_running", "message": "no server"}}
    with pytest.raises(HerdrDecodeError, match="not_running"):
        decode_agent_list(json.dumps(payload))


def test_decode_agent_status() -> None:
    payload = {
        "id": "cli:agent:get",
        "result": {
            "type": "agent",
            "pane_id": "w1:p2",
            "agent": "claude",
            "agent_status": "idle",
            "cwd": "/tmp",
        },
    }
    out = decode_agent_status(json.dumps(payload))
    assert out["pane_id"] == "w1:p2"
    assert out["agent_status"] == "idle"


def test_decode_pane_text_plain_and_envelope() -> None:
    assert decode_pane_text("hello\nworld\n") == "hello\nworld\n"
    enveloped = {
        "result": {"read": {"text": "from json"}},
    }
    assert decode_pane_text(json.dumps(enveloped)) == "from json"


def test_redaction_and_bounds() -> None:
    raw = "Authorization: Bearer SECRETTOKEN123\npassword=hunter2\nAKIAIOSFODNN7EXAMPLE\nok"
    redacted = redact_secrets(raw)
    assert "SECRETTOKEN123" not in redacted
    assert "hunter2" not in redacted
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted
    assert "[REDACTED" in redacted or "REDACTED" in redacted
    text, truncated = bound_text("abcdefghij", 5)
    assert truncated is True
    assert text.startswith("abcde")
