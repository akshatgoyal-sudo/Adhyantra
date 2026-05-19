from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import re
import sqlite3


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SQLITE_PATH = PROJECT_ROOT / "exam_guru.db"
PREMIUM_EMAIL = "akshatgoyal2615@gmail.com"
SECOND_PREMIUM_EMAIL = "goyalakshat10551@gmail.com"
FREE_EMAIL = "akshatgoyal2165@gmail.com"
DEFAULT_EXAM = "upsc"
DEFAULT_SUBJECT = "polity"
PREMIUM_PERIOD_DAYS = 30
ADMIN_ROLE_STUDENT = "student"
ADMIN_ROLE_CONTENT_ADMIN = "content_admin"
ADMIN_PRIVILEGES = (
    "content_import",
    "content_publish",
    "content_qa",
    "content_read",
    "content_review",
    "content_write",
)


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _normalize_email(value: str) -> str:
    candidate = str(value or "").strip().lower()
    if not re.match(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$", candidate):
        raise ValueError(f"Invalid email address: {value!r}")
    return candidate


def _normalize_display_name(email: str) -> str:
    local_part = email.split("@", 1)[0]
    pieces = [piece for piece in re.split(r"[._+\-]+", local_part) if piece]
    if not pieces:
        return "Adhyantra Learner"
    return " ".join(piece.capitalize() for piece in pieces)[:120]


def _build_avatar_initials(display_name: str, email: str) -> str:
    name_parts = [part for part in re.split(r"\s+", display_name.strip()) if part]
    if len(name_parts) >= 2:
        return f"{name_parts[0][0]}{name_parts[1][0]}".upper()[:12]
    if len(name_parts) == 1 and name_parts[0]:
        return name_parts[0][:2].upper()

    local_part = email.split("@", 1)[0]
    compact = "".join(part[:1] for part in re.split(r"[._+\-]+", local_part) if part)
    return compact[:2].upper() or "AD"


def _resolve_sqlite_path() -> Path:
    db_url = str(os.getenv("EXAM_GURU_DB_URL") or "").strip()
    if db_url.startswith("sqlite:///"):
        raw_path = db_url.removeprefix("sqlite:///")
        candidate = Path(raw_path)
        return candidate if candidate.is_absolute() else (PROJECT_ROOT / candidate).resolve()
    return DEFAULT_SQLITE_PATH


def _ensure_local_operation(sqlite_path: Path) -> None:
    environment = str(os.getenv("APP_ENV") or "development").strip().lower()
    if environment not in {"development", "dev", "local", "test"}:
        raise RuntimeError(
            f"Local account configuration is blocked while APP_ENV={environment!r}. "
            "Use this script only against the local development SQLite database."
        )
    if sqlite_path.resolve().parent != PROJECT_ROOT.resolve():
        raise RuntimeError(
            f"Refusing to modify SQLite database outside the project root: {sqlite_path}"
        )
    if not sqlite_path.exists():
        raise FileNotFoundError(
            f"SQLite database does not exist yet: {sqlite_path}. Start the backend once to initialize the schema first."
        )


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}


def _require_columns(columns: set[str], table_name: str, required: set[str]) -> None:
    missing = sorted(required - columns)
    if missing:
        raise RuntimeError(
            f"Table {table_name!r} is missing required columns: {', '.join(missing)}"
        )


def _row_to_dict(cursor: sqlite3.Cursor, row: sqlite3.Row | None) -> dict[str, object] | None:
    if row is None:
        return None
    return {str(description[0]): row[index] for index, description in enumerate(cursor.description or [])}


def _insert_record(connection: sqlite3.Connection, table_name: str, payload: dict[str, object]) -> None:
    columns = list(payload.keys())
    placeholders = ", ".join("?" for _ in columns)
    quoted_columns = ", ".join(columns)
    values = [payload[column] for column in columns]
    connection.execute(
        f"INSERT INTO {table_name} ({quoted_columns}) VALUES ({placeholders})",
        values,
    )


def _update_record(
    connection: sqlite3.Connection,
    table_name: str,
    *,
    payload: dict[str, object],
    where_clause: str,
    where_params: tuple[object, ...],
) -> None:
    assignments = ", ".join(f"{column} = ?" for column in payload)
    values = [payload[column] for column in payload]
    connection.execute(
        f"UPDATE {table_name} SET {assignments} WHERE {where_clause}",
        (*values, *where_params),
    )


