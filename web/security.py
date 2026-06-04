from __future__ import annotations

import os
from urllib.parse import urlparse

from fastapi import FastAPI


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
PLACEHOLDER_HOSTS = {"example.com", "example.org", "example.net"}
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    ),
}


def allowed_cors_origins(settings: dict) -> list[str]:
    configured = os.getenv("CORS_ORIGINS", "").strip()
    if configured:
        origins = [origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()]
    else:
        origins = [settings["frontend_url"]]
        if not settings.get("is_production"):
            origins.extend(["http://localhost:5173", "http://127.0.0.1:5173"])

    _validate_cors_origins(origins, is_production=bool(settings.get("is_production")))
    return origins


def install_security_headers(app: FastAPI, *, is_production: bool) -> None:
    @app.middleware("http")
    async def security_headers_middleware(request, call_next):
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        if is_production:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response


def _validate_cors_origins(origins: list[str], *, is_production: bool) -> None:
    if not origins:
        raise RuntimeError("At least one CORS origin must be configured")
    for origin in origins:
        parsed = urlparse(origin)
        if origin == "*" or parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError(f"Invalid CORS origin: {origin}")
        if is_production:
            host = (parsed.hostname or "").lower()
            if (
                parsed.scheme != "https"
                or host in LOCAL_HOSTS
                or host in PLACEHOLDER_HOSTS
                or host.endswith(".example.com")
            ):
                raise RuntimeError(
                    "Production CORS origins must be real HTTPS origins; "
                    f"invalid origin: {origin}"
                )
