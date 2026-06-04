import os
import io
import json
import subprocess
import sys
import threading
import unittest
import yaml
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from team.artifacts import write_run_artifacts
from team.artifact_store import ArtifactStore
from team.cache import clear_cache, get_cached_json, set_cached_json
from team.guardrails import input_guardrail
from team.claimverifier import apply_verifications, source_blocks_for_claim, source_lookup
from team.evaluator import apply_report_verification, evaluate_grounding, markdown_url_label_mismatches
from team.graph import route_after_report_verify
from team.humanreview import human_review_agent, is_high_stakes
from team.web_review import register_review, submit_web_approval, wait_for_web_approval
import team.web_review as web_review
from team.reportrepair import failed_report_items, remove_failed_report_items, report_repair_agent
from team.reportverifier import build_records, cited_report_items, relevant_excerpt
from team.runtime_context import current_web_job_id, is_web_context, web_job_context
from team.sourcequality import rank_source, source_quality_passes
from team.sourcefetcher import clean_text, fetch_and_parse_source, is_probably_bad_page, parse_html
from team.searcher import (
    classify_source_type,
    search_days_for_brief,
    searcher_agent,
    should_skip_source,
)
from team.factchecker import source_passes_static_checks
from team.main import run_research
from team.utils import response_to_text, strip_json_fences
from team.writer import writer_agent
from evals.run_eval import score_case
from scripts.smoke import normalize_base_url, run_smoke_checks
from scripts.validate_config import validate_production_config
from scripts.load_probe import run_load_probe
from scripts.release_gate import (
    GateCommand,
    build_release_gate_commands,
    run_release_gate,
    validate_release_target,
)
from web.alerts import alerts_enabled, send_job_alert
from web.auth.config import auth_settings
from web.auth.database import ensure_dev_user, get_user_by_id, init_db, upsert_google_user
from web.auth.tokens import decode_access_token
from web.job_store import JobStore
from web.limits import (
    JobCreateRateLimiter,
    LimitSettings,
    active_job_count,
    enforce_active_job_limit,
)
from web.jobs import JobEvent, JobManager, JobStatus, ResearchJob
from web.runs import get_run, list_runs
from web.health import readiness_report
from web.metrics import metrics_snapshot, reset_metrics
from web.observability import current_request_id
from web.server import create_app
from worker import run_worker_healthcheck, run_worker_loop


class FailingSearchClient:
    def search(self, **kwargs):
        raise RuntimeError("search unavailable")


class CountingSearchClient:
    def __init__(self):
        self.calls = 0

    def search(self, **kwargs):
        self.calls += 1
        return {
            "results": [
                {
                    "title": "Cached result",
                    "url": "https://example.com/cached",
                    "content": "This source has enough content to pass the snippet length check for caching. It includes a second sentence so the searcher accepts it as usable evidence.",
                    "raw_content": "Cached raw source content about evidence quality.",
                }
            ]
        }


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeHTTPResponse:
    encoding = "utf-8"
    apparent_encoding = "utf-8"


class FakeSmokeResponse:
    def __init__(self, status, headers, payload):
        self.status = status
        self.headers = headers
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


class FakeLoadResponse(FakeSmokeResponse):
    pass


class FakeAsyncHTTPResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeGoogleOAuthClient:
    def __init__(self, *args, **kwargs):
        self.posts = []
        self.gets = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback):
        return False

    async def post(self, url, data):
        self.posts.append((url, data))
        return FakeAsyncHTTPResponse(200, {"access_token": "google-access-token"})

    async def get(self, url, headers):
        self.gets.append((url, headers))
        return FakeAsyncHTTPResponse(
            200,
            {
                "sub": "google-user-1",
                "email": "oauth@example.com",
                "name": "OAuth User",
                "picture": "https://example.com/avatar.png",
            },
        )


