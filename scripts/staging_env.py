from __future__ import annotations

from pathlib import Path
import os


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_env_file(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.exists():
        raise FileNotFoundError(f"Environment file does not exist: {env_path}")

    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def load_env_file(env_file: str | None, *, override: bool = False) -> Path | None:
    if not env_file:
        return None

    env_path = Path(env_file)
    if not env_path.is_absolute():
        env_path = PROJECT_ROOT / env_path
    env_path = env_path.resolve()

    values = parse_env_file(env_path)
    for key, value in values.items():
        if override or key not in os.environ:
            os.environ[key] = value
    return env_path


def first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return default


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
