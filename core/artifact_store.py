"""Model artifact storage: S3 or a local directory, selected by environment.

  MLB_DATA_BUCKET set    -> s3://$MLB_DATA_BUCKET/$MLB_MODELS_PREFIX<name>
  else MLB_MODELS_DIR    -> that local directory (offline mirror)
  else                   -> disabled: save/load are no-ops returning None

Port of the NBA core/artifact_store.py pattern. Model bundles never live in
the repo.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _bucket() -> str | None:
    return os.getenv("MLB_DATA_BUCKET") or None


def _prefix() -> str:
    return os.getenv("MLB_MODELS_PREFIX", "models/")


def _local_dir() -> Path | None:
    d = os.getenv("MLB_MODELS_DIR")
    return Path(d) if d else None


def save_artifact(local_path: str | Path, name: str) -> str | None:
    """Store a model bundle under `name`; returns its URI, or None if disabled."""
    local_path = Path(local_path)
    bucket = _bucket()
    if bucket:
        import boto3

        key = f"{_prefix()}{name}"
        boto3.client("s3").upload_file(str(local_path), bucket, key)
        return f"s3://{bucket}/{key}"
    local_dir = _local_dir()
    if local_dir:
        local_dir.mkdir(parents=True, exist_ok=True)
        dest = local_dir / name
        dest.write_bytes(local_path.read_bytes())
        return str(dest)
    return None


def load_artifact(name: str, dest_path: str | Path) -> Path | None:
    """Fetch a model bundle by `name` into dest_path; returns it, or None."""
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    bucket = _bucket()
    if bucket:
        import boto3
        from botocore.exceptions import ClientError

        try:
            boto3.client("s3").download_file(bucket, f"{_prefix()}{name}", str(dest_path))
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey", "NotFound"):
                return None
            raise
        return dest_path
    local_dir = _local_dir()
    if local_dir and (local_dir / name).exists():
        dest_path.write_bytes((local_dir / name).read_bytes())
        return dest_path
    return None
