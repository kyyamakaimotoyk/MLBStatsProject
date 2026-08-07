"""Database engine factory — the single entry point for all DB access.

Credential resolution, in order:
  1. MLB_DB_PASSWORD set in the environment/.env  -> used directly.
  2. MLB_DB_SECRET_ARN                            -> fetched from Secrets Manager.

RDS manages and rotates the master password (manage_master_user_password in
infra/database.tf), so path 2 is the default: every fresh process picks up the
current password and rotation never breaks anything. Long-running services
(Phase 6) should rebuild the engine on authentication failure instead of
caching one forever.

Timeout guardrails (see _connect_args): one engine factory serves two very
different workloads, so the defaults here are the ones that cannot break
either. `connect_timeout` is always on — a TCP/TLS connect that hangs should
never occupy a pool slot indefinitely. `statement_timeout` is OPT-IN, because
the pipeline legitimately runs multi-minute statements and a blanket ceiling
would kill a feature build or a walk-forward pull mid-run. The read-only API
opts in via MLB_DB_STATEMENT_TIMEOUT in its task definition.
"""

import json
import os
from functools import lru_cache

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine

load_dotenv()


def _resolve_password() -> str:
    password = os.getenv("MLB_DB_PASSWORD")
    if password:
        return password
    secret_arn = os.getenv("MLB_DB_SECRET_ARN")
    if not secret_arn:
        raise RuntimeError("Set MLB_DB_PASSWORD or MLB_DB_SECRET_ARN (see .env.example)")
    import boto3

    client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "us-east-1"))
    secret = json.loads(client.get_secret_value(SecretId=secret_arn)["SecretString"])
    return secret["password"]


def _connect_args() -> dict:
    """libpq connection parameters, including the timeout guardrails.

    MLB_DB_CONNECT_TIMEOUT   seconds to wait for a connect (default 10)
    MLB_DB_STATEMENT_TIMEOUT server-side ceiling per statement, passed through
                             to Postgres verbatim — a bare number is
                             milliseconds, or give a unit ("15s"). Unset means
                             no ceiling, which is what the pipeline needs.
    """
    args = {
        "sslmode": "require",
        # Without this, an unreachable host blocks on the OS default (minutes)
        # while holding a pool slot. With pool_size=5 on a single-worker API,
        # a handful of those is the whole service.
        "connect_timeout": int(os.getenv("MLB_DB_CONNECT_TIMEOUT", "10")),
    }
    statement_timeout = os.getenv("MLB_DB_STATEMENT_TIMEOUT", "").strip()
    if statement_timeout:
        # Applied at connect time, so it covers every statement on the session
        # — including the ones pandas.read_sql issues.
        args["options"] = f"-c statement_timeout={statement_timeout}"
    return args


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    url = URL.create(
        "postgresql+psycopg",
        username=os.getenv("MLB_DB_USER", "mlbadmin"),
        password=_resolve_password(),
        host=os.environ["MLB_DB_HOST"],
        port=int(os.getenv("MLB_DB_PORT", "5432")),
        database=os.getenv("MLB_DB_NAME", "mlb_data"),
    )
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args=_connect_args(),
    )
