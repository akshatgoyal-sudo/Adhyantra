# PostgreSQL migrations

Adhyantra uses Alembic for reviewed PostgreSQL schema changes. The migration
configuration is deliberately separate from application startup:

- Alembic reads only `EXAM_GURU_MIGRATION_DB_URL` from the process environment.
- It does not read `.env`, use `EXAM_GURU_DB_URL`, start FastAPI or workers, call
  `init_db()`, or fall back to SQLite.
- PostgreSQL is required. Remote hosts fail closed unless
  `EXAM_GURU_MIGRATION_ALLOW_REMOTE=true` is set for a separately authorized
  operation.
- `alembic.ini` contains no database URL or credential.

The initial revision `20260823_0001` is the current 15-table model/schema
baseline. Use `alembic upgrade head` only for an empty PostgreSQL database.
An existing database whose schema has been independently proven compatible must
be backed up and then stamped with `alembic stamp 20260823_0001`; it must not run
the initial upgrade.

Typical local commands, after setting an explicit disposable PostgreSQL URL:

```powershell
$env:EXAM_GURU_MIGRATION_DB_URL="<explicit-local-postgresql-url>"
python -m alembic current
python -m alembic upgrade head
python -m alembic check
python -m alembic downgrade base
python -m alembic upgrade head --sql
```

Never put the URL in a tracked file or command history. `downgrade base` is
destructive and is permitted only against a validated disposable database.

The baseline intentionally preserves existing SQLAlchemy model behavior:

- business defaults remain Python/ORM-side unless metadata already defines a
  server default;
- JSON-shaped fields remain PostgreSQL `TEXT`;
- RLS policies and least-privileged application roles are deferred to a
  separate security-reviewed migration;
- API, embedded-worker, and external-worker startup never call `create_all()`,
  Alembic upgrade, or Alembic stamp for PostgreSQL. They perform read-only
  revision and required-table validation and fail closed unless the database is
  at the single source head.
- explicit development/test SQLite startup retains local table bootstrap and
  compatibility updates. PostgreSQL development uses Alembic too.

For a new empty PostgreSQL database, the authorized migration owner runs
`python -m alembic upgrade head`. For an existing compatible Supabase database,
only after a verified backup, zero-drift comparison, and explicit operational
approval, run `python -m alembic stamp 20260823_0001`. Stamping records migration
history; it does not create or repair existing tables.

API and worker processes must never both attempt migrations. A future Render
deployment needs one separately controlled pre-deploy migration owner; no Render
configuration is added by this change.

For a managed database, take and verify a native backup, compare the live schema
to SQLAlchemy metadata and the baseline, and obtain explicit authorization before
stamping or applying any revision.
