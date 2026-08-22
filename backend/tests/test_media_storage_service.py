from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest


from backend.config import Settings
from backend.models import MediaRenderJob
from backend.services import media_storage_service
from backend.services.media_render_ops_service import build_media_render_pipeline_snapshot
from backend.services.media_storage_service import (
    MediaStorageInitializationError,
    get_media_render_storage_availability,
    initialize_media_render_storage,
    relative_media_render_storage_path,
)
from backend.services.tts_service import build_media_render_output_directory


def _settings(root: Path | str) -> Settings:
    return Settings(media_render_output_dir=str(root), media_render_worker_mode="embedded")


def test_missing_media_root_is_initialized_without_readiness_side_effects(tmp_path: Path) -> None:
    root = tmp_path / "clean-checkout" / "generated_media" / "renders"
    settings = _settings(root)

    before = get_media_render_storage_availability(settings, create=False)

    assert before["ready"] is False
    assert before["reason"] == "storage_parent_missing"
    assert before["root_exists"] is False
    assert root.exists() is False
    readiness = build_media_render_pipeline_snapshot(settings=settings, worker_snapshot={"ready": True})
    assert readiness["storage_ready"] is False
    assert readiness["storage_reason"] == "storage_parent_missing"
    assert root.exists() is False

    initialized_root = initialize_media_render_storage(settings)

    assert initialized_root == root.resolve()
    assert root.is_dir()
    assert get_media_render_storage_availability(settings, create=False)["ready"] is True


def test_existing_media_root_initialization_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "existing-renders"
    root.mkdir()
    settings = _settings(root)

    assert initialize_media_render_storage(settings) == root.resolve()
    assert initialize_media_render_storage(settings) == root.resolve()
    assert list(root.iterdir()) == []


def test_nested_job_output_stays_under_configured_media_root(tmp_path: Path) -> None:
    root = tmp_path / "nested" / "generated_media" / "renders"
    settings = _settings(root)
    job = MediaRenderJob(
        id=17,
        topic="../../Outside Attempt",
        lesson_mode="video_lecture",
        render_type="slide_video",
        created_at=datetime(2026, 8, 21, 12, 0, tzinfo=UTC),
    )

    output_directory = build_media_render_output_directory(job, settings)
    output_directory.mkdir(parents=True, exist_ok=True)

    assert output_directory.is_dir()
    assert relative_media_render_storage_path(output_directory, settings).startswith("2026/08/21/job-17-")
    assert ".." not in output_directory.relative_to(root).parts
    with pytest.raises(ValueError, match="outside the active storage root"):
        relative_media_render_storage_path(root.parent / "outside.zip", settings)


def test_concurrent_media_storage_initialization_is_safe_and_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "concurrent" / "generated_media" / "renders"
    settings = _settings(root)

    with ThreadPoolExecutor(max_workers=12) as executor:
        initialized_roots = list(executor.map(lambda _: initialize_media_render_storage(settings), range(36)))

    assert initialized_roots == [initialized_roots[0]] * 36
    assert initialized_roots[0].samefile(root)
    assert root.is_dir()
    assert list(root.glob(".adhyantra-storage-check-*")) == []


def test_invalid_and_unwritable_media_storage_report_clear_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_root = tmp_path / "not-a-directory"
    invalid_root.write_text("blocked", encoding="utf-8")

    with pytest.raises(MediaStorageInitializationError) as invalid_error:
        initialize_media_render_storage(_settings(invalid_root))
    assert invalid_error.value.reason == "storage_root_not_directory"
    assert "NotADirectoryError" in str(invalid_error.value)

    writable_root = tmp_path / "permission-check"
    writable_root.mkdir()

    def deny_probe(*args, **kwargs):
        raise PermissionError("write denied")

    monkeypatch.setattr(media_storage_service.tempfile, "NamedTemporaryFile", deny_probe)
    with pytest.raises(MediaStorageInitializationError) as permission_error:
        initialize_media_render_storage(_settings(writable_root))
    assert permission_error.value.reason == "storage_root_unwritable"
    assert "PermissionError" in str(permission_error.value)


def test_object_storage_uri_is_not_treated_as_local_path() -> None:
    settings = _settings("s3://example-bucket/adhyantra-renders")

    availability = get_media_render_storage_availability(settings, create=False)

    assert availability["ready"] is False
    assert availability["reason"] == "unsupported_storage_backend"
    assert availability["storage_backend"] == "s3"
    assert availability["root"] is None
    validation = settings.validate_runtime_config()
    assert "unsupported_media_storage_backend" in {issue.code for issue in validation.errors}
    with pytest.raises(MediaStorageInitializationError, match="local or mounted filesystem path"):
        initialize_media_render_storage(settings)
