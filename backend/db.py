from __future__ import annotations

import logging
from typing import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from backend.config import LEGACY_BACKEND_DB_FILE_PATH, get_active_sqlite_db_path, get_settings


logger = logging.getLogger(__name__)
settings = get_settings()
DB_SCHEMA_MANAGEMENT = {
    "strategy": "sqlalchemy_create_all_plus_sqlite_compatibility_updates",
    "migration_framework": "none",
    "sqlite_compatibility_updates": True,
    "destructive_auto_migrations": False,
}

engine = create_engine(
    settings.db_url,
    connect_args={"check_same_thread": False} if settings.db_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def database_readiness_snapshot() -> dict:
    db_type = str(settings.db_url or "").split(":", 1)[0] or "unknown"
    sqlite_db_path = get_active_sqlite_db_path(settings.db_url)
    required_tables = {
        "analytics_events",
        "billing_event_receipts",
        "content_items",
        "email_otp_challenges",
        "media_render_jobs",
        "runtime_process_heartbeats",
        "usage_consumption_records",
        "user_accounts",
        "user_sessions",
        "user_settings",
    }

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar()

        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())
        missing_tables = sorted(required_tables - existing_tables)
        return {
            "ok": not missing_tables,
            "status": "ready" if not missing_tables else "schema_incomplete",
            "database_type": db_type,
            "ping": "ok",
            "schema_management": DB_SCHEMA_MANAGEMENT,
            "schema": {
                "required_tables_present": not missing_tables,
                "required_table_count": len(required_tables),
                "missing_required_tables": missing_tables,
            },
            "sqlite": {
                "configured": sqlite_db_path is not None or str(settings.db_url or "").startswith("sqlite"),
                "file_backed": sqlite_db_path is not None,
                "parent_exists": bool(sqlite_db_path and sqlite_db_path.parent.exists()),
            },
        }
    except Exception as exc:
        logger.exception("Database readiness check failed.")
        return {
            "ok": False,
            "status": "unavailable",
            "database_type": db_type,
            "ping": "failed",
            "error_type": type(exc).__name__,
            "schema_management": DB_SCHEMA_MANAGEMENT,
            "schema": {
                "required_tables_present": False,
                "required_table_count": len(required_tables),
                "missing_required_tables": [],
            },
            "sqlite": {
                "configured": sqlite_db_path is not None or str(settings.db_url or "").startswith("sqlite"),
                "file_backed": sqlite_db_path is not None,
                "parent_exists": bool(sqlite_db_path and sqlite_db_path.parent.exists()),
            },
        }



def _prepare_sqlite_path() -> None:
    sqlite_db_path = get_active_sqlite_db_path(settings.db_url)
    if sqlite_db_path is None:
        return

    sqlite_db_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Active SQLite database path: %s", sqlite_db_path)

    if LEGACY_BACKEND_DB_FILE_PATH.exists() and LEGACY_BACKEND_DB_FILE_PATH != sqlite_db_path:
        logger.warning(
            "Legacy SQLite file exists at %s but is not active. Use scripts/reset_local_db.py to remove stale local data.",
            LEGACY_BACKEND_DB_FILE_PATH,
        )



def _has_columns(table_name: str, required_columns: set[str]) -> bool:
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    return required_columns.issubset(columns)



def _has_unique_index(table_name: str, columns: set[str]) -> bool:
    inspector = inspect(engine)
    unique_sets = [set(constraint.get("column_names") or []) for constraint in inspector.get_unique_constraints(table_name)]
    index_sets = [
        set(index.get("column_names") or [])
        for index in inspector.get_indexes(table_name)
        if index.get("unique")
    ]
    return columns in unique_sets or columns in index_sets



