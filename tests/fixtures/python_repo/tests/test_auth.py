"""Tests for AuthService.authenticate."""

from __future__ import annotations

import hashlib

import pytest

from src.services.auth_service import AuthError, AuthService


def _service() -> AuthService:
    pw = hashlib.sha256(b"secret").hexdigest()
    return AuthService(credentials={"alice": pw})


def test_authenticate_accepts_valid_credentials() -> None:
    assert _service().authenticate("alice", "secret") is True


def test_authenticate_rejects_wrong_password() -> None:
    assert _service().authenticate("alice", "wrong") is False


def test_authenticate_unknown_user_raises() -> None:
    with pytest.raises(AuthError):
        _service().authenticate("bob", "secret")
