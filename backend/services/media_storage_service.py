from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile
from typing import Any

from backend.config import DEFAULT_MEDIA_RENDER_OUTPUT_DIR, PROJECT_ROOT, Settings, get_settings


LEGACY_MEDIA_RENDER_OUTPUT_DIR = (PROJECT_ROOT / "backend" / "media_render_output").resolve()
MEDIA_STORAGE_URI_PATTERN = re.compile(r"^(?P<scheme>[a-z][a-z0-9+.-]*)://", re.IGNORECASE)


class MediaStorageInitializationError(RuntimeError):
    def __init__(self, reason: str, message: str, *, error_type: str | None = None):
        self.reason = reason
        self.error_type = error_type
        super().__init__(message)


def _configured_media_storage_scheme(settings: Settings) -> str | None:
    candidate = str(settings.media_render_output_dir or "").strip()
    match = MEDIA_STORAGE_URI_PATTERN.match(candidate)
    return str(match.group("scheme")).lower() if match else None


def media_render_storage_uses_local_filesystem(settings: Settings | None = None) -> bool:
    active_settings = settings or get_settings()
    return _configured_media_storage_scheme(active_settings) is None


def _normalize_local_path(path: Path) -> Path:
    normalized = str(path)
    if normalized.startswith("\\\\?\\UNC\\"):
        normalized = f"\\\\{normalized[8:]}"
    elif normalized.startswith("\\\\?\\"):
        normalized = normalized[4:]
    return Path(normalized)


def _local_media_render_storage_root(settings: Settings) -> Path:
    scheme = _configured_media_storage_scheme(settings)
    if scheme is not None:
        raise MediaStorageInitializationError(
            "unsupported_storage_backend",
            (
                f"MEDIA_RENDER_OUTPUT_DIR uses the unsupported '{scheme}' URI scheme. "
                "Adhyantra currently requires a local or mounted filesystem path."
            ),
            error_type="UnsupportedStorageBackend",
        )
    return _normalize_local_path(settings.effective_media_render_output_dir.resolve())


def initialize_media_render_storage(settings: Settings | None = None) -> Path:
    active_settings = settings or get_settings()
    root = _local_media_render_storage_root(active_settings)
    try:
        if root.exists() and not root.is_dir():
            raise NotADirectoryError(f"Configured media storage root is not a directory: {root.as_posix()}")
        root.mkdir(parents=True, exist_ok=True)
        if not root.is_dir():
            raise NotADirectoryError(f"Configured media storage root is not a directory: {root.as_posix()}")
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".adhyantra-storage-check-",
            dir=root,
            delete=True,
        ) as probe:
            probe.write(b"ready")
            probe.flush()
    except OSError as exc:
        reason = (
            "storage_root_not_directory"
            if (root.exists() and not root.is_dir()) or isinstance(exc, NotADirectoryError)
            else "storage_root_unwritable"
        )
        raise MediaStorageInitializationError(
            reason,
            f"Unable to initialize writable media storage at {root.as_posix()}: {type(exc).__name__}.",
            error_type=type(exc).__name__,
        ) from exc
    return root


def get_media_render_storage_root(settings: Settings | None = None, *, create: bool = False) -> Path:
    active_settings = settings or get_settings()
    if create:
        return initialize_media_render_storage(active_settings)
    return _local_media_render_storage_root(active_settings)


