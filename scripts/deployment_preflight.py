from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

try:
    from staging_env import PROJECT_ROOT, first_env, load_env_file
except ModuleNotFoundError:  # pragma: no cover - import-safe fallback for tests/module execution
    from scripts.staging_env import PROJECT_ROOT, first_env, load_env_file


sys.path.insert(0, str(PROJECT_ROOT))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Adhyantra deployment preflight checks for API, worker, media storage, and readiness expectations.",
    )
    parser.add_argument(
        "--env-file",
        default=first_env("ADHYANTRA_STAGING_ENV_FILE", default=".env.staging"),
        help="Optional env file to load before deployment preflight. Defaults to .env.staging when present.",
    )
    parser.add_argument("--override-env-file", action="store_true", help="Let --env-file values override existing process env vars.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON instead of the text summary.")
    parser.add_argument("--skip-worker", action="store_true", help="Skip the separate worker role check even when worker mode is external.")
    parser.add_argument("--skip-storage", action="store_true", help="Skip the media storage availability check.")
    parser.add_argument("--backend-host", default=first_env("STAGING_BACKEND_HOST", default="127.0.0.1"), help="Fallback local backend host for readiness URLs.")
    parser.add_argument("--backend-port", default=first_env("STAGING_BACKEND_PORT", default="8000"), help="Fallback local backend port for readiness URLs.")
    return parser


def _load_optional_env_file(env_file: str, *, override: bool) -> str | None:
    if not env_file:
        return None
    try:
        env_path = load_env_file(env_file, override=override)
    except FileNotFoundError:
        return None
    return str(env_path) if env_path else None


def _validation_payload(result: Any) -> dict[str, Any]:
    return {
        "ok": bool(result.ok),
        "environment": result.environment,
        "errors": [issue.__dict__ for issue in result.errors],
        "warnings": [issue.__dict__ for issue in result.warnings],
    }


def _display_url_host(host: str) -> str:
    cleaned = str(host or "").strip() or "127.0.0.1"
    if cleaned == "0.0.0.0":
        return "127.0.0.1"
    return cleaned


def _health_urls(*, backend_public_url: str, backend_host: str, backend_port: str) -> dict[str, str]:
    base_url = str(backend_public_url or "").strip().rstrip("/")
    if not base_url:
        base_url = f"http://{_display_url_host(backend_host)}:{str(backend_port).strip() or '8000'}"
    return {
        "live": f"{base_url}/health/live",
        "ready": f"{base_url}/health/ready",
    }


def _storage_payload(storage: dict[str, Any], *, project_local: bool) -> dict[str, Any]:
    return {
        "ready": bool(storage["ready"]),
        "reason": storage["reason"],
        "root": storage["root"].as_posix(),
        "root_exists": bool(storage["root_exists"]),
        "parent": storage["parent"].as_posix(),
        "parent_exists": bool(storage["parent_exists"]),
        "project_local": project_local,
    }


def _display_arg(value: str) -> str:
    text = str(value or "").strip()
    return f'"{text}"' if any(character.isspace() for character in text) else text


def _build_recommended_commands(*, env_file: str, worker_mode: str) -> list[str]:
    display_env_file = _display_arg(env_file)
    commands = [
        f"npm run db:preflight -- --env-file {display_env_file}",
        "npm run db:migrate",
        f"npm run staging:backend -- --env-file {display_env_file}",
    ]
    if worker_mode == "external":
        commands.append(f"npm run staging:worker -- --env-file {display_env_file}")
    commands.append(f"npm run staging:frontend -- --env-file {display_env_file} --build")
    commands.append("npm run smoke:staging")
    return commands


