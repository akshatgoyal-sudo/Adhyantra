from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.script.revision import ResolutionError, RevisionError
from alembic.util import CommandError
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from backend.models import Base as ModelsBase


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG_PATH = PROJECT_ROOT / "alembic.ini"
REQUIRED_APPLICATION_TABLES = frozenset(ModelsBase.metadata.tables)


@dataclass(frozen=True)
class DatabaseRevisionStatus:
    ok: bool
    status: str
    source_heads: tuple[str, ...]
    database_revisions: tuple[str, ...] = ()
    missing_required_tables: tuple[str, ...] = ()
    error_type: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_heads"] = list(self.source_heads)
        payload["database_revisions"] = list(self.database_revisions)
        payload["missing_required_tables"] = list(self.missing_required_tables)
        return payload


def load_source_revision_heads(config_path: Path = ALEMBIC_CONFIG_PATH) -> tuple[str, ...]:
    config = Config(str(config_path))
    script = ScriptDirectory.from_config(config)
    return tuple(sorted(script.get_heads()))


def inspect_database_revision(engine: Engine) -> DatabaseRevisionStatus:
    """Inspect application tables and Alembic state without mutating the database."""
    try:
        source_heads = load_source_revision_heads()
    except Exception as exc:
        return DatabaseRevisionStatus(False, "source_revision_unavailable", (), error_type=type(exc).__name__)

    if len(source_heads) != 1:
        return DatabaseRevisionStatus(False, "multiple_heads", source_heads)

    try:
        with engine.connect() as connection:
            if engine.dialect.name == "postgresql":
                connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SELECT 1")).scalar_one()
            table_names = set(
                inspect(connection).get_table_names(schema="public" if engine.dialect.name == "postgresql" else None)
            )
            missing_tables = tuple(sorted(REQUIRED_APPLICATION_TABLES - table_names))
            if "alembic_version" not in table_names:
                return DatabaseRevisionStatus(
                    False,
                    "version_table_missing",
                    source_heads,
                    missing_required_tables=missing_tables,
                )
            database_revisions = tuple(
                sorted(str(row[0]) for row in connection.execute(text("SELECT version_num FROM alembic_version")))
            )
    except SQLAlchemyError as exc:
        return DatabaseRevisionStatus(False, "database_unavailable", source_heads, error_type=type(exc).__name__)

    if not database_revisions:
        return DatabaseRevisionStatus(
            False,
            "unstamped",
            source_heads,
            database_revisions,
            missing_tables,
        )
    if len(database_revisions) != 1:
        return DatabaseRevisionStatus(
            False,
            "multiple_heads",
            source_heads,
            database_revisions,
            missing_tables,
        )

    current = database_revisions[0]
    head = source_heads[0]
    if current == head:
        if missing_tables:
            return DatabaseRevisionStatus(
                False,
                "required_tables_missing",
                source_heads,
                database_revisions,
                missing_tables,
            )
        return DatabaseRevisionStatus(True, "at_head", source_heads, database_revisions)

    try:
        script = ScriptDirectory.from_config(Config(str(ALEMBIC_CONFIG_PATH)))
        current_revision = script.get_revision(current)
        if current_revision is None:
            raise ResolutionError(current)
        revisions_to_head = tuple(script.iterate_revisions(head, current))
    except (CommandError, RevisionError) as exc:
        # Alembic raises several graph-specific subclasses for unknown, ahead,
        # and divergent revisions. None are safe to accept at application startup.
        return DatabaseRevisionStatus(
            False,
            "unknown_revision",
            source_heads,
            database_revisions,
            missing_tables,
            type(exc).__name__,
        )

    if revisions_to_head:
        return DatabaseRevisionStatus(
            False,
            "behind",
            source_heads,
            database_revisions,
            missing_tables,
        )
    return DatabaseRevisionStatus(
        False,
        "unknown_revision",
        source_heads,
        database_revisions,
        missing_tables,
    )