def _set_premium_fields(now_iso: str) -> dict[str, object]:
    current_period_end = (datetime.now(UTC) + timedelta(days=PREMIUM_PERIOD_DAYS)).replace(microsecond=0).isoformat()
    return {
        "subscription_plan": "premium",
        "subscription_status": "active",
        "subscription_started_at": now_iso,
        "subscription_current_period_end": current_period_end,
        "subscription_trial_ends_at": None,
        "subscription_cancel_at_period_end": 0,
        "subscription_customer_ref": None,
        "subscription_price_id": None,
        "subscription_product_id": None,
    }


def _set_free_fields() -> dict[str, object]:
    return {
        "subscription_plan": "free",
        "subscription_status": "inactive",
        "subscription_started_at": None,
        "subscription_current_period_end": None,
        "subscription_trial_ends_at": None,
        "subscription_cancel_at_period_end": 0,
        "subscription_customer_ref": None,
        "subscription_price_id": None,
        "subscription_product_id": None,
    }


def _normalize_role(value: str | None) -> str:
    candidate = str(value or ADMIN_ROLE_STUDENT).strip().lower()
    return candidate or ADMIN_ROLE_STUDENT


def _normalize_admin_privileges(value: tuple[str, ...] | list[str] | None) -> str:
    if not value:
        return "[]"
    normalized = sorted({str(item).strip() for item in value if str(item).strip()})
    return json.dumps(normalized)


def _build_admin_expectation(role: str, raw_privileges_json: str | None) -> dict[str, object]:
    normalized_role = _normalize_role(role)
    try:
        explicit = json.loads(str(raw_privileges_json or "[]"))
    except json.JSONDecodeError:
        explicit = []
    explicit_set = {str(item).strip() for item in explicit if str(item).strip()}
    if normalized_role == ADMIN_ROLE_CONTENT_ADMIN:
        privileges = sorted(set(ADMIN_PRIVILEGES) | explicit_set)
    else:
        privileges = sorted(explicit_set)
    return {
        "account_role": normalized_role,
        "is_admin": bool(privileges),
        "privileges": privileges,
    }


def _ensure_user_account(
    connection: sqlite3.Connection,
    *,
    email: str,
    plan: str,
    subscription_status: str,
    account_role: str,
    admin_privileges_json: str,
) -> dict[str, object]:
    now_iso = _utc_now_iso()
    display_name = _normalize_display_name(email)
    user_columns = _table_columns(connection, "user_accounts")
    _require_columns(
        user_columns,
        "user_accounts",
        {
            "id",
            "email",
            "display_name",
            "is_active",
            "auth_status",
            "primary_auth_method",
            "billing_email",
            "subscription_plan",
            "subscription_status",
            "feature_access_overrides_json",
            "account_role",
            "admin_privileges_json",
        },
    )

    select_cursor = connection.execute(
        "SELECT * FROM user_accounts WHERE email = ?",
        (email,),
    )
    existing = _row_to_dict(select_cursor, select_cursor.fetchone())
    created = existing is None

    base_payload: dict[str, object] = {
        "email": email,
        "display_name": str((existing or {}).get("display_name") or display_name).strip() or display_name,
        "is_active": 1,
        "auth_status": "verified" if (existing or {}).get("email_verified_at") else "pending_verification",
        "primary_auth_method": "email_otp",
        "billing_email": email,
        "feature_access_overrides_json": "{}",
        "account_role": _normalize_role(account_role),
        "admin_privileges_json": admin_privileges_json,
        "last_active_at": (existing or {}).get("last_active_at") or (existing or {}).get("last_login_at") or now_iso,
        "updated_at": now_iso,
    }

    if plan == "premium" and subscription_status == "active":
        base_payload.update(_set_premium_fields(now_iso))
    else:
        base_payload.update(_set_free_fields())

    if created:
        insert_payload = {
            "email": base_payload["email"],
            "display_name": base_payload["display_name"],
            "is_active": base_payload["is_active"],
            "auth_status": "pending_verification",
            "primary_auth_method": base_payload["primary_auth_method"],
            "billing_email": base_payload["billing_email"],
            "subscription_plan": base_payload["subscription_plan"],
            "subscription_status": base_payload["subscription_status"],
            "subscription_customer_ref": base_payload["subscription_customer_ref"],
            "subscription_started_at": base_payload["subscription_started_at"],
            "subscription_current_period_end": base_payload["subscription_current_period_end"],
            "subscription_trial_ends_at": base_payload["subscription_trial_ends_at"],
            "subscription_cancel_at_period_end": base_payload["subscription_cancel_at_period_end"],
            "subscription_price_id": base_payload["subscription_price_id"],
            "subscription_product_id": base_payload["subscription_product_id"],
            "feature_access_overrides_json": base_payload["feature_access_overrides_json"],
            "account_role": base_payload["account_role"],
            "admin_privileges_json": base_payload["admin_privileges_json"],
            "created_at": now_iso,
            "updated_at": now_iso,
            "last_active_at": base_payload["last_active_at"],
        }
        _insert_record(connection, "user_accounts", insert_payload)
    else:
        _update_record(
            connection,
            "user_accounts",
            payload=base_payload,
            where_clause="email = ?",
            where_params=(email,),
        )

    select_cursor = connection.execute(
        "SELECT * FROM user_accounts WHERE email = ?",
        (email,),
    )
    user = _row_to_dict(select_cursor, select_cursor.fetchone())
    if user is None:
        raise RuntimeError(f"Failed to create or update local account {email}.")
    user["created"] = created
    return user