def _build_launch_checklist(*, env_file: str, worker_mode: str) -> list[dict[str, Any]]:
    display_env_file = _display_arg(env_file)
    checklist = [
        {
            "key": "prelaunch_config",
            "label": "Pre-launch config validation",
            "command": f"npm run ops:preflight -- --env-file {display_env_file}",
            "purpose": "Confirm API, worker mode, media storage, and readiness expectations before rollout.",
            "stage": "prelaunch",
        },
        {
            "key": "prelaunch_db",
            "label": "Pre-launch DB validation",
            "command": f"npm run db:preflight -- --env-file {display_env_file}",
            "purpose": "Verify schema posture and runtime DB readiness before first boot.",
            "stage": "prelaunch",
        },
        {
            "key": "prelaunch_schema",
            "label": "Reviewed migration path",
            "command": "npm run db:migrate",
            "purpose": "Run Alembic once from an authorized pre-deploy owner with EXAM_GURU_MIGRATION_DB_URL; API and workers never migrate.",
            "stage": "prelaunch",
        },
        {
            "key": "postdeploy_public",
            "label": "Post-deploy public and route smoke",
            "command": "npm run smoke:staging",
            "purpose": "Check readiness, auth entry, pricing/exam pages, robots/sitemap, and learner route cleanliness.",
            "stage": "postdeploy",
        },
        {
            "key": "postdeploy_auth",
            "label": "Authenticated learner smoke",
            "command": "npm run smoke:staging -- --interactive-otp --require-auth-flow",
            "purpose": "Validate sign-in, onboarding continuity, tutor, progress, test, plan, revision, and logout.",
            "stage": "postdeploy",
        },
        {
            "key": "postdeploy_billing",
            "label": "Premium and payment smoke",
            "command": "npm run smoke:staging -- --interactive-otp --require-auth-flow --check-billing-flow",
            "purpose": "Validate learner billing state and attempt a real ready billing action only when the account lifecycle allows it.",
            "stage": "postdeploy",
        },
        {
            "key": "postdeploy_admin",
            "label": "Admin and provider validation smoke",
            "command": "npm run smoke:staging -- --admin-interactive-otp --require-admin-flow --require-provider-validation-ready",
            "purpose": "Validate admin route access, support lookup, and provider-backed billing readiness before sign-off.",
            "stage": "postdeploy",
        },
    ]
    if worker_mode == "external":
        checklist.insert(
            3,
            {
                "key": "launch_worker",
                "label": "Separate worker launch",
                "command": f"npm run staging:worker -- --env-file {display_env_file}",
                "purpose": "Start the dedicated media worker when the deployed environment expects external queue processing.",
                "stage": "prelaunch",
            },
        )
    return checklist


def _build_notes(*, worker_mode: str, external_worker_expected: bool, storage_ready: bool, storage_project_local: bool) -> list[str]:
    notes: list[str] = []
    if worker_mode == "external":
        notes.append("External worker mode is configured. Start the backend and worker as separate processes.")
    elif worker_mode == "embedded":
        notes.append("Embedded worker mode is configured. Do not start a separate worker unless you intentionally change MEDIA_RENDER_WORKER_MODE.")
    else:
        notes.append("Media render workers are disabled, so queued media jobs will not progress.")

    if not storage_ready:
        notes.append("Media storage is not currently ready. Fix MEDIA_RENDER_OUTPUT_DIR or its parent path before exposing render features.")
    elif external_worker_expected and storage_project_local:
        notes.append("Media storage resolves inside the project tree. A shared mounted absolute path is safer for separate API and worker processes.")
    else:
        notes.append("Media storage path looks consistent with the current startup mode.")
    return notes


