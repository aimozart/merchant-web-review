"""
Stores raw web-presence snapshots in S3-compatible object storage (MinIO locally,
real S3 in AWS) — keeping the original evidence a review's recommendation was based
on, so any underwriting decision is auditable back to its source, same principle as
Entropa's Attestation Receipts: don't just assert a conclusion, keep the evidence.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

import boto3
from botocore.client import Config


def _client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT_URL"),  # MinIO locally; unset uses real AWS
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "minioadmin"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "minioadmin"),
        config=Config(signature_version="s3v4"),
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
    )


def _bucket() -> str:
    return os.environ.get("SNAPSHOT_BUCKET", "merchant-review-snapshots")


def ensure_bucket_exists() -> None:
    client = _client()
    bucket = _bucket()
    try:
        client.head_bucket(Bucket=bucket)
    except Exception:
        client.create_bucket(Bucket=bucket)


def store_snapshot(review_id: str, snapshot_dict: dict) -> str:
    """Stores the raw snapshot as JSON, returns the object key."""
    ensure_bucket_exists()
    key = f"reviews/{review_id}/{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}.json"
    _client().put_object(
        Bucket=_bucket(),
        Key=key,
        Body=json.dumps(snapshot_dict, default=str).encode("utf-8"),
        ContentType="application/json",
    )
    return key


def load_snapshot(object_key: str) -> dict:
    resp = _client().get_object(Bucket=_bucket(), Key=object_key)
    return json.loads(resp["Body"].read())
