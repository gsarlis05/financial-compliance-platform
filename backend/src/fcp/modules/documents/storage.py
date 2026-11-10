"""Object storage for documents through the S3 API (SeaweedFS locally, AWS S3 when deployed).

Keys are ``tenants/<tenant id>/documents/<document id>``; reads refuse keys outside the caller's
tenant prefix, as a second line behind row-level security. When ``DOCUMENTS_KMS_KEY_ID`` is set
(always when deployed), objects are written with SSE-KMS and an encryption context naming the
tenant, so a key can only be decrypted for the tenant it was written for (ADR-0016).
"""

import base64
import json
from functools import cache
from typing import TYPE_CHECKING, Any
from uuid import UUID

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

from fcp.core.errors import DomainError

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


class StorageUnavailableError(DomainError):
    code = "documents.storage_unavailable"
    status = 503
    title = "Document storage is unavailable"


def tenant_prefix(tenant_id: UUID) -> str:
    return f"tenants/{tenant_id}/"


def document_key(tenant_id: UUID, document_id: UUID) -> str:
    return f"{tenant_prefix(tenant_id)}documents/{document_id}"


@cache
def _client() -> "S3Client":
    options: dict[str, Any] = {
        "region_name": settings.S3_REGION,
        "config": Config(
            signature_version="s3v4",
            retries={"max_attempts": 3},
            s3={"addressing_style": "path" if settings.S3_ENDPOINT else "auto"},
        ),
    }
    if settings.S3_ENDPOINT:
        options["endpoint_url"] = settings.S3_ENDPOINT
    if settings.S3_ACCESS_KEY:
        options["aws_access_key_id"] = settings.S3_ACCESS_KEY
        options["aws_secret_access_key"] = settings.S3_SECRET_KEY
    return boto3.client("s3", **options)


def _context(tenant_id: UUID) -> str:
    return base64.b64encode(json.dumps({"tenant_id": str(tenant_id)}).encode()).decode()


def put(tenant_id: UUID, key: str, data: bytes, content_type: str) -> None:
    if not key.startswith(tenant_prefix(tenant_id)):
        raise ValueError("document key outside the tenant prefix")
    extra: dict[str, Any] = {}
    if settings.DOCUMENTS_KMS_KEY_ID:
        extra = {
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": settings.DOCUMENTS_KMS_KEY_ID,
            "SSEKMSEncryptionContext": _context(tenant_id),
        }
    try:
        _client().put_object(
            Bucket=settings.DOCUMENTS_BUCKET, Key=key, Body=data, ContentType=content_type, **extra
        )
    except (BotoCoreError, ClientError):
        raise StorageUnavailableError("The document could not be stored. Try again.") from None


def get(tenant_id: UUID, key: str) -> bytes:
    if not key.startswith(tenant_prefix(tenant_id)):
        raise ValueError("document key outside the tenant prefix")
    try:
        body = _client().get_object(Bucket=settings.DOCUMENTS_BUCKET, Key=key)["Body"]
        data: bytes = body.read()
    except (BotoCoreError, ClientError):
        raise StorageUnavailableError("The document could not be read. Try again.") from None
    return data


def delete_all(tenant_id: UUID) -> dict[str, int]:
    """Remove every object of a workspace (its purge, M5-6), all versions where the store keeps
    versions. An object under a retention lock cannot be removed before the lock ends; it is
    counted as retained and expires with the bucket's lifecycle rules."""
    client, bucket, prefix = _client(), settings.DOCUMENTS_BUCKET, tenant_prefix(tenant_id)
    result = {"deleted": 0, "retained": 0}
    try:
        try:
            pages = client.get_paginator("list_object_versions").paginate(
                Bucket=bucket, Prefix=prefix
            )
            found: list[tuple[str, str | None]] = []
            for page in pages:
                for version in page.get("Versions", []):
                    found.append((version["Key"], version.get("VersionId")))
                for marker in page.get("DeleteMarkers", []):
                    found.append((marker["Key"], marker.get("VersionId")))
        except ClientError:  # a store without versioning
            found = []
        if not found:
            listing = client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix)
            found = [(item["Key"], None) for page in listing for item in page.get("Contents", [])]
        for key, version_id in found:
            try:
                if version_id and version_id != "null":
                    client.delete_object(Bucket=bucket, Key=key, VersionId=version_id)
                else:
                    client.delete_object(Bucket=bucket, Key=key)
                result["deleted"] += 1
            except ClientError:
                result["retained"] += 1
    except BotoCoreError:
        raise StorageUnavailableError("The document storage could not be reached.") from None
    return result


def ensure_bucket() -> None:
    """Development and tests only: deployed buckets are created by infrastructure code."""
    client = _client()
    try:
        client.head_bucket(Bucket=settings.DOCUMENTS_BUCKET)
    except ClientError:
        client.create_bucket(Bucket=settings.DOCUMENTS_BUCKET)
