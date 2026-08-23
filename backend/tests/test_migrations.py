from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy.engine import URL

from backend.models import Base
from migrations.runtime import (
    ALLOW_REMOTE_ENV,
    MIGRATION_URL_ENV,
    MigrationConfigurationError,
    get_migration_target,
    scrub_secret,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REVISION_PATH = PROJECT_ROOT / "migrations" / "versions" / "20260823_0001_initial_postgresql_model_baseline.py"


def _postgresql_url(*, host: str, password: str, database: str) -> str:
    return URL.create(
        "postgresql+psycopg2",
        username="migration_user",
        password=password,
        host=host,
        port=5432,
        database=database,
    ).render_as_string(hide_password=False)


def test_missing_migration_url_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(MIGRATION_URL_ENV, raising=False)
    monkeypatch.delenv(ALLOW_REMOTE_ENV, raising=False)

    with pytest.raises(MigrationConfigurationError, match=MIGRATION_URL_ENV):
        get_migration_target()


def test_sqlite_migration_url_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MIGRATION_URL_ENV, "sqlite:///migration.db")

    with pytest.raises(MigrationConfigurationError, match="PostgreSQL"):
        get_migration_target()


def test_remote_migration_url_requires_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        MIGRATION_URL_ENV,
        _postgresql_url(host="database.example", password="secret", database="db"),
    )
    monkeypatch.delenv(ALLOW_REMOTE_ENV, raising=False)

    with pytest.raises(MigrationConfigurationError, match=ALLOW_REMOTE_ENV):
        get_migration_target()


def test_local_migration_url_is_accepted_and_secret_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    password = "not-for-logs"
    monkeypatch.setenv(
        MIGRATION_URL_ENV,
        _postgresql_url(host="127.0.0.1", password=password, database="adhyantra_migration_test_unit"),
    )
    monkeypatch.delenv(ALLOW_REMOTE_ENV, raising=False)

    target = get_migration_target()
    rendered = target.redacted_url
    scrubbed = scrub_secret(f"failed for {target.url.render_as_string(hide_password=False)} {password}", target)

    assert target.is_local is True
    assert password not in rendered
    assert password not in scrubbed
    assert "***" in rendered


def test_model_metadata_import_does_not_import_app_engine_or_workers(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.pop("EXAM_GURU_DB_URL", None)
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    code = (
        "import sys; import backend.models; "
        "forbidden={'backend.db','backend.main','backend.workers.media_render_worker'}; "
        "assert forbidden.isdisjoint(sys.modules); "
        "print(len(backend.models.Base.metadata.tables))"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "15"


def test_initial_revision_creates_exact_model_table_set() -> None:
    spec = importlib.util.spec_from_file_location("adhyantra_initial_migration", REVISION_PATH)
    assert spec and spec.loader
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)

    class OperationsRecorder:
        def __init__(self) -> None:
            self.tables: list[str] = []
            self.indexes: list[tuple[str, str, tuple[str, ...], bool]] = []

        @staticmethod
        def f(name: str) -> str:
            return name

        def create_table(self, name: str, *_items: object, **_kwargs: object) -> None:
            self.tables.append(name)

        def create_index(
            self,
            name: str,
            table_name: str,
            columns: list[str],
            *,
            unique: bool,
            **_kwargs: object,
        ) -> None:
            self.indexes.append((name, table_name, tuple(columns), unique))

    recorder = OperationsRecorder()
    revision.op = recorder
    revision.upgrade()

    assert set(recorder.tables) == set(Base.metadata.tables)
    assert len(recorder.tables) == 15
    expected_indexes = sum(len(table.indexes) for table in Base.metadata.tables.values())
    assert len(recorder.indexes) == expected_indexes


def test_offline_upgrade_sql_is_postgresql_and_does_not_log_credentials() -> None:
    password = "offline-secret-must-not-appear"
    env = os.environ.copy()
    env.pop("EXAM_GURU_DB_URL", None)
    env[MIGRATION_URL_ENV] = _postgresql_url(
        host="127.0.0.1",
        password=password,
        database="adhyantra_migration_test_offline",
    )
    env.pop(ALLOW_REMOTE_ENV, None)

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    combined = result.stdout + result.stderr

    assert result.returncode == 0, combined
    assert combined.count("CREATE TABLE") == 16  # 15 application tables plus alembic_version.
    assert "TIMESTAMP WITH TIME ZONE" in combined
    assert "BOOLEAN" in combined
    assert " TEXT " in combined
    assert password not in combined


def test_alembic_ini_does_not_contain_a_database_url() -> None:
    content = (PROJECT_ROOT / "alembic.ini").read_text(encoding="utf-8")
    assert "sqlalchemy.url" not in content
    assert "postgresql://" not in content
    assert "postgresql+" not in content
