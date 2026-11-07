"""Input validation tests."""

from __future__ import annotations

import pytest

from herdr_grok_bridge.validation import (
    ValidationError,
    resolve_read_lines,
    validate_pane_id,
    validate_source,
)


@pytest.mark.parametrize("pane_id", ["w1:p2", "wF:p1", "ws_9:p12"])
def test_accepts_live_pane_ids(pane_id: str) -> None:
    assert validate_pane_id(pane_id) == pane_id


@pytest.mark.parametrize(
    "pane_id",
    [
        "claude",
        "codex",
        "Claude",
        "agent",
        "w1",
        "w1:t1",
        "w1:p",
        "w1:pX",
        "../p1",
        "w1:p1;rm",
        "w1:p1 $(id)",
        "",
        "  ",
        "w1:p1 extra",
    ],
)
def test_rejects_bad_or_bare_targets(pane_id: str) -> None:
    with pytest.raises(ValidationError):
        validate_pane_id(pane_id)


def test_source_validation() -> None:
    assert validate_source("visible") == "visible"
    with pytest.raises(ValidationError):
        validate_source("scrollback")


def test_lines_omitted_for_visible_even_if_requested() -> None:
    assert resolve_read_lines("visible", 40, max_lines=200) is None


def test_lines_default_and_cap_for_recent() -> None:
    assert resolve_read_lines("recent", None, max_lines=50) == 50
    assert resolve_read_lines("recent-unwrapped", 120, max_lines=200) == 120
    with pytest.raises(ValidationError):
        resolve_read_lines("recent", 9999, max_lines=200)
