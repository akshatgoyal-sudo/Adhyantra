from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import LEGACY_BACKEND_DB_FILE_PATH, get_active_sqlite_db_path, get_demo_seed_marker_path, get_settings
from backend.db import engine, init_db


BACKUP_DIR = PROJECT_ROOT / "backups"
DEMO_EMAIL_DOMAIN = "@adhyantra.test"


def require_sqlite_db_path() -> Path:
    settings = get_settings()
    sqlite_db_path = get_active_sqlite_db_path(settings.db_url)
    if sqlite_db_path is None:
        raise RuntimeError("Local reset/seed scripts currently support only SQLite EXAM_GURU_DB_URL values.")
    return sqlite_db_path


def ensure_non_deployed_local_operation(operation_name: str) -> None:
    settings = get_settings()
    if settings.deployed_mode:
        raise RuntimeError(
            f"{operation_name} is blocked while APP_ENV={settings.environment_name}. "
            "Use staging/production backup and migration workflows instead of local reset/seed tooling."
        )


def backup_sqlite_db(*, backup_dir: Path | None = None) -> Path:
    source_path = require_sqlite_db_path()
    if not source_path.exists():
        raise FileNotFoundError(f"SQLite database does not exist: {source_path}")

    destination_dir = backup_dir or BACKUP_DIR
    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_path = destination_dir / f"{source_path.stem}-{timestamp}.sqlite3"

    with sqlite3.connect(source_path) as source_connection:
        with sqlite3.connect(backup_path) as backup_connection:
            source_connection.backup(backup_connection)

    return backup_path


def clear_demo_seed_marker() -> bool:
    marker_path = get_demo_seed_marker_path()
    if not marker_path.exists():
        return False
    marker_path.unlink()
    return True


def read_demo_seed_marker() -> dict[str, Any] | None:
    marker_path = get_demo_seed_marker_path()
    if not marker_path.exists():
        return None
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "path": marker_path.as_posix(),
            "present": True,
            "invalid": True,
            "error": str(exc),
        }
    return {
        "path": marker_path.as_posix(),
        "present": True,
        "invalid": False,
        **payload,
    }


def write_demo_seed_marker(payload: dict[str, Any]) -> Path:
    marker_path = get_demo_seed_marker_path()
    marker_payload = {
        "seeded_at": datetime.now(UTC).isoformat(),
        **payload,
    }
    marker_path.write_text(json.dumps(marker_payload, indent=2), encoding="utf-8")
    return marker_path


def _sqlite_table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _sqlite_scalar_int(
    connection: sqlite3.Connection,
    query: str,
    params: tuple[Any, ...] = (),
) -> int:
    row = connection.execute(query, params).fetchone()
    if row is None:
        return 0
    try:
        return int(row[0] or 0)
    except (TypeError, ValueError):
        return 0


def _inspect_local_sqlite_runtime(sqlite_db_path: Path | None) -> dict[str, Any]:
    inspection = {
        "inspectable": bool(sqlite_db_path and sqlite_db_path.exists()),
        "inspection_error": None,
        "user_count": 0,
        "demo_user_count": 0,
        "product_user_count": 0,
        "quiz_attempt_count": 0,
        "quiz_count": 0,
    }
    if sqlite_db_path is None or not sqlite_db_path.exists():
        return inspection

    try:
        with sqlite3.connect(sqlite_db_path) as connection:
            if _sqlite_table_exists(connection, "user_accounts"):
                inspection["user_count"] = _sqlite_scalar_int(
                    connection,
                    "SELECT COUNT(*) FROM user_accounts",
                )
                inspection["demo_user_count"] = _sqlite_scalar_int(
                    connection,
                    "SELECT COUNT(*) FROM user_accounts WHERE LOWER(email) LIKE ?",
                    (f"%{DEMO_EMAIL_DOMAIN.lower()}",),
                )
                inspection["product_user_count"] = _sqlite_scalar_int(
                    connection,
                    "SELECT COUNT(*) FROM user_accounts WHERE email IS NOT NULL AND LOWER(email) NOT LIKE ?",
                    (f"%{DEMO_EMAIL_DOMAIN.lower()}",),
                )
            if _sqlite_table_exists(connection, "quiz_attempts"):
                inspection["quiz_attempt_count"] = _sqlite_scalar_int(
                    connection,
                    "SELECT COUNT(*) FROM quiz_attempts",
                )
            if _sqlite_table_exists(connection, "quizzes"):
                inspection["quiz_count"] = _sqlite_scalar_int(
                    connection,
                    "SELECT COUNT(*) FROM quizzes",
                )
    except sqlite3.DatabaseError as exc:
        inspection["inspection_error"] = str(exc)

    return inspection


