from __future__ import annotations

import argparse
import os
import subprocess
import sys

try:
    from staging_env import first_env, load_env_file
except ModuleNotFoundError:  # pragma: no cover - import-safe fallback for tests/module execution
    from scripts.staging_env import first_env, load_env_file


def _npm_command() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Adhyantra frontend with staging-oriented runtime env.")
    parser.add_argument(
        "--env-file",
        default=first_env("ADHYANTRA_STAGING_ENV_FILE", default=".env.staging"),
        help="Optional env file to load before starting Next.js.",
    )
    parser.add_argument("--override-env-file", action="store_true", help="Let --env-file values override existing process env vars.")
    parser.add_argument("--host", default=first_env("STAGING_FRONTEND_HOST", default="0.0.0.0"), help="Frontend bind host.")
    parser.add_argument("--port", default=first_env("STAGING_FRONTEND_PORT", default="3000"), help="Frontend bind port.")
    parser.add_argument("--build", action="store_true", help="Run the frontend production build before starting.")
    return parser


def _load_optional_env_file(env_file: str, *, override: bool) -> str | None:
    if not env_file:
        return None
    try:
        env_path = load_env_file(env_file, override=override)
    except FileNotFoundError:
        return None
    return str(env_path) if env_path else None


def main() -> int:
    args = _build_parser().parse_args()
    loaded_env = _load_optional_env_file(args.env_file, override=bool(args.override_env_file))
    if loaded_env:
        print(f"Loaded staging env file: {loaded_env}")
    else:
        print("No staging env file loaded; using process environment.")

    backend_url = first_env("NEXT_PUBLIC_API_BASE_URL", "STAGING_BACKEND_URL", "BACKEND_PUBLIC_URL")
    if backend_url:
        os.environ.setdefault("NEXT_PUBLIC_API_BASE_URL", backend_url)
        print(f"NEXT_PUBLIC_API_BASE_URL configured for staging frontend: {os.environ['NEXT_PUBLIC_API_BASE_URL']}")
    else:
        print("WARNING: NEXT_PUBLIC_API_BASE_URL is not set; frontend will use its compiled/default API base URL.")

    site_url = first_env("NEXT_PUBLIC_SITE_URL", "STAGING_FRONTEND_URL", "FRONTEND_ORIGIN")
    if site_url:
        os.environ.setdefault("NEXT_PUBLIC_SITE_URL", site_url)
        print(f"NEXT_PUBLIC_SITE_URL configured for staging frontend: {os.environ['NEXT_PUBLIC_SITE_URL']}")
    else:
        print("WARNING: NEXT_PUBLIC_SITE_URL is not set; canonical URLs will be omitted from public metadata.")

    npm = _npm_command()
    if args.build:
        build_command = [npm, "run", "build", "--workspace", "frontend"]
        print("Building Adhyantra frontend:")
        print(" ".join(build_command))
        build_result = subprocess.run(build_command, check=False)
        if build_result.returncode != 0:
            return int(build_result.returncode)

    start_command = [
        npm,
        "run",
        "start",
        "--workspace",
        "frontend",
        "--",
        "-H",
        str(args.host),
        "-p",
        str(args.port),
    ]
    print("Starting Adhyantra frontend:")
    print(" ".join(start_command))
    return subprocess.run(start_command, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
