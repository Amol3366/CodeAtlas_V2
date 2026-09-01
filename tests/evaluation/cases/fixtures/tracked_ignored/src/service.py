"""Capture service."""

def capture(key: str) -> str:
    if not key:
        raise ValueError("key is required")
    return f"captured:{key}"
