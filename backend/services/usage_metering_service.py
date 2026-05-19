from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models import UsageConsumptionRecord, UserAccount
from backend.services.lesson_export_service import normalize_lesson_export_format
from backend.services.plan_service import USAGE_LIMIT_DEFINITIONS, require_authenticated_entitlement
from backend.services.subscription_reconciliation_service import reconcile_subscription_entitlements_and_quotas


USAGE_METERING_VERSION = "phase29_usage_meter_v1"
PREMIUM_LESSON_MODES = frozenset({"video_lecture", "revision_video", "crash_course_video"})
PREMIUM_EXPORT_FORMATS = frozenset({"json_export", "slide_outline_export", "audio_script_export"})
TUTOR_USAGE_ACTIONS = frozenset({"tutor.explain", "lesson.export", "media_render.audio_create", "media_render.video_create"})


@dataclass(frozen=True)
class UsageQuotaSnapshot:
    limit_key: str
    label: str
    description: str
    plan_tier: str
    subscription_status: str
    plan_current: bool
    limit_value: int | None
    unlimited: bool
    consumed_units: int
    remaining_units: int | None
    units_requested: int
    period_start: datetime
    period_end: datetime
    feature_key: str | None
    required_plan: str | None
    entitlement_enabled: bool
    source: str


@dataclass(frozen=True)
class UsageQuotaRequirement:
    limit_key: str
    units_requested: int = 1


def _ensure_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _monthly_usage_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    anchor = _ensure_utc_datetime(now) or datetime.now(UTC)
    period_start = anchor.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if period_start.month == 12:
        period_end = period_start.replace(year=period_start.year + 1, month=1)
    else:
        period_end = period_start.replace(month=period_start.month + 1)
    return period_start, period_end


def _serialize_metadata(metadata: dict[str, Any] | None) -> str:
    try:
        return json.dumps(metadata or {}, ensure_ascii=True, sort_keys=True)
    except (TypeError, ValueError):
        return "{}"


def normalize_usage_lesson_mode(lesson_mode: str | None) -> str:
    return str(lesson_mode or "").strip().lower()


