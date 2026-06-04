# web/auth/router.py

from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from web.auth.config import auth_settings, google_redirect_uri
from web.auth.database import upsert_google_user
from web.auth.deps import get_optional_user, require_user
from web.auth.tokens import create_access_token

router = APIRouter(prefix="/api/auth", tags=["auth"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def _set_session_cookie(response: RedirectResponse, token: str) -> None:
    settings = auth_settings()
    response.set_cookie(
        key=settings["cookie_name"],
        value=token,
        httponly=True,
        secure=settings["cookie_secure"],
        samesite="lax",
        max_age=settings["cookie_max_age"],
        path="/",
    )


@router.get("/config")
def auth_config() -> dict:
    settings = auth_settings()
    return {
        "auth_required": settings["auth_required"],
        "google_enabled": settings["google_enabled"],
    }


@router.get("/me")
def auth_me(user=Depends(get_optional_user)) -> dict:
    if user is None:
        return {"authenticated": False, "user": None}
    return {"authenticated": True, "user": user.to_public()}


@router.get("/google")
def google_login(request: Request) -> RedirectResponse:
    settings = auth_settings()
    if not settings["google_enabled"]:
        raise HTTPException(
            status_code=503,
            detail="Google sign-in is not configured. Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET.",
        )

    state = secrets.token_urlsafe(24)
    params = {
        "client_id": settings["client_id"],
        "redirect_uri": google_redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
        "state": state,
    }
    response = RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")
    response.set_cookie(
        "fc_oauth_state",
        state,
        httponly=True,
        secure=settings["cookie_secure"],
        samesite="lax",
        max_age=600,
        path="/",
    )
    return response


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    settings = auth_settings()
    frontend = settings["frontend_url"]

    if error:
        return RedirectResponse(f"{frontend}/login?error={error}")

    if not code or not state:
        return RedirectResponse(f"{frontend}/login?error=missing_code")

    saved_state = request.cookies.get("fc_oauth_state")
    if not saved_state or saved_state != state:
        return RedirectResponse(f"{frontend}/login?error=invalid_state")

    async with httpx.AsyncClient(timeout=20.0) as client:
        token_res = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings["client_id"],
                "client_secret": settings["client_secret"],
                "redirect_uri": google_redirect_uri(),
                "grant_type": "authorization_code",
            },
        )
        if token_res.status_code >= 400:
            return RedirectResponse(f"{frontend}/login?error=token_exchange_failed")

        access_token = token_res.json().get("access_token")
        if not access_token:
            return RedirectResponse(f"{frontend}/login?error=no_access_token")

        profile_res = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if profile_res.status_code >= 400:
            return RedirectResponse(f"{frontend}/login?error=profile_failed")

        profile = profile_res.json()

    google_sub = profile.get("sub")
    email = profile.get("email")
    if not google_sub or not email:
        return RedirectResponse(f"{frontend}/login?error=profile_incomplete")

    user = upsert_google_user(
        google_sub=google_sub,
        email=email,
        name=profile.get("name") or email.split("@")[0],
        picture=profile.get("picture"),
    )
    token = create_access_token(user.id, email=user.email, name=user.name)
    response = RedirectResponse(f"{frontend}/")
    _set_session_cookie(response, token)
    response.delete_cookie("fc_oauth_state", path="/")
    return response


@router.post("/logout")
def logout(response: Response) -> dict:
    settings = auth_settings()
    response.delete_cookie(settings["cookie_name"], path="/")
    return {"ok": True}