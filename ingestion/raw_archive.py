"""Raw-response archive: everything fetched from an external API lands in S3
gzipped before parsing, so a parser bug is a reprocess, not a re-fetch.

Keys: raw/statsapi/feed_live/{season}/{game_pk}.json.gz
      raw/statcast/{season}/{date}.csv.gz
"""

import gzip
import json
import os

import boto3
from dotenv import load_dotenv

load_dotenv()

_client = None


def _s3():
    global _client
    if _client is None:
        _client = boto3.client("s3")
    return _client


def put_json_gz(key_suffix: str, obj: dict) -> str:
    key = f"{os.getenv('MLB_RAW_PREFIX', 'raw/')}{key_suffix}"
    body = gzip.compress(json.dumps(obj, separators=(",", ":")).encode("utf-8"))
    _s3().put_object(
        Bucket=os.environ["MLB_DATA_BUCKET"], Key=key, Body=body,
        ContentType="application/json", ContentEncoding="gzip",
    )
    return key


def get_json_gz(key: str) -> dict:
    """Read back an archived JSON object by its FULL key (as stored in the
    ingest ledger's s3_key column — prefix already included)."""
    obj = _s3().get_object(Bucket=os.environ["MLB_DATA_BUCKET"], Key=key)
    return json.loads(gzip.decompress(obj["Body"].read()).decode("utf-8"))


def put_text_gz(key_suffix: str, content: str, content_type: str = "text/csv") -> str:
    key = f"{os.getenv('MLB_RAW_PREFIX', 'raw/')}{key_suffix}"
    _s3().put_object(
        Bucket=os.environ["MLB_DATA_BUCKET"], Key=key,
        Body=gzip.compress(content.encode("utf-8")),
        ContentType=content_type, ContentEncoding="gzip",
    )
    return key