def _classify_runtime_hygiene(
    *,
    deployed_mode: bool,
    sqlite_db_path: Path | None,
    sqlite_exists: bool,
    marker: dict[str, Any],
    inspection: dict[str, Any],
) -> dict[str, Any]:
    marker_present = bool(marker.get("present"))
    marker_invalid = bool(marker.get("invalid"))
    demo_user_count = int(inspection.get("demo_user_count") or 0)
    product_user_count = int(inspection.get("product_user_count") or 0)
    user_count = int(inspection.get("user_count") or 0)
    quiz_attempt_count = int(inspection.get("quiz_attempt_count") or 0)

    if deployed_mode or sqlite_db_path is None:
        return {
            "lane": "managed_runtime_data",
            "label": "Managed Runtime Data",
            "note": "This runtime should use staging or production backup, migration, and smoke workflows instead of local reset/demo seed tooling.",
            "recommended_workflow": "staging_or_production_ops",
            "risk_level": "controlled",
        }

    if not sqlite_exists:
        return {
            "lane": "local_dev_reset_data",
            "label": "Local Dev Reset Data",
            "note": "The active local SQLite file does not exist yet. This is the cleanest baseline for local boot, schema init, or intentional demo seeding.",
            "recommended_workflow": "boot_or_seed_local",
            "risk_level": "low",
        }

    if marker_invalid:
        return {
            "lane": "mixed_or_ambiguous_local_data",
            "label": "Mixed or Ambiguous Local Data",
            "note": "A demo marker exists but could not be parsed. Reset the local runtime or reseed intentionally before using this DB for QA/demo work.",
            "recommended_workflow": "reset_then_reseed",
            "risk_level": "high",
        }

    if marker_present and product_user_count == 0:
        return {
            "lane": "deterministic_demo_data",
            "label": "Deterministic Demo Data",
            "note": "The local runtime is intentionally seeded for repeatable demo or QA work. Prefer scenario-aware smoke checks instead of ordinary ad hoc usage.",
            "recommended_workflow": "demo_seed_and_scenario_smoke",
            "risk_level": "low",
        }

    if marker_present and product_user_count > 0:
        return {
            "lane": "mixed_or_ambiguous_local_data",
            "label": "Mixed or Ambiguous Local Data",
            "note": "Deterministic demo state and ordinary user-owned local runtime data coexist in the same SQLite DB. Reset before trusting this DB for screenshots or QA assertions.",
            "recommended_workflow": "backup_reset_then_choose_one_lane",
            "risk_level": "high",
        }

    if demo_user_count > 0 and product_user_count == 0:
        return {
            "lane": "mixed_or_ambiguous_local_data",
            "label": "Mixed or Ambiguous Local Data",
            "note": "Demo-like accounts exist without an active marker. Treat this DB as untracked seeded data until you reset or intentionally reseed it.",
            "recommended_workflow": "reset_or_reseed_demo",
            "risk_level": "medium",
        }

    if user_count == 0 and quiz_attempt_count == 0:
        return {
            "lane": "local_dev_reset_data",
            "label": "Local Dev Reset Data",
            "note": "The local DB exists but has no user-owned runtime history yet. This is still a clean local baseline.",
            "recommended_workflow": "boot_or_seed_local",
            "risk_level": "low",
        }

    return {
        "lane": "ordinary_local_runtime_data",
        "label": "Ordinary Local Runtime Data",
        "note": "The local DB contains ordinary user-owned runtime state. Avoid mixing deterministic demo seeds into this DB unless you reset intentionally first.",
        "recommended_workflow": "ordinary_local_product_use",
        "risk_level": "watch",
    }


