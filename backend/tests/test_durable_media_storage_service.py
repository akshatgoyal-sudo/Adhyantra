from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from backend.config import Settings
from backend.services.durable_media_storage_service import (
    MediaStorageObjectTooLargeError,
    MediaStorageProviderError,
    cleanup_media_working_directory,
    delete_media_artifact,
    inspect_private_supabase_bucket,
    media_object_key_for_job,
    parse_supabase_media_reference,
    persist_media_artifact,
    retrieve_media_artifact,
)


SECRET = "service-role-test-secret"


def _settings(root: Path, **overrides) -> Settings:
    values = {
        "app_env": "production",
        "db_url": "postgresql://example.invalid/app",
        "media_storage_backend": "supabase",
        "media_render_output_dir": str(root),
        "supabase_url": "https://project.invalid",
        "supabase_service_role_key": SECRET,
        "supabase_media_bucket": "private-media",
        "media_storage_max_object_bytes": 49_000_000,
    }
    values.update(overrides)
    return Settings(**values)


def _factory(handler):
    def create(timeout):
        return httpx.Client(transport=httpx.MockTransport(handler), timeout=timeout)
    return create


def test_private_bucket_readiness_is_read_only_and_rejects_public_bucket(tmp_path):
    methods = []
    def handler(request):
        methods.append(request.method)
        assert request.headers["authorization"] == f"Bearer {SECRET}"
        return httpx.Response(200, json={"public": False})
    result = inspect_private_supabase_bucket(_settings(tmp_path), http_client_factory=_factory(handler))
    assert result == {"ready": True, "reason": None, "error_type": None}
    assert methods == ["GET"]

    public = inspect_private_supabase_bucket(
        _settings(tmp_path),
        http_client_factory=_factory(lambda request: httpx.Response(200, json={"public": True})),
    )
    assert public["reason"] == "storage_bucket_not_private"


def test_upload_retrieve_delete_and_idempotent_job_key(tmp_path):
    root = tmp_path / "work"
    bundle_dir = root / "job"
    bundle_dir.mkdir(parents=True)
    artifact = bundle_dir / "lesson.zip"
    artifact.write_bytes(b"zip-data")
    requests = []
    def handler(request):
        requests.append((request.method, request.url.path, request.headers.get("x-upsert")))
        if request.method == "GET":
            return httpx.Response(200, content=b"zip-data")
        return httpx.Response(200, json={})
    settings = _settings(root)
    job = SimpleNamespace(id=42, user_id=7)
    first = persist_media_artifact(job, artifact, content_type="application/zip", settings=settings, http_client_factory=_factory(handler))
    second = persist_media_artifact(job, artifact, content_type="application/zip", settings=settings, http_client_factory=_factory(handler))
    assert first.reference == second.reference
    assert first.object_key == "production/users/7/jobs/42/lesson.zip"
    assert requests[:2] == [
        ("POST", "/storage/v1/object/private-media/production/users/7/jobs/42/lesson.zip", "true"),
        ("POST", "/storage/v1/object/private-media/production/users/7/jobs/42/lesson.zip", "true"),
    ]
    retrieved = retrieve_media_artifact(first.reference, settings=settings, http_client_factory=_factory(handler))
    assert retrieved.content == b"zip-data"
    assert delete_media_artifact(first.reference, settings=settings, http_client_factory=_factory(handler)) is True


def test_keys_reject_traversal_cross_bucket_and_paths_outside_work_root(tmp_path):
    settings = _settings(tmp_path / "work")
    key = media_object_key_for_job(SimpleNamespace(id="../42", user_id="../7"), "../../lesson.zip", settings)
    assert ".." not in key
    with pytest.raises(ValueError):
        parse_supabase_media_reference("supabase://other/production/users/7/jobs/42/lesson.zip", settings)
    outside = tmp_path / "outside.zip"
    outside.write_bytes(b"x")
    with pytest.raises(ValueError):
        persist_media_artifact(SimpleNamespace(id=1, user_id=1), outside, content_type="application/zip", settings=settings)


def test_oversize_and_timeout_are_sanitized_and_cleanup_temp_files(tmp_path):
    root = tmp_path / "work"
    bundle_dir = root / "job"
    bundle_dir.mkdir(parents=True)
    artifact = bundle_dir / "audio.zip"
    artifact.write_bytes(b"12345")
    settings = _settings(root, media_storage_max_object_bytes=4)
    with pytest.raises(MediaStorageObjectTooLargeError):
        persist_media_artifact(SimpleNamespace(id=1, user_id=1), artifact, content_type="application/zip", settings=settings)

    settings = _settings(root)
    def timeout(request):
        raise httpx.ReadTimeout("unsafe provider details", request=request)
    with pytest.raises(MediaStorageProviderError) as captured:
        persist_media_artifact(SimpleNamespace(id=1, user_id=1), artifact, content_type="application/zip", settings=settings, http_client_factory=_factory(timeout))
    assert captured.value.reason == "storage_provider_timeout"
    assert SECRET not in str(captured.value)
    assert "project.invalid" not in str(captured.value)
    cleanup_media_working_directory(bundle_dir, settings)
    assert not bundle_dir.exists()


def test_local_backend_preserves_relative_reference_and_files(tmp_path):
    root = tmp_path / "media"
    bundle_dir = root / "job"
    bundle_dir.mkdir(parents=True)
    artifact = bundle_dir / "audio.zip"
    artifact.write_bytes(b"audio")
    settings = Settings(media_storage_backend="local", media_render_output_dir=str(root))
    stored = persist_media_artifact(SimpleNamespace(id=1, user_id=1), artifact, content_type="application/zip", settings=settings)
    assert stored.reference == "job/audio.zip"
    assert retrieve_media_artifact(stored.reference, settings=settings).local_path == artifact.resolve()
    cleanup_media_working_directory(bundle_dir, settings)
    assert artifact.exists()
