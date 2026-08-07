"""Concurrency tests for the public API's read cache (api/cache.py).

The cache exists to keep one 0.25 vCPU process from recomputing full-history
aggregates per page view, and its two load-bearing properties are the ones a
smoke test never exercises: single-flight (a burst of cold requests must run
the query once, not once each) and stale-while-revalidate (nobody blocks on a
refresh once the entry exists). Both are threading behaviour, so they get a
real test rather than a manual curl.

No database needed — the cached callable is a counter.

Usage: python scripts/test_api_cache.py
"""

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api import cache  # noqa: E402

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{'  -- ' + detail if detail else ''}")
    if not ok:
        FAILURES.append(name)


def test_memoizes_per_key() -> None:
    print("memoizes on arguments")
    calls: list[int] = []

    @cache.cached(ttl=60)
    def fn(days: int) -> str:
        calls.append(days)
        return f"v{days}"

    check("repeat call is served from cache",
          [fn(days=7), fn(days=7), fn(days=7)] == ["v7"] * 3 and len(calls) == 1,
          f"{len(calls)} execution(s)")
    fn(days=30)
    check("a different argument is a different entry", len(calls) == 2,
          f"{len(calls)} execution(s)")


def test_single_flight() -> None:
    """Eight threads hit a cold key at once. The query must run once."""
    print("single-flight on a cold key")
    calls: list[float] = []

    @cache.cached(ttl=60)
    def slow() -> str:
        calls.append(time.monotonic())
        time.sleep(0.4)
        return "computed"

    results: list[str] = []
    threads = [threading.Thread(target=lambda: results.append(slow())) for _ in range(8)]
    started = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.monotonic() - started

    check("query ran exactly once for 8 concurrent callers", len(calls) == 1,
          f"{len(calls)} execution(s)")
    check("all 8 callers got the value", results == ["computed"] * 8)
    check("callers waited for one run, not eight", elapsed < 1.0,
          f"{elapsed:.2f}s wall clock")


def test_stale_while_revalidate() -> None:
    """Past the TTL, a request must return immediately with the old value and
    leave the refresh to a background thread."""
    print("stale-while-revalidate")
    version = {"n": 0}

    @cache.cached(ttl=0.2, stale=60)
    def fn() -> str:
        version["n"] += 1
        time.sleep(0.4)
        return f"v{version['n']}"

    check("first call computes", fn() == "v1")
    time.sleep(0.3)  # now stale, not expired

    started = time.monotonic()
    served = fn()
    blocked = time.monotonic() - started
    check("stale request does not block", blocked < 0.1, f"waited {blocked:.3f}s")
    check("stale request serves the old value", served == "v1", f"got {served}")

    time.sleep(0.8)  # let the background refresh land
    check("background refresh replaced the value", fn() == "v2", f"got {fn()}")


def test_errors_are_not_cached() -> None:
    print("errors are not cached")
    calls: list[int] = []

    @cache.cached(ttl=60)
    def flaky() -> str:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return "recovered"

    try:
        flaky()
    except RuntimeError:
        pass
    else:
        check("first call raised", False, "no exception")
    check("a later call retries and succeeds", flaky() == "recovered",
          f"{len(calls)} execution(s)")


def test_entry_cap() -> None:
    """`days` is caller-controlled up to 2000; entries must stay bounded so a
    crawler walking the range cannot fill a 512 MiB container."""
    print("entry cap holds under distinct keys")
    cache.clear()

    @cache.cached(ttl=60)
    def fn(days: int) -> int:
        return days

    for d in range(cache.MAX_ENTRIES * 3):
        fn(days=d)
    entries = cache.stats()["entries"]
    check(f"entries stay at or below MAX_ENTRIES ({cache.MAX_ENTRIES})",
          entries <= cache.MAX_ENTRIES, f"{entries} entries")


def main() -> None:
    for test in (test_memoizes_per_key, test_single_flight,
                 test_stale_while_revalidate, test_errors_are_not_cached,
                 test_entry_cap):
        cache.clear()
        test()

    print()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} check(s) failed: {', '.join(FAILURES)}")
        sys.exit(1)
    print("PASS: cache memoizes per key, collapses concurrent misses, serves "
          "stale without blocking, retries after errors, and stays bounded")


if __name__ == "__main__":
    main()