def _usage_limit_payload_for_user(
    user: UserAccount,
    limit_key: str,
    *,
    summary: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved_summary = summary or reconcile_subscription_entitlements_and_quotas(user).entitlement_summary
    usage_limit = resolved_summary["usage_policy"]["limits"].get(limit_key)
    if usage_limit is None or limit_key not in USAGE_LIMIT_DEFINITIONS:
        raise ValueError(f"Unknown usage limit key '{limit_key}'.")
    return resolved_summary, usage_limit


def build_tutor_usage_requirements(
    *,
    action_name: str,
    lesson_mode: str | None = None,
    export_format: str | None = None,
) -> list[UsageQuotaRequirement]:
    normalized_action = str(action_name or "").strip().lower()
    if normalized_action not in TUTOR_USAGE_ACTIONS:
        raise ValueError(f"Unsupported tutor usage action '{action_name}'.")

    requirements: list[UsageQuotaRequirement] = []
    normalized_lesson_mode = normalize_usage_lesson_mode(lesson_mode)
    normalized_export_format = normalize_lesson_export_format(export_format) if export_format is not None else None

    if normalized_action == "tutor.explain" and normalized_lesson_mode in PREMIUM_LESSON_MODES:
        requirements.append(UsageQuotaRequirement(limit_key="premium_lesson_mode_generations"))

    if normalized_action == "lesson.export" and normalized_export_format in PREMIUM_EXPORT_FORMATS:
        requirements.append(UsageQuotaRequirement(limit_key="advanced_lesson_exports"))

    if normalized_action in {"media_render.audio_create", "media_render.video_create"}:
        requirements.append(UsageQuotaRequirement(limit_key="media_render_creations"))

    return requirements


def build_usage_quota_snapshot(
    db: Session,
    *,
    user: UserAccount,
    limit_key: str,
    units_requested: int = 1,
    now: datetime | None = None,
) -> UsageQuotaSnapshot:
    if units_requested < 1:
        raise ValueError("Usage consumption must request at least one unit.")

    reconciliation = reconcile_subscription_entitlements_and_quotas(user, now=now)
    if reconciliation.changed:
        db.add(user)

    summary, usage_limit = _usage_limit_payload_for_user(
        user,
        limit_key,
        summary=reconciliation.entitlement_summary,
    )
    period_start, period_end = _monthly_usage_window(now)
    consumed_units = int(
        db.query(func.coalesce(func.sum(UsageConsumptionRecord.units_consumed), 0))
        .filter(
            UsageConsumptionRecord.user_id == user.id,
            UsageConsumptionRecord.limit_key == limit_key,
            UsageConsumptionRecord.created_at >= period_start,
            UsageConsumptionRecord.created_at < period_end,
        )
        .scalar()
        or 0
    )
    limit_value = usage_limit.get("limit")
    unlimited = limit_value is None
    remaining_units = None if unlimited else max(int(limit_value) - consumed_units, 0)

    return UsageQuotaSnapshot(
        limit_key=limit_key,
        label=str(usage_limit.get("label") or limit_key.replace("_", " ")),
        description=str(usage_limit.get("description") or ""),
        plan_tier=str(summary["plan_tier"]),
        subscription_status=str(summary["subscription_status"]),
        plan_current=bool(summary["plan_current"]),
        limit_value=None if limit_value is None else int(limit_value),
        unlimited=unlimited,
        consumed_units=consumed_units,
        remaining_units=remaining_units,
        units_requested=units_requested,
        period_start=period_start,
        period_end=period_end,
        feature_key=usage_limit.get("feature_key"),
        required_plan=usage_limit.get("required_plan"),
        entitlement_enabled=bool(usage_limit.get("entitlement_enabled", True)),
        source=str(usage_limit.get("source") or "plan"),
    )


def ensure_usage_available(
    db: Session,
    *,
    user: UserAccount,
    limit_key: str,
    units_requested: int = 1,
    now: datetime | None = None,
) -> UsageQuotaSnapshot:
    snapshot = build_usage_quota_snapshot(
        db,
        user=user,
        limit_key=limit_key,
        units_requested=units_requested,
        now=now,
    )
    if snapshot.unlimited:
        return snapshot

    if snapshot.limit_value is not None and snapshot.consumed_units + units_requested <= snapshot.limit_value:
        return snapshot

    raise HTTPException(
        status_code=429,
        detail={
            "message": f"You've reached this month's {snapshot.label.lower()} limit.",
            "usage_limit_reached": True,
            "limit_key": snapshot.limit_key,
            "limit_label": snapshot.label,
            "feature_key": snapshot.feature_key,
            "required_plan": snapshot.required_plan,
            "sign_in_required": False,
            "upgrade_required": False,
            "limit": snapshot.limit_value,
            "consumed": snapshot.consumed_units,
            "remaining": snapshot.remaining_units,
            "reset_period": "monthly",
            "reset_at": snapshot.period_end.isoformat(),
        },
    )


def enforce_tutor_action_access_and_quota(
    db: Session,
    *,
    user: UserAccount | None,
    action_name: str,
    lesson_mode: str | None = None,
    export_format: str | None = None,
) -> dict[str, UsageQuotaSnapshot]:
    normalized_action = str(action_name or "").strip().lower()
    normalized_lesson_mode = normalize_usage_lesson_mode(lesson_mode)
    normalized_export_format = normalize_lesson_export_format(export_format) if export_format is not None else None

    if normalized_action == "tutor.explain" and normalized_lesson_mode in PREMIUM_LESSON_MODES:
        require_authenticated_entitlement(user, "premium_lesson_modes")

    if normalized_action == "media_render.video_create":
        require_authenticated_entitlement(user, "premium_lesson_modes")

    if normalized_action in {"lesson.export", "media_render.audio_create", "media_render.video_create"} and normalized_lesson_mode in PREMIUM_LESSON_MODES:
        require_authenticated_entitlement(user, "premium_lesson_modes")

    if normalized_export_format in PREMIUM_EXPORT_FORMATS:
        require_authenticated_entitlement(user, "lesson_exports")

    if user is None:
        return {}

    requirements = build_tutor_usage_requirements(
        action_name=action_name,
        lesson_mode=normalized_lesson_mode,
        export_format=normalized_export_format,
    )
    return {
        requirement.limit_key: ensure_usage_available(
            db,
            user=user,
            limit_key=requirement.limit_key,
            units_requested=requirement.units_requested,
        )
        for requirement in requirements
    }


def record_usage_consumption(
    db: Session,
    *,
    user: UserAccount,
    limit_key: str,
    source_action: str,
    quota_snapshot: UsageQuotaSnapshot | None = None,
    units_consumed: int = 1,
    exam: str | None = None,
    subject: str | None = None,
    content_subject: str | None = None,
    chapter: str | None = None,
    topic: str | None = None,
    lesson_mode: str | None = None,
    export_format: str | None = None,
    render_type: str | None = None,
    media_render_job_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> UsageConsumptionRecord:
    snapshot = quota_snapshot or build_usage_quota_snapshot(db, user=user, limit_key=limit_key, units_requested=units_consumed)
    record = UsageConsumptionRecord(
        user_id=user.id,
        limit_key=limit_key,
        source_action=str(source_action or limit_key)[:120],
        units_consumed=max(int(units_consumed), 1),
        plan_tier=snapshot.plan_tier,
        subscription_status=snapshot.subscription_status,
        exam=exam,
        subject=subject,
        content_subject=content_subject,
        chapter=chapter,
        topic=topic,
        lesson_mode=lesson_mode,
        export_format=export_format,
        render_type=render_type,
        media_render_job_id=media_render_job_id,
        metadata_json=_serialize_metadata(
            {
                "usage_metering_version": USAGE_METERING_VERSION,
                **(metadata or {}),
            }
        ),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def record_tutor_action_usage(
    db: Session,
    *,
    user: UserAccount,
    action_name: str,
    quota_snapshots: dict[str, UsageQuotaSnapshot],
    lesson: dict[str, Any],
    export_format: str | None = None,
    render_type: str | None = None,
    media_render_job_id: int | None = None,
) -> None:
    if not quota_snapshots:
        return

    common_kwargs = {
        "exam": lesson.get("exam"),
        "subject": lesson.get("subject"),
        "content_subject": lesson.get("content_subject"),
        "chapter": lesson.get("chapter"),
        "topic": lesson.get("topic"),
        "lesson_mode": lesson.get("lesson_mode"),
        "metadata": {
            "content_item_id": lesson.get("content_item_id"),
            "content_source_scope": lesson.get("content_source_scope"),
            "content_fallback_used": bool(lesson.get("content_fallback_used")),
        },
    }

    premium_mode_snapshot = quota_snapshots.get("premium_lesson_mode_generations")
    if premium_mode_snapshot is not None:
        record_usage_consumption(
            db,
            user=user,
            limit_key="premium_lesson_mode_generations",
            source_action=action_name,
            quota_snapshot=premium_mode_snapshot,
            **common_kwargs,
        )

    export_snapshot = quota_snapshots.get("advanced_lesson_exports")
    if export_snapshot is not None:
        record_usage_consumption(
            db,
            user=user,
            limit_key="advanced_lesson_exports",
            source_action=action_name,
            quota_snapshot=export_snapshot,
            export_format=export_format,
            **common_kwargs,
        )

    render_snapshot = quota_snapshots.get("media_render_creations")
    if render_snapshot is not None:
        record_usage_consumption(
            db,
            user=user,
            limit_key="media_render_creations",
            source_action=action_name,
            quota_snapshot=render_snapshot,
            export_format=export_format,
            render_type=render_type,
            media_render_job_id=media_render_job_id,
            **common_kwargs,
        )
