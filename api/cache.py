"""In-process TTL cache with stale-while-revalidate, for the public read API.

Why this exists: the public endpoints recompute full-history aggregates from
base tables on every request (`/api/public/summary` pulled 162k rows out of
Postgres to return 257 bytes). The underlying data only changes when the
pipeline runs — the daily job at 14:00 UTC, prediction refreshes at 18/21/23,
score refreshes on the even hours — so serving a few-minute-old answer is
always safe here. These handlers are pure reads; nothing in this process
writes.

Two properties matter as much as the TTL itself:

- Single-flight. The Record page fires four requests at once and the API is
  one uvicorn process on 0.25 vCPU, so a cold cache without a per-key lock
  means four concurrent full-history scans all slowing each other down.
- Stale-while-revalidate. A plain TTL just moves the 30-second wait onto
  whichever visitor arrives first after it expires. Serving the stale value
  while one background thread refreshes means only a genuinely cold process
  ever blocks — and `warm()` covers that case at startup.

Deliberately stdlib-only and process-local: one task, no Redis, no new
dependency. It follows that a deploy or scale-out starts cold, which is what
`warm()` is for. If this ever runs more than one task, the answer is not a
bigger cache here — it is precomputing the grading into rollup tables so the
queries stop being expensive in the first place.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any

log = logging.getLogger(__name__)

# Bounded so a caller walking `?days=1..2000` can't grow this without limit —
# each entry can hold a multi-MB list on a 512 MiB container.
MAX_ENTRIES = 64

# How long to keep serving a stale value after a failed background refresh
# before trying again. Stops a broken DB from spawning a thread per request.
RETRY_AFTER = 30.0


@dataclass
class _Entry:
    value: Any
    fresh_until: float
    stale_until: float
    refreshing: bool = False


_LOCK = threading.Lock()  # guards _ENTRIES and _KEY_LOCKS
_ENTRIES: dict[tuple, _Entry] = {}
_KEY_LOCKS: dict[tuple, threading.Lock] = {}


def _key_lock(key: tuple) -> threading.Lock:
    with _LOCK:
        lock = _KEY_LOCKS.get(key)
        if lock is None:
            lock = _KEY_LOCKS[key] = threading.Lock()
        return lock


def _evict_if_needed() -> None:
    """Caller must hold _LOCK. Drop fully-expired entries first, then the
    entries closest to expiry until we are back under the cap."""
    if len(_ENTRIES) <= MAX_ENTRIES:
        return
    now = time.monotonic()
    for key in [k for k, e in _ENTRIES.items() if e.stale_until <= now]:
        del _ENTRIES[key]
        _KEY_LOCKS.pop(key, None)
    if len(_ENTRIES) <= MAX_ENTRIES:
        return
    for key, _ in sorted(_ENTRIES.items(), key=lambda kv: kv[1].stale_until)[
        : len(_ENTRIES) - MAX_ENTRIES
    ]:
        del _ENTRIES[key]
        _KEY_LOCKS.pop(key, None)


def _store(key: tuple, value: Any, ttl: float, stale: float) -> None:
    now = time.monotonic()
    with _LOCK:
        _ENTRIES[key] = _Entry(value, now + ttl, now + ttl + stale)
        _evict_if_needed()


def _refresh(key: tuple, fn: Callable, args: tuple, kwargs: dict,
             ttl: float, stale: float) -> None:
    """Background refresh of a stale entry. Never raises: on failure the old
    value stays in place and we back off, so a DB blip degrades to slightly
    staler numbers instead of an error page."""
    try:
        _store(key, fn(*args, **kwargs), ttl, stale)
    except Exception:
        log.exception("cache refresh failed for %s; serving stale", key[0])
        now = time.monotonic()
        with _LOCK:
            entry = _ENTRIES.get(key)
            if entry is not None:
                entry.fresh_until = now + RETRY_AFTER
                entry.stale_until = max(entry.stale_until, entry.fresh_until + stale)
    finally:
        with _LOCK:
            entry = _ENTRIES.get(key)
            if entry is not None:
                entry.refreshing = False


def cached(ttl: float, stale: float = 900.0):
    """Memoize a sync endpoint handler on its arguments for `ttl` seconds,
    then serve the stale value for up to `stale` more while one background
    thread refreshes it.

    Exceptions are never cached — a 404 from an empty window stays cheap to
    recompute and must not stick around once data lands.
    """

    def decorate(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = (fn.__qualname__, args, tuple(sorted(kwargs.items())))
            now = time.monotonic()
            with _LOCK:
                entry = _ENTRIES.get(key)
                if entry is not None and now < entry.fresh_until:
                    return entry.value
                serve_stale = entry is not None and now < entry.stale_until
                if serve_stale and not entry.refreshing:
                    entry.refreshing = True
                    spawn = True
                else:
                    spawn = False
                stale_value = entry.value if serve_stale else None
            if serve_stale:
                if spawn:
                    threading.Thread(
                        target=_refresh,
                        args=(key, fn, args, kwargs, ttl, stale),
                        name=f"cache-refresh-{fn.__name__}",
                        daemon=True,
                    ).start()
                return stale_value

            # Cold or fully expired: block, but only one thread per key.
            with _key_lock(key):
                now = time.monotonic()
                with _LOCK:
                    entry = _ENTRIES.get(key)
                    if entry is not None and now < entry.fresh_until:
                        return entry.value
                value = fn(*args, **kwargs)
                _store(key, value, ttl, stale)
                return value

        wrapper.__wrapped__ = fn
        return wrapper

    return decorate


def clear() -> None:
    """Drop everything. Used by tests."""
    with _LOCK:
        _ENTRIES.clear()
        _KEY_LOCKS.clear()


def stats() -> dict:
    now = time.monotonic()
    with _LOCK:
        return {
            "entries": len(_ENTRIES),
            "fresh": sum(1 for e in _ENTRIES.values() if now < e.fresh_until),
            "refreshing": sum(1 for e in _ENTRIES.values() if e.refreshing),
        }


def warm(calls: list[tuple[Callable, dict]]) -> None:
    """Best-effort background priming so the first visitor after a deploy
    doesn't pay for a cold cache. Runs sequentially — the point is to fill
    the cache without stealing the whole 0.25 vCPU from live requests or the
    ALB health check."""

    def run() -> None:
        for fn, kwargs in calls:
            try:
                started = time.monotonic()
                fn(**kwargs)
                log.info("cache warm %s(%s) in %.1fs", fn.__name__, kwargs,
                         time.monotonic() - started)
            except Exception:
                log.exception("cache warm failed for %s(%s)", fn.__name__, kwargs)

    threading.Thread(target=run, name="cache-warm", daemon=True).start()
