from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from backend.models import UserAccount
from backend.services.ops_logging import log_event, request_log_context


logger = logging.getLogger(__name__)

ADMIN_ROLE_STUDENT = "student"
ADMIN_ROLE_REVIEWER = "content_reviewer"
ADMIN_ROLE_ADMIN = "content_admin"
ADMIN_ROLE_OWNER = "owner"

ADMIN_PRIVILEGES = frozenset(
    {
        "content_read",
        "content_write",
        "content_review",
        "content_publish",
        "content_import",
        "content_qa",
    }
)

ROLE_PRIVILEGES: dict[str, frozenset[str]] = {
    ADMIN_ROLE_STUDENT: frozenset(),
    ADMIN_ROLE_REVIEWER: frozenset({"content_read", "content_review", "content_qa"}),
    ADMIN_ROLE_ADMIN: frozenset(ADMIN_PRIVILEGES),
    ADMIN_ROLE_OWNER: frozenset(ADMIN_PRIVILEGES),
}

ROLE_ALIASES = {
    "learner": ADMIN_ROLE_STUDENT,
    "user": ADMIN_ROLE_STUDENT,
    "reviewer": ADMIN_ROLE_REVIEWER,
    "editor": ADMIN_ROLE_ADMIN,
    "admin": ADMIN_ROLE_ADMIN,
    "staff": ADMIN_ROLE_ADMIN,
    "superadmin": ADMIN_ROLE_OWNER,
}


def normalize_account_role(raw_role: str | None) -> str:
    candidate = str(raw_role or ADMIN_ROLE_STUDENT).strip().lower()
    if candidate in ROLE_PRIVILEGES:
        return candidate
    return ROLE_ALIASES.get(candidate, ADMIN_ROLE_STUDENT)


def parse_admin_privileges(raw_value: str | None) -> set[str]:
    candidate = str(raw_value or "").strip()
    if not candidate:
        return set()

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return set()

    if isinstance(parsed, list):
        return {str(item).strip() for item in parsed if str(item).strip() in ADMIN_PRIVILEGES}

    if isinstance(parsed, dict):
        return {
            str(key).strip()
            for key, value in parsed.items()
            if bool(value) and str(key).strip() in ADMIN_PRIVILEGES
        }

    return set()


def build_admin_access(user: UserAccount | None) -> dict[str, Any]:
    role = normalize_account_role(getattr(user, "account_role", None) if user is not None else None)
    role_privileges = set(ROLE_PRIVILEGES.get(role, frozenset()))
    explicit_privileges = parse_admin_privileges(
        getattr(user, "admin_privileges_json", None) if user is not None else None
    )
    privileges = sorted(role_privileges | explicit_privileges)
    is_admin = bool(privileges)
    can_manage_content = any(
        privilege in privileges
        for privilege in ("content_write", "content_review", "content_publish", "content_import")
    )
    source = "role_plus_explicit_privileges" if explicit_privileges else "role"
    access_note = (
        "Admin content tools are available for this account."
        if is_admin
        else "Student account; admin tools are not available."
    )
    return {
        "role": role,
        "is_admin": is_admin,
        "privileges": privileges,
        "can_manage_content": can_manage_content,
        "source": source,
        "access_note": access_note,
    }


def user_has_admin_privilege(user: UserAccount | None, privilege: str = "content_read") -> bool:
    required_privilege = str(privilege or "content_read").strip()
    if required_privilege not in ADMIN_PRIVILEGES:
        return False
    access = build_admin_access(user)
    return bool(access["is_admin"] and required_privilege in access["privileges"])


def _admin_denied_detail(user: UserAccount | None, *, privilege: str) -> dict[str, Any]:
    access = build_admin_access(user)
    return {
        "message": "Admin access is required for this internal content operation.",
        "required_privilege": privilege,
        "account_role": access["role"],
        "admin_access": access["is_admin"],
    }


def require_admin_user(user: UserAccount | None, privilege: str = "content_read") -> dict[str, Any]:
    required_privilege = str(privilege or "content_read").strip()
    if required_privilege not in ADMIN_PRIVILEGES:
        required_privilege = "content_read"

    if user is None:
        raise HTTPException(status_code=401, detail="You need to sign in first.")

    access = build_admin_access(user)
    if required_privilege in access["privileges"]:
        return access

    raise HTTPException(
        status_code=403,
        detail=_admin_denied_detail(user, privilege=required_privilege),
    )


def require_admin_auth_context(
    db: Session,
    request: Request,
    *,
    privilege: str = "content_read",
) -> dict[str, Any]:
    from backend.services.auth_service import require_current_auth_context

    context = require_current_auth_context(db, request)
    access = require_admin_user(context["user"], privilege=privilege)
    context["admin_access"] = access
    log_event(
        logger,
        logging.INFO,
        "admin.access_granted",
        **request_log_context(request),
        user_id=context["user"].id,
        account_role=access["role"],
        required_privilege=privilege,
    )
    return context
