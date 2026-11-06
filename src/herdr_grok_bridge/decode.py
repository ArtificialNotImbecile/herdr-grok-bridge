"""Decode Herdr CLI stdout into structured results."""

from __future__ import annotations

import json
from typing import Any


class HerdrDecodeError(ValueError):
    """Stdout was not valid Herdr JSON (or expected text)."""


def decode_json_payload(stdout: str) -> Any:
    """Parse Herdr JSON envelope or bare JSON object.

    Accepts envelopes shaped like::

        {"id": "cli:agent:list", "result": {"type": "agent_list", "agents": [...]}}

    or an error object::

        {"error": {"code": "...", "message": "..."}}
    """
    text = (stdout or "").strip()
    if not text:
        raise HerdrDecodeError("empty herdr stdout")

    # Herdr sometimes prints a banner line before JSON; take the first object.
    payload = _loads_first_json(text)
    if not isinstance(payload, dict):
        raise HerdrDecodeError("herdr JSON root must be an object")

    if isinstance(payload.get("error"), dict):
        err = payload["error"]
        code = err.get("code", "error")
        message = err.get("message", "unknown error")
        raise HerdrDecodeError(f"{code}: {message}")

    if "result" in payload:
        return payload["result"]
    return payload


def decode_agent_list(stdout: str) -> dict[str, Any]:
    """Normalize ``agent list --format json`` into a stable dict."""
    result = decode_json_payload(stdout)
    if not isinstance(result, dict):
        raise HerdrDecodeError("agent list result must be an object")

    agents = result.get("agents")
    if agents is None and result.get("type") == "agent_list":
        agents = []
    if agents is None and isinstance(result.get("result"), dict):
        # Nested accidental double-envelope.
        inner = result["result"]
        agents = inner.get("agents", [])
        result = inner
    if not isinstance(agents, list):
        raise HerdrDecodeError("agent list missing agents array")

    normalized: list[dict[str, Any]] = []
    for item in agents:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "pane_id": item.get("pane_id"),
                "agent": item.get("agent"),
                "agent_status": item.get("agent_status") or item.get("status"),
                "cwd": item.get("cwd"),
                "name": item.get("name") or item.get("agent_name"),
                "workspace_id": item.get("workspace_id"),
                "tab_id": item.get("tab_id"),
            }
        )
    return {
        "type": result.get("type") or "agent_list",
        "agents": normalized,
        "count": len(normalized),
    }


def decode_agent_status(stdout: str) -> dict[str, Any]:
    """Normalize ``agent get --format json``."""
    result = decode_json_payload(stdout)
    if not isinstance(result, dict):
        raise HerdrDecodeError("agent status result must be an object")
    # Prefer nested agent object when present.
    agent_obj = result.get("agent") if isinstance(result.get("agent"), dict) else result
    return {
        "type": result.get("type") or "agent",
        "pane_id": agent_obj.get("pane_id") or result.get("pane_id"),
        "agent": agent_obj.get("agent") or agent_obj.get("kind"),
        "agent_status": agent_obj.get("agent_status")
        or agent_obj.get("status")
        or result.get("agent_status"),
        "cwd": agent_obj.get("cwd") or result.get("cwd"),
        "name": agent_obj.get("name") or agent_obj.get("agent_name"),
        "raw_keys": sorted(result.keys()),
    }


def decode_pane_text(stdout: str) -> str:
    """Pane read returns UTF-8 text; tolerate accidental JSON envelopes."""
    text = stdout if stdout is not None else ""
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            return text
        if isinstance(payload, dict):
            if isinstance(payload.get("error"), dict):
                err = payload["error"]
                raise HerdrDecodeError(
                    f"{err.get('code', 'error')}: {err.get('message', 'unknown error')}"
                )
            result = payload.get("result", payload)
            if isinstance(result, dict):
                read = result.get("read")
                if isinstance(read, dict) and isinstance(read.get("text"), str):
                    return read["text"]
                if isinstance(result.get("text"), str):
                    return result["text"]
    return text


def _loads_first_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Scan for a JSON object start.
    start = text.find("{")
    if start < 0:
        raise HerdrDecodeError("no JSON object in herdr stdout")
    decoder = json.JSONDecoder()
    try:
        payload, _end = decoder.raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise HerdrDecodeError(f"invalid herdr JSON: {exc}") from exc
    return payload
