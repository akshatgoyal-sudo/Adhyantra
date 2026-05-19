from __future__ import annotations

import argparse
import json
import sys

from staging_env import PROJECT_ROOT, load_env_file


sys.path.insert(0, str(PROJECT_ROOT))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect Adhyantra DB readiness and apply lightweight schema updates when requested.")
    parser.add_argument("--env-file", default="", help="Optional env file to load before DB checks.")
    parser.add_argument("--override-env-file", action="store_true", help="Let --env-file values override existing process env vars.")
    parser.add_argument(
        "--apply-schema-updates",
        action="store_true",
        help="Run backend init_db(), which creates tables and applies current SQLite compatibility updates.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON only.")
    return parser


def _load_optional_env(env_file: str, *, override: bool) -> str | None:
    if not env_file:
        return None
    try:
        env_path = load_env_file(env_file, override=override)
    except FileNotFoundError:
        raise SystemExit(f"Environment file was not found: {env_file}")
    return str(env_path) if env_path else None


def _build_summary(*, env_file_loaded: str | None, applied_schema_updates: bool) -> dict:
    from backend.config import get_active_sqlite_db_path, get_demo_seed_marker_path, get_settings
    from backend.db import DB_SCHEMA_MANAGEMENT, database_readiness_snapshot
    from local_db_tools import build_local_runtime_state_summary

    settings = get_settings()
    sqlite_path = get_active_sqlite_db_path(settings.db_url)
    readiness = database_readiness_snapshot()
    demo_marker_path = get_demo_seed_marker_path()
    validation = settings.validate_runtime_config()
    runtime_state = build_local_runtime_state_summary()
    return {
        "ok": bool(readiness.get("ok")) and validation.ok,
        "environment": settings.environment_name,
        "deployed_mode": settings.deployed_mode,
        "env_file_loaded": env_file_loaded,
        "applied_schema_updates": applied_schema_updates,
        "database": {
            "type": readiness.get("database_type"),
            "status": readiness.get("status"),
            "ping": readiness.get("ping"),
            "schema_ok": bool(readiness.get("schema", {}).get("required_tables_present")),
            "missing_required_tables": readiness.get("schema", {}).get("missing_required_tables", []),
            "sqlite_file_backed": bool(readiness.get("sqlite", {}).get("file_backed")),
            "sqlite_path": sqlite_path.as_posix() if sqlite_path and not settings.deployed_mode else None,
        },
        "schema_management": DB_SCHEMA_MANAGEMENT,
        "operations": {
            "backup_supported": sqlite_path is not None,
            "local_reset_allowed": bool(sqlite_path is not None and not settings.deployed_mode),
            "demo_seed_allowed": bool(sqlite_path is not None and not settings.deployed_mode),
            "managed_db_backup_required": sqlite_path is None,
        },
        "demo_seed_marker_present": demo_marker_path.exists(),
        "demo_seed_state": runtime_state["marker"],
        "runtime_hygiene": runtime_state["runtime_hygiene"],
        "data_profile": runtime_state["data_profile"],
        "config_validation": {
            "ok": validation.ok,
            "error_count": len(validation.errors),
            "warning_count": len(validation.warnings),
            "errors": [f"{issue.category}.{issue.code}" for issue in validation.errors],
            "warnings": [f"{issue.category}.{issue.code}" for issue in validation.warnings],
        },
    }


def _print_human_summary(summary: dict) -> None:
    print("Adhyantra DB preflight")
    print(f"- environment: {summary['environment']} (deployed={summary['deployed_mode']})")
    print(f"- db: {summary['database']['type']} status={summary['database']['status']} schema_ok={summary['database']['schema_ok']}")
    print(f"- schema strategy: {summary['schema_management']['strategy']}")
    print(f"- schema updates applied: {summary['applied_schema_updates']}")
    print(f"- backup supported: {summary['operations']['backup_supported']}")
    print(f"- local reset allowed: {summary['operations']['local_reset_allowed']}")
    print(f"- demo seed allowed: {summary['operations']['demo_seed_allowed']}")
    print(
        "- runtime data lane: "
        f"{summary['runtime_hygiene']['label']} "
        f"({summary['runtime_hygiene']['lane']})"
    )
    print(f"- hygiene note: {summary['runtime_hygiene']['note']}")
    profile = summary.get("data_profile") or {}
    print(
        "- data profile: "
        f"users={profile.get('user_count', 0)} "
        f"demo_users={profile.get('demo_user_count', 0)} "
        f"product_users={profile.get('product_user_count', 0)} "
        f"quiz_attempts={profile.get('quiz_attempt_count', 0)}"
    )
    if summary["demo_seed_state"]["present"]:
        marker_mode = summary["demo_seed_state"].get("mode") or "unknown"
        marker_scenarios = summary["demo_seed_state"].get("scenarios") or []
        marker_accounts = summary["demo_seed_state"].get("account_keys") or []
        print(
            "- demo seed state: "
            f"mode={marker_mode} "
            f"scenarios={', '.join(marker_scenarios) if marker_scenarios else 'none'} "
            f"accounts={', '.join(marker_accounts) if marker_accounts else 'none'}"
        )
    if summary["database"]["sqlite_path"]:
        print(f"- sqlite path: {summary['database']['sqlite_path']}")
    if summary["database"]["missing_required_tables"]:
        print(f"- missing required tables: {', '.join(summary['database']['missing_required_tables'])}")
    if not summary["config_validation"]["ok"]:
        print(f"- config errors: {', '.join(summary['config_validation']['errors'])}")
    if summary["config_validation"]["warnings"]:
        print(f"- config warnings: {', '.join(summary['config_validation']['warnings'])}")


def main() -> int:
    args = _build_parser().parse_args()
    env_file_loaded = _load_optional_env(args.env_file, override=bool(args.override_env_file))

    if args.apply_schema_updates:
        from backend.db import init_db

        init_db()

    summary = _build_summary(env_file_loaded=env_file_loaded, applied_schema_updates=bool(args.apply_schema_updates))
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        _print_human_summary(summary)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