def main() -> int:
    args = _build_parser().parse_args()
    loaded_env = _load_optional_env_file(args.env_file, override=bool(args.override_env_file))
    os.environ.setdefault("APP_ENV", "staging")

    from backend.config import Settings
    from backend.services.media_storage_service import get_media_render_storage_availability, media_render_output_dir_is_relative_to_project

    settings = Settings()
    api_validation = settings.validate_runtime_config(process_role="api")
    worker_mode = settings.effective_media_render_worker_mode
    external_worker_expected = bool(settings.external_media_render_worker_expected)
    worker_validation = None
    if external_worker_expected and not args.skip_worker:
        worker_validation = settings.validate_runtime_config(process_role="worker")

    storage = None
    storage_project_local = False
    if not args.skip_storage:
        storage = get_media_render_storage_availability(settings, create=False)
        storage_project_local = media_render_output_dir_is_relative_to_project(settings)

    readiness_urls = _health_urls(
        backend_public_url=str(settings.backend_public_url or "").strip(),
        backend_host=args.backend_host,
        backend_port=args.backend_port,
    )
    env_file_display = str(args.env_file or "").strip() or ".env.staging"
    recommended_commands = _build_recommended_commands(env_file=env_file_display, worker_mode=worker_mode)
    launch_checklist = _build_launch_checklist(env_file=env_file_display, worker_mode=worker_mode)

    failed = not api_validation.ok
    if worker_validation is not None and not worker_validation.ok:
        failed = True
    if storage is not None and worker_mode != "disabled" and not bool(storage["ready"]):
        failed = True

    payload = {
        "environment": settings.environment_name,
        "deployed_mode": bool(settings.deployed_mode),
        "loaded_env_file": loaded_env,
        "api": _validation_payload(api_validation),
        "worker_mode": worker_mode,
        "external_worker_expected": external_worker_expected,
        "worker": _validation_payload(worker_validation) if worker_validation is not None else None,
        "media_storage": _storage_payload(storage, project_local=storage_project_local) if storage is not None else None,
        "health_urls": readiness_urls,
        "recommended_commands": recommended_commands,
        "launch_checklist": launch_checklist,
        "notes": _build_notes(
            worker_mode=worker_mode,
            external_worker_expected=external_worker_expected,
            storage_ready=bool(storage["ready"]) if storage is not None else True,
            storage_project_local=storage_project_local,
        ),
        "ok": not failed,
    }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if not failed else 2

    print("Adhyantra deployment preflight")
    print(f"Environment: {settings.environment_name} (deployed={settings.deployed_mode})")
    if loaded_env:
        print(f"Loaded env file: {loaded_env}")
    else:
        print("Loaded env file: none (using process environment)")
    print(f"API config ok: {api_validation.ok}")
    for issue in api_validation.errors:
        print(f"ERROR [api:{issue.category}.{issue.code}] {issue.message}")
    for issue in api_validation.warnings:
        print(f"WARNING [api:{issue.category}.{issue.code}] {issue.message}")

    print(f"Worker mode: {worker_mode}")
    if worker_validation is not None:
        print(f"Worker config ok: {worker_validation.ok}")
        for issue in worker_validation.errors:
            print(f"ERROR [worker:{issue.category}.{issue.code}] {issue.message}")
        for issue in worker_validation.warnings:
            print(f"WARNING [worker:{issue.category}.{issue.code}] {issue.message}")
    elif external_worker_expected and args.skip_worker:
        print("Worker config check: skipped by --skip-worker")
    else:
        print("Worker config check: not required for the current worker mode")

    if storage is not None:
        print(f"Media storage root: {storage['root'].as_posix()}")
        print(f"Media storage ready: {bool(storage['ready'])}")
        if storage["reason"]:
            print(f"Media storage reason: {storage['reason']}")
        if storage_project_local:
            print("WARNING [storage.project_local_path] MEDIA_RENDER_OUTPUT_DIR resolves inside the project tree.")
    else:
        print("Media storage check: skipped by --skip-storage")

    print("Health checks:")
    print(f"- Live: {readiness_urls['live']}")
    print(f"- Ready: {readiness_urls['ready']}")

    print("Recommended commands:")
    for command in recommended_commands:
        print(f"- {command}")

    print("Launch checklist:")
    for item in launch_checklist:
        print(f"- [{item['stage']}] {item['label']}: {item['command']}")
        print(f"  {item['purpose']}")

    print("Notes:")
    for note in payload["notes"]:
        print(f"- {note}")

    print(f"Overall preflight ok: {payload['ok']}")
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
