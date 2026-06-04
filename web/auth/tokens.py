# web/auth/tokens.py

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt

from web.auth.config import auth_settings


def create_access_token(user_id: str, *, email: str, name: str) -> str:
    settings = auth_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "name": name,
        "iat": now,
        "exp": now + timedelta(seconds=settings["cookie_max_age"]),
    }
    return jwt.encode(payload, settings["secret_key"], algorithm="HS256")


def decode_access_token(token: str) -> Optional[dict[str, Any]]:
    settings = auth_settings()
    try:
        return jwt.decode(token, settings["secret_key"], algorithms=["HS256"])
    except jwt.PyJWTError:
        return None