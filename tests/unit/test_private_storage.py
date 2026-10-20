"""Private storage (ADR 0010). No database; the local backend uses a temp dir."""

from __future__ import annotations

import hashlib
import io

import pytest

from app.services.private_storage import (
    LocalBackend,
    PrivateStorage,
    S3Backend,
    is_private_uri,
)


@pytest.fixture
def storage(tmp_path):
    return PrivateStorage(LocalBackend(str(tmp_path)))


def test_round_trip_with_a_random_key_that_hides_the_file_name(storage, tmp_path):
    stored = storage.save(
        b"protocol",
        kind="knowledge",
        owner="AVATAR-1",
        filename="Patient Smith notes.PDF",
    )

    assert is_private_uri(stored.uri)
    assert stored.uri.startswith("private://knowledge/avatar-1/")
    assert stored.uri.endswith(".pdf")
    assert "smith" not in stored.uri.lower()
    assert stored.size == 8
    assert stored.checksum_sha256 == hashlib.sha256(b"protocol").hexdigest()
    assert storage.read(stored.uri) == b"protocol"
    assert (
        storage.presigned_url(stored.uri) is None
    )  # local files need an authenticated endpoint

    storage.delete(stored.uri)
    assert list(tmp_path.rglob("*.pdf")) == []


def test_files_are_kept_outside_the_public_mounts(storage, tmp_path):
    stored = storage.save(b"x", kind="headshot", owner="u1", filename="me.jpg")
    key = stored.uri.removeprefix("private://")
    assert (tmp_path / key).exists()


@pytest.mark.parametrize(
    "uri",
    [
        "/uploads/avatar_1/file.pdf",
        "private://knowledge/../../etc/passwd",
        "private://knowledge/avatar-1/../../secret",
        "private://knowledge/avatar-1/notes.pdf",
        "private://KNOWLEDGE/avatar-1/" + "a" * 32,
        "private://knowledge/" + "a" * 32,
    ],
)
def test_rejects_legacy_and_malformed_uris(storage, uri):
    with pytest.raises(ValueError):
        storage.read(uri)


@pytest.mark.parametrize(
    "kind,owner", [("../x", "a"), ("k", "a/b"), ("", "a"), ("k", "")]
)
def test_rejects_unsafe_kind_or_owner(storage, kind, owner):
    with pytest.raises(ValueError):
        storage.save(b"x", kind=kind, owner=owner)


def test_unusual_extensions_are_dropped(storage):
    stored = storage.save(b"x", kind="knowledge", owner="a", filename="evil.p h p")
    assert stored.uri.rsplit("/", 1)[1].isalnum()


def test_delete_quietly_ignores_legacy_paths_and_missing_files(storage):
    storage.delete_quietly(None)
    storage.delete_quietly("/uploads/avatar_1/file.pdf")
    storage.delete_quietly(
        "private://knowledge/a/" + "b" * 32 + ".pdf"
    )  # missing: no error


class _FakeS3:
    def __init__(self):
        self.objects = {}
        self.put_kwargs = None

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.objects[(Bucket, Key)] = Body
        self.put_kwargs = kwargs

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def delete_object(self, Bucket, Key):
        self.objects.pop((Bucket, Key), None)

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"https://signed/{Params['Key']}?expires={ExpiresIn}"


def test_s3_backend_encrypts_and_presigns_short_lived_urls():
    s3 = _FakeS3()
    storage = PrivateStorage(S3Backend("private-bucket", client=s3))

    stored = storage.save(
        b"voice",
        kind="voice_sample",
        owner="u1",
        filename="a.wav",
        content_type="audio/wav",
    )

    assert s3.put_kwargs == {
        "ServerSideEncryption": "AES256",
        "ContentType": "audio/wav",
    }
    assert storage.read(stored.uri) == b"voice"
    assert storage.presigned_url(stored.uri, expires_s=120).endswith("expires=120")
    storage.delete(stored.uri)
    assert s3.objects == {}
