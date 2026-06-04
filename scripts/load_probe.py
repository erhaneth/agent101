from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable

from scripts.smoke import normalize_base_url


UrlOpener = Callable[[urllib.request.Request, float], object]


@dataclass(frozen=True)
class RequestResult:
    name: str
    ok: bool
    status_code: int
    latency_ms: float
    detail: str


@dataclass(frozen=True)
class LoadProbeSummary:
    total_requests: int
    failed_requests: int
    failure_rate: float
    p95_latency_ms: float
    max_latency_ms: float
    ok: bool
    detail: str


def run_load_probe(
    base_url: str,
    *,
    requests: int = 30,
    concurrency: int = 5,
    timeout_seconds: float = 10.0,
    include_job_flow: bool = False,
    max_failure_rate: float = 0.0,
    max_p95_latency_ms: float = 1500.0,
    opener: UrlOpener | None = None,
) -> tuple[LoadProbeSummary, list[RequestResult]]:
    base = normalize_base_url(base_url)
    opener = opener or _default_opener
    total = max(1, requests)
    workers = max(1, min(concurrency, total))

    jobs = []
    for index in range(total):
        if include_job_flow and index % 4 == 3:
            jobs.append(("job_flow", f"{base}/api/jobs"))
        else:
            path = ["/api/health", "/api/ready", "/api/metrics", "/api/runs?limit=1", "/api/jobs"][index % 5]
            jobs.append((path, f"{base}{path}"))

    results: list[RequestResult] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(
                _job_flow if name == "job_flow" else _get_json,
                opener,
                url,
                timeout_seconds,
                index,
            )
            for index, (name, url) in enumerate(jobs)
        ]
        for future in as_completed(futures):
            results.append(future.result())

    failed = sum(1 for result in results if not result.ok)
    latencies = [result.latency_ms for result in results]
    p95 = _percentile(latencies, 95)
    failure_rate = failed / len(results)
    ok = failure_rate <= max_failure_rate and p95 <= max_p95_latency_ms
    detail = (
        f"requests={len(results)} failures={failed} "
        f"failure_rate={failure_rate:.2%} p95_ms={p95:.1f}"
    )
    return (
        LoadProbeSummary(
            total_requests=len(results),
            failed_requests=failed,
            failure_rate=failure_rate,
            p95_latency_ms=p95,
            max_latency_ms=max(latencies) if latencies else 0.0,
            ok=ok,
            detail=detail,
        ),
        results,
    )


def _default_opener(request: urllib.request.Request, timeout_seconds: float) -> object:
    return urllib.request.urlopen(request, timeout=timeout_seconds)


def _get_json(
    opener: UrlOpener,
    url: str,
    timeout_seconds: float,
    index: int,
) -> RequestResult:
    started = time.perf_counter()
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with opener(request, timeout_seconds) as response:
            raw = response.read().decode("utf-8")
            payload = json.loads(raw) if raw else {}
            status_code = int(response.status)
    except urllib.error.HTTPError as exc:
        return _failed_result(url, started, int(exc.code), f"HTTP {exc.code}")
    except Exception as exc:  # noqa: BLE001
        return _failed_result(url, started, 0, str(exc))

    ok = 200 <= status_code < 300 and isinstance(payload, dict)
    return RequestResult(
        name=f"{index}:{request.full_url}",
        ok=ok,
        status_code=status_code,
        latency_ms=_elapsed_ms(started),
        detail=f"status={status_code}",
    )


def _job_flow(
    opener: UrlOpener,
    url: str,
    timeout_seconds: float,
    index: int,
) -> RequestResult:
    started = time.perf_counter()
    goal = f"Load probe queued cancel flow {index}"
    try:
        created = _json_request(
            opener,
            url,
            timeout_seconds,
            method="POST",
            payload={"goal": goal},
        )
        job_id = str(created.get("id", ""))
        if not job_id:
            return _failed_result(url, started, 0, "job create response missing id")
        canceled = _json_request(
            opener,
            f"{url}/{job_id}/cancel",
            timeout_seconds,
            method="POST",
            payload=None,
        )
    except urllib.error.HTTPError as exc:
        return _failed_result(url, started, int(exc.code), f"HTTP {exc.code}")
    except Exception as exc:  # noqa: BLE001
        return _failed_result(url, started, 0, str(exc))

    ok = canceled.get("status") == "canceled"
    return RequestResult(
        name=f"{index}:job_flow",
        ok=ok,
        status_code=200 if ok else 0,
        latency_ms=_elapsed_ms(started),
        detail=f"created={job_id} canceled={canceled.get('status')}",
    )


def _json_request(
    opener: UrlOpener,
    url: str,
    timeout_seconds: float,
    *,
    method: str,
    payload: dict | None,
) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    with opener(request, timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def _failed_result(url: str, started: float, status_code: int, detail: str) -> RequestResult:
    return RequestResult(
        name=url,
        ok=False,
        status_code=status_code,
        latency_ms=_elapsed_ms(started),
        detail=detail,
    )


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[percentile - 1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a lightweight FactCrafter API load probe.")
    parser.add_argument("base_url")
    parser.add_argument("--requests", type=int, default=30)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--include-job-flow", action="store_true")
    parser.add_argument("--max-failure-rate", type=float, default=0.0)
    parser.add_argument("--max-p95-latency-ms", type=float, default=1500.0)
    args = parser.parse_args(argv)

    try:
        summary, results = run_load_probe(
            args.base_url,
            requests=args.requests,
            concurrency=args.concurrency,
            timeout_seconds=args.timeout_seconds,
            include_job_flow=args.include_job_flow,
            max_failure_rate=args.max_failure_rate,
            max_p95_latency_ms=args.max_p95_latency_ms,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"load probe failed before assertions: {exc}", file=sys.stderr)
        return 2

    marker = "PASS" if summary.ok else "FAIL"
    print(f"{marker} load_probe: {summary.detail}")
    for result in sorted(results, key=lambda item: item.name):
        result_marker = "PASS" if result.ok else "FAIL"
        print(f"{result_marker} {result.name}: {result.detail} latency_ms={result.latency_ms:.1f}")
    return 0 if summary.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