def _ensure_product_account_tables() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if not existing_tables:
        return

    with engine.begin() as connection:
        if "user_accounts" in existing_tables:
            if not _has_columns("user_accounts", {"auth_status"}):
                connection.execute(text("ALTER TABLE user_accounts ADD COLUMN auth_status VARCHAR(30) NOT NULL DEFAULT 'pending_verification'"))
            if not _has_columns("user_accounts", {"primary_auth_method"}):
                connection.execute(text("ALTER TABLE user_accounts ADD COLUMN primary_auth_method VARCHAR(30) NOT NULL DEFAULT 'email_otp'"))
            if not _has_columns("user_accounts", {"last_active_at"}):
                connection.execute(text("ALTER TABLE user_accounts ADD COLUMN last_active_at DATETIME"))
            if not _has_columns("user_accounts", {"billing_email"}):
                connection.execute(text("ALTER TABLE user_accounts ADD COLUMN billing_email VARCHAR(320)"))
            if not _has_columns("user_accounts", {"subscription_customer_ref"}):
                connection.execute(text("ALTER TABLE user_accounts ADD COLUMN subscription_customer_ref VARCHAR(120)"))
            if not _has_columns("user_accounts", {"subscription_provider_ref"}):
                connection.execute(text("ALTER TABLE user_accounts ADD COLUMN subscription_provider_ref VARCHAR(160)"))
            if not _has_columns("user_accounts", {"subscription_started_at"}):
                connection.execute(text("ALTER TABLE user_accounts ADD COLUMN subscription_started_at DATETIME"))
            if not _has_columns("user_accounts", {"subscription_current_period_end"}):
                connection.execute(text("ALTER TABLE user_accounts ADD COLUMN subscription_current_period_end DATETIME"))
            if not _has_columns("user_accounts", {"subscription_trial_ends_at"}):
                connection.execute(text("ALTER TABLE user_accounts ADD COLUMN subscription_trial_ends_at DATETIME"))
            if not _has_columns("user_accounts", {"subscription_cancel_at_period_end"}):
                connection.execute(text("ALTER TABLE user_accounts ADD COLUMN subscription_cancel_at_period_end BOOLEAN NOT NULL DEFAULT 0"))
            if not _has_columns("user_accounts", {"subscription_price_id"}):
                connection.execute(text("ALTER TABLE user_accounts ADD COLUMN subscription_price_id VARCHAR(120)"))
            if not _has_columns("user_accounts", {"subscription_product_id"}):
                connection.execute(text("ALTER TABLE user_accounts ADD COLUMN subscription_product_id VARCHAR(120)"))
            if not _has_columns("user_accounts", {"feature_access_overrides_json"}):
                connection.execute(text("ALTER TABLE user_accounts ADD COLUMN feature_access_overrides_json TEXT NOT NULL DEFAULT '{}'"))
            if not _has_columns("user_accounts", {"account_role"}):
                connection.execute(text("ALTER TABLE user_accounts ADD COLUMN account_role VARCHAR(30) NOT NULL DEFAULT 'student'"))
            if not _has_columns("user_accounts", {"admin_privileges_json"}):
                connection.execute(text("ALTER TABLE user_accounts ADD COLUMN admin_privileges_json TEXT NOT NULL DEFAULT '[]'"))
            connection.execute(
                text(
                    "UPDATE user_accounts "
                    "SET account_role = 'student' "
                    "WHERE account_role IS NULL OR TRIM(account_role) = ''"
                )
            )
            connection.execute(
                text(
                    "UPDATE user_accounts "
                    "SET admin_privileges_json = '[]' "
                    "WHERE admin_privileges_json IS NULL OR TRIM(admin_privileges_json) = ''"
                )
            )

            connection.execute(
                text(
                    """
                    UPDATE user_accounts
                    SET auth_status = CASE
                        WHEN email_verified_at IS NOT NULL THEN 'verified'
                        ELSE 'pending_verification'
                    END
                    WHERE auth_status IS NULL OR TRIM(auth_status) = ''
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE user_accounts
                    SET primary_auth_method = 'email_otp'
                    WHERE primary_auth_method IS NULL OR TRIM(primary_auth_method) = ''
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE user_accounts
                    SET billing_email = email
                    WHERE billing_email IS NULL OR TRIM(billing_email) = ''
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE user_accounts
                    SET last_active_at = COALESCE(last_login_at, created_at)
                    WHERE last_active_at IS NULL
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE user_accounts
                    SET subscription_cancel_at_period_end = 0
                    WHERE subscription_cancel_at_period_end IS NULL
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE user_accounts
                    SET feature_access_overrides_json = '{}'
                    WHERE feature_access_overrides_json IS NULL OR TRIM(feature_access_overrides_json) = ''
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS ix_user_accounts_subscription_customer_ref
                    ON user_accounts (subscription_customer_ref)
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_user_accounts_subscription_provider_ref
                    ON user_accounts (subscription_provider_ref)
                    """
                )
            )

        if "user_profiles" in existing_tables and "user_accounts" in existing_tables:
            if not _has_columns("user_profiles", {"onboarding_completed_at"}):
                connection.execute(text("ALTER TABLE user_profiles ADD COLUMN onboarding_completed_at DATETIME"))
            connection.execute(
                text(
                    """
                    INSERT INTO user_profiles (user_id, avatar_initials, onboarding_state, created_at, updated_at)
                    SELECT ua.id, NULL, 'new', ua.created_at, ua.updated_at
                    FROM user_accounts ua
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM user_profiles up
                        WHERE up.user_id = ua.id
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE user_profiles
                    SET onboarding_completed_at = COALESCE(onboarding_completed_at, updated_at)
                    WHERE onboarding_state = 'completed' AND onboarding_completed_at IS NULL
                    """
                )
            )

        if "user_settings" in existing_tables:
            if not _has_columns("user_settings", {"current_exam"}):
                connection.execute(text("ALTER TABLE user_settings ADD COLUMN current_exam VARCHAR(50) NOT NULL DEFAULT 'upsc'"))
            if not _has_columns("user_settings", {"current_subject"}):
                connection.execute(text("ALTER TABLE user_settings ADD COLUMN current_subject VARCHAR(100) NOT NULL DEFAULT 'polity'"))
            if not _has_columns("user_settings", {"study_reminders_enabled"}):
                connection.execute(text("ALTER TABLE user_settings ADD COLUMN study_reminders_enabled BOOLEAN NOT NULL DEFAULT 1"))
            if not _has_columns("user_settings", {"marketing_emails_enabled"}):
                connection.execute(text("ALTER TABLE user_settings ADD COLUMN marketing_emails_enabled BOOLEAN NOT NULL DEFAULT 0"))
            if not _has_columns("user_settings", {"progress_digest_frequency"}):
                connection.execute(text("ALTER TABLE user_settings ADD COLUMN progress_digest_frequency VARCHAR(30) NOT NULL DEFAULT 'important_only'"))
            if not _has_columns("user_settings", {"billing_notifications_enabled"}):
                connection.execute(text("ALTER TABLE user_settings ADD COLUMN billing_notifications_enabled BOOLEAN NOT NULL DEFAULT 1"))
            connection.execute(
                text(
                    """
                    UPDATE user_settings
                    SET current_exam = COALESCE(NULLIF(preferred_exam, ''), 'upsc')
                    WHERE current_exam IS NULL OR TRIM(current_exam) = ''
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE user_settings
                    SET current_subject = COALESCE(NULLIF(preferred_subject, ''), 'polity')
                    WHERE current_subject IS NULL OR TRIM(current_subject) = ''
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE user_settings
                    SET study_reminders_enabled = 1
                    WHERE study_reminders_enabled IS NULL
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE user_settings
                    SET marketing_emails_enabled = 0
                    WHERE marketing_emails_enabled IS NULL
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE user_settings
                    SET progress_digest_frequency = 'important_only'
                    WHERE progress_digest_frequency IS NULL OR TRIM(progress_digest_frequency) = ''
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE user_settings
                    SET billing_notifications_enabled = 1
                    WHERE billing_notifications_enabled IS NULL
                    """
                )
            )

        if "user_sessions" in existing_tables:
            if not _has_columns("user_sessions", {"auth_method"}):
                connection.execute(text("ALTER TABLE user_sessions ADD COLUMN auth_method VARCHAR(30) NOT NULL DEFAULT 'email_otp'"))
            if not _has_columns("user_sessions", {"session_label"}):
                connection.execute(text("ALTER TABLE user_sessions ADD COLUMN session_label VARCHAR(120)"))
            if not _has_columns("user_sessions", {"device_label"}):
                connection.execute(text("ALTER TABLE user_sessions ADD COLUMN device_label VARCHAR(120)"))
            if not _has_columns("user_sessions", {"last_authenticated_at"}):
                connection.execute(text("ALTER TABLE user_sessions ADD COLUMN last_authenticated_at DATETIME"))
            if not _has_columns("user_sessions", {"revoke_reason"}):
                connection.execute(text("ALTER TABLE user_sessions ADD COLUMN revoke_reason VARCHAR(120)"))
            connection.execute(
                text(
                    """
                    UPDATE user_sessions
                    SET auth_method = 'email_otp'
                    WHERE auth_method IS NULL OR TRIM(auth_method) = ''
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE user_sessions
                    SET last_authenticated_at = COALESCE(last_seen_at, created_at)
                    WHERE last_authenticated_at IS NULL
                    """
                )
            )

        if "email_otp_challenges" in existing_tables:
            if not _has_columns("email_otp_challenges", {"requested_ip_address"}):
                connection.execute(text("ALTER TABLE email_otp_challenges ADD COLUMN requested_ip_address VARCHAR(64)"))
            if not _has_columns("email_otp_challenges", {"requested_user_agent"}):
                connection.execute(text("ALTER TABLE email_otp_challenges ADD COLUMN requested_user_agent VARCHAR(512)"))
            if not _has_columns("email_otp_challenges", {"verified_at"}):
                connection.execute(text("ALTER TABLE email_otp_challenges ADD COLUMN verified_at DATETIME"))
            connection.execute(
                text(
                    """
                    UPDATE email_otp_challenges
                    SET verified_at = consumed_at
                    WHERE verified_at IS NULL AND consumed_at IS NOT NULL
                    """
                )
            )


