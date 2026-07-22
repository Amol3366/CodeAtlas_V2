"""Authentication HTTP routes (FastAPI)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.services.auth_service import AuthError, AuthService

router = APIRouter(prefix="/auth", tags=["auth"])

_service = AuthService(credentials={})


@router.post("/login")
def login(username: str, password: str) -> dict[str, str]:
    """Authenticate a user and start a session.

    The authentication flow starts here and delegates to AuthService.authenticate.
    """
    try:
        ok = _service.authenticate(username, password)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail="invalid credentials") from exc
    if not ok:
        raise HTTPException(status_code=401, detail="invalid credentials")
    return {"status": "ok", "user": username}
