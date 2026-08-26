from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
from typing import Any, Callable
from urllib.parse import quote, urlparse

import httpx

from backend.config import Settings, get_settings


SAFE_OBJECT_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SUPABASE_REFERENCE_SCHEME = "supabase"
HttpClientFactory = Callable[[float], Any]


class MediaStorageProviderError(RuntimeError):
    def __init__(self, reason: str, message: str, *, retryable: bool = False, status_code: int | None = None):
        self.reason = reason
        self.retryable = retryable
        self.status_code = status_code
        super().__init__(message)


class MediaStorageObjectMissingError(MediaStorageProviderError):
    pass


class MediaStorageObjectTooLargeError(MediaStorageProviderError):
    pass


@dataclass(frozen=True)
class StoredMediaArtifact:
    storage_backend: str
    reference: str
    object_key: str | None
    file_size_bytes: int


@dataclass(frozen=True)
class RetrievedMediaArtifact:
    storage_backend: str
    local_path: Path | None = None
    content: bytes | None = None


def _default_http_client_factory(timeout_seconds: float) -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 5.0)))


def validate_supabase_storage_configuration(settings: Settings) -> None:
    base_url = str(settings.supabase_url or "").strip().rstrip("/")
    service_key = str(settings.supabase_service_role_key or "").strip()
    bucket = str(settings.supabase_media_bucket or "").strip()
    parsed = urlparse(base_url)
    if not base_url or not service_key or not bucket:
        raise MediaStorageProviderError("supabase_storage_configuration_incomplete", "Supabase media storage configuration is incomplete.")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise MediaStorageProviderError("invalid_supabase_storage_url", "Supabase media storage URL is invalid.")
    if settings.deployed_mode and parsed.scheme != "https":
        raise MediaStorageProviderError("insecure_supabase_storage_url", "Supabase media storage requires HTTPS in deployed environments.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", bucket):
        raise MediaStorageProviderError("invalid_supabase_media_bucket", "Supabase media bucket name is invalid.")


def _headers(settings: Settings, *, content_type: str | None = None) -> dict[str, str]:
    service_key = str(settings.supabase_service_role_key or "").strip()
    headers = {"Authorization": f"Bearer {service_key}", "apikey": service_key}
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _response_error(response: httpx.Response, *, missing_reason: str = "storage_object_missing") -> MediaStorageProviderError:
    status_code = int(response.status_code)
    provider_status_code = None
    try:
        payload = response.json()
        if isinstance(payload, dict):
            provider_status_code = int(payload.get("statusCode")) if payload.get("statusCode") is not None else None
    except (TypeError, ValueError):
        provider_status_code = None
    if status_code == 404 or provider_status_code == 404:
        return MediaStorageObjectMissingError(missing_reason, "The requested media object was not found.", status_code=404)
    if status_code in {401, 403}:
        return MediaStorageProviderError("storage_authentication_failed", "Media storage authentication failed.", status_code=status_code)
    if status_code == 413:
        return MediaStorageObjectTooLargeError("storage_object_too_large", "The media object exceeds the configured size limit.", status_code=413)
    return MediaStorageProviderError(
        "storage_provider_unavailable",
        "Media storage is temporarily unavailable.",
        retryable=status_code == 429 or status_code >= 500,
        status_code=status_code,
    )


def inspect_private_supabase_bucket(
    settings: Settings,
    *,
    http_client_factory: HttpClientFactory | None = None,
) -> dict[str, Any]:
    try:
        validate_supabase_storage_configuration(settings)
    except MediaStorageProviderError as exc:
        return {"ready": False, "reason": exc.reason, "error_type": type(exc).__name__}
    bucket = str(settings.supabase_media_bucket).strip()
    url = f"{str(settings.supabase_url).rstrip('/')}/storage/v1/bucket/{quote(bucket, safe='')}"
    try:
        with (http_client_factory or _default_http_client_factory)(settings.effective_media_storage_request_timeout_seconds) as client:
            response = client.get(url, headers=_headers(settings))
    except httpx.TimeoutException:
        return {"ready": False, "reason": "storage_provider_timeout", "error_type": "StorageTimeout"}
    except httpx.HTTPError:
        return {"ready": False, "reason": "storage_provider_unavailable", "error_type": "StorageProviderError"}
    if not response.is_success:
        error = _response_error(response, missing_reason="storage_bucket_missing")
        return {"ready": False, "reason": error.reason, "error_type": type(error).__name__}
    try:
        payload = response.json()
    except ValueError:
        return {"ready": False, "reason": "storage_provider_invalid_response", "error_type": "StorageProviderError"}
    if not isinstance(payload, dict) or payload.get("public") is not False:
        return {"ready": False, "reason": "storage_bucket_not_private", "error_type": "StorageSecurityError"}
    return {"ready": True, "reason": None, "error_type": None}