def _ensure_content_item_table() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if "content_items" not in existing_tables:
        return

    with engine.begin() as connection:
        if not _has_columns("content_items", {"content_subject"}):
            connection.execute(text("ALTER TABLE content_items ADD COLUMN content_subject VARCHAR(100)"))
        if not _has_columns("content_items", {"chapter"}):
            connection.execute(text("ALTER TABLE content_items ADD COLUMN chapter VARCHAR(255) NOT NULL DEFAULT 'General'"))
        if not _has_columns("content_items", {"slug"}):
            connection.execute(text("ALTER TABLE content_items ADD COLUMN slug VARCHAR(255) NOT NULL DEFAULT 'content'"))
        if not _has_columns("content_items", {"title"}):
            connection.execute(text("ALTER TABLE content_items ADD COLUMN title VARCHAR(255) NOT NULL DEFAULT 'Untitled content'"))
        if not _has_columns("content_items", {"content_type"}):
            connection.execute(text("ALTER TABLE content_items ADD COLUMN content_type VARCHAR(50) NOT NULL DEFAULT 'topic_note'"))
        if not _has_columns("content_items", {"lifecycle_state"}):
            connection.execute(text("ALTER TABLE content_items ADD COLUMN lifecycle_state VARCHAR(30) NOT NULL DEFAULT 'draft'"))
        if not _has_columns("content_items", {"body_markdown"}):
            connection.execute(text("ALTER TABLE content_items ADD COLUMN body_markdown TEXT NOT NULL DEFAULT ''"))
        if not _has_columns("content_items", {"summary"}):
            connection.execute(text("ALTER TABLE content_items ADD COLUMN summary TEXT"))
        if not _has_columns("content_items", {"metadata_json"}):
            connection.execute(text("ALTER TABLE content_items ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'"))
        if not _has_columns("content_items", {"source_corpus_id"}):
            connection.execute(text("ALTER TABLE content_items ADD COLUMN source_corpus_id VARCHAR(120)"))
        if not _has_columns("content_items", {"source_path"}):
            connection.execute(text("ALTER TABLE content_items ADD COLUMN source_path VARCHAR(512)"))
        if not _has_columns("content_items", {"author_user_id"}):
            connection.execute(text("ALTER TABLE content_items ADD COLUMN author_user_id INTEGER"))
        if not _has_columns("content_items", {"reviewer_user_id"}):
            connection.execute(text("ALTER TABLE content_items ADD COLUMN reviewer_user_id INTEGER"))
        if not _has_columns("content_items", {"publisher_user_id"}):
            connection.execute(text("ALTER TABLE content_items ADD COLUMN publisher_user_id INTEGER"))
        if not _has_columns("content_items", {"version"}):
            connection.execute(text("ALTER TABLE content_items ADD COLUMN version INTEGER NOT NULL DEFAULT 1"))
        if not _has_columns("content_items", {"submitted_for_review_at"}):
            connection.execute(text("ALTER TABLE content_items ADD COLUMN submitted_for_review_at DATETIME"))
        if not _has_columns("content_items", {"reviewed_at"}):
            connection.execute(text("ALTER TABLE content_items ADD COLUMN reviewed_at DATETIME"))
        if not _has_columns("content_items", {"published_at"}):
            connection.execute(text("ALTER TABLE content_items ADD COLUMN published_at DATETIME"))
        if not _has_columns("content_items", {"archived_at"}):
            connection.execute(text("ALTER TABLE content_items ADD COLUMN archived_at DATETIME"))

        connection.execute(text("UPDATE content_items SET exam = 'upsc' WHERE exam IS NULL OR TRIM(exam) = ''"))
        connection.execute(text("UPDATE content_items SET subject = 'polity' WHERE subject IS NULL OR TRIM(subject) = ''"))
        connection.execute(text("UPDATE content_items SET chapter = 'General' WHERE chapter IS NULL OR TRIM(chapter) = ''"))
        connection.execute(text("UPDATE content_items SET slug = LOWER(REPLACE(topic, ' ', '-')) WHERE slug IS NULL OR TRIM(slug) = ''"))
        connection.execute(text("UPDATE content_items SET title = topic WHERE title IS NULL OR TRIM(title) = ''"))
        connection.execute(text("UPDATE content_items SET content_type = 'topic_note' WHERE content_type IS NULL OR TRIM(content_type) = ''"))
        connection.execute(
            text(
                """
                UPDATE content_items
                SET lifecycle_state = 'draft'
                WHERE lifecycle_state IS NULL
                   OR TRIM(lifecycle_state) = ''
                   OR lifecycle_state NOT IN ('draft', 'in_review', 'published', 'archived')
                """
            )
        )
        connection.execute(text("UPDATE content_items SET body_markdown = '' WHERE body_markdown IS NULL"))
        connection.execute(text("UPDATE content_items SET metadata_json = '{}' WHERE metadata_json IS NULL OR TRIM(metadata_json) = ''"))
        connection.execute(text("UPDATE content_items SET version = 1 WHERE version IS NULL OR version < 1"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_content_items_exam ON content_items (exam)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_content_items_subject ON content_items (subject)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_content_items_topic ON content_items (topic)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_content_items_slug ON content_items (slug)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_content_items_content_type ON content_items (content_type)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_content_items_lifecycle_state ON content_items (lifecycle_state)"))


def _ensure_quiz_table_columns() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if "quizzes" not in existing_tables or "quiz_attempts" not in existing_tables:
        return

    with engine.begin() as connection:
        if not _has_columns("quizzes", {"user_id"}):
            connection.execute(text("ALTER TABLE quizzes ADD COLUMN user_id INTEGER"))
        if not _has_columns("quiz_attempts", {"user_id"}):
            connection.execute(text("ALTER TABLE quiz_attempts ADD COLUMN user_id INTEGER"))
        if not _has_columns("quizzes", {"subject"}):
            connection.execute(text("ALTER TABLE quizzes ADD COLUMN subject VARCHAR(100) NOT NULL DEFAULT 'polity'"))
        if not _has_columns("quiz_attempts", {"subject"}):
            connection.execute(text("ALTER TABLE quiz_attempts ADD COLUMN subject VARCHAR(100) NOT NULL DEFAULT 'polity'"))
        if not _has_columns("quizzes", {"exam"}):
            connection.execute(text("ALTER TABLE quizzes ADD COLUMN exam VARCHAR(50) NOT NULL DEFAULT 'upsc'"))
        if not _has_columns("quiz_attempts", {"exam"}):
            connection.execute(text("ALTER TABLE quiz_attempts ADD COLUMN exam VARCHAR(50) NOT NULL DEFAULT 'upsc'"))
        if not _has_columns("quizzes", {"chapter"}):
            connection.execute(text("ALTER TABLE quizzes ADD COLUMN chapter VARCHAR(255) NOT NULL DEFAULT 'General'"))
        if not _has_columns("quiz_attempts", {"chapter"}):
            connection.execute(text("ALTER TABLE quiz_attempts ADD COLUMN chapter VARCHAR(255) NOT NULL DEFAULT 'General'"))
        if not _has_columns("quizzes", {"quiz_mode"}):
            connection.execute(text("ALTER TABLE quizzes ADD COLUMN quiz_mode VARCHAR(50) NOT NULL DEFAULT 'test'"))
        if not _has_columns("quiz_attempts", {"quiz_mode"}):
            connection.execute(text("ALTER TABLE quiz_attempts ADD COLUMN quiz_mode VARCHAR(50) NOT NULL DEFAULT 'test'"))
        if not _has_columns("quiz_attempts", {"topic_breakdown_json"}):
            connection.execute(text("ALTER TABLE quiz_attempts ADD COLUMN topic_breakdown_json TEXT NOT NULL DEFAULT '[]'"))

        connection.execute(text("UPDATE quizzes SET chapter = 'General' WHERE chapter IS NULL OR TRIM(chapter) = ''"))
        connection.execute(text("UPDATE quiz_attempts SET chapter = 'General' WHERE chapter IS NULL OR TRIM(chapter) = ''"))
        connection.execute(text("UPDATE quizzes SET subject = 'polity' WHERE subject IS NULL OR TRIM(subject) = ''"))
        connection.execute(text("UPDATE quiz_attempts SET subject = 'polity' WHERE subject IS NULL OR TRIM(subject) = ''"))
        connection.execute(text("UPDATE quizzes SET exam = 'upsc' WHERE exam IS NULL OR TRIM(exam) = ''"))
        connection.execute(text("UPDATE quiz_attempts SET exam = 'upsc' WHERE exam IS NULL OR TRIM(exam) = ''"))
        connection.execute(text("UPDATE quizzes SET quiz_mode = 'test' WHERE quiz_mode IS NULL OR TRIM(quiz_mode) = '' OR quiz_mode = 'standard'"))
        connection.execute(text("UPDATE quiz_attempts SET quiz_mode = 'test' WHERE quiz_mode IS NULL OR TRIM(quiz_mode) = '' OR quiz_mode = 'standard'"))
        connection.execute(text("UPDATE quiz_attempts SET topic_breakdown_json = '[]' WHERE topic_breakdown_json IS NULL OR TRIM(topic_breakdown_json) = ''"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_quizzes_user_id ON quizzes (user_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_quiz_attempts_user_id ON quiz_attempts (user_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_quizzes_exam ON quizzes (exam)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_quiz_attempts_exam ON quiz_attempts (exam)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_quizzes_user_exam_subject ON quizzes (user_id, exam, subject)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_quiz_attempts_user_exam_subject ON quiz_attempts (user_id, exam, subject)"))



def _ensure_billing_event_receipt_table() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if "billing_event_receipts" not in existing_tables:
        return

    with engine.begin() as connection:
        if not _has_columns("billing_event_receipts", {"delivery_attempt_count"}):
            connection.execute(text("ALTER TABLE billing_event_receipts ADD COLUMN delivery_attempt_count INTEGER NOT NULL DEFAULT 0"))
        if not _has_columns("billing_event_receipts", {"duplicate_delivery_count"}):
            connection.execute(text("ALTER TABLE billing_event_receipts ADD COLUMN duplicate_delivery_count INTEGER NOT NULL DEFAULT 0"))
        if not _has_columns("billing_event_receipts", {"last_received_at"}):
            connection.execute(text("ALTER TABLE billing_event_receipts ADD COLUMN last_received_at DATETIME"))
        if not _has_columns("billing_event_receipts", {"resolved_lifecycle_state"}):
            connection.execute(text("ALTER TABLE billing_event_receipts ADD COLUMN resolved_lifecycle_state VARCHAR(40)"))
        if not _has_columns("billing_event_receipts", {"resolved_plan_tier"}):
            connection.execute(text("ALTER TABLE billing_event_receipts ADD COLUMN resolved_plan_tier VARCHAR(30)"))
        if not _has_columns("billing_event_receipts", {"resolved_subscription_status"}):
            connection.execute(text("ALTER TABLE billing_event_receipts ADD COLUMN resolved_subscription_status VARCHAR(30)"))
        if not _has_columns("billing_event_receipts", {"resolved_premium_quota_state"}):
            connection.execute(text("ALTER TABLE billing_event_receipts ADD COLUMN resolved_premium_quota_state VARCHAR(30)"))

        connection.execute(
            text(
                """
                UPDATE billing_event_receipts
                SET delivery_attempt_count = CASE
                    WHEN delivery_attempt_count IS NULL OR delivery_attempt_count < 1 THEN 1
                    ELSE delivery_attempt_count
                END
                """
            )
        )
        connection.execute(
            text(
                """
                UPDATE billing_event_receipts
                SET duplicate_delivery_count = 0
                WHERE duplicate_delivery_count IS NULL OR duplicate_delivery_count < 0
                """
            )
        )
        connection.execute(
            text(
                """
                UPDATE billing_event_receipts
                SET last_received_at = COALESCE(last_received_at, processed_at, failed_at, first_received_at, created_at)
                WHERE last_received_at IS NULL
                """
            )
        )
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_billing_event_receipts_last_received_at ON billing_event_receipts (last_received_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_billing_event_receipts_resolved_lifecycle_state ON billing_event_receipts (resolved_lifecycle_state)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_billing_event_receipts_resolved_plan_tier ON billing_event_receipts (resolved_plan_tier)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_billing_event_receipts_resolved_subscription_status ON billing_event_receipts (resolved_subscription_status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_billing_event_receipts_resolved_premium_quota_state ON billing_event_receipts (resolved_premium_quota_state)"))


def _ensure_media_render_job_table() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if "media_render_jobs" not in existing_tables:
        return

    with engine.begin() as connection:
        if not _has_columns("media_render_jobs", {"attempt_count"}):
            connection.execute(text("ALTER TABLE media_render_jobs ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0"))
        if not _has_columns("media_render_jobs", {"max_attempts"}):
            connection.execute(text("ALTER TABLE media_render_jobs ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 3"))
        if not _has_columns("media_render_jobs", {"last_attempted_at"}):
            connection.execute(text("ALTER TABLE media_render_jobs ADD COLUMN last_attempted_at DATETIME"))
        if not _has_columns("media_render_jobs", {"queued_at"}):
            connection.execute(text("ALTER TABLE media_render_jobs ADD COLUMN queued_at DATETIME"))
        if not _has_columns("media_render_jobs", {"claimed_by"}):
            connection.execute(text("ALTER TABLE media_render_jobs ADD COLUMN claimed_by VARCHAR(120)"))
        if not _has_columns("media_render_jobs", {"claim_expires_at"}):
            connection.execute(text("ALTER TABLE media_render_jobs ADD COLUMN claim_expires_at DATETIME"))
        if not _has_columns("media_render_jobs", {"retry_after_at"}):
            connection.execute(text("ALTER TABLE media_render_jobs ADD COLUMN retry_after_at DATETIME"))
        if not _has_columns("media_render_jobs", {"canceled_at"}):
            connection.execute(text("ALTER TABLE media_render_jobs ADD COLUMN canceled_at DATETIME"))
        if not _has_columns("media_render_jobs", {"dispatch_payload_json"}):
            connection.execute(text("ALTER TABLE media_render_jobs ADD COLUMN dispatch_payload_json TEXT NOT NULL DEFAULT '{}'"))
        if not _has_columns("media_render_jobs", {"artifact_retention_expires_at"}):
            connection.execute(text("ALTER TABLE media_render_jobs ADD COLUMN artifact_retention_expires_at DATETIME"))
        if not _has_columns("media_render_jobs", {"last_downloaded_at"}):
            connection.execute(text("ALTER TABLE media_render_jobs ADD COLUMN last_downloaded_at DATETIME"))
        if not _has_columns("media_render_jobs", {"artifact_deleted_at"}):
            connection.execute(text("ALTER TABLE media_render_jobs ADD COLUMN artifact_deleted_at DATETIME"))
        if not _has_columns("media_render_jobs", {"artifact_cleanup_attempted_at"}):
            connection.execute(text("ALTER TABLE media_render_jobs ADD COLUMN artifact_cleanup_attempted_at DATETIME"))
        if not _has_columns("media_render_jobs", {"artifact_cleanup_retry_after_at"}):
            connection.execute(text("ALTER TABLE media_render_jobs ADD COLUMN artifact_cleanup_retry_after_at DATETIME"))
        if not _has_columns("media_render_jobs", {"artifact_cleanup_failure_count"}):
            connection.execute(text("ALTER TABLE media_render_jobs ADD COLUMN artifact_cleanup_failure_count INTEGER NOT NULL DEFAULT 0"))
        if not _has_columns("media_render_jobs", {"artifact_cleanup_error"}):
            connection.execute(text("ALTER TABLE media_render_jobs ADD COLUMN artifact_cleanup_error TEXT"))

        connection.execute(
            text(
                """
                UPDATE media_render_jobs
                SET attempt_count = 0
                WHERE attempt_count IS NULL OR attempt_count < 0
                """
            )
        )
        connection.execute(
            text(
                """
                UPDATE media_render_jobs
                SET max_attempts = 3
                WHERE max_attempts IS NULL OR max_attempts < 1
                """
            )
        )
        connection.execute(
            text(
                """
                UPDATE media_render_jobs
                SET lifecycle_state = 'queued'
                WHERE lifecycle_state IS NULL
                   OR TRIM(lifecycle_state) = ''
                   OR lifecycle_state NOT IN (
                       'queued',
                       'running',
                       'retryable_failed',
                       'succeeded',
                       'failed',
                       'canceled',
                       'abandoned'
                   )
                """
            )
        )
        connection.execute(
            text(
                """
                UPDATE media_render_jobs
                SET queued_at = COALESCE(queued_at, created_at, updated_at)
                WHERE queued_at IS NULL
                """
            )
        )
        connection.execute(
            text(
                """
                UPDATE media_render_jobs
                SET claimed_by = NULL,
                    claim_expires_at = NULL
                WHERE lifecycle_state != 'running'
                """
            )
        )
        connection.execute(
            text(
                """
                UPDATE media_render_jobs
                SET retry_after_at = NULL
                WHERE lifecycle_state NOT IN ('retryable_failed', 'abandoned')
                """
            )
        )
        connection.execute(
            text(
                """
                UPDATE media_render_jobs
                SET dispatch_payload_json = '{}'
                WHERE dispatch_payload_json IS NULL OR TRIM(dispatch_payload_json) = ''
                """
            )
        )
        connection.execute(
            text(
                """
                UPDATE media_render_jobs
                SET artifact_cleanup_failure_count = 0
                WHERE artifact_cleanup_failure_count IS NULL OR artifact_cleanup_failure_count < 0
                """
            )
        )
        connection.execute(
            text(
                """
                UPDATE media_render_jobs
                SET artifact_cleanup_retry_after_at = NULL
                WHERE artifact_deleted_at IS NOT NULL
                """
            )
        )
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_media_render_jobs_claim_expires_at ON media_render_jobs (claim_expires_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_media_render_jobs_retry_after_at ON media_render_jobs (retry_after_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_media_render_jobs_queued_at ON media_render_jobs (queued_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_media_render_jobs_claimed_by ON media_render_jobs (claimed_by)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_media_render_jobs_artifact_retention_expires_at ON media_render_jobs (artifact_retention_expires_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_media_render_jobs_artifact_deleted_at ON media_render_jobs (artifact_deleted_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_media_render_jobs_artifact_cleanup_retry_after_at ON media_render_jobs (artifact_cleanup_retry_after_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_media_render_jobs_lifecycle_retry_ready ON media_render_jobs (lifecycle_state, retry_after_at, created_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_media_render_jobs_lifecycle_dispatch_ready ON media_render_jobs (lifecycle_state, retry_after_at, queued_at, created_at)"))
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_media_render_jobs_artifact_cleanup_ready "
                "ON media_render_jobs (lifecycle_state, artifact_retention_expires_at, artifact_deleted_at, artifact_cleanup_retry_after_at)"
            )
        )


def _ensure_topic_studies_table() -> None:
    if not _has_columns("topic_studies", {"user_id", "exam", "subject", "chapter", "topic"}) or not _has_unique_index(
        "topic_studies", {"user_id", "exam", "subject", "chapter", "topic"}
    ):
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE topic_studies RENAME TO topic_studies_old"))
            connection.execute(
                text(
                    """
                    CREATE TABLE topic_studies (
                        id INTEGER NOT NULL PRIMARY KEY,
                        user_id INTEGER REFERENCES user_accounts (id),
                        exam VARCHAR(50) NOT NULL DEFAULT 'upsc',
                        subject VARCHAR(100) NOT NULL DEFAULT 'polity',
                        chapter VARCHAR(255) NOT NULL DEFAULT 'General',
                        topic VARCHAR(255) NOT NULL,
                        study_count INTEGER NOT NULL DEFAULT 0,
                        last_interaction_at DATETIME NOT NULL,
                        CONSTRAINT uq_topic_studies_user_exam_subject_chapter_topic UNIQUE (user_id, exam, subject, chapter, topic)
                    )
                    """
                )
            )
            existing_columns = {column["name"] for column in inspect(engine).get_columns("topic_studies_old")}
            user_id_expression = "user_id" if "user_id" in existing_columns else "NULL"
            exam_expression = "COALESCE(NULLIF(exam, ''), 'upsc')" if "exam" in existing_columns else "'upsc'"
            subject_expression = "COALESCE(NULLIF(subject, ''), 'polity')" if "subject" in existing_columns else "'polity'"
            chapter_expression = "COALESCE(NULLIF(chapter, ''), 'General')" if "chapter" in existing_columns else "'General'"
            connection.execute(
                text(
                    f"""
                    INSERT INTO topic_studies (id, user_id, exam, subject, chapter, topic, study_count, last_interaction_at)
                    SELECT id, {user_id_expression}, {exam_expression}, {subject_expression}, {chapter_expression}, topic, study_count, last_interaction_at
                    FROM topic_studies_old
                    """
                )
            )
            connection.execute(text("DROP TABLE topic_studies_old"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_topic_studies_topic ON topic_studies (topic)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_topic_studies_user_id ON topic_studies (user_id)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_topic_studies_exam ON topic_studies (exam)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_topic_studies_user_exam_subject ON topic_studies (user_id, exam, subject)"))



def _ensure_topic_progress_table() -> None:
    if not _has_columns("topic_progress", {"user_id", "exam", "subject", "chapter", "topic"}) or not _has_unique_index(
        "topic_progress", {"user_id", "exam", "subject", "chapter", "topic"}
    ):
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE topic_progress RENAME TO topic_progress_old"))
            connection.execute(
                text(
                    """
                    CREATE TABLE topic_progress (
                        id INTEGER NOT NULL PRIMARY KEY,
                        user_id INTEGER REFERENCES user_accounts (id),
                        exam VARCHAR(50) NOT NULL DEFAULT 'upsc',
                        subject VARCHAR(100) NOT NULL DEFAULT 'polity',
                        chapter VARCHAR(255) NOT NULL DEFAULT 'General',
                        topic VARCHAR(255) NOT NULL,
                        attempts_count INTEGER NOT NULL DEFAULT 0,
                        correct_answers INTEGER NOT NULL DEFAULT 0,
                        total_answers INTEGER NOT NULL DEFAULT 0,
                        accuracy FLOAT NOT NULL DEFAULT 0.0,
                        difficulty_band VARCHAR(50) NOT NULL DEFAULT 'medium',
                        weak_topic BOOLEAN NOT NULL DEFAULT 0,
                        last_attempt_at DATETIME NOT NULL,
                        CONSTRAINT uq_topic_progress_user_exam_subject_chapter_topic UNIQUE (user_id, exam, subject, chapter, topic)
                    )
                    """
                )
            )
            existing_columns = {column["name"] for column in inspect(engine).get_columns("topic_progress_old")}
            user_id_expression = "user_id" if "user_id" in existing_columns else "NULL"
            exam_expression = "COALESCE(NULLIF(exam, ''), 'upsc')" if "exam" in existing_columns else "'upsc'"
            subject_expression = "COALESCE(NULLIF(subject, ''), 'polity')" if "subject" in existing_columns else "'polity'"
            chapter_expression = "COALESCE(NULLIF(chapter, ''), 'General')" if "chapter" in existing_columns else "'General'"
            connection.execute(
                text(
                    f"""
                    INSERT INTO topic_progress (
                        id, user_id, exam, subject, chapter, topic, attempts_count, correct_answers, total_answers,
                        accuracy, difficulty_band, weak_topic, last_attempt_at
                    )
                    SELECT id, {user_id_expression}, {exam_expression}, {subject_expression}, {chapter_expression}, topic, attempts_count,
                           correct_answers, total_answers, accuracy, difficulty_band, weak_topic, last_attempt_at
                    FROM topic_progress_old
                    """
                )
            )
            connection.execute(text("DROP TABLE topic_progress_old"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_topic_progress_topic ON topic_progress (topic)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_topic_progress_user_id ON topic_progress (user_id)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_topic_progress_exam ON topic_progress (exam)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_topic_progress_user_exam_subject ON topic_progress (user_id, exam, subject)"))



def _ensure_hierarchical_sqlite_tables() -> None:
    if not settings.db_url.startswith("sqlite"):
        return

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if not existing_tables:
        return

    _ensure_product_account_tables()
    _ensure_content_item_table()
    _ensure_quiz_table_columns()
    _ensure_billing_event_receipt_table()
    _ensure_media_render_job_table()
    if "topic_studies" in existing_tables:
        _ensure_topic_studies_table()
    if "topic_progress" in existing_tables:
        _ensure_topic_progress_table()



def init_db() -> None:
    from backend.models import Base as ModelsBase

    _prepare_sqlite_path()
    ModelsBase.metadata.create_all(bind=engine)
    _ensure_hierarchical_sqlite_tables()
