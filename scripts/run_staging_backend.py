from __future__ import annotations

import argparse
import os
import sys

import uvicorn

try:
    from staging_env import PROJECT_ROOT, env_bool, first_env, load_env_file
except ModuleNotFoundError:  # pragma: no cover - import-safe fallback for tests/module execution
    from scripts.staging_env import PROJECT_ROOT, env_bool, first_env, load_env_file


sys.path.insert(0, str(PROJECT_ROOT))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preflight and run the Adhyantra backend with staging-oriented defaults.")
    parser.add_argument(
        "--env-file",
        default=first_env("ADHYANTRA_STAGING_ENV_FILE", default=".env.staging"),
        help="Optional env file to load before config validation. Defaults to .env.staging when present.",
    )
    parser.add_argument("--override-env-file", action="store_true", help="Let --env-file values override existing process env vars.")
    parser.add_argument("--host", default=first_env("STAGING_BACKEND_HOST", default="0.0.0.0"), help="Backend bind host.")
    parser.add_argument("--port", default=first_env("STAGING_BACKEND_PORT", "PORT", default="8000"), help="Backend bind port.")
    parser.add_argument(
        "--forwarded-allow-ips",
        default=first_env("UVICORN_FORWARDED_ALLOW_IPS", default="*"),
        help="Value passed to uvicorn --forwarded-allow-ips when proxy headers are enabled.",
    )
    parser.add_argument(
        "--no-proxy-headers",
        action="store_true",
        help="Disable uvicorn proxy header handling. Keep enabled behind a trusted reverse proxy.",
    )
    parser.add_argument("--check-only", action="store_true", help="Validate staging config and exit without launching uvicorn.")
    return parser


def _load_optional_env_file(env_file: str, *, override: bool) -> str | None:
    if not env_file:
        return None
    try:
        env_path = load_env_file(env_file, override=override)
    except FileNotFoundError:
        return None
    return str(env_path) if env_path else None


def _display_arg(value: str) -> str:
    return f'"{value}"' if any(character.isspace() for character in value) else value


def _validate_config() -> int:
    from backend.config import Settings

    settings = Settings()
    result = settings.validate_runtime_config(process_role="api")
    print(f"Adhyantra staging config preflight: environment={result.environment} ok={result.ok}")
    for issue in result.errors:
        print(f"ERROR [{issue.category}.{issue.code}] {issue.message}")
    for issue in result.warnings:
        print(f"WARNING [{issue.category}.{issue.code}] {issue.message}")
    return 0 if result.ok else 2


def _print_runtime_next_steps(*, env_file: str) -> None:
    from backend.config import Settings

    settings = Settings()
    worker_mode = settings.effective_media_render_worker_mode
    backend_url = str(settings.backend_public_url or "").strip() or f"http://127.0.0.1:{first_env('STAGING_BACKEND_PORT', 'PORT', default='8000')}"

    print(f"Backend readiness URL: {backend_url.rstrip('/')}/health/ready")
    if worker_mode == "external":
        print(
            "External media worker mode is configured. "
            f"Start the separate worker with: python scripts/run_staging_worker.py --env-file {_display_arg(env_file)}"
        )
    elif worker_mode == "embedded":
        print("Embedded media worker mode is configured. No separate worker process is expected for this backend launch.")
    else:
        print("Media render worker mode is disabled, so queued media jobs will not progress until worker mode is enabled.")


def main() -> int:
    args = _build_parser().parse_args()
    loaded_env = _load_optional_env_file(args.env_file, override=bool(args.override_env_file))
    if loaded_env:
        print(f"Loaded staging env file: {loaded_env}")
    else:
        print("No staging env file loaded; using process environment.")
    # Avoid accidentally launching the staging runner under development policy.
    os.environ.setdefault("APP_ENV", "staging")

    preflight_status = _validate_config()
    if args.check_only or preflight_status != 0:
        return preflight_status
    _print_runtime_next_steps(env_file=str(args.env_file or "").strip() or ".env.staging")

    proxy_headers_enabled = not args.no_proxy_headers and env_bool("UVICORN_PROXY_HEADERS", True)
    print("Starting Adhyantra backend:")
    print(
        "uvicorn backend.main:app "
        f"--host {args.host} --port {args.port} "
        + (
            f"--proxy-headers --forwarded-allow-ips {_display_arg(str(args.forwarded_allow_ips))}"
            if proxy_headers_enabled
            else "--no-proxy-headers"
        )
    )
    uvicorn.run(
        "backend.main:app",
        host=str(args.host),
        port=int(str(args.port)),
        proxy_headers=proxy_headers_enabled,
        forwarded_allow_ips=str(args.forwarded_allow_ips),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
