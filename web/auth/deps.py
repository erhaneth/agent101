# web/auth/deps.py

from __future__ import annotations

from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Request

from web.auth.config import auth_settings
from web.auth.database import User, ensure_dev_user, get_user_by_id
from web.auth.tokens import decode_access_token


def _user_from_token(token: str | None) -> Optional[User]:
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    return get_user_by_id(str(user_id))


def get_optional_user(
    request: Request,
    fc_token: str | None = Cookie(default=None),
) -> Optional[User]:
    settings = auth_settings()
    user = _user_from_token(fc_token)
    if user:
        return user
    if not settings["auth_required"]:
        return ensure_dev_user(
            settings["dev_user_id"],
            "dev@local.factcrafter",
            "Local Dev",
        )
    return None


def require_user(user: Optional[User] = Depends(get_optional_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def verify_job_owner(job_user_id: str | None, current: User) -> None:
    if job_user_id and job_user_id != current.id:
        raise HTTPException(status_code=403, detail="Forbidden")