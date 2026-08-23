from __future__ import annotations

import argparse
import os
import subprocess
import sys

try:
    from staging_env import PROJECT_ROOT, first_env, load_env_file
except ModuleNotFoundError:  # pragma: no cover - import-safe fallback for tests/module execution
    from scripts.staging_env import PROJECT_ROOT, first_env, load_env_file


sys.path.insert(0, str(PROJECT_ROOT))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preflight and run the Adhyantra media render worker with staging-oriented defaults.")
    parser.add_argument(
        "--env-file",
        default=first_env("ADHYANTRA_STAGING_ENV_FILE", default=".env.staging"),
        help="Optional env file to load before worker config validation. Defaults to .env.staging when present.",
    )
    parser.add_argument("--override-env-file", action="store_true", help="Let --env-file values override existing process env vars.")
    parser.add_argument("--check-only", action="store_true", help="Validate worker config and storage expectations without launching the worker.")
    parser.add_argument("--run-once", action="store_true", help="Process at most one queued job, then exit.")
    parser.add_argument("--max-jobs", type=int, default=None, help="Process up to this many jobs before exiting.")
    parser.add_argument("--worker-id", type=str, default="", help="Optional worker identifier override.")
    parser.add_argument("--poll-interval-seconds", type=float, default=None, help="Optional queue poll interval override.")
    parser.add_argument("--claim-lease-seconds", type=int, default=None, help="Optional claim lease duration override.")
    parser.add_argument("--skip-db-init", action="store_true", help="Skip local SQLite bootstrap only; deployed PostgreSQL validation is never skipped.")
    return parser


def _load_optional_env_file(env_file: str, *, override: bool) -> str | None:
    if not env_file:
        return None
    try:
        env_path = load_env_file(env_file, override=override)
    except FileNotFoundError:
        return None
    return str(env_path) if env_path else None


def _validate_worker_startup() -> int:
    from backend.config import Settings
    from backend.db import database_readiness_snapshot
    from backend.services.media_storage_service import get_media_render_storage_availability, media_render_output_dir_is_relative_to_project

    settings = Settings()
    result = settings.validate_runtime_config(process_role="worker")
    storage = get_media_render_storage_availability(settings, create=False)
    database = database_readiness_snapshot(configured_settings=settings)
    worker_mode = settings.effective_media_render_worker_mode

    print(
        "Adhyantra worker preflight: "
        f"environment={result.environment} ok={result.ok} mode={worker_mode} "
        f"storage_ready={bool(storage['ready'])} database_ready={bool(database['ok'])}"
    )
    for issue in result.errors:
        print(f"ERROR [{issue.category}.{issue.code}] {issue.message}")
    for issue in result.warnings:
        print(f"WARNING [{issue.category}.{issue.code}] {issue.message}")

    failed = not result.ok
    if not database["ok"]:
        revision_status = str((database.get("revision") or {}).get("status") or database.get("status") or "unknown")
        print(f"ERROR [database.schema_not_ready] Read-only schema validation failed with status={revision_status}.")
        failed = True
    if worker_mode != "external":
        print(
            "ERROR [deployment.worker_mode_not_external] "
            "Standalone worker startup expects MEDIA_RENDER_WORKER_MODE=external "
            "so queue processing is not duplicated across API and worker processes."
        )
        failed = True
    if not storage["ready"]:
        print(
            "ERROR [storage.media_render_output_unavailable] "
            f"MEDIA_RENDER_OUTPUT_DIR is not currently usable at {storage['root'].as_posix()} "
            f"(reason={storage['reason'] or 'unknown'})."
        )
        failed = True
    elif not storage["root_exists"]:
        print(
            "INFO [storage.media_render_output_create_on_first_render] "
            f"MEDIA_RENDER_OUTPUT_DIR will be created on first render under {storage['root'].as_posix()}."
        )
    else:
        print(f"INFO [storage.media_render_output_ready] Using media output root {storage['root'].as_posix()}.")

    if media_render_output_dir_is_relative_to_project(settings):
        print(
            "WARNING [deployment.project_local_media_storage] "
            "MEDIA_RENDER_OUTPUT_DIR resolves inside the project tree. "
            "A shared mounted path is safer for separate API and worker processes."
        )

    return 0 if not failed else 2


def main() -> int:
    args = _build_parser().parse_args()
    loaded_env = _load_optional_env_file(args.env_file, override=bool(args.override_env_file))
    if loaded_env:
        print(f"Loaded staging env file: {loaded_env}")
    else:
        print("No staging env file loaded; using process environment.")
    os.environ.setdefault("APP_ENV", "staging")

    preflight_status = _validate_worker_startup()
    if args.check_only or preflight_status != 0:
        return preflight_status

    command = [sys.executable, "-m", "backend.workers.media_render_worker"]
    if args.run_once:
        command.append("--run-once")
    if args.max_jobs is not None:
        command.extend(["--max-jobs", str(args.max_jobs)])
    if str(args.worker_id or "").strip():
        command.extend(["--worker-id", str(args.worker_id).strip()])
    if args.poll_interval_seconds is not None:
        command.extend(["--poll-interval-seconds", str(args.poll_interval_seconds)])
    if args.claim_lease_seconds is not None:
        command.extend(["--claim-lease-seconds", str(args.claim_lease_seconds)])
    if args.skip_db_init:
        command.append("--skip-db-init")

    print("Starting Adhyantra media render worker:")
    print(" ".join(command))
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
