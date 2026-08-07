"""Timeout guardrails on the shared engine (core/db.py).

One engine factory serves the read-only API and the batch pipeline, whose
tolerable query lengths differ by three orders of magnitude. That makes the
DEFAULT the dangerous part: a statement_timeout that leaked into the pipeline
would kill a feature build or a walk-forward pull mid-run, and it would do it
silently on the next deploy rather than here.

So this asserts both directions — that the ceiling actually fires when set,
and that nothing is imposed when it isn't.

Needs the database (it runs a real pg_sleep against it).

Usage: python scripts/test_db_guardrails.py
"""

import os
import sys
import time
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import db  # noqa: E402

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{'  -- ' + detail if detail else ''}")
    if not ok:
        FAILURES.append(name)


def engine_with(**env):
    """Rebuild the engine under a given environment. get_engine is lru_cached,
    so the cache has to be dropped or the first config wins forever."""
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    db.get_engine.cache_clear()
    return db.get_engine()


def test_connect_timeout_always_set() -> None:
    print("connect_timeout is always applied")
    args = db._connect_args()
    check("present by default", args.get("connect_timeout") == 10,
          f"connect_timeout={args.get('connect_timeout')}")
    os.environ["MLB_DB_CONNECT_TIMEOUT"] = "3"
    check("overridable", db._connect_args().get("connect_timeout") == 3)
    os.environ.pop("MLB_DB_CONNECT_TIMEOUT", None)


def test_no_ceiling_by_default() -> None:
    """The pipeline path. '0' is Postgres for 'no limit'."""
    print("no statement ceiling unless asked for (the pipeline default)")
    check("no options key in connect_args",
          "options" not in db._connect_args())
    eng = engine_with(MLB_DB_STATEMENT_TIMEOUT=None)
    with eng.connect() as c:
        got = c.execute(text("SHOW statement_timeout")).scalar()
    check("server session has no ceiling", got == "0", f"statement_timeout={got!r}")

    with eng.connect() as c:
        started = time.perf_counter()
        c.execute(text("SELECT pg_sleep(3)"))
        elapsed = time.perf_counter() - started
    check("a 3s statement is allowed to finish", elapsed >= 2.5,
          f"{elapsed:.1f}s")


def test_ceiling_fires_when_set() -> None:
    print("statement ceiling fires when set (the API config)")
    eng = engine_with(MLB_DB_STATEMENT_TIMEOUT="2s")
    check("options carries the setting",
          db._connect_args().get("options") == "-c statement_timeout=2s")
    with eng.connect() as c:
        got = c.execute(text("SHOW statement_timeout")).scalar()
    check("server session reports the ceiling", got == "2s", f"statement_timeout={got!r}")

    started = time.perf_counter()
    try:
        with eng.connect() as c:
            c.execute(text("SELECT pg_sleep(30)"))
    except OperationalError as exc:
        elapsed = time.perf_counter() - started
        check("a runaway statement is cancelled", elapsed < 10, f"cancelled after {elapsed:.1f}s")
        check("cancelled for the right reason",
              "statement timeout" in str(exc).lower(), str(exc).split("\n")[0][:70])
    else:
        check("a runaway statement is cancelled", False, "pg_sleep(30) completed")

    # The ceiling must not be so tight it clips real work: the slowest query
    # the API issues measured ~520 ms.
    eng = engine_with(MLB_DB_STATEMENT_TIMEOUT="15s")
    with eng.connect() as c:
        started = time.perf_counter()
        c.execute(text("SELECT pg_sleep(1)"))
        elapsed = time.perf_counter() - started
    check("normal work is untouched at the API's 15s setting", elapsed >= 0.9,
          f"1s statement took {elapsed:.1f}s")


def main() -> None:
    # Resolve the password once so each engine rebuild below doesn't re-hit
    # Secrets Manager; the guardrails under test are independent of it.
    if not os.getenv("MLB_DB_PASSWORD"):
        os.environ["MLB_DB_PASSWORD"] = db._resolve_password()

    try:
        test_connect_timeout_always_set()
        test_no_ceiling_by_default()
        test_ceiling_fires_when_set()
    finally:
        os.environ.pop("MLB_DB_STATEMENT_TIMEOUT", None)
        db.get_engine.cache_clear()

    print()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} check(s) failed: {', '.join(FAILURES)}")
        sys.exit(1)
    print("PASS: connect timeout always on, no statement ceiling by default, "
          "ceiling cancels runaways when set")


if __name__ == "__main__":
    main()
