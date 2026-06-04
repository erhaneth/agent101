from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class ConfigCheck:
    name: str
    ok: bool
    severity: str
    detail: str


PLACEHOLDER_VALUES = {
    "",
    "changeme",
    "change-me",
    "generate-a-long-random-string",
    "your_google_gemini_api_key",
    "your_tavily_api_key",
}

PLACEHOLDER_HOSTS = {
    "example.com",
    "example.org",
    "example.net",
    "localhost",
    "127.0.0.1",
    "::1",
}


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        raise FileNotFoundError(path)
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def merged_env(env_file: str | None = None) -> dict[str, str]:
    env = dict(os.environ)
    if env_file:
        env.update(load_env_file(Path(env_file)))
    return env


def validate_production_config(env: dict[str, str]) -> list[ConfigCheck]:
    checks = [
        _required_secret(env, "AUTH_SECRET_KEY", min_length=32),
        _bool_is_true(env, "AUTH_COOKIE_SECURE"),
        _bool_is_true(env, "AUTH_REQUIRED"),
        _https_url(env, "AUTH_FRONTEND_URL"),
        _https_url(env, "AUTH_BACKEND_URL"),
        _cors_origins(env),
        _required_secret(env, "GOOGLE_OAUTH_CLIENT_ID", min_length=8),
        _required_secret(env, "GOOGLE_OAUTH_CLIENT_SECRET", min_length=8),
        _required_secret(env, "GOOGLE_API_KEY", min_length=8),
        _required_secret(env, "TAVILY_API_KEY", min_length=8),
        _equals(env, "JOB_EXECUTION_MODE", "external"),
        _postgres_url(env, "JOB_DATABASE_URL"),
        _postgres_url(env, "AUTH_DATABASE_URL"),
        _durable_artifact_storage(env),
        _positive_int(env, "JOB_MAX_ATTEMPTS"),
        _positive_int(env, "JOB_STALE_AFTER_SECONDS"),
        _non_negative_int(env, "MAX_ACTIVE_JOBS_PER_USER"),
        _non_negative_int(env, "MAX_JOB_CREATES_PER_WINDOW"),
        _positive_int(env, "JOB_CREATE_WINDOW_SECONDS"),
        _optional_url(env, "ALERT_WEBHOOK_URL", severity="warning"),
        _optional_url(env, "FACTCRAFTER_SMOKE_URL", severity="warning"),
    ]
    return checks


def _value(env: dict[str, str], key: str) -> str:
    return env.get(key, "").strip()


def _is_placeholder(value: str) -> bool:
    return value.strip().lower() in PLACEHOLDER_VALUES


def _is_placeholder_host(hostname: str | None) -> bool:
    if not hostname:
        return True
    host = hostname.strip().lower()
    return host in PLACEHOLDER_HOSTS or host.endswith(".example.com")


def _required_secret(env: dict[str, str], key: str, *, min_length: int) -> ConfigCheck:
    value = _value(env, key)
    ok = bool(value) and not _is_placeholder(value) and len(value) >= min_length
    return ConfigCheck(
        key,
        ok,
        "error",
        f"{key} is set" if ok else f"{key} must be set to a non-placeholder value",
    )


def _bool_is_true(env: dict[str, str], key: str) -> ConfigCheck:
    ok = _value(env, key).lower() in {"1", "true", "yes", "on"}
    return ConfigCheck(
        key,
        ok,
        "error",
        f"{key}=true" if ok else f"{key} must be true in production",
    )


def _https_url(env: dict[str, str], key: str) -> ConfigCheck:
    value = _value(env, key)
    parsed = urlparse(value)
    ok = parsed.scheme == "https" and bool(parsed.netloc) and not _is_placeholder_host(parsed.hostname)
    return ConfigCheck(
        key,
        ok,
        "error",
        f"{key} is HTTPS" if ok else f"{key} must be a real production https:// URL",
    )


