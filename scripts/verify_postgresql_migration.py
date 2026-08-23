from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from backend.models import MediaRenderJob, Quiz, QuizAttempt, TopicProgress, UserAccount, UserSession
from backend.services.plan_service import user_has_entitlement
from migrations.runtime import get_migration_target


def main() -> int:
    target = get_migration_target()
    engine = create_engine(target.url, poolclass=NullPool, hide_parameters=True, future=True)
    now = datetime.now(UTC)
    tracked_models = (UserAccount, UserSession, Quiz, QuizAttempt, TopicProgress, MediaRenderJob)

    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            session = Session(bind=connection)
            try:
                before = {model.__tablename__: session.scalar(select(func.count()).select_from(model)) for model in tracked_models}
                user = UserAccount(
                    email="migration-smoke@example.invalid",
                    display_name="Migration Smoke",
                    is_active=True,
                    auth_status="verified",
                    primary_auth_method="email_otp",
                    subscription_plan="premium",
                    subscription_status="active",
                    subscription_started_at=now,
                    subscription_current_period_end=now + timedelta(days=30),
                    subscription_cancel_at_period_end=False,
                    feature_access_overrides_json="{}",
                    account_role="student",
                    admin_privileges_json="[]",
                    created_at=now,
                    updated_at=now,
                )
                session.add(user)
                session.flush()

                session.add(
                    UserSession(
                        user_id=user.id,
                        session_token_hash="0" * 128,
                        auth_method="email_otp",
                        created_at=now,
                        last_authenticated_at=now,
                        last_seen_at=now,
                        expires_at=now + timedelta(hours=1),
                    )
                )
                quiz = Quiz(
                    user_id=user.id,
                    exam="upsc",
                    subject="polity",
                    chapter="Constitution",
                    topic="Preamble",
                    difficulty="medium",
                    quiz_mode="test",
                    question_count=1,
                    questions_json=json.dumps([{"id": 1}]),
                    created_at=now,
                )
                session.add(quiz)
                session.flush()
                session.add(
                    QuizAttempt(
                        quiz_id=quiz.id,
                        user_id=user.id,
                        exam="upsc",
                        subject="polity",
                        chapter="Constitution",
                        topic="Preamble",
                        difficulty="medium",
                        quiz_mode="test",
                        submitted_answers_json="[]",
                        score=1,
                        total_questions=1,
                        accuracy=100.0,
                        incorrect_questions_json="[]",
                        weak_areas_json="[]",
                        topic_breakdown_json="[]",
                        next_recommendation="Continue",
                        created_at=now,
                    )
                )
                session.add(
                    TopicProgress(
                        user_id=user.id,
                        exam="upsc",
                        subject="polity",
                        chapter="Constitution",
                        topic="Preamble",
                        attempts_count=1,
                        correct_answers=1,
                        total_answers=1,
                        accuracy=100.0,
                        difficulty_band="medium",
                        weak_topic=False,
                        last_attempt_at=now,
                    )
                )
                session.add(
                    MediaRenderJob(
                        user_id=user.id,
                        exam="upsc",
                        subject="polity",
                        chapter="Constitution",
                        topic="Preamble",
                        render_type="audio",
                        lifecycle_state="queued",
                        source_content_fallback_used=False,
                        attempt_count=0,
                        max_attempts=3,
                        request_metadata_json="{}",
                        dispatch_payload_json="{}",
                        output_metadata_json="{}",
                        artifact_cleanup_failure_count=0,
                        created_at=now,
                        updated_at=now,
                    )
                )
                session.flush()

                assert user_has_entitlement(user, "premium_lesson_modes") is True
                for model in tracked_models:
                    current = session.scalar(select(func.count()).select_from(model))
                    assert current == before[model.__tablename__] + 1
                print("POSTGRESQL_MIGRATION_SMOKE=PASS")
                print("COMPONENTS=authentication,session,quiz,progress,entitlement,media_job")
            finally:
                session.close()
                transaction.rollback()

        with engine.connect() as connection:
            with Session(bind=connection) as session:
                after = {model.__tablename__: session.scalar(select(func.count()).select_from(model)) for model in tracked_models}
        assert after == before
        print("ROLLBACK_PRESERVED_COUNTS=true")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
