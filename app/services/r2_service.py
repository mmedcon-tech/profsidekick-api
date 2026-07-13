"""
Cloudflare R2 storage client using the S3-compatible API.

Object key convention for SAE submissions:
    sae/{student_code}/handwritten.pdf
    sae/{student_code}/webassign.pdf
    sae/{student_code}/handwritten_transcript.md
    sae/{student_code}/metadata.json
"""

import logging

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import settings

logger = logging.getLogger(__name__)


class R2StorageService:
    """Cloudflare R2 via the S3-compatible API."""

    def __init__(self):
        self.enabled = bool(
            settings.r2_account_id
            and settings.r2_access_key_id
            and settings.r2_secret_access_key
            and settings.r2_bucket_name
        )
        if not self.enabled:
            logger.info("R2 storage not configured — SAE files will use local disk.")
            return

        self.client = boto3.client(
            "s3",
            endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
            config=Config(signature_version="s3v4"),
        )
        self.bucket = settings.r2_bucket_name
        logger.info("R2 storage initialised (bucket=%s)", self.bucket)

    def upload(self, key: str, data: bytes, content_type: str = "application/pdf") -> None:
        """Upload bytes under the given object key."""
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        except ClientError as exc:
            raise RuntimeError(f"R2 upload failed for key '{key}': {exc}") from exc

    def download(self, key: str) -> bytes:
        """Download an object and return its raw bytes."""
        try:
            resp = self.client.get_object(Bucket=self.bucket, Key=key)
            return resp["Body"].read()
        except ClientError as exc:
            raise RuntimeError(f"R2 download failed for key '{key}': {exc}") from exc

    def presigned_get_url(self, key: str, expires: int = 600) -> str:
        """Return a presigned GET URL (default 10 min)."""
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires,
            )
        except ClientError as exc:
            raise RuntimeError(f"R2 presign failed for key '{key}': {exc}") from exc


r2 = R2StorageService()