def build_local_runtime_state_summary() -> dict[str, Any]:
    settings = get_settings()
    sqlite_db_path = get_active_sqlite_db_path(settings.db_url)
    inspection = _inspect_local_sqlite_runtime(sqlite_db_path)
    marker = read_demo_seed_marker()
    marker_accounts = marker.get("accounts", []) if isinstance(marker, dict) else []
    marker_account_keys = [
        str(item.get("key") or "").strip()
        for item in marker_accounts
        if isinstance(item, dict) and str(item.get("key") or "").strip()
    ]
    marker_scenarios = marker.get("scenarios") if isinstance(marker, dict) else None
    if not marker_scenarios and isinstance(marker, dict):
        scenario = str(marker.get("scenario") or "").strip()
        marker_scenarios = [scenario] if scenario else []
    hygiene = _classify_runtime_hygiene(
        deployed_mode=settings.deployed_mode,
        sqlite_db_path=sqlite_db_path,
        sqlite_exists=bool(sqlite_db_path and sqlite_db_path.exists()),
        marker=marker if isinstance(marker, dict) else {},
        inspection=inspection,
    )

    return {
        "environment": settings.environment_name,
        "deployed_mode": settings.deployed_mode,
        "sqlite_path": sqlite_db_path.as_posix() if sqlite_db_path is not None else None,
        "sqlite_exists": bool(sqlite_db_path and sqlite_db_path.exists()),
        "local_reset_allowed": bool(sqlite_db_path is not None and not settings.deployed_mode),
        "demo_seed_allowed": bool(sqlite_db_path is not None and not settings.deployed_mode),
        "data_profile": inspection,
        "runtime_hygiene": hygiene,
        "marker": {
            "present": bool(marker),
            "path": marker.get("path") if isinstance(marker, dict) else None,
            "invalid": bool(marker.get("invalid")) if isinstance(marker, dict) else False,
            "mode": marker.get("mode") if isinstance(marker, dict) else None,
            "seeded_at": marker.get("seeded_at") if isinstance(marker, dict) else None,
            "scenario": marker.get("scenario") if isinstance(marker, dict) else None,
            "scenarios": list(marker_scenarios or []),
            "account_keys": marker_account_keys,
        },
    }


def reset_local_db(*, recreate_schema: bool = True, backup_before_reset: bool = True) -> dict[str, Any]:
    ensure_non_deployed_local_operation("Local database reset")
    sqlite_db_path = require_sqlite_db_path()
    engine.dispose()

    backup_path: Path | None = None
    if backup_before_reset and sqlite_db_path.exists():
        backup_path = backup_sqlite_db()

    removed_paths: list[str] = []
    for candidate_path in (sqlite_db_path, LEGACY_BACKEND_DB_FILE_PATH):
        if candidate_path.exists():
            try:
                candidate_path.unlink()
            except PermissionError as exc:
                raise RuntimeError(
                    f"Could not reset the local SQLite database because '{candidate_path}' is locked by another process. "
                    "Stop any running Adhyantra backend/frontend server, Python session, or SQLite viewer using this DB, then try again."
                ) from exc
            removed_paths.append(candidate_path.as_posix())

    marker_removed = clear_demo_seed_marker()
    if recreate_schema:
        init_db()

    return {
        "active_db_path": sqlite_db_path.as_posix(),
        "backup_path": backup_path.as_posix() if backup_path else None,
        "removed_paths": removed_paths,
        "legacy_db_path": LEGACY_BACKEND_DB_FILE_PATH.as_posix(),
        "marker_removed": marker_removed,
    }