def _safe_segment(value: Any, fallback: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-.")
    return normalized[:100] or fallback


def validate_media_object_key(object_key: str) -> str:
    candidate = str(object_key or "").strip().strip("/")
    parts = candidate.split("/") if candidate else []
    if not parts or len(candidate) > 900 or any(part in {"", ".", ".."} or not SAFE_OBJECT_SEGMENT_PATTERN.fullmatch(part) for part in parts):
        raise ValueError("Media storage object key is invalid.")
    return "/".join(parts)


def media_object_key_for_job(job: Any, filename: str, settings: Settings | None = None) -> str:
    active_settings = settings or get_settings()
    return validate_media_object_key(
        "/".join(
            (
                _safe_segment(active_settings.environment_name, "environment"),
                "users",
                _safe_segment(getattr(job, "user_id", None), "system"),
                "jobs",
                _safe_segment(getattr(job, "id", None), "unassigned"),
                _safe_segment(filename, "artifact.zip"),
            )
        )
    )


def supabase_media_reference(bucket: str, object_key: str) -> str:
    safe_bucket = str(bucket or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", safe_bucket):
        raise ValueError("Supabase media bucket name is invalid.")
    return f"{SUPABASE_REFERENCE_SCHEME}://{safe_bucket}/{validate_media_object_key(object_key)}"


def is_supabase_media_reference(reference: str | None) -> bool:
    return str(reference or "").strip().lower().startswith(f"{SUPABASE_REFERENCE_SCHEME}://")


def parse_supabase_media_reference(reference: str, settings: Settings | None = None) -> str:
    active_settings = settings or get_settings()
    parsed = urlparse(str(reference or "").strip())
    if (
        parsed.scheme != SUPABASE_REFERENCE_SCHEME
        or parsed.netloc != str(active_settings.supabase_media_bucket or "").strip()
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Supabase media reference is invalid for the configured bucket.")
    return validate_media_object_key(parsed.path.lstrip("/"))


def _assert_working_file(local_path: Path, settings: Settings) -> Path:
    root = settings.effective_media_render_output_dir.resolve()
    resolved = local_path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("Media artifact must remain inside the configured working root.") from exc
    if not resolved.is_file():
        raise ValueError("Media artifact file does not exist.")
    return resolved


def persist_media_artifact(
    job: Any,
    local_path: Path,
    *,
    content_type: str,
    settings: Settings | None = None,
    http_client_factory: HttpClientFactory | None = None,
) -> StoredMediaArtifact:
    active_settings = settings or get_settings()
    resolved = _assert_working_file(local_path, active_settings)
    file_size = resolved.stat().st_size
    if file_size > active_settings.effective_media_storage_max_object_bytes:
        raise MediaStorageObjectTooLargeError("storage_object_too_large", "The generated media artifact exceeds the configured storage limit.")
    if active_settings.effective_media_storage_backend == "local":
        from backend.services.media_storage_service import relative_media_render_storage_path

        return StoredMediaArtifact("local", relative_media_render_storage_path(resolved, active_settings), None, file_size)
    validate_supabase_storage_configuration(active_settings)
    object_key = media_object_key_for_job(job, resolved.name, active_settings)
    bucket = str(active_settings.supabase_media_bucket).strip()
    url = f"{str(active_settings.supabase_url).rstrip('/')}/storage/v1/object/{quote(bucket, safe='')}/{quote(object_key, safe='/')}"
    headers = _headers(active_settings, content_type=content_type)
    headers.update({"x-upsert": "true", "Content-Length": str(file_size)})
    try:
        with (http_client_factory or _default_http_client_factory)(active_settings.effective_media_storage_request_timeout_seconds) as client:
            with resolved.open("rb") as artifact_file:
                response = client.post(url, headers=headers, content=artifact_file)
    except httpx.TimeoutException as exc:
        raise MediaStorageProviderError("storage_provider_timeout", "Media storage upload timed out.", retryable=True) from exc
    except httpx.HTTPError as exc:
        raise MediaStorageProviderError("storage_provider_unavailable", "Media storage upload failed.", retryable=True) from exc
    if not response.is_success:
        raise _response_error(response)
    return StoredMediaArtifact("supabase", supabase_media_reference(bucket, object_key), object_key, file_size)


def retrieve_media_artifact(
    reference: str | None,
    *,
    settings: Settings | None = None,
    http_client_factory: HttpClientFactory | None = None,
) -> RetrievedMediaArtifact:
    active_settings = settings or get_settings()
    if not is_supabase_media_reference(reference):
        from backend.services.media_storage_service import resolve_media_render_storage_path

        path = resolve_media_render_storage_path(reference, settings=active_settings, require_exists=True, require_file=True)
        if path is None:
            raise MediaStorageObjectMissingError("storage_object_missing", "The requested media object was not found.", status_code=404)
        return RetrievedMediaArtifact("local", local_path=path)
    object_key = parse_supabase_media_reference(str(reference), active_settings)
    bucket = str(active_settings.supabase_media_bucket).strip()
    url = f"{str(active_settings.supabase_url).rstrip('/')}/storage/v1/object/authenticated/{quote(bucket, safe='')}/{quote(object_key, safe='/')}"
    try:
        with (http_client_factory or _default_http_client_factory)(active_settings.effective_media_storage_request_timeout_seconds) as client:
            response = client.get(url, headers=_headers(active_settings))
    except httpx.TimeoutException as exc:
        raise MediaStorageProviderError("storage_provider_timeout", "Media storage download timed out.", retryable=True) from exc
    except httpx.HTTPError as exc:
        raise MediaStorageProviderError("storage_provider_unavailable", "Media storage download failed.", retryable=True) from exc
    if not response.is_success:
        raise _response_error(response)
    content = bytes(response.content or b"")
    if len(content) > active_settings.effective_media_storage_max_object_bytes:
        raise MediaStorageObjectTooLargeError("storage_object_too_large", "Stored media exceeds the configured download limit.")
    return RetrievedMediaArtifact("supabase", content=content)


def delete_media_artifact(
    reference: str | None,
    *,
    settings: Settings | None = None,
    http_client_factory: HttpClientFactory | None = None,
) -> bool:
    active_settings = settings or get_settings()
    if not is_supabase_media_reference(reference):
        from backend.services.media_storage_service import resolve_media_render_storage_path

        path = resolve_media_render_storage_path(reference, settings=active_settings, require_exists=False, require_file=True)
        if path is None or not path.exists():
            return False
        path.unlink()
        return True
    object_key = parse_supabase_media_reference(str(reference), active_settings)
    bucket = str(active_settings.supabase_media_bucket).strip()
    url = f"{str(active_settings.supabase_url).rstrip('/')}/storage/v1/object/{quote(bucket, safe='')}"
    try:
        with (http_client_factory or _default_http_client_factory)(active_settings.effective_media_storage_request_timeout_seconds) as client:
            response = client.request("DELETE", url, headers=_headers(active_settings, content_type="application/json"), json={"prefixes": [object_key]})
    except httpx.TimeoutException as exc:
        raise MediaStorageProviderError("storage_provider_timeout", "Media storage cleanup timed out.", retryable=True) from exc
    except httpx.HTTPError as exc:
        raise MediaStorageProviderError("storage_provider_unavailable", "Media storage cleanup failed.", retryable=True) from exc
    if response.status_code == 404:
        return False
    if not response.is_success:
        raise _response_error(response)
    return True


def cleanup_media_working_directory(path: Path, settings: Settings | None = None) -> None:
    active_settings = settings or get_settings()
    if active_settings.effective_media_storage_backend != "supabase":
        return
    root = active_settings.effective_media_render_output_dir.resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("Media working directory cleanup target is outside the configured root.") from exc
    if resolved == root:
        raise ValueError("Media working root cannot be deleted by job cleanup.")
    if resolved.exists():
        shutil.rmtree(resolved)
