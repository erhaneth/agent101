from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable


UrlOpener = Callable[[urllib.request.Request, float], object]


@dataclass
class SmokeResult:
    name: str
    ok: bool
    detail: str


def normalize_base_url(value: str) -> str:
    base_url = value.strip().rstrip("/")
    if not base_url:
        raise ValueError("base URL is required")
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("base URL must start with http:// or https://")
    return base_url


def run_smoke_checks(
    base_url: str,
    *,
    timeout_seconds: float = 10.0,
    allow_degraded_ready: bool = False,
    opener: UrlOpener | None = None,
) -> list[SmokeResult]:
    base = normalize_base_url(base_url)
    opener = opener or _default_opener
    results: list[SmokeResult] = []

    health = _get_json(opener, f"{base}/api/health", timeout_seconds)
    results.append(_check_health(health))
    results.append(_check_request_id(health))

    ready = _get_json(opener, f"{base}/api/ready", timeout_seconds)
    results.append(_check_ready(ready, allow_degraded_ready=allow_degraded_ready))
    metrics = _get_json(opener, f"{base}/api/metrics", timeout_seconds)
    results.append(_check_metrics(metrics))
    return results


def _default_opener(request: urllib.request.Request, timeout_seconds: float) -> object:
    return urllib.request.urlopen(request, timeout=timeout_seconds)


def _get_json(opener: UrlOpener, url: str, timeout_seconds: float) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with opener(request, timeout_seconds) as response:
            body = response.read().decode("utf-8")
            headers = dict(response.headers.items())
            return {
                "status_code": response.status,
                "headers": headers,
                "json": json.loads(body),
            }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"raw": body}
        return {
            "status_code": exc.code,
            "headers": dict(exc.headers.items()),
            "json": payload,
        }


def _check_health(response: dict) -> SmokeResult:
    status_code = response["status_code"]
    payload = response["json"]
    ok = status_code == 200 and payload.get("status") == "ok"
    return SmokeResult(
        "health",
        ok,
        f"/api/health status={status_code} payload_status={payload.get('status')}",
    )


def _check_request_id(response: dict) -> SmokeResult:
    headers = {key.lower(): value for key, value in response["headers"].items()}
    request_id = headers.get("x-request-id", "")
    return SmokeResult(
        "request_id",
        bool(request_id),
        "X-Request-ID present" if request_id else "X-Request-ID missing",
    )


def _check_ready(response: dict, *, allow_degraded_ready: bool) -> SmokeResult:
    status_code = response["status_code"]
    payload = response["json"]
    ready = bool(payload.get("ready"))
    degraded_allowed = allow_degraded_ready and status_code == 503 and payload.get("status") == "degraded"
    ok = (status_code == 200 and ready) or degraded_allowed
    return SmokeResult(
        "ready",
        ok,
        f"/api/ready status={status_code} ready={ready} service_status={payload.get('status')}",
    )


def _check_metrics(response: dict) -> SmokeResult:
    status_code = response["status_code"]
    payload = response["json"]
    ok = (
        status_code == 200
        and isinstance(payload.get("api"), dict)
        and isinstance(payload.get("jobs"), dict)
    )
    return SmokeResult(
        "metrics",
        ok,
        f"/api/metrics status={status_code} has_api={isinstance(payload.get('api'), dict)}",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-check a deployed FactCrafter API.")
    parser.add_argument("base_url", help="Base URL, for example https://factcrafter-api.onrender.com")
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument(
        "--allow-degraded-ready",
        action="store_true",
        help="Allow /api/ready to return 503 degraded; useful before production data stores are configured.",
    )
    args = parser.parse_args(argv)

    try:
        results = run_smoke_checks(
            args.base_url,
            timeout_seconds=args.timeout_seconds,
            allow_degraded_ready=args.allow_degraded_ready,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"smoke check failed before assertions: {exc}", file=sys.stderr)
        return 2

    failed = False
    for result in results:
        marker = "PASS" if result.ok else "FAIL"
        print(f"{marker} {result.name}: {result.detail}")
        failed = failed or not result.ok
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
