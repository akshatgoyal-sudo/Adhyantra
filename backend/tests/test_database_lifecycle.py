from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect, text

import backend.db as db_module
from backend.db import DatabaseLifecycleError
from backend.models import Base
from backend.services.database_revision_service import inspect_database_revision, load_source_revision_heads
from backend.workers import media_render_worker


def _settings(*, environment: str, db_url: str) -> SimpleNamespace:
    aliases = {"dev": "development", "local": "development", "testing": "test", "prod": "production"}
    normalized = aliases.get(environment, environment)
    return SimpleNamespace(
        app_env=environment,
        raw_environment_name=environment,
        environment_name=normalized,
        db_url=db_url,
    )


def test_development_sqlite_bootstrap_creates_schema_and_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "nested" / "local.sqlite3"
    local_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    monkeypatch.setattr(db_module, "settings", _settings(environment="development", db_url=str(local_engine.url)))
    monkeypatch.setattr(db_module, "engine", local_engine)

    db_module.prepare_database_for_startup()
    db_module.prepare_database_for_startup()

    assert set(inspect(local_engine).get_table_names()) == set(Base.metadata.tables)
    local_engine.dispose()


def test_unknown_environment_cannot_bootstrap_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_path = tmp_path / "unknown.sqlite3"
    local_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    monkeypatch.setattr(db_module, "settings", _settings(environment="custom", db_url=str(local_engine.url)))
    monkeypatch.setattr(db_module, "engine", local_engine)

    with pytest.raises(DatabaseLifecycleError, match="Deployed startup requires") as caught:
        db_module.prepare_database_for_startup()

    assert caught.value.status == "unsupported_database"
    assert not database_path.exists()
    local_engine.dispose()


def test_production_sqlite_cannot_bootstrap_even_when_config_accepts_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "production.sqlite3"
    local_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    monkeypatch.setattr(db_module, "settings", _settings(environment="production", db_url=str(local_engine.url)))
    monkeypatch.setattr(db_module, "engine", local_engine)

    with pytest.raises(DatabaseLifecycleError) as caught:
        db_module.prepare_database_for_startup()

    assert caught.value.status == "unsupported_database"
    assert not database_path.exists()
    local_engine.dispose()


def test_postgresql_startup_fails_closed_without_running_local_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        db_module,
        "settings",
        _settings(environment="production", db_url="postgresql+psycopg2://invalid.example/db"),
    )
    monkeypatch.setattr(
        db_module,
        "database_readiness_snapshot",
        lambda **_kwargs: {"ok": False, "status": "version_table_missing", "revision": {"status": "version_table_missing"}},
    )
    monkeypatch.setattr(
        db_module,
        "bootstrap_local_sqlite_schema",
        lambda: pytest.fail("PostgreSQL startup must not bootstrap schema"),
    )

    with pytest.raises(DatabaseLifecycleError) as caught:
        db_module.prepare_database_for_startup()

    assert caught.value.status == "version_table_missing"
    assert "invalid.example" not in str(caught.value)


def test_worker_skip_flag_never_skips_database_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []
    fake_settings = SimpleNamespace(
        effective_log_level="WARNING",
        enforce_worker_startup_config=lambda: SimpleNamespace(warnings=[]),
    )
    monkeypatch.setattr(media_render_worker, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(media_render_worker, "initialize_media_render_storage", lambda _settings: None)
    monkeypatch.setattr(
        media_render_worker,
        "prepare_database_for_startup",
        lambda *, skip_local_bootstrap: calls.append(skip_local_bootstrap),
    )
    monkeypatch.setattr(media_render_worker, "run_media_render_worker_once", lambda **_kwargs: 0)

    assert media_render_worker.main(["--run-once", "--skip-db-init"]) == 0
    assert calls == [True]


def test_worker_reports_database_validation_failure_before_processing(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_settings = SimpleNamespace(
        effective_log_level="WARNING",
        enforce_worker_startup_config=lambda: SimpleNamespace(warnings=[]),
    )
    monkeypatch.setattr(media_render_worker, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(media_render_worker, "initialize_media_render_storage", lambda _settings: None)
    monkeypatch.setattr(
        media_render_worker,
        "prepare_database_for_startup",
        lambda **_kwargs: (_ for _ in ()).throw(DatabaseLifecycleError("behind", "schema is behind")),
    )
    monkeypatch.setattr(
        media_render_worker,
        "run_media_render_worker_once",
        lambda **_kwargs: pytest.fail("Worker must not process jobs after failed schema validation"),
    )

    assert media_render_worker.main(["--run-once"]) == 4


def test_revision_inspection_distinguishes_unstamped_unknown_and_missing_tables(tmp_path: Path) -> None:
    revision_engine = create_engine(f"sqlite:///{(tmp_path / 'revision.sqlite3').as_posix()}")
    try:
        Base.metadata.create_all(revision_engine)

        unstamped = inspect_database_revision(revision_engine)
        assert unstamped.status == "version_table_missing"

        with revision_engine.begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
            connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('not_a_source_revision')"))
        unknown = inspect_database_revision(revision_engine)
        assert unknown.status == "unknown_revision"

        head = load_source_revision_heads()[0]
        with revision_engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num = :head"), {"head": head})
            connection.execute(text("DROP TABLE analytics_events"))
        incomplete = inspect_database_revision(revision_engine)
        assert incomplete.status == "required_tables_missing"
        assert incomplete.missing_required_tables == ("analytics_events",)
    finally:
        revision_engine.dispose()
