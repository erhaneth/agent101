from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.validate_config import load_env_file  # noqa: E402

PLACEHOLDER_HOSTS = {"example.com", "example.org", "example.net", "localhost", "127.0.0.1", "::1"}


@dataclass(frozen=True)
class GateCommand:
    name: str
    argv: list[str]


def validate_release_target(*, env_file: str, base_url: str) -> None:
    env = load_env_file(Path(env_file))
    normalized_base = _normalize_production_url(base_url, "base URL")
    smoke_url = env.get("FACTCRAFTER_SMOKE_URL", "").strip()
    if not smoke_url:
        raise ValueError("FACTCRAFTER_SMOKE_URL must be set in the production env file")
    normalized_smoke = _normalize_production_url(smoke_url, "FACTCRAFTER_SMOKE_URL")
    if normalized_base != normalized_smoke:
        raise ValueError(
            "release gate base URL must match FACTCRAFTER_SMOKE_URL "
            f"({normalized_base} != {normalized_smoke})"
        )


def _normalize_production_url(value: str, label: str) -> str:
    parsed = urlparse(value.strip().rstrip("/"))
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{label} must be a production https:// URL")
    host = (parsed.hostname or "").lower()
    if host in PLACEHOLDER_HOSTS or host.endswith(".example.com"):
        raise ValueError(f"{label} must not use a local or placeholder host")
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def build_release_gate_commands(
    *,
    env_file: str,
    base_url: str,
    load_requests: int = 60,
    load_concurrency: int = 6,
    load_max_p95_latency_ms: float = 1500.0,
    include_job_flow: bool = False,
    allow_degraded_ready: bool = False,
) -> list[GateCommand]:
    python = sys.executable
    commands = [
        GateCommand(
            "config",
            [
                python,
                str(ROOT_DIR / "scripts" / "validate_config.py"),
                "--env-file",
                env_file,
                "--strict-warnings",
            ],
        ),
        GateCommand(
            "smoke",
            [
                python,
                str(ROOT_DIR / "scripts" / "smoke.py"),
                base_url,
                "--timeout-seconds",
                "20",
            ],
        ),
        GateCommand(
            "load",
            [
                python,
                str(ROOT_DIR / "scripts" / "load_probe.py"),
                base_url,
                "--requests",
                str(load_requests),
                "--concurrency",
                str(load_concurrency),
                "--max-p95-latency-ms",
                str(load_max_p95_latency_ms),
            ],
        ),
    ]
    if allow_degraded_ready:
        commands[1].argv.append("--allow-degraded-ready")
    if include_job_flow:
        commands[2].argv.append("--include-job-flow")
    return commands


def run_release_gate(commands: list[GateCommand], *, dry_run: bool = False) -> int:
    for command in commands:
        printable = " ".join(command.argv)
        if dry_run:
            print(f"DRY-RUN {command.name}: {printable}")
            continue
        print(f"RUN {command.name}: {printable}")
        result = subprocess.run(command.argv, cwd=ROOT_DIR, check=False)
        if result.returncode != 0:
            print(f"FAIL {command.name}: exit_code={result.returncode}", file=sys.stderr)
            return result.returncode
        print(f"PASS {command.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the FactCrafter production release gate: config, smoke, then load probe.",
    )
    parser.add_argument("--env-file", required=True, help="Production .env-style file to validate.")
    parser.add_argument("--base-url", required=True, help="Hosted deployment base URL.")
    parser.add_argument("--load-requests", type=int, default=60)
    parser.add_argument("--load-concurrency", type=int, default=6)
    parser.add_argument("--load-max-p95-latency-ms", type=float, default=1500.0)
    parser.add_argument("--include-job-flow", action="store_true")
    parser.add_argument("--allow-degraded-ready", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if not args.dry_run:
        try:
            validate_release_target(env_file=args.env_file, base_url=args.base_url)
        except Exception as exc:  # noqa: BLE001
            print(f"release target validation failed: {exc}", file=sys.stderr)
            return 2

    commands = build_release_gate_commands(
        env_file=args.env_file,
        base_url=args.base_url,
        load_requests=args.load_requests,
        load_concurrency=args.load_concurrency,
        load_max_p95_latency_ms=args.load_max_p95_latency_ms,
        include_job_flow=args.include_job_flow,
        allow_degraded_ready=args.allow_degraded_ready,
    )
    return run_release_gate(commands, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