def _cors_origins(env: dict[str, str]) -> ConfigCheck:
    value = _value(env, "CORS_ORIGINS")
    frontend_url = _value(env, "AUTH_FRONTEND_URL")
    origins = [origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()]
    if not origins:
        return ConfigCheck(
            "CORS_ORIGINS",
            True,
            "warning",
            "CORS_ORIGINS not set; defaults to AUTH_FRONTEND_URL",
        )
    bad_origins: list[str] = []
    for origin in origins:
        parsed = urlparse(origin)
        if (
            origin == "*"
            or parsed.scheme != "https"
            or not parsed.netloc
            or _is_placeholder_host(parsed.hostname)
        ):
            bad_origins.append(origin)
    includes_frontend = frontend_url.rstrip("/") in origins
    ok = not bad_origins and includes_frontend
    detail = (
        "CORS_ORIGINS uses real HTTPS origins and includes AUTH_FRONTEND_URL"
        if ok
        else "CORS_ORIGINS must use real HTTPS origins and include AUTH_FRONTEND_URL"
    )
    return ConfigCheck("CORS_ORIGINS", ok, "error", detail)


def _optional_url(env: dict[str, str], key: str, *, severity: str) -> ConfigCheck:
    value = _value(env, key)
    if not value:
        return ConfigCheck(key, False, severity, f"{key} is not configured")
    parsed = urlparse(value)
    ok = (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and not _is_placeholder_host(parsed.hostname)
    )
    return ConfigCheck(
        key,
        ok,
        "error" if not ok else severity,
        f"{key} is configured" if ok else f"{key} must be a real http:// or https:// URL",
    )


def _postgres_url(env: dict[str, str], key: str) -> ConfigCheck:
    value = _value(env, key)
    parsed = urlparse(value)
    ok = parsed.scheme in {"postgres", "postgresql"} and bool(parsed.netloc)
    return ConfigCheck(
        key,
        ok,
        "error",
        f"{key} uses Postgres" if ok else f"{key} must be a postgres:// or postgresql:// URL",
    )


def _equals(env: dict[str, str], key: str, expected: str) -> ConfigCheck:
    ok = _value(env, key).lower() == expected
    return ConfigCheck(
        key,
        ok,
        "error",
        f"{key}={expected}" if ok else f"{key} must be {expected}",
    )


def _durable_artifact_storage(env: dict[str, str]) -> ConfigCheck:
    artifact_db = _value(env, "ARTIFACT_DATABASE_URL")
    run_dir = _value(env, "RUN_ARTIFACT_DIR")
    db_ok = False
    if artifact_db:
        parsed = urlparse(artifact_db)
        db_ok = parsed.scheme in {"postgres", "postgresql"} and bool(parsed.netloc)
    ok = db_ok or bool(run_dir)
    detail = "durable artifact storage is configured" if ok else (
        "set ARTIFACT_DATABASE_URL or a persistent RUN_ARTIFACT_DIR"
    )
    return ConfigCheck("artifact_storage", ok, "error", detail)


def _positive_int(env: dict[str, str], key: str) -> ConfigCheck:
    return _int_check(env, key, minimum=1)


def _non_negative_int(env: dict[str, str], key: str) -> ConfigCheck:
    return _int_check(env, key, minimum=0)


def _int_check(env: dict[str, str], key: str, *, minimum: int) -> ConfigCheck:
    value = _value(env, key)
    try:
        parsed = int(value)
    except ValueError:
        return ConfigCheck(key, False, "error", f"{key} must be an integer")
    ok = parsed >= minimum
    return ConfigCheck(
        key,
        ok,
        "error",
        f"{key}={parsed}" if ok else f"{key} must be >= {minimum}",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate FactCrafter production configuration.")
    parser.add_argument("--env-file", help="Optional .env-style file to validate.")
    parser.add_argument(
        "--strict-warnings",
        action="store_true",
        help="Fail when warning-level checks are missing, useful for final release gates.",
    )
    args = parser.parse_args(argv)

    checks = validate_production_config(merged_env(args.env_file))
    failed = False
    for check in checks:
        marker = "PASS" if check.ok else check.severity.upper()
        print(f"{marker} {check.name}: {check.detail}")
        if not check.ok and (check.severity == "error" or args.strict_warnings):
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
