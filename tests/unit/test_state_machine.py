"""Snapshot lifecycle transition tests (Blueprint §4.3.6, CLAUDE.md §2.10)."""

from __future__ import annotations

import pytest

from codeatlas.domain.enums import SnapshotStatus as S
from codeatlas.domain.errors import SnapshotError
from codeatlas.indexing.state_machine import assert_transition, can_transition


def test_valid_transitions() -> None:
    assert can_transition(S.STAGING, S.VALIDATING)
    assert can_transition(S.STAGING, S.FAILED)
    assert can_transition(S.VALIDATING, S.ACTIVE)
    assert can_transition(S.VALIDATING, S.FAILED)
    assert can_transition(S.ACTIVE, S.SUPERSEDED)


def test_invalid_transitions() -> None:
    assert not can_transition(S.STAGING, S.ACTIVE)  # must validate first
    assert not can_transition(S.ACTIVE, S.STAGING)
    assert not can_transition(S.FAILED, S.ACTIVE)
    assert not can_transition(S.SUPERSEDED, S.ACTIVE)


def test_assert_transition_raises() -> None:
    with pytest.raises(SnapshotError):
        assert_transition(S.FAILED, S.ACTIVE)
