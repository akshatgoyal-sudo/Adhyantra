from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy.engine import URL, make_url


MIGRATION_URL_ENV = "EXAM_GURU_MIGRATION_DB_URL"
ALLOW_REMOTE_ENV = "EXAM_GURU_MIGRATION_ALLOW_REMOTE"
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


class MigrationConfigurationError(RuntimeError):
    """Raised when the explicit migration target fails closed validation."""


@dataclass(frozen=True)
class MigrationTarget:
    url: URL
    is_local: bool

    @property
    def redacted_url(self) -> str:
        return self.url.render_as_string(hide_password=True)


def _enabled(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in _TRUE_VALUES


def get_migration_target() -> MigrationTarget:
    raw_url = str(os.environ.get(MIGRATION_URL_ENV) or "").strip()
    if not raw_url:
        raise MigrationConfigurationError(
            f"{MIGRATION_URL_ENV} is required; migrations never use the application database URL or SQLite fallback."
        )

    try:
        url = make_url(raw_url)
    except Exception:
        raise MigrationConfigurationError(f"{MIGRATION_URL_ENV} is not a valid SQLAlchemy URL.") from None

    if url.get_backend_name() != "postgresql":
        raise MigrationConfigurationError("Migrations require an explicit PostgreSQL URL; SQLite is not supported.")

    host = str(url.host or "").strip().lower()
    if not host:
        raise MigrationConfigurationError("The migration PostgreSQL URL must include an explicit host.")

    is_local = host in LOCAL_HOSTS
    if not is_local and not _enabled(ALLOW_REMOTE_ENV):
        raise MigrationConfigurationError(
            f"Remote migration targets fail closed. Set {ALLOW_REMOTE_ENV}=true only for a separately authorized remote migration."
        )

    return MigrationTarget(url=url, is_local=is_local)


def scrub_secret(text: str, target: MigrationTarget) -> str:
    scrubbed = str(text)
    raw_password = target.url.password
    if raw_password:
        scrubbed = scrubbed.replace(str(raw_password), "***")
    return scrubbed.replace(target.url.render_as_string(hide_password=False), target.redacted_url)
