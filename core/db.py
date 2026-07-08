"""Database engine factory — the single entry point for all DB access.

Credential resolution, in order:
  1. MLB_DB_PASSWORD set in the environment/.env  -> used directly.
  2. MLB_DB_SECRET_ARN                            -> fetched from Secrets Manager.

RDS manages and rotates the master password (manage_master_user_password in
infra/database.tf), so path 2 is the default: every fresh process picks up the
current password and rotation never breaks anything. Long-running services
(Phase 6) should rebuild the engine on authentication failure instead of
caching one forever.
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
        connect_args={"sslmode": "require"},
    )
