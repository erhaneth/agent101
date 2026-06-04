# web/auth/config.py

from __future__ import annotations

import os
import secrets
from functools import lru_cache


def _is_production() -> bool:
    env = os.getenv("ENVIRONMENT", os.getenv("ENV", "")).strip().lower()
    return env in {"production", "prod"} or os.getenv("RENDER", "").strip().lower() == "true"


@lru_cache
def auth_settings() -> dict:
    frontend = os.getenv("AUTH_FRONTEND_URL", "http://localhost:5173").rstrip("/")
    backend = os.getenv("AUTH_BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
    secret = os.getenv("AUTH_SECRET_KEY", "").strip()
    is_production = _is_production()

    if is_production and not secret:
        raise RuntimeError("AUTH_SECRET_KEY must be set in production")

    if not secret:
        secret = secrets.token_urlsafe(32)

    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    auth_required = os.getenv("AUTH_REQUIRED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }

    return {
        "frontend_url": frontend,
        "backend_url": backend,
        "secret_key": secret,
        "client_id": client_id,
        "client_secret": client_secret,
        "google_enabled": bool(client_id and client_secret),
        "auth_required": auth_required,
        "cookie_name": os.getenv("AUTH_COOKIE_NAME", "fc_token"),
        "cookie_secure": os.getenv(
            "AUTH_COOKIE_SECURE",
            "true" if is_production else "false",
        ).strip().lower()
        in {"1", "true", "yes", "on"},
        "cookie_max_age": int(os.getenv("AUTH_COOKIE_MAX_AGE", str(7 * 24 * 3600))),
        "dev_user_id": os.getenv("AUTH_DEV_USER_ID", "dev-local"),
        "is_production": is_production,
    }


def google_redirect_uri() -> str:
    return f"{auth_settings()['backend_url']}/api/auth/google/callback"