def get_media_render_storage_availability(
    settings: Settings | None = None,
    *,
    create: bool = False,
) -> dict[str, Any]:
    active_settings = settings or get_settings()
    scheme = _configured_media_storage_scheme(active_settings)
    if scheme is not None:
        return {
            "ready": False,
            "reason": "unsupported_storage_backend",
            "root": None,
            "parent": None,
            "root_exists": False,
            "root_is_directory": False,
            "parent_exists": False,
            "parent_is_directory": False,
            "error_type": "UnsupportedStorageBackend",
            "storage_backend": scheme,
        }

    root = _local_media_render_storage_root(active_settings)
    parent = root.parent

    try:
        if create:
            initialize_media_render_storage(active_settings)
    except MediaStorageInitializationError as exc:
        return {
            "ready": False,
            "reason": exc.reason,
            "root": root,
            "parent": parent,
            "root_exists": root.exists(),
            "root_is_directory": root.is_dir() if root.exists() else False,
            "parent_exists": parent.exists(),
            "parent_is_directory": parent.is_dir() if parent.exists() else False,
            "error_type": exc.error_type or type(exc).__name__,
            "storage_backend": "filesystem",
        }

    root_exists = root.exists()
    root_is_directory = root.is_dir() if root_exists else False
    parent_exists = parent.exists()
    parent_is_directory = parent.is_dir() if parent_exists else False

    if root_exists and not root_is_directory:
        reason = "storage_root_not_directory"
        ready = False
    elif root_exists and not os.access(root, os.R_OK | os.W_OK):
        reason = "storage_root_unwritable"
        ready = False
    elif not root_exists and not parent_exists:
        reason = "storage_parent_missing"
        ready = False
    elif not root_exists and parent_exists and not parent_is_directory:
        reason = "storage_parent_not_directory"
        ready = False
    elif not root_exists:
        reason = "storage_root_missing"
        ready = False
    else:
        reason = None
        ready = True

    return {
        "ready": ready,
        "reason": reason,
        "root": root,
        "parent": parent,
        "root_exists": root_exists,
        "root_is_directory": root_is_directory,
        "parent_exists": parent_exists,
        "parent_is_directory": parent_is_directory,
        "error_type": None,
        "storage_backend": "filesystem",
    }


def media_render_output_dir_is_relative_to_project(settings: Settings | None = None) -> bool:
    if not media_render_storage_uses_local_filesystem(settings):
        return False
    root = get_media_render_storage_root(settings)
    try:
        root.relative_to(_normalize_local_path(PROJECT_ROOT.resolve()))
        return True
    except ValueError:
        return False


def _allowed_media_render_roots(settings: Settings | None = None) -> tuple[Path, ...]:
    active_root = get_media_render_storage_root(settings)
    roots = [active_root]
    if LEGACY_MEDIA_RENDER_OUTPUT_DIR != active_root:
        roots.append(LEGACY_MEDIA_RENDER_OUTPUT_DIR)
    return tuple(roots)


def _path_under_allowed_root(path: Path, allowed_roots: tuple[Path, ...]) -> bool:
    resolved = _normalize_local_path(path.resolve())
    for root in allowed_roots:
        try:
            resolved.relative_to(_normalize_local_path(root.resolve()))
            return True
        except ValueError:
            continue
    return False


def relative_media_render_storage_path(path: Path, settings: Settings | None = None) -> str:
    resolved = _normalize_local_path(path.resolve())
    active_root = get_media_render_storage_root(settings)
    try:
        return resolved.relative_to(active_root).as_posix()
    except ValueError as exc:
        raise ValueError(f"Media render asset path {resolved.as_posix()} is outside the active storage root.") from exc


def package_relative_media_render_path(path: Path, package_root: Path) -> str:
    resolved = _normalize_local_path(path.resolve())
    root = _normalize_local_path(package_root.resolve())
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"Package asset path {resolved.as_posix()} is outside its package root.") from exc


def resolve_media_render_storage_path(
    candidate: str | Path | None,
    *,
    settings: Settings | None = None,
    require_exists: bool = True,
    require_file: bool = True,
) -> Path | None:
    raw_text = str(candidate or "").strip()
    if not raw_text:
        return None

    if not media_render_storage_uses_local_filesystem(settings):
        return None

    raw_path = Path(raw_text)
    allowed_roots = _allowed_media_render_roots(settings)
    active_root = get_media_render_storage_root(settings)
    candidate_paths: list[Path] = []

    if raw_path.is_absolute():
        candidate_paths.append(_normalize_local_path(raw_path.resolve()))
    else:
        project_relative_path = _normalize_local_path((PROJECT_ROOT / raw_path).resolve())
        if _path_under_allowed_root(project_relative_path, allowed_roots):
            candidate_paths.append(project_relative_path)

        active_root_relative_path = _normalize_local_path((active_root / raw_path).resolve())
        if active_root_relative_path not in candidate_paths:
            candidate_paths.append(active_root_relative_path)

    seen: set[Path] = set()
    for path in candidate_paths:
        if path in seen:
            continue
        seen.add(path)
        if not _path_under_allowed_root(path, allowed_roots):
            continue
        if require_exists and not path.exists():
            continue
        if require_exists and require_file and not path.is_file():
            continue
        if require_exists and not require_file and not path.is_dir():
            continue
        return path

    return None