class HardeningTests(unittest.TestCase):
    def test_smoke_check_requires_http_base_url(self):
        with self.assertRaisesRegex(ValueError, "http"):
            normalize_base_url("factcrafter.example.com")

    def test_smoke_check_passes_for_healthy_api(self):
        def opener(request, _timeout):
            if request.full_url.endswith("/api/health"):
                return FakeSmokeResponse(
                    200,
                    {"X-Request-ID": "req-smoke"},
                    {"status": "ok"},
                )
            if request.full_url.endswith("/api/ready"):
                return FakeSmokeResponse(
                    200,
                    {"X-Request-ID": "req-smoke-ready"},
                    {"status": "ready", "ready": True},
                )
            if request.full_url.endswith("/api/metrics"):
                return FakeSmokeResponse(
                    200,
                    {"X-Request-ID": "req-smoke-metrics"},
                    {"api": {}, "jobs": {}},
                )
            raise AssertionError(request.full_url)

        results = run_smoke_checks("https://factcrafter.example.com/", opener=opener)

        self.assertTrue(all(result.ok for result in results))

    def test_smoke_check_rejects_degraded_readiness_by_default(self):
        def opener(request, _timeout):
            if request.full_url.endswith("/api/health"):
                return FakeSmokeResponse(
                    200,
                    {"X-Request-ID": "req-smoke"},
                    {"status": "ok"},
                )
            if request.full_url.endswith("/api/ready"):
                return FakeSmokeResponse(
                    503,
                    {"X-Request-ID": "req-smoke-ready"},
                    {"status": "degraded", "ready": False},
                )
            if request.full_url.endswith("/api/metrics"):
                return FakeSmokeResponse(
                    200,
                    {"X-Request-ID": "req-smoke-metrics"},
                    {"api": {}, "jobs": {}},
                )
            raise AssertionError(request.full_url)

        results = run_smoke_checks("https://factcrafter.example.com", opener=opener)

        self.assertFalse(next(result for result in results if result.name == "ready").ok)

    def test_smoke_check_can_allow_degraded_readiness(self):
        def opener(request, _timeout):
            if request.full_url.endswith("/api/health"):
                return FakeSmokeResponse(
                    200,
                    {"X-Request-ID": "req-smoke"},
                    {"status": "ok"},
                )
            if request.full_url.endswith("/api/ready"):
                return FakeSmokeResponse(
                    503,
                    {"X-Request-ID": "req-smoke-ready"},
                    {"status": "degraded", "ready": False},
                )
            if request.full_url.endswith("/api/metrics"):
                return FakeSmokeResponse(
                    200,
                    {"X-Request-ID": "req-smoke-metrics"},
                    {"api": {}, "jobs": {}},
                )
            raise AssertionError(request.full_url)

        results = run_smoke_checks(
            "https://factcrafter.example.com",
            allow_degraded_ready=True,
            opener=opener,
        )

        self.assertTrue(next(result for result in results if result.name == "ready").ok)

    def test_load_probe_passes_for_healthy_read_paths(self):
        def opener(request, _timeout):
            if request.full_url.endswith("/api/health"):
                return FakeLoadResponse(200, {}, {"status": "ok"})
            if request.full_url.endswith("/api/ready"):
                return FakeLoadResponse(200, {}, {"ready": True, "status": "ready"})
            if request.full_url.endswith("/api/metrics"):
                return FakeLoadResponse(200, {}, {"api": {}, "jobs": {}})
            if "/api/runs" in request.full_url:
                return FakeLoadResponse(200, {}, {"runs": []})
            if request.full_url.endswith("/api/jobs"):
                return FakeLoadResponse(200, {}, {"jobs": []})
            raise AssertionError(request.full_url)

        summary, results = run_load_probe(
            "https://factcrafter.example.com",
            requests=8,
            concurrency=2,
            opener=opener,
        )

        self.assertTrue(summary.ok)
        self.assertEqual(summary.failed_requests, 0)
        self.assertEqual(len(results), 8)

    def test_load_probe_fails_when_endpoint_errors(self):
        def opener(request, _timeout):
            if request.full_url.endswith("/api/ready"):
                raise RuntimeError("ready timed out")
            return FakeLoadResponse(200, {}, {"ok": True})

        summary, _results = run_load_probe(
            "https://factcrafter.example.com",
            requests=4,
            concurrency=2,
            opener=opener,
        )

        self.assertFalse(summary.ok)
        self.assertEqual(summary.failed_requests, 1)

    def test_load_probe_job_flow_creates_and_cancels(self):
        created_jobs = []

        def opener(request, _timeout):
            if request.full_url.endswith("/api/jobs") and request.get_method() == "POST":
                job_id = f"job-{len(created_jobs) + 1}"
                created_jobs.append(job_id)
                return FakeLoadResponse(200, {}, {"id": job_id, "status": "queued"})
            if request.full_url.endswith("/cancel"):
                return FakeLoadResponse(200, {}, {"status": "canceled"})
            return FakeLoadResponse(200, {}, {"ok": True})

        summary, results = run_load_probe(
            "https://factcrafter.example.com",
            requests=4,
            concurrency=2,
            include_job_flow=True,
            opener=opener,
        )

        self.assertTrue(summary.ok)
        self.assertEqual(created_jobs, ["job-1"])
        self.assertTrue(any(result.name.endswith("job_flow") for result in results))

    def test_release_gate_builds_config_smoke_and_load_commands(self):
        commands = build_release_gate_commands(
            env_file=".env.production",
            base_url="https://factcrafter.example.com",
            load_requests=12,
            load_concurrency=3,
            include_job_flow=True,
            allow_degraded_ready=True,
        )

        self.assertEqual([command.name for command in commands], ["config", "smoke", "load"])
        self.assertIn("validate_config.py", commands[0].argv[1])
        self.assertIn("--strict-warnings", commands[0].argv)
        self.assertIn("--allow-degraded-ready", commands[1].argv)
        self.assertIn("load_probe.py", commands[2].argv[1])
        self.assertIn("--include-job-flow", commands[2].argv)
        self.assertIn("12", commands[2].argv)
        self.assertIn("3", commands[2].argv)

    def test_release_gate_dry_run_does_not_execute_subprocesses(self):
        commands = [GateCommand("config", ["python", "missing.py"])]

        with patch("scripts.release_gate.subprocess.run") as run:
            with redirect_stdout(io.StringIO()):
                result = run_release_gate(commands, dry_run=True)

        self.assertEqual(result, 0)
        run.assert_not_called()

    def test_release_gate_cli_dry_run_works_from_script_path(self):
        result = subprocess.run(
            [
                sys.executable,
                "scripts/release_gate.py",
                "--env-file",
                ".env.example",
                "--base-url",
                "https://factcrafter.example.com",
                "--dry-run",
            ],
            cwd=Path(__file__).resolve().parents[1],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DRY-RUN config:", result.stdout)

    def test_release_gate_stops_on_first_failure(self):
        commands = [
            GateCommand("config", ["python", "config.py"]),
            GateCommand("smoke", ["python", "smoke.py"]),
        ]
        fake_result = type("Result", (), {"returncode": 7})()

        with patch("scripts.release_gate.subprocess.run", return_value=fake_result) as run:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                result = run_release_gate(commands)

        self.assertEqual(result, 7)
        run.assert_called_once()

    def test_release_gate_target_must_match_configured_smoke_url(self):
        with TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env.production"
            env_file.write_text(
                "FACTCRAFTER_SMOKE_URL=https://api.factcrafter.app\n",
                encoding="utf-8",
            )

            validate_release_target(
                env_file=str(env_file),
                base_url="https://api.factcrafter.app/",
            )

            with self.assertRaisesRegex(ValueError, "must match"):
                validate_release_target(
                    env_file=str(env_file),
                    base_url="https://staging.factcrafter.app",
                )

    def test_release_gate_target_rejects_placeholder_hosts(self):
        with TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env.production"
            env_file.write_text(
                "FACTCRAFTER_SMOKE_URL=https://factcrafter.example.com\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "placeholder"):
                validate_release_target(
                    env_file=str(env_file),
                    base_url="https://factcrafter.example.com",
                )

    def test_hosted_smoke_workflow_runs_smoke_script(self):
        workflow_path = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "hosted-smoke.yml"
        workflow = yaml.load(workflow_path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

        self.assertIn("workflow_dispatch", workflow["on"])
        self.assertIn("workflow_run", workflow["on"])
        run_steps = [
            step.get("run", "")
            for job in workflow["jobs"].values()
            for step in job.get("steps", [])
            if isinstance(step, dict)
        ]
        self.assertTrue(any("python scripts/smoke.py" in step for step in run_steps))
        self.assertTrue(any("FACTCRAFTER_SMOKE_URL" in step for step in run_steps))

    def test_dependabot_covers_dependency_update_surfaces(self):
        config_path = Path(__file__).resolve().parents[2] / ".github" / "dependabot.yml"
        config = yaml.load(config_path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        updates = {
            (entry["package-ecosystem"], entry["directory"])
            for entry in config["updates"]
        }

        self.assertIn(("pip", "/research-agent"), updates)
        self.assertIn(("npm", "/research-agent/ui"), updates)
        self.assertIn(("npm", "/factcrafter-web"), updates)
        self.assertIn(("github-actions", "/"), updates)
        self.assertTrue(
            all(entry["schedule"]["interval"] == "weekly" for entry in config["updates"])
        )

    def test_render_blueprint_declares_production_storage_and_plans(self):
        blueprint_path = Path(__file__).resolve().parents[1] / "render.yaml"
        blueprint = yaml.load(blueprint_path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        services = {service["name"]: service for service in blueprint["services"]}
        databases = {database["name"]: database for database in blueprint["databases"]}

        self.assertEqual(services["factcrafter-api"]["plan"], "starter")
        self.assertEqual(services["factcrafter-worker"]["plan"], "starter")
        self.assertEqual(databases["factcrafter-postgres"]["plan"], "basic-256mb")
        self.assertEqual(services["factcrafter-api"]["healthCheckPath"], "/api/ready")
        self.assertEqual(services["factcrafter-worker"]["maxShutdownDelaySeconds"], "300")

    def test_render_blueprint_wires_shared_postgres_and_oauth_env(self):
        blueprint_path = Path(__file__).resolve().parents[1] / "render.yaml"
        blueprint = yaml.load(blueprint_path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        services = {service["name"]: service for service in blueprint["services"]}
        api_env = {
            entry["key"]: entry
            for entry in services["factcrafter-api"]["envVars"]
            if "key" in entry
        }
        worker_env = {
            entry["key"]: entry
            for entry in services["factcrafter-worker"]["envVars"]
            if "key" in entry
        }

        for key in ("AUTH_DATABASE_URL", "JOB_DATABASE_URL", "ARTIFACT_DATABASE_URL"):
            self.assertEqual(api_env[key]["fromDatabase"]["name"], "factcrafter-postgres")
            self.assertEqual(worker_env[key]["fromDatabase"]["name"], "factcrafter-postgres")
            self.assertEqual(api_env[key]["fromDatabase"]["property"], "connectionString")
            self.assertEqual(worker_env[key]["fromDatabase"]["property"], "connectionString")

        for key in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"):
            self.assertEqual(api_env[key]["sync"], "false")
        self.assertEqual(api_env["AUTH_REQUIRED"]["value"], "true")
        self.assertEqual(api_env["JOB_EXECUTION_MODE"]["value"], "external")
        self.assertEqual(worker_env["JOB_EXECUTION_MODE"]["value"], "external")

    def test_production_config_validator_accepts_complete_config(self):
        checks = validate_production_config(
            {
                "AUTH_SECRET_KEY": "x" * 48,
                "AUTH_COOKIE_SECURE": "true",
                "AUTH_REQUIRED": "true",
                "AUTH_FRONTEND_URL": "https://factcrafter.app",
                "AUTH_BACKEND_URL": "https://api.factcrafter.app",
                "GOOGLE_OAUTH_CLIENT_ID": "google-client-id",
                "GOOGLE_OAUTH_CLIENT_SECRET": "google-client-secret",
                "GOOGLE_API_KEY": "gemini-api-key",
                "TAVILY_API_KEY": "tavily-api-key",
                "JOB_EXECUTION_MODE": "external",
                "JOB_DATABASE_URL": "postgresql://user:pass@db.example/factcrafter",
                "AUTH_DATABASE_URL": "postgresql://user:pass@db.example/factcrafter",
                "ARTIFACT_DATABASE_URL": "postgresql://user:pass@db.example/factcrafter",
                "JOB_MAX_ATTEMPTS": "3",
                "JOB_STALE_AFTER_SECONDS": "900",
                "MAX_ACTIVE_JOBS_PER_USER": "3",
                "MAX_JOB_CREATES_PER_WINDOW": "10",
                "JOB_CREATE_WINDOW_SECONDS": "3600",
                "ALERT_WEBHOOK_URL": "https://alerts.factcrafter.app/webhook",
                "FACTCRAFTER_SMOKE_URL": "https://api.factcrafter.app",
            }
        )

        self.assertTrue(all(check.ok for check in checks))

    def test_production_config_validator_rejects_placeholder_urls(self):
        checks = validate_production_config(
            {
                "AUTH_SECRET_KEY": "x" * 48,
                "AUTH_COOKIE_SECURE": "true",
                "AUTH_REQUIRED": "true",
                "AUTH_FRONTEND_URL": "https://factcrafter.example.com",
                "AUTH_BACKEND_URL": "https://api.factcrafter.example.com",
                "GOOGLE_OAUTH_CLIENT_ID": "google-client-id",
                "GOOGLE_OAUTH_CLIENT_SECRET": "google-client-secret",
                "GOOGLE_API_KEY": "gemini-api-key",
                "TAVILY_API_KEY": "tavily-api-key",
                "JOB_EXECUTION_MODE": "external",
                "JOB_DATABASE_URL": "postgresql://user:pass@db.example/factcrafter",
                "AUTH_DATABASE_URL": "postgresql://user:pass@db.example/factcrafter",
                "ARTIFACT_DATABASE_URL": "postgresql://user:pass@db.example/factcrafter",
                "JOB_MAX_ATTEMPTS": "3",
                "JOB_STALE_AFTER_SECONDS": "900",
                "MAX_ACTIVE_JOBS_PER_USER": "3",
                "MAX_JOB_CREATES_PER_WINDOW": "10",
                "JOB_CREATE_WINDOW_SECONDS": "3600",
                "ALERT_WEBHOOK_URL": "https://alerts.example.com/webhook",
                "FACTCRAFTER_SMOKE_URL": "https://api.factcrafter.example.com",
            }
        )
        failed = {check.name for check in checks if not check.ok}

        self.assertIn("AUTH_FRONTEND_URL", failed)
        self.assertIn("AUTH_BACKEND_URL", failed)
        self.assertIn("ALERT_WEBHOOK_URL", failed)
        self.assertIn("FACTCRAFTER_SMOKE_URL", failed)

    def test_production_config_validator_rejects_unsafe_cors_origins(self):
        checks = validate_production_config(
            {
                "AUTH_SECRET_KEY": "x" * 48,
                "AUTH_COOKIE_SECURE": "true",
                "AUTH_REQUIRED": "true",
                "AUTH_FRONTEND_URL": "https://factcrafter.app",
                "AUTH_BACKEND_URL": "https://api.factcrafter.app",
                "CORS_ORIGINS": "https://factcrafter.app,http://localhost:5173",
                "GOOGLE_OAUTH_CLIENT_ID": "google-client-id",
                "GOOGLE_OAUTH_CLIENT_SECRET": "google-client-secret",
                "GOOGLE_API_KEY": "gemini-api-key",
                "TAVILY_API_KEY": "tavily-api-key",
                "JOB_EXECUTION_MODE": "external",
                "JOB_DATABASE_URL": "postgresql://user:pass@db.example/factcrafter",
                "AUTH_DATABASE_URL": "postgresql://user:pass@db.example/factcrafter",
                "ARTIFACT_DATABASE_URL": "postgresql://user:pass@db.example/factcrafter",
                "JOB_MAX_ATTEMPTS": "3",
                "JOB_STALE_AFTER_SECONDS": "900",
                "MAX_ACTIVE_JOBS_PER_USER": "3",
                "MAX_JOB_CREATES_PER_WINDOW": "10",
                "JOB_CREATE_WINDOW_SECONDS": "3600",
                "ALERT_WEBHOOK_URL": "https://alerts.factcrafter.app/webhook",
                "FACTCRAFTER_SMOKE_URL": "https://api.factcrafter.app",
            }
        )
        failed = {check.name for check in checks if not check.ok}

        self.assertIn("CORS_ORIGINS", failed)

    def test_production_config_validator_rejects_unsafe_config(self):
        checks = validate_production_config(
            {
                "AUTH_SECRET_KEY": "generate-a-long-random-string",
                "AUTH_COOKIE_SECURE": "false",
                "AUTH_REQUIRED": "false",
                "AUTH_FRONTEND_URL": "http://localhost:5173",
                "AUTH_BACKEND_URL": "http://127.0.0.1:8000",
                "GOOGLE_OAUTH_CLIENT_ID": "",
                "GOOGLE_OAUTH_CLIENT_SECRET": "",
                "GOOGLE_API_KEY": "",
                "TAVILY_API_KEY": "",
                "JOB_EXECUTION_MODE": "thread",
                "JOB_DATABASE_URL": "",
                "AUTH_DATABASE_URL": "",
                "ARTIFACT_DATABASE_URL": "",
                "JOB_MAX_ATTEMPTS": "0",
                "JOB_STALE_AFTER_SECONDS": "0",
                "MAX_ACTIVE_JOBS_PER_USER": "-1",
                "MAX_JOB_CREATES_PER_WINDOW": "-1",
                "JOB_CREATE_WINDOW_SECONDS": "0",
            }
        )
        errors = {check.name for check in checks if not check.ok and check.severity == "error"}

        self.assertIn("AUTH_SECRET_KEY", errors)
        self.assertIn("AUTH_COOKIE_SECURE", errors)
        self.assertIn("AUTH_FRONTEND_URL", errors)
        self.assertIn("JOB_DATABASE_URL", errors)
        self.assertIn("artifact_storage", errors)

    def test_alerts_are_disabled_without_webhook_url(self):
        with patch.dict(os.environ, {"ALERT_WEBHOOK_URL": ""}, clear=False):
            with patch("web.alerts._post_json") as post_json:
                sent = send_job_alert(
                    job_id="job-1",
                    user_id="user-1",
                    status="failed",
                    goal="Test alert disabled",
                    reason="boom",
                )

        self.assertFalse(alerts_enabled())
        self.assertFalse(sent)
        post_json.assert_not_called()

    def test_job_alert_posts_structured_payload_when_enabled(self):
        with patch.dict(os.environ, {"ALERT_WEBHOOK_URL": "https://alerts.example/webhook"}, clear=False):
            with patch("web.alerts._post_json") as post_json:
                sent = send_job_alert(
                    job_id="job-1",
                    user_id="user-1",
                    status="blocked",
                    goal="Test alert payload",
                    reason="grounding failed",
                    run_id="run-1",
                    attempt_count=2,
                    current_step="evaluate",
                )

        self.assertTrue(sent)
        url, payload = post_json.call_args.args
        self.assertEqual(url, "https://alerts.example/webhook")
        self.assertEqual(payload["event"], "factcrafter_job_alert")
        self.assertEqual(payload["job_id"], "job-1")
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "grounding failed")
        self.assertEqual(payload["attempt_count"], 2)
        self.assertEqual(payload["current_step"], "evaluate")

    def test_job_alert_failure_is_logged_without_raising(self):
        with patch.dict(os.environ, {"ALERT_WEBHOOK_URL": "https://alerts.example/webhook"}, clear=False):
            with patch("web.alerts._post_json", side_effect=RuntimeError("webhook down")):
                with self.assertLogs("factcrafter.alerts", level="WARNING") as logs:
                    sent = send_job_alert(
                        job_id="job-1",
                        user_id="user-1",
                        status="failed",
                        goal="Test alert failure",
                        reason="boom",
                    )

        self.assertFalse(sent)
        payload = json.loads(logs.records[0].getMessage())
        self.assertEqual(payload["event"], "job_alert_delivery_failed")
        self.assertEqual(payload["job_id"], "job-1")
        self.assertIn("webhook down", payload["error"])

    def test_search_failure_is_marked_done(self):
        state = {
            "goal": "test goal",
            "brief": {"freshness_required": True, "research_type": "current_events"},
            "plan": [{"query": "one query", "purpose": "overview", "priority": 1}],
            "searches_done": [],
            "findings": [],
        }

        with patch("team.searcher.get_search_client", return_value=FailingSearchClient()):
            result = searcher_agent(state)

        self.assertEqual(result["findings"], [])
        self.assertEqual(result["searches_done"], ["one query"])

    def test_social_sources_are_classified_and_skipped(self):
        url = "https://www.facebook.com/example/posts/123"

        self.assertEqual(classify_source_type(url, "EV tax credit post"), "social")
        should_skip, reason = should_skip_source(url, "EV tax credit post", "x" * 120)

        self.assertTrue(should_skip)
        self.assertIn("social", reason)

    def test_factchecker_static_checks_reject_social_sources(self):
        source_ok, reason = source_passes_static_checks(
            "https://www.facebook.com/example/posts/123",
            "social",
        )

        self.assertFalse(source_ok)
        self.assertIn("social", reason)

    def test_academic_brief_rejects_secondary_academic_profiles(self):
        source_ok, reason = source_passes_static_checks(
            "https://www.researchgate.net/publication/123",
            "web",
            {"research_type": "scientific_academic"},
        )

        self.assertFalse(source_ok)
        self.assertIn("secondary academic", reason)

    def test_academic_brief_rejects_academic_adjacent_commentary(self):
        source_ok, reason = source_passes_static_checks(
            "https://blogs.lse.ac.uk/impactofsocialsciences/example",
            "web",
            {"research_type": "scientific_academic"},
        )

        self.assertFalse(source_ok)
        self.assertIn("not strong enough", reason)

    def test_search_freshness_uses_brief(self):
        self.assertEqual(
            search_days_for_brief({"freshness_required": True, "research_type": "product_comparison"}),
            365,
        )
        self.assertIsNone(
            search_days_for_brief({"freshness_required": False, "research_type": "historical_background"})
        )
        self.assertEqual(
            search_days_for_brief({"freshness_required": True, "research_type": "general_explainer"}),
            30,
        )

    def test_guardrail_allows_rules_only_when_llm_fails(self):
        with patch("team.guardrails.invoke_guard_llm", side_effect=RuntimeError("model unavailable")):
            is_safe, reason = input_guardrail("Compare electric cars under $40k right now.")

        self.assertTrue(is_safe)
        self.assertEqual(reason, "passed rules-only guardrail")

    def test_structured_llm_content_is_normalized_to_text(self):
        response = FakeResponse([{"type": "text", "text": "```json\n{\"ok\": true}\n```"}])

        self.assertEqual(response_to_text(response), "```json\n{\"ok\": true}\n```")
        self.assertEqual(strip_json_fences(response), "{\"ok\": true}")

    def test_evaluator_accepts_structured_report_content(self):
        report = [
            {
                "type": "text",
                "text": "## Direct Answer\nCitation quality matters. [source](https://example.com/a)\n\n## Sources\nhttps://example.com/a",
            }
        ]
        claims = [{"claim": "Citation quality matters.", "support_urls": ["https://example.com/a"]}]

        result = evaluate_grounding(report, claims)

        self.assertIn("grounding_score", result)
        self.assertEqual(result["report_url_count"], 1)

    def test_evaluator_rejects_mismatched_markdown_url_citations(self):
        report = (
            "## Direct Answer\n"
            "Citation quality matters "
            "[https://example.com/a](https://example.com/b).\n\n"
            "## Sources\n"
            "https://example.com/a"
        )
        claims = [{"claim": "Citation quality matters.", "support_urls": ["https://example.com/a"]}]

        result = evaluate_grounding(report, claims)

        self.assertFalse(result["passes_grounding"])
        self.assertFalse(result["citation_integrity_passes"])
        self.assertEqual(result["citation_mismatch_count"], 1)
        self.assertEqual(len(markdown_url_label_mismatches(report)), 1)

    def test_claim_verifier_maps_claims_to_verified_source_text(self):
        findings = [
            {
                "url": "https://example.com/study",
                "title": "Study",
                "snippet": "short",
                "evidence_text": "The study found source credibility increases perceived accuracy.",
            }
        ]
        claim = {"claim": "Source credibility increases perceived accuracy.", "support_urls": ["https://example.com/study/"]}

        blocks = source_blocks_for_claim(claim, source_lookup(findings))

        self.assertFalse(blocks[0]["missing"])
        self.assertIn("perceived accuracy", blocks[0]["evidence_text"])

    def test_claim_verifier_filters_unsupported_claims(self):
        claims = [
            {"claim": "Supported claim", "support_urls": ["https://example.com/a"], "confidence": "high"},
            {"claim": "Partial claim", "support_urls": ["https://example.com/b"], "confidence": "medium", "caveat": None},
            {"claim": "Unsupported claim", "support_urls": ["https://example.com/c"], "confidence": "high"},
        ]
        verifications = [
            {"verdict": "supported", "supported_urls": ["https://example.com/a"], "reason": "directly supported"},
            {"verdict": "partial", "supported_urls": ["https://example.com/b"], "reason": "scope is narrower"},
            {"verdict": "unsupported", "supported_urls": [], "reason": "not in source"},
        ]

        verified_claims, rejected_claims = apply_verifications(claims, verifications)

        self.assertEqual(len(verified_claims), 2)
        self.assertEqual(len(rejected_claims), 1)
        self.assertEqual(verified_claims[1]["confidence"], "low")
        self.assertIn("scope is narrower", verified_claims[1]["caveat"])

    def test_eval_harness_scores_agent_state(self):
        case = {
            "id": "sample",
            "goal": "test",
            "expected": {
                "require_passes_grounding": True,
                "require_citation_integrity": True,
                "require_claim_verification": True,
                "require_report_verification": True,
                "min_grounding_score": 80,
                "min_verified_findings": 1,
                "min_claims": 1,
                "required_report_sections": ["## Direct Answer", "## Sources"],
                "disallowed_domains": ["facebook.com"],
            },
        }
        state = {
            "input_guardrail_passed": True,
            "input_guardrail_reason": "passed",
            "verified_findings": [{"url": "https://example.com/a"}],
            "claims": [{"claim": "A", "support_urls": ["https://example.com/a"]}],
            "claim_verifications": [{"verdict": "supported"}],
            "report": "## Direct Answer\nA [source](https://example.com/a).\n\n## Sources\nhttps://example.com/a",
            "report_verification": {
                "passes": True,
                "skipped": False,
                "reason": "ok",
                "total_items": 1,
                "support_rate": 1.0,
            },
            "evaluation": {
                "passes_grounding": True,
                "grounding_score": 95,
                "citation_integrity_passes": True,
                "citation_mismatch_count": 0,
                "reason": "ok",
            },
        }

        result = score_case(case, state)

        self.assertTrue(result["passed"])
        self.assertEqual(result["checks_passed"], result["checks_total"])

    def test_source_fetcher_parses_html_text(self):
        html = b"""
        <html>
          <head><title>Research page</title><script>ignore()</script></head>
          <body><h1>Finding</h1><p>Source credibility improves trust decisions.</p></body>
        </html>
        """

        text, metadata = parse_html(html, FakeHTTPResponse())

        self.assertIn("Source credibility improves trust decisions", text)
        self.assertNotIn("ignore", text)
        self.assertEqual(metadata["parsed_title"], "Research page")

    def test_source_fetcher_detects_bad_pages(self):
        self.assertTrue(is_probably_bad_page("Sign in"))
        self.assertEqual(clean_text("a   b\n\n\n c"), "a b\n\nc")

    def test_source_fetcher_handles_fetch_failures_without_raising(self):
        result = fetch_and_parse_source("http://127.0.0.1:1/not-running", timeout_seconds=1)

        self.assertEqual(result["fetch_status"], "failed")
        self.assertIn("fetch_error", result)

    def test_source_quality_ranks_official_sources_high(self):
        rank = rank_source(
            {
                "url": "https://www.irs.gov/credits-deductions/clean-vehicle-credit",
                "source_type": "official",
                "fetch_status": "ok",
                "evidence_text": "x" * 2000,
            },
            {"research_type": "policy_legal"},
        )

        self.assertEqual(rank["source_quality_score"], 5)
        self.assertEqual(rank["source_quality_category"], "official_primary")
        self.assertFalse(rank["source_quality_hard_reject"])

    def test_source_quality_rejects_social_sources(self):
        rank = rank_source(
            {
                "url": "https://www.reddit.com/r/example/comments/1",
                "source_type": "social",
                "fetch_status": "ok",
                "evidence_text": "x" * 2000,
            },
            {"research_type": "general_explainer"},
        )

        passed, reason = source_quality_passes(rank, {"research_type": "general_explainer"})

        self.assertFalse(passed)
        self.assertIn("hard reject", reason)

    def test_source_quality_scientific_requires_strong_evidence(self):
        rank = rank_source(
            {
                "url": "https://example.com/opinion",
                "source_type": "web",
                "fetch_status": "ok",
                "evidence_text": "x" * 2000,
            },
            {"research_type": "scientific_academic"},
        )

        passed, reason = source_quality_passes(rank, {"research_type": "scientific_academic"})

        self.assertFalse(passed)
        self.assertLess(rank["source_quality_score"], 3)
        self.assertIn("scientific-academic", reason)

    def test_run_artifacts_write_audit_files(self):
        state = {
            "goal": "test goal",
            "brief": {"research_type": "general_explainer"},
            "plan": [{"query": "test", "purpose": "overview", "priority": 1}],
            "findings": [],
            "verified_findings": [],
            "rejected_findings": [],
            "claims": [],
            "claim_verifications": [],
            "rejected_claims": [],
            "report_verification": {"passes": True, "support_rate": 1.0},
            "report_verifications": [],
            "report_repair_attempts": 0,
            "report_repair_history": [],
            "evaluation": {"grounding_score": 91, "passes_grounding": True},
            "report": "## Direct Answer\nTest.\n\n## Sources\n",
            "input_guardrail_passed": True,
            "output_guardrail_passed": True,
            "grounding_gate_passed": True,
        }

        with TemporaryDirectory() as tmpdir:
            artifact_dir = write_run_artifacts(state, root=tmpdir, run_id="test-run")

            self.assertTrue((artifact_dir / "summary.json").exists())
            self.assertTrue((artifact_dir / "report.md").exists())
            self.assertTrue((artifact_dir / "state.json").exists())
            self.assertTrue((artifact_dir / "claim_verifications.json").exists())
            self.assertTrue((artifact_dir / "report_verification.json").exists())
            self.assertTrue((artifact_dir / "report_repair_history.json").exists())

    def test_run_artifacts_mirror_to_configured_artifact_store(self):
        state = {
            "goal": "stored report",
            "brief": {"research_type": "general_explainer"},
            "plan": [],
            "findings": [],
            "verified_findings": [],
            "rejected_findings": [],
            "claims": [],
            "claim_verifications": [],
            "rejected_claims": [],
            "report_verification": {"passes": True},
            "report_verifications": [],
            "report_repair_history": [],
            "evaluation": {"grounding_score": 95, "passes_grounding": True},
            "report": "## Direct Answer\nStored.\n\n## Sources\n",
            "input_guardrail_passed": True,
            "output_guardrail_passed": True,
            "grounding_gate_passed": True,
            "user_id": "user-1",
        }

        with TemporaryDirectory() as tmpdir:
            artifact_db = Path(tmpdir) / "artifacts.db"
            with patch.dict("os.environ", {"ARTIFACT_DB_PATH": str(artifact_db), "ARTIFACT_DATABASE_URL": ""}):
                write_run_artifacts(state, root=Path(tmpdir) / "runs", run_id="stored-run", user_id="user-1")
                store = ArtifactStore(path=artifact_db)

                self.assertEqual(
                    store.get_text(user_id="user-1", run_id="stored-run", filename="report.md"),
                    "## Direct Answer\nStored.\n\n## Sources\n",
                )
                self.assertEqual(
                    store.get_json(user_id="user-1", run_id="stored-run", filename="summary.json")["goal"],
                    "stored report",
                )

    def test_run_api_reads_from_configured_artifact_store(self):
        state = {
            "goal": "api stored report",
            "brief": {"research_type": "general_explainer"},
            "plan": [],
            "findings": [],
            "verified_findings": [],
            "rejected_findings": [],
            "claims": [],
            "claim_verifications": [],
            "rejected_claims": [],
            "report_verification": {"passes": True},
            "report_verifications": [],
            "report_repair_history": [],
            "evaluation": {"grounding_score": 96, "passes_grounding": True},
            "report": "## Direct Answer\nReadable from DB.\n\n## Sources\n",
            "input_guardrail_passed": True,
            "output_guardrail_passed": True,
            "grounding_gate_passed": True,
            "user_id": "user-1",
        }

        with TemporaryDirectory() as tmpdir:
            artifact_db = Path(tmpdir) / "artifacts.db"
            with patch.dict("os.environ", {"ARTIFACT_DB_PATH": str(artifact_db), "ARTIFACT_DATABASE_URL": ""}):
                write_run_artifacts(state, root=Path(tmpdir) / "runs", run_id="api-run", user_id="user-1")
                runs = list_runs("user-1")
                payload = get_run("api-run", "user-1")

        self.assertEqual(runs[0]["run_id"], "api-run")
        self.assertIsNotNone(payload)
        self.assertIn("Readable from DB", payload["report_md"])
        self.assertEqual(payload["summary"]["goal"], "api stored report")

    def test_report_verifier_selects_relevant_source_excerpt(self):
        source_text = (
            ("Navigation Pricing Login Demo\n" * 400)
            + "\n"
            "Unrelated paragraph about a product launch.\n\n"
            "RAG enables attribution and auditability by grounding answers in retrieved documents. "
            "Fine-tuning can improve style but does not provide source-level traceability."
        )

        excerpt = relevant_excerpt(
            source_text,
            "RAG enables attribution and auditability for enterprise answers.",
        )

        self.assertIn("RAG enables attribution", excerpt)
        self.assertNotIn("Navigation Pricing", excerpt)

    def test_report_verifier_extracts_cited_report_items(self):
        report = (
            "## Direct Answer\n"
            "Research evidence indicates citation quality increases perceived accuracy and trust "
            "in user decisions [source](https://example.com/study).\n\n"
            "## Sources\n"
            "https://example.com/study"
        )

        items = cited_report_items(report)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["urls"], ["https://example.com/study"])
        self.assertIn("citation quality", items[0]["text"])

    def test_report_verifier_flags_missing_cited_sources(self):
        items = [
            {
                "item_index": 1,
                "kind": "paragraph",
                "start_line": 2,
                "text": "Research evidence indicates citation quality increases trust.",
                "urls": ["https://example.com/missing"],
            }
        ]
        verifications = [
            {
                "item_index": 1,
                "verdict": "supported",
                "supported_urls": ["https://example.com/missing"],
                "reason": "model believed it was supported",
            }
        ]

        records, summary = build_records(items, verifications, verified_findings=[])

        self.assertFalse(summary["passes"])
        self.assertEqual(summary["missing_source_url_count"], 1)
        self.assertEqual(records[0]["missing_source_urls"], ["https://example.com/missing"])

    def test_report_verifier_passes_supported_citations(self):
        items = [
            {
                "item_index": 1,
                "kind": "paragraph",
                "start_line": 2,
                "text": "Research evidence indicates citation quality increases trust.",
                "urls": ["https://example.com/study"],
            }
        ]
        verifications = [
            {
                "item_index": 1,
                "verdict": "supported",
                "supported_urls": ["https://example.com/study"],
                "reason": "source text supports the report item",
            }
        ]
        verified_findings = [
            {
                "url": "https://example.com/study",
                "evidence_text": "Research evidence indicates citation quality increases trust.",
            }
        ]

        records, summary = build_records(items, verifications, verified_findings=verified_findings)

        self.assertTrue(summary["passes"])
        self.assertEqual(summary["support_rate"], 1.0)
        self.assertEqual(records[0]["verdict"], "supported")

    def test_evaluator_fails_when_report_verifier_fails(self):
        evaluation = evaluate_grounding(
            "## Direct Answer\nA [source](https://example.com/a).\n\n## Sources\nhttps://example.com/a",
            [{"claim": "A", "support_urls": ["https://example.com/a"]}],
        )

        updated = apply_report_verification(
            evaluation,
            {
                "passes": False,
                "skipped": False,
                "reason": "unsupported final-report citation",
                "total_items": 1,
                "unsupported_count": 1,
                "missing_source_url_count": 0,
                "support_rate": 0.0,
            },
        )

        self.assertFalse(updated["passes_grounding"])
        self.assertFalse(updated["semantic_citation_passes"])
        self.assertLessEqual(updated["grounding_score"], 69.0)

    def test_report_repair_removes_failed_report_items_in_fallback(self):
        report = (
            "## Key Findings\n"
            "* Supported claim [source](https://example.com/a).\n"
            "* Unsupported claim [source](https://example.com/b).\n\n"
            "## Sources\n"
            "https://example.com/a\n"
            "https://example.com/b"
        )
        failed = [
            {
                "item_index": 2,
                "start_line": 3,
                "text": "Unsupported claim.",
                "verdict": "unsupported",
                "cited_urls": ["https://example.com/b"],
            }
        ]

        repaired = remove_failed_report_items(report, failed)

        self.assertIn("Supported claim", repaired)
        self.assertNotIn("Unsupported claim", repaired)
        self.assertIn("## Sources", repaired)

    def test_report_repair_agent_fallback_records_attempt(self):
        state = {
            "goal": "test",
            "claims": [],
            "report": (
                "## Key Findings\n"
                "* Supported claim [source](https://example.com/a).\n"
                "* Unsupported claim [source](https://example.com/b).\n\n"
                "## Sources\n"
                "https://example.com/a\n"
                "https://example.com/b"
            ),
            "report_verifications": [
                {
                    "item_index": 2,
                    "start_line": 3,
                    "text": "Unsupported claim.",
                    "verdict": "unsupported",
                    "cited_urls": ["https://example.com/b"],
                    "reason": "not supported",
                }
            ],
            "report_repair_attempts": 0,
            "report_repair_history": [],
        }

        with patch("team.reportrepair.get_report_repair_llm", side_effect=RuntimeError("model unavailable")):
            result = report_repair_agent(state)

        self.assertEqual(result["report_repair_attempts"], 1)
        self.assertEqual(result["report_repair_history"][0]["method"], "fallback_remove_failed_blocks")
        self.assertNotIn("Unsupported claim", result["report"])

    def test_report_repair_route_retries_once_then_evaluates(self):
        state = {
            "report_verification": {"passes": False, "skipped": False},
            "report_repair_attempts": 0,
        }

        with patch.dict("os.environ", {"REPORT_REPAIR_MAX_ATTEMPTS": "1"}):
            self.assertEqual(route_after_report_verify(state), "report_repair")
            self.assertEqual(
                route_after_report_verify({**state, "report_repair_attempts": 1}),
                "evaluate",
            )

    def test_failed_report_items_ignores_partial_and_supported(self):
        failed = failed_report_items(
            [
                {"verdict": "supported", "missing_source_urls": []},
                {"verdict": "partial", "missing_source_urls": []},
                {"verdict": "partial", "missing_source_urls": ["https://example.com/missing"]},
                {"verdict": "unsupported", "missing_source_urls": []},
            ]
        )

        self.assertEqual(len(failed), 2)

    def test_file_cache_round_trip_and_clear(self):
        with TemporaryDirectory() as tmpdir:
            payload = {"query": "test"}
            self.assertIsNone(get_cached_json("unit", payload, root=tmpdir))

            set_cached_json("unit", payload, {"ok": True}, root=tmpdir)
            self.assertEqual(get_cached_json("unit", payload, root=tmpdir), {"ok": True})
            self.assertEqual(clear_cache("unit", root=tmpdir), 1)
            self.assertIsNone(get_cached_json("unit", payload, root=tmpdir))

    def test_searcher_uses_cached_search_results(self):
        state = {
            "goal": "test goal",
            "brief": {"freshness_required": False, "research_type": "general_explainer"},
            "plan": [{"query": "cache query", "purpose": "overview", "priority": 1}],
            "searches_done": [],
            "findings": [],
        }
        client = CountingSearchClient()

        with TemporaryDirectory() as tmpdir:
            with patch.dict("os.environ", {"FACTCRAFTER_CACHE_DIR": tmpdir}):
                with patch("team.searcher.get_search_client", return_value=client):
                    first = searcher_agent(state)
                    second = searcher_agent({**state, "searches_done": [], "findings": []})

        self.assertEqual(client.calls, 1)
        self.assertEqual(first["findings"][0]["search_cache_status"], "miss")
        self.assertEqual(second["findings"][0]["search_cache_status"], "hit")

    def test_human_review_detects_high_stakes_topics(self):
        high_stakes, reasons = is_high_stakes(
            "What changed in U.S. EV tax credit eligibility?",
            {"research_type": "policy_legal", "must_cover": []},
        )

        self.assertTrue(high_stakes)
        self.assertTrue(any("policy_legal" in reason for reason in reasons))

    def test_human_review_auto_mode_blocks_high_stakes_without_interactive_reviewer(self):
        state = {
            "goal": "What changed in U.S. EV tax credit eligibility?",
            "brief": {"research_type": "policy_legal", "must_cover": []},
            "claims": [
                {
                    "claim": "Buyers should verify eligibility before purchase.",
                    "support_urls": ["https://example.com"],
                    "confidence": "high",
                }
            ],
            "rejected_claims": [],
        }

        with patch.dict("os.environ", {"HITL_REVIEW_MODE": "auto"}):
            with patch("team.humanreview.is_interactive", return_value=False):
                result = human_review_agent(state)

        self.assertFalse(result["human_review"]["approved"])
        self.assertEqual(result["human_review"]["mode"], "auto")
        self.assertEqual(result["claims"], [])

    def test_human_review_required_mode_blocks_without_interactive_reviewer(self):
        state = {
            "goal": "What changed in U.S. EV tax credit eligibility?",
            "brief": {"research_type": "policy_legal", "must_cover": []},
            "claims": [
                {
                    "claim": "Buyers should verify eligibility before purchase.",
                    "support_urls": ["https://example.com"],
                    "confidence": "high",
                }
            ],
            "rejected_claims": [],
        }

        with patch.dict("os.environ", {"HITL_REVIEW_MODE": "required"}):
            with patch("team.humanreview.is_interactive", return_value=False):
                result = human_review_agent(state)

        self.assertFalse(result["human_review"]["approved"])
        self.assertEqual(result["claims"], [])
        self.assertEqual(result["rejected_claims"][0]["verdict"], "blocked_for_human_review")

    def test_human_review_rejection_clears_claims(self):
        state = {
            "goal": "What changed in U.S. EV tax credit eligibility?",
            "brief": {"research_type": "policy_legal", "must_cover": []},
            "claims": [
                {
                    "claim": "Buyers should verify eligibility before purchase.",
                    "support_urls": ["https://example.com"],
                    "confidence": "high",
                }
            ],
            "rejected_claims": [],
        }

        with patch.dict("os.environ", {"HITL_REVIEW_MODE": "auto"}):
            with patch("team.humanreview.is_interactive", return_value=True):
                with patch("builtins.input", return_value="n"):
                    result = human_review_agent(state)

        self.assertFalse(result["human_review"]["approved"])
        self.assertEqual(result["human_review"]["reviewer"], "human_cli")
        self.assertEqual(result["claims"], [])
        self.assertEqual(result["rejected_claims"][0]["reason"], "Interactive human reviewer rejected the claims before writing.")

    def test_writer_does_not_fallback_when_human_review_blocks(self):
        result = writer_agent(
            {
                "goal": "What changed in U.S. EV tax credit eligibility?",
                "brief": {"research_type": "policy_legal"},
                "claims": [],
                "verified_findings": [{"snippet": "Do not turn this raw evidence into a report."}],
                "human_review": {
                    "required": True,
                    "approved": False,
                    "decision": "blocked: no interactive reviewer available",
                    "reasons": ["research_type=policy_legal"],
                },
            }
        )

        self.assertIn("Report Blocked", result["report"])
        self.assertNotIn("Do not turn this raw evidence", result["report"])

    def test_run_research_returns_human_review_block_before_grounding_failure(self):
        blocked_report = "## Report Blocked: Human Review Required\n\nReview needed."
        graph_result = {
            "report": blocked_report,
            "human_review": {
                "required": True,
                "approved": False,
                "decision": "blocked: no interactive reviewer available",
            },
            "evaluation": {"passes_grounding": False, "grounding_score": 0},
        }

        with patch("team.main.input_guardrail", return_value=(True, "passed")):
            with patch("team.main.research_team.invoke", return_value=graph_result):
                with patch("team.main.should_save_artifacts", return_value=False):
                    report = run_research("What changed in U.S. EV tax credit eligibility?")

        self.assertEqual(report, blocked_report)

    def test_scientific_academic_health_outcomes_does_not_trigger_hitl(self):
        """Regression test: population-level 'health outcomes' in CCT research must NOT trigger HITL.

        This was the exact failure mode for queries like:
        "how effective have conditional cash transfer programs been at improving ... health ... outcomes"
        with research_type=scientific_academic.
        """
        high_stakes, reasons = is_high_stakes(
            "According to rigorous evaluations, how effective have conditional cash transfer programs been at improving education, health, and poverty outcomes?",
            {
                "research_type": "scientific_academic",
                "topic": "Efficacy of Conditional Cash Transfer (CCT) Programs",
                "must_cover": [
                    "Impact on child health and nutrition outcomes",
                    "Long-term poverty reduction",
                ],
            },
        )

        self.assertFalse(high_stakes, f"Should not be high-stakes, but got reasons: {reasons}")
        self.assertEqual(reasons, [])

    def test_scientific_academic_personal_advice_still_triggers(self):
        """Personal advice intent inside a scientific brief should still be caught (narrow case)."""
        high_stakes, reasons = is_high_stakes(
            "I have hypertension. Should I take this new drug based on the latest trials?",
            {"research_type": "scientific_academic"},
        )
        self.assertTrue(high_stakes)
        self.assertTrue(any("personal_advice_intent" in r for r in reasons))

    def test_auth_requires_stable_secret_in_production(self):
        auth_settings.cache_clear()
        try:
            with patch.dict("os.environ", {"ENVIRONMENT": "production", "AUTH_SECRET_KEY": ""}, clear=False):
                with self.assertRaisesRegex(RuntimeError, "AUTH_SECRET_KEY"):
                    auth_settings()
        finally:
            auth_settings.cache_clear()

    def test_auth_defaults_secure_cookies_in_production(self):
        auth_settings.cache_clear()
        try:
            with patch.dict(
                "os.environ",
                {"ENVIRONMENT": "production", "AUTH_SECRET_KEY": "stable-test-secret"},
                clear=False,
            ):
                self.assertTrue(auth_settings()["cookie_secure"])
        finally:
            auth_settings.cache_clear()

    def test_production_responses_include_browser_security_headers(self):
        auth_settings.cache_clear()
        try:
            with patch.dict(
                os.environ,
                {
                    "ENVIRONMENT": "production",
                    "AUTH_SECRET_KEY": "stable-test-secret-for-security",
                    "AUTH_FRONTEND_URL": "https://factcrafter.app",
                    "AUTH_BACKEND_URL": "https://api.factcrafter.app",
                    "CORS_ORIGINS": "",
                },
                clear=False,
            ):
                auth_settings.cache_clear()
                response = TestClient(create_app()).get("/api/health")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(response.headers["X-Frame-Options"], "DENY")
            self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
            self.assertIn("max-age=31536000", response.headers["Strict-Transport-Security"])
        finally:
            auth_settings.cache_clear()

    def test_production_rejects_local_cors_origins(self):
        auth_settings.cache_clear()
        try:
            with patch.dict(
                os.environ,
                {
                    "ENVIRONMENT": "production",
                    "AUTH_SECRET_KEY": "stable-test-secret-for-cors",
                    "AUTH_FRONTEND_URL": "https://factcrafter.app",
                    "AUTH_BACKEND_URL": "https://api.factcrafter.app",
                    "CORS_ORIGINS": "http://localhost:5173",
                },
                clear=False,
            ):
                auth_settings.cache_clear()
                with self.assertRaisesRegex(RuntimeError, "Production CORS"):
                    create_app()
        finally:
            auth_settings.cache_clear()

    def test_auth_sqlite_store_round_trips_dev_user_with_configured_path(self):
        with TemporaryDirectory() as tmpdir:
            with patch.dict(
                "os.environ",
                {"AUTH_DB_PATH": str(Path(tmpdir) / "auth.db"), "AUTH_DATABASE_URL": "", "DATABASE_URL": ""},
                clear=False,
            ):
                init_db()
                user = ensure_dev_user("dev-test", "dev@example.com", "Dev User")
                loaded = get_user_by_id("dev-test")

        self.assertEqual(user.id, "dev-test")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.email, "dev@example.com")

    def test_auth_sqlite_store_updates_google_user(self):
        with TemporaryDirectory() as tmpdir:
            with patch.dict(
                "os.environ",
                {"AUTH_DB_PATH": str(Path(tmpdir) / "auth.db"), "AUTH_DATABASE_URL": "", "DATABASE_URL": ""},
                clear=False,
            ):
                init_db()
                first = upsert_google_user(
                    google_sub="google-1",
                    email="old@example.com",
                    name="Old",
                    picture=None,
                )
                second = upsert_google_user(
                    google_sub="google-1",
                    email="new@example.com",
                    name="New",
                    picture="https://example.com/avatar.png",
                )

        self.assertEqual(first.id, second.id)
        self.assertEqual(second.email, "new@example.com")
        self.assertEqual(second.name, "New")

    def test_google_login_redirect_sets_oauth_state_cookie(self):
        auth_settings.cache_clear()
        try:
            with TemporaryDirectory() as tmpdir:
                with patch.dict(
                    os.environ,
                    {
                        "AUTH_DB_PATH": str(Path(tmpdir) / "auth.db"),
                        "AUTH_DATABASE_URL": "",
                        "DATABASE_URL": "",
                        "AUTH_SECRET_KEY": "stable-test-secret-for-oauth",
                        "AUTH_FRONTEND_URL": "https://factcrafter.example.com",
                        "AUTH_BACKEND_URL": "https://api.factcrafter.example.com",
                        "GOOGLE_OAUTH_CLIENT_ID": "google-client-id",
                        "GOOGLE_OAUTH_CLIENT_SECRET": "google-client-secret",
                        "AUTH_COOKIE_SECURE": "true",
                    },
                    clear=False,
                ):
                    auth_settings.cache_clear()
                    response = TestClient(create_app(), follow_redirects=False).get("/api/auth/google")

            self.assertEqual(response.status_code, 307)
            self.assertIn("accounts.google.com", response.headers["location"])
            self.assertIn("client_id=google-client-id", response.headers["location"])
            self.assertIn("fc_oauth_state", response.headers["set-cookie"])
            self.assertIn("HttpOnly", response.headers["set-cookie"])
            self.assertIn("Secure", response.headers["set-cookie"])
        finally:
            auth_settings.cache_clear()

    def test_google_callback_creates_user_and_session_cookie(self):
        auth_settings.cache_clear()
        try:
            with TemporaryDirectory() as tmpdir:
                with patch.dict(
                    os.environ,
                    {
                        "AUTH_DB_PATH": str(Path(tmpdir) / "auth.db"),
                        "AUTH_DATABASE_URL": "",
                        "DATABASE_URL": "",
                        "AUTH_SECRET_KEY": "stable-test-secret-for-oauth-callback",
                        "AUTH_FRONTEND_URL": "https://factcrafter.example.com",
                        "AUTH_BACKEND_URL": "https://api.factcrafter.example.com",
                        "GOOGLE_OAUTH_CLIENT_ID": "google-client-id",
                        "GOOGLE_OAUTH_CLIENT_SECRET": "google-client-secret",
                        "AUTH_COOKIE_SECURE": "true",
                    },
                    clear=False,
                ):
                    auth_settings.cache_clear()
                    init_db()
                    client = TestClient(create_app(), follow_redirects=False)
                    client.cookies.set("fc_oauth_state", "state-123")
                    with patch("web.auth.router.httpx.AsyncClient", FakeGoogleOAuthClient):
                        response = client.get(
                            "/api/auth/google/callback?code=code-123&state=state-123"
                        )

                    token = response.cookies.get("fc_token")
                    payload = decode_access_token(token or "")

            self.assertEqual(response.status_code, 307)
            self.assertEqual(response.headers["location"], "https://factcrafter.example.com/")
            self.assertIsNotNone(payload)
            self.assertEqual(payload["email"], "oauth@example.com")
            self.assertIn("fc_token", response.headers["set-cookie"])
            self.assertIn("HttpOnly", response.headers["set-cookie"])
            self.assertIn("Secure", response.headers["set-cookie"])
            self.assertIn("fc_oauth_state=", response.headers["set-cookie"])
        finally:
            auth_settings.cache_clear()

    def test_google_callback_rejects_invalid_state_before_token_exchange(self):
        auth_settings.cache_clear()
        try:
            with TemporaryDirectory() as tmpdir:
                with patch.dict(
                    os.environ,
                    {
                        "AUTH_DB_PATH": str(Path(tmpdir) / "auth.db"),
                        "AUTH_DATABASE_URL": "",
                        "DATABASE_URL": "",
                        "AUTH_SECRET_KEY": "stable-test-secret-for-invalid-oauth",
                        "AUTH_FRONTEND_URL": "https://factcrafter.example.com",
                        "AUTH_BACKEND_URL": "https://api.factcrafter.example.com",
                        "GOOGLE_OAUTH_CLIENT_ID": "google-client-id",
                        "GOOGLE_OAUTH_CLIENT_SECRET": "google-client-secret",
                    },
                    clear=False,
                ):
                    auth_settings.cache_clear()
                    client = TestClient(create_app(), follow_redirects=False)
                    client.cookies.set("fc_oauth_state", "state-123")
                    with patch("web.auth.router.httpx.AsyncClient") as async_client:
                        response = client.get(
                            "/api/auth/google/callback?code=code-123&state=wrong-state"
                        )

            self.assertEqual(response.status_code, 307)
            self.assertEqual(
                response.headers["location"],
                "https://factcrafter.example.com/login?error=invalid_state",
            )
            async_client.assert_not_called()
        finally:
            auth_settings.cache_clear()

    def test_web_job_context_is_scoped_and_restored(self):
        self.assertFalse(is_web_context())
        self.assertEqual(current_web_job_id(), "")

        with web_job_context("job-a"):
            self.assertTrue(is_web_context())
            self.assertEqual(current_web_job_id(), "job-a")
            with web_job_context("job-b"):
                self.assertEqual(current_web_job_id(), "job-b")
            self.assertEqual(current_web_job_id(), "job-a")

        self.assertFalse(is_web_context())
        self.assertEqual(current_web_job_id(), "")

    def test_job_store_round_trips_job_metadata(self):
        with TemporaryDirectory() as tmpdir:
            store = JobStore(Path(tmpdir) / "jobs.db")
            job = ResearchJob(
                id="job-1",
                goal="Compare current EV tax credit rules",
                user_id="user-1",
                status=JobStatus.COMPLETED,
                completed_steps=["brief", "plan"],
                events=[JobEvent(type="completed", message="done")],
                state={"report": "## Direct Answer\nDone."},
                run_id="run-1",
            )

            store.upsert(job.to_record())
            loaded = store.get("job-1")

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["status"], "completed")
        self.assertEqual(loaded["completed_steps"], ["brief", "plan"])
        self.assertEqual(loaded["events"][0]["type"], "completed")
        self.assertEqual(loaded["state"]["report"], "## Direct Answer\nDone.")

    def test_job_manager_marks_restored_running_jobs_interrupted(self):
        with TemporaryDirectory() as tmpdir:
            store = JobStore(Path(tmpdir) / "jobs.db")
            running = ResearchJob(
                id="job-running",
                goal="Research something",
                user_id="user-1",
                status=JobStatus.RUNNING,
                current_step="search",
            )
            store.upsert(running.to_record())

            manager = JobManager(store=store, load_existing=True)
            restored = manager.get_job("job-running", "user-1")

        self.assertIsNotNone(restored)
        self.assertEqual(restored.status, JobStatus.FAILED)
        self.assertIn("interrupted", restored.error)
        self.assertEqual(restored.events[-1].type, "error")

    def test_external_job_mode_enqueues_without_starting_thread(self):
        with TemporaryDirectory() as tmpdir:
            store = JobStore(Path(tmpdir) / "jobs.db")
            manager = JobManager(store=store, execution_mode="external", load_existing=False)

            with patch.object(manager, "start_job_thread") as start_thread:
                job = manager.create_job("Research durable queue behavior", "user-1")

            stored = store.get(job.id)

        start_thread.assert_not_called()
        self.assertEqual(job.status, JobStatus.QUEUED)
        self.assertEqual(stored["status"], "queued")

    def test_job_creation_emits_structured_lifecycle_log(self):
        with TemporaryDirectory() as tmpdir:
            store = JobStore(Path(tmpdir) / "jobs.db")
            manager = JobManager(store=store, execution_mode="external", load_existing=False)

            with self.assertLogs("factcrafter.jobs", level="INFO") as logs:
                job = manager.create_job("Research job logging", "user-1")

        entries = [json.loads(record.getMessage()) for record in logs.records]
        created = next(entry for entry in entries if entry["event"] == "job_created")
        self.assertEqual(created["job_id"], job.id)
        self.assertEqual(created["user_id"], "user-1")
        self.assertEqual(created["status"], "queued")
        self.assertEqual(created["execution_mode"], "external")

    def test_worker_claims_oldest_queued_job(self):
        with TemporaryDirectory() as tmpdir:
            store = JobStore(Path(tmpdir) / "jobs.db")
            first = ResearchJob(id="job-1", goal="First", user_id="user-1")
            second = ResearchJob(id="job-2", goal="Second", user_id="user-1")
            store.upsert(first.to_record())
            store.upsert(second.to_record())

            manager = JobManager(store=store, execution_mode="external", load_existing=False)
            claimed = manager.claim_next_job()

            self.assertIsNotNone(claimed)
            self.assertEqual(claimed.id, "job-1")
            self.assertEqual(claimed.status, JobStatus.RUNNING)
            self.assertEqual(store.get("job-1")["status"], "running")
            self.assertEqual(store.get("job-1")["attempt_count"], 1)
            self.assertTrue(store.get("job-1")["locked_by"].startswith("worker-"))
            self.assertEqual(store.get("job-2")["status"], "queued")

    def test_worker_claim_records_worker_lease(self):
        with TemporaryDirectory() as tmpdir:
            store = JobStore(Path(tmpdir) / "jobs.db")
            store.upsert(ResearchJob(id="job-1", goal="Lease", user_id="user-1").to_record())

            manager = JobManager(store=store, execution_mode="external", load_existing=False)
            with self.assertLogs("factcrafter.jobs", level="INFO") as logs:
                claimed = manager.claim_next_job(worker_id="worker-a")
            stored = store.get("job-1")

        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.locked_by, "worker-a")
        self.assertEqual(stored["locked_by"], "worker-a")
        self.assertIsNotNone(stored["locked_at"])
        self.assertIsNotNone(stored["last_heartbeat_at"])
        entries = [json.loads(record.getMessage()) for record in logs.records]
        claimed_log = next(entry for entry in entries if entry["event"] == "job_claimed")
        self.assertEqual(claimed_log["job_id"], "job-1")
        self.assertEqual(claimed_log["worker_id"], "worker-a")
        self.assertEqual(claimed_log["status"], "running")

    def test_cancel_queued_job_persists_terminal_status(self):
        with TemporaryDirectory() as tmpdir:
            store = JobStore(Path(tmpdir) / "jobs.db")
            manager = JobManager(store=store, execution_mode="external", load_existing=False)
            job = manager.create_job("Research cancellation behavior", "user-1")

            with self.assertLogs("factcrafter.jobs", level="INFO") as logs:
                canceled = manager.cancel_job(job.id, "user-1")
            stored = store.get(job.id)

        self.assertIsNotNone(canceled)
        self.assertEqual(canceled.status, JobStatus.CANCELED)
        self.assertEqual(stored["status"], "canceled")
        self.assertEqual(stored["events"][-1]["type"], "canceled")
        self.assertIn("canceled", stored["error"])
        entries = [json.loads(record.getMessage()) for record in logs.records]
        canceled_log = next(entry for entry in entries if entry["event"] == "job_canceled")
        self.assertEqual(canceled_log["job_id"], job.id)
        self.assertEqual(canceled_log["status"], "canceled")

    def test_canceled_job_is_not_claimed_by_worker(self):
        with TemporaryDirectory() as tmpdir:
            store = JobStore(Path(tmpdir) / "jobs.db")
            manager = JobManager(store=store, execution_mode="external", load_existing=False)
            job = manager.create_job("Cancel before worker claim", "user-1")

            manager.cancel_job(job.id, "user-1")
            claimed = manager.claim_next_job(worker_id="worker-a")

        self.assertIsNone(claimed)

    def test_cancel_terminal_job_is_rejected(self):
        with TemporaryDirectory() as tmpdir:
            store = JobStore(Path(tmpdir) / "jobs.db")
            manager = JobManager(store=store, execution_mode="external", load_existing=False)
            completed = ResearchJob(
                id="job-completed",
                goal="Already completed",
                user_id="user-1",
                status=JobStatus.COMPLETED,
            )
            store.upsert(completed.to_record())
            manager = JobManager(store=store, execution_mode="external", load_existing=True)

            canceled = manager.cancel_job("job-completed", "user-1")

        self.assertIsNone(canceled)

    def test_running_job_cancel_request_is_persisted_for_worker(self):
        with TemporaryDirectory() as tmpdir:
            store = JobStore(Path(tmpdir) / "jobs.db")
            running = ResearchJob(
                id="job-running",
                goal="Cancel running",
                user_id="user-1",
                status=JobStatus.RUNNING,
            )
            store.upsert(running.to_record())
            manager = JobManager(store=store, execution_mode="external", load_existing=False)
            manager._remember_job(running)

            requested = manager.cancel_job("job-running", "user-1")
            stored = store.get("job-running")

        self.assertIsNotNone(requested)
        self.assertEqual(requested.status, JobStatus.RUNNING)
        self.assertTrue(requested.cancel_requested)
        self.assertTrue(stored["cancel_requested"])
        self.assertEqual(stored["events"][-1]["type"], "canceled")

    def test_running_job_cancel_endpoint_marks_cancel_requested(self):
        with TemporaryDirectory() as tmpdir:
            store = JobStore(Path(tmpdir) / "jobs.db")
            user_id = auth_settings()["dev_user_id"]
            running = ResearchJob(
                id="job-running",
                goal="Cancel running from API",
                user_id=user_id,
                status=JobStatus.RUNNING,
            )
            store.upsert(running.to_record())
            manager = JobManager(store=store, execution_mode="external", load_existing=False)
            manager._remember_job(running)

            with patch("web.server.job_manager", manager):
                response = TestClient(create_app()).post("/api/jobs/job-running/cancel")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "running")
        self.assertTrue(response.json()["cancel_requested"])

    def test_worker_honors_cancel_request_before_expensive_work(self):
        with TemporaryDirectory() as tmpdir:
            store = JobStore(Path(tmpdir) / "jobs.db")
            running = ResearchJob(
                id="job-running",
                goal="Cancel before guardrail",
                user_id="user-1",
                status=JobStatus.RUNNING,
                cancel_requested=True,
            )
            store.upsert(running.to_record())
            manager = JobManager(store=store, execution_mode="external", load_existing=False)
            manager._remember_job(running)

            with patch("web.jobs.input_guardrail") as guardrail:
                manager._run_job("job-running")
            stored = store.get("job-running")

        guardrail.assert_not_called()
        self.assertEqual(stored["status"], "canceled")
        self.assertTrue(stored["cancel_requested"])
        self.assertIn("canceled", stored["error"])

    def test_stale_running_job_requeues_below_retry_limit(self):
        stale_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with TemporaryDirectory() as tmpdir:
            store = JobStore(Path(tmpdir) / "jobs.db")
            store.upsert(
                ResearchJob(
                    id="job-stale",
                    goal="Retry me",
                    user_id="user-1",
                    status=JobStatus.RUNNING,
                    attempt_count=1,
                    locked_by="worker-old",
                    locked_at=stale_time,
                    last_heartbeat_at=stale_time,
                ).to_record()
            )

            recovered = store.recover_stale_running_jobs(stale_after_seconds=60, max_attempts=3)
            stored = store.get("job-stale")

        self.assertEqual(recovered, 1)
        self.assertEqual(stored["status"], "queued")
        self.assertIsNone(stored["locked_by"])
        self.assertEqual(stored["attempt_count"], 1)

    def test_stale_running_job_fails_at_retry_limit(self):
        stale_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with TemporaryDirectory() as tmpdir:
            store = JobStore(Path(tmpdir) / "jobs.db")
            store.upsert(
                ResearchJob(
                    id="job-dead",
                    goal="Fail me",
                    user_id="user-1",
                    status=JobStatus.RUNNING,
                    attempt_count=3,
                    locked_by="worker-old",
                    locked_at=stale_time,
                    last_heartbeat_at=stale_time,
                ).to_record()
            )

            recovered = store.recover_stale_running_jobs(stale_after_seconds=60, max_attempts=3)
            stored = store.get("job-dead")

        self.assertEqual(recovered, 1)
        self.assertEqual(stored["status"], "failed")
        self.assertIn("retry limit", stored["error"])

    def test_worker_run_next_executes_claimed_job(self):
        with TemporaryDirectory() as tmpdir:
            store = JobStore(Path(tmpdir) / "jobs.db")
            store.upsert(ResearchJob(id="job-1", goal="Run it", user_id="user-1").to_record())
            manager = JobManager(store=store, execution_mode="external", load_existing=False)

            with patch.object(manager, "_run_job") as run_job:
                ran = manager.run_next_queued_job()

        self.assertTrue(ran)
        run_job.assert_called_once_with("job-1")

    def test_web_review_decision_persists_across_process_memory(self):
        with TemporaryDirectory() as tmpdir:
            job_db = Path(tmpdir) / "jobs.db"
            with patch.dict(os.environ, {"JOB_DB_PATH": str(job_db)}, clear=False):
                store = JobStore(job_db)
                store.upsert(
                    ResearchJob(
                        id="job-review",
                        goal="Review me",
                        user_id="user-1",
                        status=JobStatus.RUNNING,
                    ).to_record()
                )

                request = register_review(
                    "job-review",
                    goal="Review me",
                    claims=[{"claim": "This claim needs approval.", "confidence": "high"}],
                    reasons=["mode=required"],
                )
                with web_review._lock:
                    web_review._requests.clear()

                self.assertTrue(submit_web_approval("job-review", True))

                with web_review._lock:
                    web_review._requests["job-review"] = request
                approved, decision = wait_for_web_approval("job-review", timeout=1)
                stored = store.get("job-review")

        self.assertTrue(approved)
        self.assertIn("approved", decision)
        self.assertEqual(stored["status"], "running")
        self.assertTrue(stored["state"]["_web_review_decision"]["approved"])

    def test_active_job_limit_counts_non_terminal_jobs(self):
        jobs = [
            {"status": "queued"},
            {"status": "running"},
            {"status": "awaiting_review"},
            {"status": "completed"},
            {"status": "failed"},
            {"status": "blocked"},
            {"status": "canceled"},
        ]

        self.assertEqual(active_job_count(jobs), 3)

    def test_active_job_limit_rejects_when_user_has_too_many_active_jobs(self):
        jobs = [{"status": "queued"}, {"status": "running"}]

        with self.assertRaisesRegex(Exception, "maximum number"):
            enforce_active_job_limit(
                jobs,
                LimitSettings(max_active_jobs_per_user=2),
            )

    def test_job_create_rate_limiter_rejects_window_excess(self):
        limiter = JobCreateRateLimiter(
            LimitSettings(max_job_creates_per_window=2, job_create_window_seconds=60)
        )
        limiter.check_and_record("user-1", now=100.0)
        limiter.check_and_record("user-1", now=110.0)

        with self.assertRaisesRegex(Exception, "Too many"):
            limiter.check_and_record("user-1", now=120.0)

        limiter.check_and_record("user-1", now=161.0)

    def test_readiness_report_checks_backing_stores(self):
        with TemporaryDirectory() as tmpdir:
            with patch.dict(
                os.environ,
                {
                    "AUTH_DB_PATH": str(Path(tmpdir) / "auth.db"),
                    "JOB_DB_PATH": str(Path(tmpdir) / "jobs.db"),
                    "RUN_ARTIFACT_DIR": str(Path(tmpdir) / "runs"),
                    "ARTIFACT_DB_PATH": "",
                    "ARTIFACT_DATABASE_URL": "",
                },
                clear=False,
            ):
                report = readiness_report()

        self.assertTrue(report["ready"])
        self.assertEqual(report["status"], "ready")
        self.assertTrue(report["checks"]["auth_store"]["ok"])
        self.assertTrue(report["checks"]["job_store"]["ok"])
        self.assertEqual(report["checks"]["artifact_storage"]["mode"], "filesystem")

    def test_readiness_report_degrades_when_dependency_probe_fails(self):
        with patch("web.health.auth_db.get_user_by_id", side_effect=RuntimeError("db down")):
            report = readiness_report()

        self.assertFalse(report["ready"])
        self.assertEqual(report["status"], "degraded")
        self.assertFalse(report["checks"]["auth_store"]["ok"])
        self.assertIn("db down", report["checks"]["auth_store"]["detail"])

    def test_ready_endpoint_returns_503_when_readiness_degrades(self):
        app = create_app()
        degraded = {
            "status": "degraded",
            "ready": False,
            "checks": {
                "auth_store": {
                    "ok": False,
                    "name": "auth_store",
                    "status": "error",
                    "detail": "db down",
                }
            },
        }

        with patch("web.server.readiness_report", return_value=degraded):
            response = TestClient(app).get("/api/ready")

        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["ready"])

    def test_e2e_api_job_create_list_cancel_and_events_workflow(self):
        with TemporaryDirectory() as tmpdir:
            with patch.dict(
                os.environ,
                {
                    "AUTH_REQUIRED": "false",
                    "AUTH_DEV_USER_ID": "e2e-user",
                    "AUTH_DB_PATH": str(Path(tmpdir) / "auth.db"),
                    "AUTH_DATABASE_URL": "",
                    "DATABASE_URL": "",
                    "JOB_DB_PATH": str(Path(tmpdir) / "jobs.db"),
                    "JOB_DATABASE_URL": "",
                    "JOB_EXECUTION_MODE": "external",
                },
                clear=False,
            ):
                auth_settings.cache_clear()
                init_db()
                store = JobStore(Path(tmpdir) / "jobs.db")
                manager = JobManager(store=store, execution_mode="external", load_existing=False)
                with patch("web.server.job_manager", manager):
                    client = TestClient(create_app())
                    create_response = client.post(
                        "/api/jobs",
                        json={"goal": "Research the production readiness workflow"},
                    )
                    job_id = create_response.json()["id"]

                    list_response = client.get("/api/jobs")
                    detail_response = client.get(f"/api/jobs/{job_id}?include_state=true")
                    cancel_response = client.post(f"/api/jobs/{job_id}/cancel")
                    final_response = client.get(f"/api/jobs/{job_id}")
                    events_response = client.get(f"/api/jobs/{job_id}/events")
                auth_settings.cache_clear()

        self.assertEqual(create_response.status_code, 200)
        self.assertEqual(create_response.json()["status"], "queued")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json()["jobs"][0]["id"], job_id)
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.json()["id"], job_id)
        self.assertEqual(cancel_response.status_code, 200)
        self.assertEqual(cancel_response.json()["status"], "canceled")
        self.assertEqual(final_response.status_code, 200)
        self.assertEqual(final_response.json()["status"], "canceled")
        self.assertEqual(events_response.status_code, 200)
        self.assertIn('"type": "done"', events_response.text)
        self.assertIn('"status": "canceled"', events_response.text)

    def test_e2e_api_jobs_require_auth_when_auth_is_enabled(self):
        auth_settings.cache_clear()
        with patch.dict(
            os.environ,
            {
                "AUTH_REQUIRED": "true",
                "AUTH_SECRET_KEY": "test-secret",
            },
            clear=False,
        ):
            auth_settings.cache_clear()
            response = TestClient(create_app()).get("/api/jobs")
        auth_settings.cache_clear()

        self.assertEqual(response.status_code, 401)

    def test_api_echoes_valid_request_id_header(self):
        response = TestClient(create_app()).get(
            "/api/health",
            headers={"X-Request-ID": "req-test-123"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Request-ID"], "req-test-123")
        self.assertEqual(current_request_id(), "")

    def test_api_generates_request_id_when_header_is_missing(self):
        response = TestClient(create_app()).get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["X-Request-ID"])

    def test_api_request_log_is_structured_and_correlated(self):
        with self.assertLogs("factcrafter.api", level="INFO") as logs:
            response = TestClient(create_app()).get(
                "/api/health",
                headers={"X-Request-ID": "req-log-1"},
            )

        self.assertEqual(response.status_code, 200)
        entries = [json.loads(record.getMessage()) for record in logs.records]
        request_log = next(entry for entry in entries if entry["event"] == "api_request")
        self.assertEqual(request_log["request_id"], "req-log-1")
        self.assertEqual(request_log["method"], "GET")
        self.assertEqual(request_log["path"], "/api/health")
        self.assertEqual(request_log["status_code"], 200)
        self.assertIn("duration_ms", request_log)

    def test_metrics_endpoint_reports_api_request_counts(self):
        reset_metrics()
        client = TestClient(create_app())

        health_response = client.get("/api/health")
        metrics_response = client.get("/api/metrics")
        payload = metrics_response.json()

        self.assertEqual(health_response.status_code, 200)
        self.assertEqual(metrics_response.status_code, 200)
        self.assertGreaterEqual(payload["api"]["requests_total"], 1)
        self.assertEqual(payload["api"]["errors_total"], 0)
        self.assertGreaterEqual(payload["api"]["status_counts"]["2xx"], 1)
        self.assertIn("latency_avg_ms", payload["api"])

    def test_job_metrics_increment_from_lifecycle_events(self):
        reset_metrics()
        with TemporaryDirectory() as tmpdir:
            store = JobStore(Path(tmpdir) / "jobs.db")
            manager = JobManager(store=store, execution_mode="external", load_existing=False)
            job = manager.create_job("Metrics job", "user-1")
            manager.cancel_job(job.id, "user-1")

        payload = metrics_snapshot()
        self.assertGreaterEqual(payload["jobs"]["events_total"]["job_created"], 1)
        self.assertGreaterEqual(payload["jobs"]["events_total"]["job_canceled"], 1)
        self.assertGreaterEqual(payload["jobs"]["terminal_total"]["canceled"], 1)

    def test_cancel_job_endpoint_cancels_owned_queued_job(self):
        with TemporaryDirectory() as tmpdir:
            store = JobStore(Path(tmpdir) / "jobs.db")
            manager = JobManager(store=store, execution_mode="external", load_existing=False)
            user_id = auth_settings()["dev_user_id"]
            job = manager.create_job("Cancel from API", user_id)

            with patch("web.server.job_manager", manager):
                response = TestClient(create_app()).post(f"/api/jobs/{job.id}/cancel")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "canceled")

    def test_cancel_job_endpoint_rejects_terminal_job(self):
        with TemporaryDirectory() as tmpdir:
            store = JobStore(Path(tmpdir) / "jobs.db")
            user_id = auth_settings()["dev_user_id"]
            completed = ResearchJob(
                id="job-completed",
                goal="Already completed",
                user_id=user_id,
                status=JobStatus.COMPLETED,
            )
            store.upsert(completed.to_record())
            manager = JobManager(store=store, execution_mode="external", load_existing=True)

            with patch("web.server.job_manager", manager):
                response = TestClient(create_app()).post("/api/jobs/job-completed/cancel")

        self.assertEqual(response.status_code, 409)

    def test_worker_loop_exits_when_stop_event_is_set(self):
        class IdleManager:
            def __init__(self):
                self.recover_calls = 0
                self.run_calls = 0

            def recover_stale_jobs(self, **_kwargs):
                self.recover_calls += 1

            def run_next_queued_job(self, **_kwargs):
                self.run_calls += 1
                stop_event.set()
                return False

        stop_event = threading.Event()
        manager = IdleManager()

        code = run_worker_loop(
            manager,
            once=False,
            poll_seconds=10,
            stale_after_seconds=60,
            max_attempts=3,
            worker_id="worker-test",
            stop_event=stop_event,
        )

        self.assertEqual(code, 0)
        self.assertEqual(manager.recover_calls, 1)
        self.assertEqual(manager.run_calls, 1)

    def test_worker_healthcheck_reports_store_connectivity(self):
        with TemporaryDirectory() as tmpdir:
            manager = JobManager(
                store=JobStore(Path(tmpdir) / "jobs.db"),
                execution_mode="external",
                load_existing=False,
            )

            with patch("builtins.print") as print_call:
                code = run_worker_healthcheck(manager)

        self.assertEqual(code, 0)
        payload = json.loads(print_call.call_args.args[0])
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["job_store"], "ok")
        self.assertEqual(payload["execution_mode"], "external")

    def test_worker_healthcheck_fails_when_store_is_unavailable(self):
        class BrokenManager:
            def healthcheck(self):
                raise RuntimeError("store unavailable")

        with patch("builtins.print") as print_call:
            code = run_worker_healthcheck(BrokenManager())

        self.assertEqual(code, 1)
        payload = json.loads(print_call.call_args.args[0])
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["job_store"], "error")
        self.assertIn("store unavailable", payload["error"])


if __name__ == "__main__":
    unittest.main()
