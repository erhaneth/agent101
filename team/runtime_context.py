from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator


_web_job_id: ContextVar[str] = ContextVar("factcrafter_web_job_id", default="")


def current_web_job_id() -> str:
    return _web_job_id.get().strip()


def is_web_context() -> bool:
    return bool(current_web_job_id())


@contextmanager
def web_job_context(job_id: str) -> Iterator[None]:
    token: Token[str] = _web_job_id.set(job_id.strip())
    try:
        yield
    finally:
        _web_job_id.reset(token)
