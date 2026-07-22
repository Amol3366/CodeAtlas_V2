"""Authentication service."""

from __future__ import annotations

import hashlib


class AuthError(Exception):
    """Raised when authentication fails."""


class AuthService:
    """Authenticates users against a simple credential store."""

    def __init__(self, credentials: dict[str, str]) -> None:
        # username -> sha256(password)
        self._credentials = credentials

    def authenticate(self, username: str, password: str) -> bool:
        """Return True when the username/password pair is valid."""
        expected = self._credentials.get(username)
        if expected is None:
            raise AuthError("unknown user")
        return hashlib.sha256(password.encode("utf-8")).hexdigest() == expected
