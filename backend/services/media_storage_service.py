from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.config import DEFAULT_MEDIA_RENDER_OUTPUT_DIR, PROJECT_ROOT, Settings, get_settings


LEGACY_MEDIA_RENDER_OUTPUT_DIR = (PROJECT_ROOT / "backend" / "media_render_output").resolve()


def get_media_render_storage_root(settings: Settings | None = None, *, create: bool = False) -> Path:
    active_settings = settings or get_settings()
    root = active_settings.effective_media_render_output_dir.resolve()
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def get_media_render_storage_availability(
    settings: Settings | None = None,
    *,
    create: bool = False,
) -> dict[str, Any]:
    active_settings = settings or get_settings()
    root = active_settings.effective_media_render_output_dir.resolve()
    parent = root.parent

    try:
        if create and not root.exists():
            root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {
            "ready": False,
            "reason": "storage_root_unwritable",
            "root": root,
            "parent": parent,
            "root_exists": root.exists(),
            "root_is_directory": root.is_dir() if root.exists() else False,
            "parent_exists": parent.exists(),
            "parent_is_directory": parent.is_dir() if parent.exists() else False,
            "error_type": type(exc).__name__,
        }

    root_exists = root.exists()
    root_is_directory = root.is_dir() if root_exists else False
    parent_exists = parent.exists()
    parent_is_directory = parent.is_dir() if parent_exists else False

    if root_exists and not root_is_directory:
        reason = "storage_root_not_directory"
        ready = False
    elif not root_exists and not parent_exists:
        reason = "storage_parent_missing"
        ready = False
    elif not root_exists and parent_exists and not parent_is_directory:
        reason = "storage_parent_not_directory"
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
    }


def media_render_output_dir_is_relative_to_project(settings: Settings | None = None) -> bool:
    root = get_media_render_storage_root(settings)
    try:
        root.relative_to(PROJECT_ROOT.resolve())
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
    resolved = path.resolve()
    for root in allowed_roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def relative_media_render_storage_path(path: Path, settings: Settings | None = None) -> str:
    resolved = path.resolve()
    active_root = get_media_render_storage_root(settings)
    try:
        return resolved.relative_to(active_root).as_posix()
    except ValueError as exc:
        raise ValueError(f"Media render asset path {resolved.as_posix()} is outside the active storage root.") from exc


def package_relative_media_render_path(path: Path, package_root: Path) -> str:
    resolved = path.resolve()
    root = package_root.resolve()
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

    raw_path = Path(raw_text)
    allowed_roots = _allowed_media_render_roots(settings)
    active_root = get_media_render_storage_root(settings)
    candidate_paths: list[Path] = []

    if raw_path.is_absolute():
        candidate_paths.append(raw_path.resolve())
    else:
        project_relative_path = (PROJECT_ROOT / raw_path).resolve()
        if _path_under_allowed_root(project_relative_path, allowed_roots):
            candidate_paths.append(project_relative_path)

        active_root_relative_path = (active_root / raw_path).resolve()
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