def _ensure_profile(connection: sqlite3.Connection, *, user: dict[str, object]) -> dict[str, object]:
    now_iso = _utc_now_iso()
    display_name = str(user.get("display_name") or "")
    email = str(user.get("email") or "")
    profile_columns = _table_columns(connection, "user_profiles")
    _require_columns(
        profile_columns,
        "user_profiles",
        {"user_id", "avatar_initials", "onboarding_state"},
    )
    select_cursor = connection.execute(
        "SELECT * FROM user_profiles WHERE user_id = ?",
        (user["id"],),
    )
    existing = _row_to_dict(select_cursor, select_cursor.fetchone())
    avatar_initials = _build_avatar_initials(display_name, email)

    if existing is None:
        payload = {
            "user_id": user["id"],
            "avatar_url": None,
            "avatar_initials": avatar_initials,
            "bio": None,
            "locale": None,
            "onboarding_state": "new",
            "onboarding_completed_at": None,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        _insert_record(connection, "user_profiles", payload)
    else:
        payload = {
            "avatar_initials": str(existing.get("avatar_initials") or "").strip() or avatar_initials,
            "onboarding_state": str(existing.get("onboarding_state") or "").strip() or "new",
            "updated_at": now_iso,
        }
        if payload["onboarding_state"] == "completed" and not existing.get("onboarding_completed_at"):
            payload["onboarding_completed_at"] = now_iso
        _update_record(
            connection,
            "user_profiles",
            payload=payload,
            where_clause="user_id = ?",
            where_params=(user["id"],),
        )

    select_cursor = connection.execute(
        "SELECT * FROM user_profiles WHERE user_id = ?",
        (user["id"],),
    )
    profile = _row_to_dict(select_cursor, select_cursor.fetchone())
    if profile is None:
        raise RuntimeError(f"Failed to ensure profile for {user['email']}.")
    return profile


def _ensure_settings(connection: sqlite3.Connection, *, user: dict[str, object]) -> dict[str, object]:
    now_iso = _utc_now_iso()
    settings_columns = _table_columns(connection, "user_settings")
    _require_columns(
        settings_columns,
        "user_settings",
        {
            "user_id",
            "theme_preference",
            "mentor_mode",
            "preferred_exam",
            "preferred_subject",
            "current_exam",
            "current_subject",
            "progress_digest_frequency",
            "billing_notifications_enabled",
        },
    )
    select_cursor = connection.execute(
        "SELECT * FROM user_settings WHERE user_id = ?",
        (user["id"],),
    )
    existing = _row_to_dict(select_cursor, select_cursor.fetchone())

    if existing is None:
        payload = {
            "user_id": user["id"],
            "theme_preference": "system",
            "mentor_mode": "normal",
            "preferred_exam": DEFAULT_EXAM,
            "preferred_subject": DEFAULT_SUBJECT,
            "current_exam": DEFAULT_EXAM,
            "current_subject": DEFAULT_SUBJECT,
            "timezone": None,
            "study_reminders_enabled": 1,
            "marketing_emails_enabled": 0,
            "progress_digest_frequency": "important_only",
            "billing_notifications_enabled": 1,
            "updated_at": now_iso,
        }
        _insert_record(connection, "user_settings", payload)
    else:
        payload = {
            "theme_preference": str(existing.get("theme_preference") or "").strip() or "system",
            "mentor_mode": str(existing.get("mentor_mode") or "").strip() or "normal",
            "preferred_exam": str(existing.get("preferred_exam") or "").strip() or DEFAULT_EXAM,
            "preferred_subject": str(existing.get("preferred_subject") or "").strip() or DEFAULT_SUBJECT,
            "current_exam": str(existing.get("current_exam") or "").strip() or DEFAULT_EXAM,
            "current_subject": str(existing.get("current_subject") or "").strip() or DEFAULT_SUBJECT,
            "progress_digest_frequency": str(existing.get("progress_digest_frequency") or "").strip() or "important_only",
            "billing_notifications_enabled": 1 if existing.get("billing_notifications_enabled") is None else existing.get("billing_notifications_enabled"),
            "updated_at": now_iso,
        }
        _update_record(
            connection,
            "user_settings",
            payload=payload,
            where_clause="user_id = ?",
            where_params=(user["id"],),
        )

    select_cursor = connection.execute(
        "SELECT * FROM user_settings WHERE user_id = ?",
        (user["id"],),
    )
    settings = _row_to_dict(select_cursor, select_cursor.fetchone())
    if settings is None:
        raise RuntimeError(f"Failed to ensure settings for {user['email']}.")
    return settings


def _account_summary(user: dict[str, object], profile: dict[str, object], settings: dict[str, object]) -> dict[str, object]:
    plan = str(user.get("subscription_plan") or "free").strip().lower()
    status = str(user.get("subscription_status") or "inactive").strip().lower()
    plan_current = plan == "free" or status in {"active", "trial"} or plan == "internal"
    return {
        "created": bool(user.get("created")),
        "email": user.get("email"),
        "display_name": user.get("display_name"),
        "is_active": bool(user.get("is_active")),
        "auth_status": user.get("auth_status"),
        "primary_auth_method": user.get("primary_auth_method"),
        "billing_email": user.get("billing_email"),
        "subscription_plan": user.get("subscription_plan"),
        "subscription_status": user.get("subscription_status"),
        "subscription_started_at": user.get("subscription_started_at"),
        "subscription_current_period_end": user.get("subscription_current_period_end"),
        "subscription_trial_ends_at": user.get("subscription_trial_ends_at"),
        "subscription_cancel_at_period_end": bool(user.get("subscription_cancel_at_period_end")),
        "account_role": user.get("account_role"),
        "admin_privileges_json": user.get("admin_privileges_json"),
        "feature_access_overrides_json": user.get("feature_access_overrides_json"),
        "profile": {
            "avatar_initials": profile.get("avatar_initials"),
            "onboarding_state": profile.get("onboarding_state"),
            "onboarding_completed_at": profile.get("onboarding_completed_at"),
        },
        "settings": {
            "preferred_exam": settings.get("preferred_exam"),
            "preferred_subject": settings.get("preferred_subject"),
            "current_exam": settings.get("current_exam"),
            "current_subject": settings.get("current_subject"),
            "mentor_mode": settings.get("mentor_mode"),
            "theme_preference": settings.get("theme_preference"),
        },
        "entitlement_expectation": {
            "plan_tier": plan,
            "plan_current": plan_current,
            "lesson_exports": bool(plan == "premium" and status in {"active", "trial"}),
            "premium_lesson_modes": bool(plan == "premium" and status in {"active", "trial"}),
            "advanced_analytics": bool(plan == "premium" and status in {"active", "trial"}),
        },
        "admin_expectation": _build_admin_expectation(
            str(user.get("account_role") or ADMIN_ROLE_STUDENT),
            str(user.get("admin_privileges_json") or "[]"),
        ),
    }


def configure_account(
    connection: sqlite3.Connection,
    *,
    email: str,
    plan: str,
    subscription_status: str,
    account_role: str = ADMIN_ROLE_STUDENT,
    admin_privileges: tuple[str, ...] | list[str] | None = None,
) -> dict[str, object]:
    normalized_email = _normalize_email(email)
    user = _ensure_user_account(
        connection,
        email=normalized_email,
        plan=plan,
        subscription_status=subscription_status,
        account_role=account_role,
        admin_privileges_json=_normalize_admin_privileges(admin_privileges),
    )
    profile = _ensure_profile(connection, user=user)
    settings = _ensure_settings(connection, user=user)
    return _account_summary(user, profile, settings)


def main() -> int:
    sqlite_path = _resolve_sqlite_path()
    _ensure_local_operation(sqlite_path)

    configured_at = _utc_now_iso()
    with sqlite3.connect(sqlite_path, timeout=5) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        accounts = {
            "premium_admin_account": configure_account(
                connection,
                email=PREMIUM_EMAIL,
                plan="premium",
                subscription_status="active",
                account_role=ADMIN_ROLE_CONTENT_ADMIN,
            ),
            "premium_learner_account": configure_account(
                connection,
                email=SECOND_PREMIUM_EMAIL,
                plan="premium",
                subscription_status="active",
                account_role=ADMIN_ROLE_STUDENT,
            ),
            "default_free_account": configure_account(
                connection,
                email=FREE_EMAIL,
                plan="free",
                subscription_status="inactive",
                account_role=ADMIN_ROLE_STUDENT,
            ),
        }
        connection.commit()

    print(
        json.dumps(
            {
                "configured_at": configured_at,
                "sqlite_path": sqlite_path.as_posix(),
                "accounts": accounts,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
