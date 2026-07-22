"""Application settings and configuration keys."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Runtime settings sourced from environment variables."""

    database_url: str
    max_capture_amount: int
    request_timeout_seconds: int


def get_settings() -> Settings:
    """Build Settings from the environment.

    Configuration keys: DATABASE_URL controls the database connection.
    """
    return Settings(
        database_url=os.environ.get("DATABASE_URL", "sqlite:///./app.db"),
        max_capture_amount=int(os.environ.get("MAX_CAPTURE_AMOUNT", "1000000")),
        request_timeout_seconds=int(os.environ.get("REQUEST_TIMEOUT_SECONDS", "30")),
    )
