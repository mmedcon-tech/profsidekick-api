"""
Private storage for personal and expert files (ADR 0010).

Files are stored under random keys and addressed as "private://<key>". They are
never served by the static mounts (/static, /uploads). Read them only from code
that has already checked ownership; hand them to a browser only through an
authenticated endpoint or a short-lived presigned URL.

Backend: a private S3 bucket when PRIVATE_S3_BUCKET_NAME is set, otherwise the
local directory PRIVATE_STORAGE_DIR.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

from app.config import settings

logger = logging.getLogger(__name__)

URI_PREFIX = "private://"
_SEGMENT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_EXTENSION = re.compile(r"^\.[a-z0-9]{1,10}$")
_NAME = re.compile(r"^[a-f0-9]{32}(\.[a-z0-9]{1,10})?$")


@dataclass(frozen=True)
class StoredFile:
    uri: str
    checksum_sha256: str
    size: int


class _Backend(Protocol):
    def put(self, key: str, content: bytes, content_type: Optional[str]) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def presigned_url(self, key: str, expires_s: int) -> Optional[str]: ...


class LocalBackend:
    def __init__(self, root: str):
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError("Storage key escapes the storage root")
        return path

    def put(self, key: str, content: bytes, content_type: Optional[str]) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def presigned_url(self, key: str, expires_s: int) -> Optional[str]:
        return None  # Local files are served only through authenticated endpoints.


class S3Backend:
    def __init__(self, bucket: str, client=None):
        if client is None:
            import boto3

            client = boto3.client(
                "s3",
                aws_access_key_id=settings.aws_access_key_id or None,
                aws_secret_access_key=settings.aws_secret_access_key or None,
                region_name=settings.aws_region,
            )
        self.bucket = bucket
        self.client = client

    def put(self, key: str, content: bytes, content_type: Optional[str]) -> None:
        extra = {"ServerSideEncryption": "AES256"}
        if content_type:
            extra["ContentType"] = content_type
        self.client.put_object(Bucket=self.bucket, Key=key, Body=content, **extra)

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def presigned_url(self, key: str, expires_s: int) -> Optional[str]:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_s,
        )


def is_private_uri(value: Optional[str]) -> bool:
    return bool(value) and value.startswith(URI_PREFIX)


def _key_from_uri(uri: str) -> str:
    if not is_private_uri(uri):
        raise ValueError("Not a private storage URI")
    key = uri[len(URI_PREFIX) :]
    parts = key.split("/")
    if (
        len(parts) != 3
        or not all(_SEGMENT.match(p) for p in parts[:2])
        or not _NAME.match(parts[2])
    ):
        raise ValueError("Malformed private storage URI")
    return key


class PrivateStorage:
    def __init__(self, backend: _Backend):
        self.backend = backend

    def save(
        self,
        content: bytes,
        *,
        kind: str,
        owner: str,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> StoredFile:
        """
        Store bytes under private://<kind>/<owner>/<random><ext>. The original
        file name is not part of the key; keep it in the database if needed.
        """
        kind, owner = kind.lower(), str(owner).lower()
        if not _SEGMENT.match(kind) or not _SEGMENT.match(owner):
            raise ValueError("kind and owner must be short lowercase identifiers")
        ext = Path(filename or "").suffix.lower()
        if not _EXTENSION.match(ext):
            ext = ""
        key = f"{kind}/{owner}/{uuid.uuid4().hex}{ext}"
        self.backend.put(key, content, content_type)
        return StoredFile(
            uri=URI_PREFIX + key,
            checksum_sha256=hashlib.sha256(content).hexdigest(),
            size=len(content),
        )

    def read(self, uri: str) -> bytes:
        return self.backend.get(_key_from_uri(uri))

    def delete(self, uri: str) -> None:
        self.backend.delete(_key_from_uri(uri))

    def delete_quietly(self, uri: Optional[str]) -> None:
        """Best-effort delete for cleanup paths; logs instead of raising."""
        if not is_private_uri(uri):
            return
        try:
            self.delete(uri)
        except (
            Exception
        ) as exc:  # noqa: BLE001 - cleanup must not mask the original outcome
            logger.warning("private storage: could not delete %s: %s", uri, exc)

    def presigned_url(self, uri: str, expires_s: int = 300) -> Optional[str]:
        return self.backend.presigned_url(_key_from_uri(uri), expires_s)


_storage: Optional[PrivateStorage] = None


def get_private_storage() -> PrivateStorage:
    global _storage
    if _storage is None:
        if settings.private_s3_bucket_name:
            backend: _Backend = S3Backend(settings.private_s3_bucket_name)
        else:
            backend = LocalBackend(settings.private_storage_dir)
        _storage = PrivateStorage(backend)
    return _storage
