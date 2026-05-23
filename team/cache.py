# team/cache.py
# 🧊 FILE CACHE
# Responsibility: cache expensive external calls such as search and source fetches.
#
# Cache is intentionally file-based and JSON-only so it is easy to inspect,
# delete, and use during local development without adding infrastructure.

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE_DIR = PROJECT_ROOT / ".cache" / "factcrafter"


def cache_enabled(value: bool | None = None) -> bool:
    if value is not None:
        return value
    env_value = os.getenv("FACTCRAFTER_CACHE_ENABLED", "true").strip().lower()
    return env_value not in {"0", "false", "no", "off"}


def cache_root(root: str | Path | None = None) -> Path:
    if root is not None:
        return Path(root)
    return Path(os.getenv("FACTCRAFTER_CACHE_DIR", DEFAULT_CACHE_DIR))


def ttl_seconds(env_name: str, default: int) -> int:
    try:
        return int(os.getenv(env_name, str(default)))
    except ValueError:
        return default


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def cache_key(namespace: str, payload: Any) -> str:
    raw = stable_json({"namespace": namespace, "payload": payload})
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cache_path(namespace: str, payload: Any, *, root: str | Path | None = None) -> Path:
    key = cache_key(namespace, payload)
    return cache_root(root) / namespace / f"{key}.json"


def get_cached_json(
    namespace: str,
    payload: Any,
    *,
    ttl: int | None = None,
    root: str | Path | None = None,
    enabled: bool | None = None,
) -> Any | None:
    """Return cached value or None when disabled, missing, expired, or corrupt."""
    if not cache_enabled(enabled):
        return None

    path = cache_path(namespace, payload, root=root)
    if not path.exists():
        return None

    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    created_at = float(record.get("created_at", 0))
    if ttl is not None and ttl >= 0 and time.time() - created_at > ttl:
        return None

    return record.get("value")


def set_cached_json(
    namespace: str,
    payload: Any,
    value: Any,
    *,
    root: str | Path | None = None,
    enabled: bool | None = None,
) -> Path | None:
    """Write a JSON cache record and return its path."""
    if not cache_enabled(enabled):
        return None

    path = cache_path(namespace, payload, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "namespace": namespace,
        "key": cache_key(namespace, payload),
        "created_at": time.time(),
        "payload": payload,
        "value": value,
    }
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def clear_cache(namespace: str | None = None, *, root: str | Path | None = None) -> int:
    """Delete cache files. Returns number of files removed."""
    base = cache_root(root)
    target = base / namespace if namespace else base
    if not target.exists():
        return 0

    count = 0
    for path in target.rglob("*.json"):
        path.unlink()
        count += 1
    return count
