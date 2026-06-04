from __future__ import annotations

import json
import logging
import string
import time
import uuid
from contextvars import ContextVar

from fastapi import FastAPI, Request
from web.metrics import record_api_request


REQUEST_ID_HEADER = "X-Request-ID"
request_id_context: ContextVar[str] = ContextVar("request_id", default="")
logger = logging.getLogger("factcrafter.api")


def current_request_id() -> str:
    return request_id_context.get()


def install_observability(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_observability_middleware(request: Request, call_next):
        request_id = _request_id_from_header(request.headers.get(REQUEST_ID_HEADER)) or str(uuid.uuid4())
        token = request_id_context.set(request_id)
        started = time.perf_counter()
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        except Exception as exc:  # noqa: BLE001
            _log_json(
                logging.ERROR,
                {
                    "event": "api_request_error",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                exc_info=True,
            )
            raise
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            record_api_request(status_code=status_code, duration_ms=duration_ms)
            _log_json(
                logging.INFO,
                {
                    "event": "api_request",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )
            request_id_context.reset(token)


def _request_id_from_header(value: str | None) -> str:
    if not value:
        return ""
    request_id = value.strip()
    if not (1 <= len(request_id) <= 128):
        return ""
    allowed = set(string.ascii_letters + string.digits + "-_.:/")
    if any(char not in allowed for char in request_id):
        return ""
    return request_id


def _log_json(level: int, payload: dict, *, exc_info: bool = False) -> None:
    logger.log(level, json.dumps(payload, sort_keys=True), exc_info=exc_info)
