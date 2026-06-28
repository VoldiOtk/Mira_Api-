from __future__ import annotations
import os


def download_file(bucket: str, key: str, local_path: str) -> None:
    raise NotImplementedError(
        f"S3 not configured. Set S3_ENDPOINT/S3_ACCESS_KEY/S3_SECRET_KEY env vars. "
        f"Cannot download s3://{bucket}/{key}"
    )


def upload_file(local_path: str, bucket: str, key: str) -> None:
    raise NotImplementedError(
        f"S3 not configured. Cannot upload {local_path} to s3://{bucket}/{key}"
    )


def ensure_buckets() -> None:
    s3_endpoint = os.getenv("S3_ENDPOINT", "")
    if not s3_endpoint:
        raise RuntimeError("S3_ENDPOINT not set — MinIO/S3 not available in dev mode")
