from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / ".deps"))

from backend.db import Base
from backend.models import Quiz, QuizAttempt, TopicStudy
from backend.services.coach_service import (
    _build_adaptive_guidance_sentence,
    build_accountability_warnings,
    build_coach_summary,
    build_daily_plan,
    build_performance_trends,
    build_progress_summary_snapshot,
    build_revision_due_snapshot,
)
from backend.services.recommendation_service import build_study_recommendation, build_topic_priority_list
from backend.services.progress_service import record_attempt, sync_topic_progress


def build_test_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return testing_session()


def create_quiz_row(
    db,
    topic: str,
    difficulty: str = "medium",
    question_count: int = 5,
    subject: str = "polity",
    chapter: str = "General",
) -> Quiz:
    quiz = Quiz(topic=topic, chapter=chapter, subject=subject, difficulty=difficulty, question_count=question_count, questions_json="[]")
    db.add(quiz)
    db.commit()
    db.refresh(quiz)
    return quiz


def create_attempt(
    db,
    *,
    topic: str,
    score: int,
    total_questions: int = 5,
    difficulty: str = "medium",
    created_at: datetime | None = None,
    subject: str = "polity",
    chapter: str = "General",
    weak_areas: list[str] | None = None,
) -> QuizAttempt:
    quiz = create_quiz_row(db, topic=topic, difficulty=difficulty, question_count=total_questions, subject=subject, chapter=chapter)
    attempt = record_attempt(
        db=db,
        quiz_id=quiz.id,
        topic=topic,
        difficulty=difficulty,
        answers=[f"Answer {index}" for index in range(total_questions)],
        score=score,
        total_questions=total_questions,
        incorrect_questions=[],
        weak_areas=weak_areas if weak_areas is not None else ([] if score == total_questions else [topic]),
        next_recommendation="Review the topic once and try another quiz.",
        subject=subject,
        chapter=chapter,
    )
    if created_at is not None:
        attempt.created_at = created_at
        db.query(QuizAttempt).filter(QuizAttempt.id == attempt.id).update({QuizAttempt.created_at: created_at})
        db.query(Quiz).filter(Quiz.id == quiz.id).update({Quiz.created_at: created_at})
        db.query(TopicStudy).filter(TopicStudy.subject == subject, TopicStudy.topic == topic).update({TopicStudy.last_interaction_at: created_at})
        db.commit()
        sync_topic_progress(db, topic=topic, subject=subject, chapter=chapter)
    return attempt

def test_daily_plan_prioritizes_overdue_weak_topic() -> None:
    db = build_test_session()
    try:
        two_days_ago = datetime.now(UTC) - timedelta(days=2)
        create_attempt(db, topic="Federalism", score=1, created_at=two_days_ago)
        summary = build_progress_summary_snapshot(db)
        revision_due = build_revision_due_snapshot(db, summary=summary)
        plan = build_daily_plan(db, summary=summary, revision_due=revision_due)

        assert plan["focus_topic"] == "Federalism"
        assert "Federalism" in plan["focus_reason"]
        assert plan["quiz_action"]
    finally:
        db.close()


def test_revision_due_groups_split_overdue_and_due_now() -> None:
    db = build_test_session()
    try:
        db.add(
            TopicStudy(
                topic="Preamble",
                subject="polity",
                study_count=1,
                last_interaction_at=datetime.now(UTC),
            )
        )
        db.commit()
        create_attempt(db, topic="Citizenship", score=1, created_at=datetime.now(UTC) - timedelta(days=2))

        summary = build_progress_summary_snapshot(db)
        revision_due = build_revision_due_snapshot(db, summary=summary)

        assert any(item["topic"] == "Citizenship" for item in revision_due["overdue"])
        assert any(item["topic"] == "Preamble" for item in revision_due["due_now"])
    finally:
        db.close()


def test_performance_trends_detect_decline() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Parliament", score=5, created_at=now - timedelta(days=6))
        create_attempt(db, topic="Parliament", score=5, created_at=now - timedelta(days=5))
        create_attempt(db, topic="Parliament", score=4, created_at=now - timedelta(days=4))
        create_attempt(db, topic="Parliament", score=2, created_at=now - timedelta(days=3))
        create_attempt(db, topic="Parliament", score=1, created_at=now - timedelta(days=2))
        create_attempt(db, topic="Parliament", score=1, created_at=now - timedelta(days=1))

        trends = build_performance_trends(db)

        assert trends["overall_trend"] == "declining"
        assert trends["topics"][0]["trend"] == "declining"
    finally:
        db.close()


def test_progress_summary_prioritizes_recent_weak_area_from_latest_quiz() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Parliament", score=5, created_at=now - timedelta(days=3))
        create_attempt(db, topic="Parliament", score=5, created_at=now - timedelta(days=2))
        create_attempt(db, topic="Parliament", score=2, created_at=now - timedelta(hours=2))

        summary = build_progress_summary_snapshot(db)
        daily_plan = build_daily_plan(db, summary=summary)
        coach_summary = build_coach_summary(db, summary=summary, daily_plan=daily_plan)

        assert summary["recent_weak_areas"] == ["Parliament"]
        assert summary["recommendation_source"] == "weak_area"
        assert summary["recommended_next_topic"] == "Parliament"
        assert "latest quiz" in summary["recommended_next_reason"].lower()
        assert daily_plan["focus_topic"] == "Parliament"
        assert coach_summary["study_today"] == "Parliament"
        assert coach_summary["weak_areas"][0] == "Parliament"
    finally:
        db.close()


def test_progress_summary_builds_revision_first_study_profile() -> None:
    db = build_test_session()
    try:
        create_attempt(db, topic="Federalism", score=1, created_at=datetime.now(UTC) - timedelta(days=3))

        summary = build_progress_summary_snapshot(db)

        assert summary["study_profile"]["readiness_status"] == "revision_first"
        assert summary["study_profile"]["profile_title"] == "Revision-first profile"
        assert summary["study_profile"]["top_risk_topic"] == "Federalism"
        assert summary["study_profile"]["next_focus_topic"] == "Federalism"
    finally:
        db.close()



def test_progress_summary_builds_stable_study_profile_for_strong_subject_base() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=12))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=8))
        create_attempt(db, topic="Citizenship", score=5, created_at=now - timedelta(hours=4))
        create_attempt(db, topic="Citizenship", score=5, created_at=now - timedelta(hours=2))

        summary = build_progress_summary_snapshot(db)

        assert summary["study_profile"]["readiness_status"] in {"steady", "ready"}
        assert summary["study_profile"]["profile_title"] in {"Balanced progress profile", "Stable progress profile"}
        assert summary["study_profile"]["top_strength_topic"] in {"Preamble", "Citizenship"}
    finally:
        db.close()


def test_recent_weak_areas_stay_subject_scoped() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Parliament", score=5, created_at=now - timedelta(days=2), subject="polity")
        create_attempt(db, topic="Parliament", score=2, created_at=now - timedelta(hours=3), subject="polity")
        create_attempt(db, topic="Indian National Congress", score=1, created_at=now - timedelta(hours=1), subject="history")

        polity_summary = build_progress_summary_snapshot(db, subject="polity")
        history_summary = build_progress_summary_snapshot(db, subject="history")

        assert polity_summary["recent_weak_areas"] == ["Parliament"]
        assert history_summary["recent_weak_areas"] == ["Indian National Congress"]
        assert history_summary["recommended_next_topic"] == "Indian National Congress"
        assert "Indian National Congress" not in polity_summary["recent_weak_areas"]
    finally:
        db.close()

def test_subject_difficulty_profile_stays_subject_scoped() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(days=4), subject="polity")
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(days=3), subject="polity")
        create_attempt(db, topic="Citizenship", score=5, created_at=now - timedelta(days=2), subject="polity")
        create_attempt(db, topic="Citizenship", score=5, created_at=now - timedelta(days=1), subject="polity")
        create_attempt(db, topic="Indian National Congress", score=1, created_at=now - timedelta(days=3), subject="history")
        create_attempt(db, topic="Revolt of 1857", score=1, created_at=now - timedelta(days=1), subject="history")

        polity_summary = build_progress_summary_snapshot(db, subject="polity")
        history_summary = build_progress_summary_snapshot(db, subject="history")

        assert polity_summary["subject_difficulty_band"] in {"medium", "hard"}
        assert polity_summary["subject_adaptive_state"] in {"steady", "challenge"}
        assert history_summary["subject_difficulty_band"] == "easy"
        assert history_summary["subject_adaptive_state"] == "recovery"
    finally:
        db.close()



def test_version8_ranked_weak_topics_stay_aligned_with_topic_strength() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=8))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=2))
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=1))

        summary = build_progress_summary_snapshot(db)
        topic_lookup = {item["topic"]: item for item in summary["topic_accuracy"]}
        ranked_weak_topics = {item["topic"] for item in summary["ranked_weak_topics"]}

        assert topic_lookup["Preamble"]["topic_strength"] != "weak"
        assert "Preamble" not in summary["weak_topics"]
        assert "Preamble" not in ranked_weak_topics
        assert topic_lookup["Federalism"]["topic_strength"] == "weak"
        assert "Federalism" in ranked_weak_topics
    finally:
        db.close()



def test_version8_retention_risk_aligns_with_revision_and_guidance() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=3))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=3))

        summary = build_progress_summary_snapshot(db)
        revision_due = build_revision_due_snapshot(db, summary=summary)
        daily_plan = build_daily_plan(db, summary=summary, revision_due=revision_due)
        coach_summary = build_coach_summary(db, summary=summary, revision_due=revision_due)
        topic_lookup = {item["topic"]: item for item in summary["topic_accuracy"]}
        revision_topics = {item["topic"] for item in revision_due["overdue"] + revision_due["due_now"]}

        assert topic_lookup["Federalism"]["retention_risk"] == "high"
        assert topic_lookup["Federalism"]["revision_signal"] in {"at_risk", "due_now"}
        assert "Federalism" in summary["at_risk_topics"] or "Federalism" in summary["due_now_topics"]
        assert "Federalism" in revision_topics
        assert summary["recommended_next_topic"] == "Federalism"
        assert daily_plan["focus_topic"] == "Federalism"
        assert coach_summary["study_today"] == "Federalism"
    finally:
        db.close()



def test_version8_trend_direction_stays_aligned_across_summary_trends_and_coach() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Parliament", score=5, created_at=now - timedelta(days=6))
        create_attempt(db, topic="Parliament", score=5, created_at=now - timedelta(days=5))
        create_attempt(db, topic="Parliament", score=4, created_at=now - timedelta(days=4))
        create_attempt(db, topic="Parliament", score=2, created_at=now - timedelta(days=3))
        create_attempt(db, topic="Parliament", score=1, created_at=now - timedelta(days=2))
        create_attempt(db, topic="Parliament", score=1, created_at=now - timedelta(days=1))

        summary = build_progress_summary_snapshot(db)
        trends = build_performance_trends(db, summary=summary)
        coach_summary = build_coach_summary(db, summary=summary, trends=trends)

        assert summary["study_profile"]["trend_direction"] == trends["overall_trend"]
        assert coach_summary["trend_status"] == trends["overall_trend"]
    finally:
        db.close()


def test_coach_summary_exposes_constructive_warnings() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Directive Principles", score=1, created_at=now - timedelta(days=3))
        create_attempt(db, topic="Directive Principles", score=2, created_at=now - timedelta(days=2))
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=1))

        summary = build_progress_summary_snapshot(db)
        revision_due = build_revision_due_snapshot(db, summary=summary)
        trends = build_performance_trends(db, summary=summary)
        warnings = build_accountability_warnings(db, summary=summary, revision_due=revision_due, trends=trends)
        coach_summary = build_coach_summary(db, summary=summary, revision_due=revision_due, trends=trends)

        assert warnings
        assert coach_summary["warnings"]
        assert all(item["severity"] in {"gentle", "moderate", "strong"} for item in warnings)
        assert coach_summary["accountability_summary"]["warning_severity"] in {"none", "gentle", "moderate", "strong"}
        assert coach_summary["trend_status"] in {"improving", "stable", "declining"}
        assert coach_summary["study_today"]
        assert coach_summary["study_reason"]
        assert "revise_now" in coach_summary
        assert "revise_reason" in coach_summary
        assert coach_summary["coach_note"]
        assert coach_summary["next_action"]
        assert coach_summary["recommended_action"]
        assert coach_summary["recommended_reason"]
        assert coach_summary["recommended_mode"] in {"study", "revise", "quiz"}
    finally:
        db.close()


def test_coach_summary_prefers_revision_guidance_after_poor_performance() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=2), subject="polity")
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=1), subject="polity")

        summary = build_progress_summary_snapshot(db, subject="polity")
        revision_due = build_revision_due_snapshot(db, summary=summary, subject="polity")
        trends = build_performance_trends(db, summary=summary, subject="polity")
        coach_summary = build_coach_summary(db, summary=summary, revision_due=revision_due, trends=trends, subject="polity")

        assert coach_summary["recommended_mode"] == "revise"
        assert coach_summary["recommended_action"] == "Revise Federalism now."
        assert coach_summary["recommended_reason"]
        assert "Federalism" in coach_summary["recommended_reason"]
        assert coach_summary["next_action"].startswith("Open Tutor for Federalism")
    finally:
        db.close()


def test_coach_summary_for_new_subject_uses_study_fallback() -> None:
    db = build_test_session()
    try:
        coach_summary = build_coach_summary(db, subject="history")

        assert coach_summary["subject"] == "history"
        assert coach_summary["recommended_mode"] == "study"
        assert coach_summary["study_today"] == "Revolt of 1857"
        assert coach_summary["recommended_action"] == "Study Revolt of 1857 next."
        assert coach_summary["recommended_reason"]
        assert coach_summary["next_action"].startswith("Open Tutor for Revolt of 1857")
    finally:
        db.close()


def test_revision_due_prioritizes_weak_topics_within_same_bucket() -> None:
    db = build_test_session()
    try:
        two_days_ago = datetime.now(UTC) - timedelta(days=2)
        create_attempt(db, topic="Federalism", score=1, created_at=two_days_ago)
        create_attempt(db, topic="Preamble", score=4, created_at=two_days_ago)

        summary = build_progress_summary_snapshot(db)
        revision_due = build_revision_due_snapshot(db, summary=summary)

        assert revision_due["overdue"]
        assert revision_due["overdue"][0]["topic"] == "Federalism"
    finally:
        db.close()


def test_accountability_warnings_stay_quiet_for_steady_recent_work() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Preamble", score=4, created_at=now - timedelta(hours=6))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=3))
        create_attempt(db, topic="Citizenship", score=4, created_at=now - timedelta(hours=1))

        summary = build_progress_summary_snapshot(db)
        revision_due = build_revision_due_snapshot(db, summary=summary)
        trends = build_performance_trends(db, summary=summary)
        warnings = build_accountability_warnings(db, summary=summary, revision_due=revision_due, trends=trends)

        assert warnings == []
    finally:
        db.close()


def test_accountability_warnings_flag_repeated_low_scores() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(hours=3))
        create_attempt(db, topic="Preamble", score=2, created_at=now - timedelta(hours=2))
        create_attempt(db, topic="Citizenship", score=4, created_at=now - timedelta(hours=1))

        warnings = build_accountability_warnings(db)

        low_score_warning = next(item for item in warnings if item["title"] == "Low scores are repeating")
        assert low_score_warning["severity"] == "strong"
    finally:
        db.close()


def test_accountability_warnings_flag_ignored_weak_topic() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=2))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=6))
        create_attempt(db, topic="Citizenship", score=4, created_at=now - timedelta(hours=3))
        create_attempt(db, topic="Preamble", score=4, created_at=now - timedelta(hours=1))

        summary = build_progress_summary_snapshot(db)
        revision_due = build_revision_due_snapshot(db, summary=summary)
        trends = build_performance_trends(db, summary=summary)
        warnings = build_accountability_warnings(db, summary=summary, revision_due=revision_due, trends=trends)

        assert any(item["title"] == "Weak topic is being skipped" for item in warnings)
    finally:
        db.close()


def test_accountability_warnings_flag_backlog_and_decline() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Parliament", score=5, created_at=now - timedelta(days=6))
        create_attempt(db, topic="Parliament", score=5, created_at=now - timedelta(days=5))
        create_attempt(db, topic="Parliament", score=4, created_at=now - timedelta(days=4))
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=3))
        create_attempt(db, topic="Directive Principles", score=1, created_at=now - timedelta(days=2))
        create_attempt(db, topic="Citizenship", score=1, created_at=now - timedelta(days=1))

        summary = build_progress_summary_snapshot(db)
        revision_due = build_revision_due_snapshot(db, summary=summary)
        trends = build_performance_trends(db, summary=summary)
        warnings = build_accountability_warnings(db, summary=summary, revision_due=revision_due, trends=trends)

        assert any(item["title"] == "Revision backlog is building" for item in warnings)
        assert any(item["title"] == "Performance is slipping" for item in warnings)
    finally:
        db.close()




def test_progress_summary_exposes_accountability_for_missed_revision_priority() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=4))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=6))
        create_attempt(db, topic="Citizenship", score=4, created_at=now - timedelta(hours=2))

        summary = build_progress_summary_snapshot(db)
        accountability = summary["accountability_summary"]

        assert accountability["missed_revision_count"] >= 1
        assert "Federalism" in accountability["missed_revision_topics"]
        assert accountability["missed_priority_topic"] == "Federalism"
        assert accountability["warning_level"] in {"warning", "urgent"}
        assert accountability["recovery_plan"]
        recovery_plan_details = accountability["recovery_plan_details"]
        assert recovery_plan_details
        assert recovery_plan_details["immediate_repair_topic"] == "Federalism"
        assert recovery_plan_details["urgent_revision_target"] == "Federalism"
        assert "Federalism" in recovery_plan_details["short_catch_up_step"]
        assert recovery_plan_details["next_stable_step"]
        assert recovery_plan_details["recovery_reason"]
    finally:
        db.close()


def test_accountability_summary_stays_subject_scoped() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=4), subject="polity")
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=3), subject="polity")
        create_attempt(db, topic="Indian National Congress", score=5, created_at=now - timedelta(hours=1), subject="history")

        polity_summary = build_progress_summary_snapshot(db, subject="polity")
        history_summary = build_progress_summary_snapshot(db, subject="history")
        polity_accountability = polity_summary["accountability_summary"]
        history_accountability = history_summary["accountability_summary"]

        assert "Federalism" in polity_accountability["missed_revision_topics"]
        assert history_accountability["subject"] == "history"
        assert "Federalism" not in history_accountability["missed_revision_topics"]
        assert history_accountability["missed_revision_count"] == 0
    finally:
        db.close()


def test_daily_plan_and_coach_summary_reuse_restart_plan_details() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=4))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=8))
        create_attempt(db, topic="Citizenship", score=4, created_at=now - timedelta(hours=2))

        summary = build_progress_summary_snapshot(db)
        revision_due = build_revision_due_snapshot(db, summary=summary)
        trends = build_performance_trends(db, summary=summary)
        daily_plan = build_daily_plan(db, summary=summary, revision_due=revision_due, trends=trends)
        coach_summary = build_coach_summary(db, summary=summary, revision_due=revision_due, trends=trends, daily_plan=daily_plan)

        restart_plan = summary["accountability_summary"]["restart_plan_details"]

        assert restart_plan
        assert daily_plan["restart_plan_details"] == restart_plan
        assert coach_summary["restart_plan_details"] == restart_plan
    finally:
        db.close()


def test_coach_summary_appends_accountability_recovery_guidance_when_revision_slips() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=4))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=6))
        create_attempt(db, topic="Citizenship", score=4, created_at=now - timedelta(hours=2))

        summary = build_progress_summary_snapshot(db)
        revision_due = build_revision_due_snapshot(db, summary=summary)
        trends = build_performance_trends(db, summary=summary)
        daily_plan = build_daily_plan(db, summary=summary, revision_due=revision_due, trends=trends)
        coach_summary = build_coach_summary(db, summary=summary, revision_due=revision_due, trends=trends, daily_plan=daily_plan)
        accountability = coach_summary["accountability_summary"]
        recovery_plan_details = accountability["recovery_plan_details"]
        motivation_summary = accountability["motivation_summary"]

        assert accountability["warning_level"] in {"warning", "urgent"}
        assert accountability["mentor_note"] in coach_summary["coach_note"]
        assert motivation_summary["guidance_message"] in coach_summary["coach_note"]
        assert accountability["recovery_plan"]
        if motivation_summary["motivation_state"] == "overloaded":
            assert accountability["recovery_plan"] not in coach_summary["coach_note"]
        else:
            assert accountability["recovery_plan"] in coach_summary["coach_note"]
        assert recovery_plan_details
        assert recovery_plan_details["immediate_repair_topic"] == "Federalism"
        assert recovery_plan_details["urgent_revision_target"] == "Federalism"
        assert "Federalism" in recovery_plan_details["short_catch_up_step"]
        assert recovery_plan_details["next_stable_step"]
        assert daily_plan["recovery_plan_details"] == recovery_plan_details
        assert coach_summary["recovery_plan_details"] == recovery_plan_details
    finally:
        db.close()

def test_accountability_summary_marks_regular_activity_as_steady() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Preamble", score=4, created_at=now - timedelta(days=3))
        create_attempt(db, topic="Citizenship", score=5, created_at=now - timedelta(days=2))
        create_attempt(db, topic="Preamble", score=4, created_at=now - timedelta(days=1, hours=4))
        create_attempt(db, topic="Parliament", score=5, created_at=now - timedelta(hours=6))

        summary = build_progress_summary_snapshot(db)
        accountability = summary["accountability_summary"]

        assert accountability["consistency_status"] == "steady"
        assert accountability["active_days_last_7"] >= 3
        assert accountability["activity_events_last_7"] >= 4
        assert accountability["warning_level"] == "quiet"
        assert accountability["warning_severity"] == "none"
        assert "tracked study event" in accountability["consistency_reason"].lower()
    finally:
        db.close()


def test_accountability_summary_builds_stable_motivation_for_steady_manageable_work() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Preamble", score=2, created_at=now - timedelta(days=5))
        create_attempt(db, topic="Preamble", score=3, created_at=now - timedelta(days=4))
        create_attempt(db, topic="Preamble", score=4, created_at=now - timedelta(days=3))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(days=2))
        create_attempt(db, topic="Parliament", score=5, created_at=now - timedelta(hours=4))

        summary = build_progress_summary_snapshot(db)
        accountability = summary["accountability_summary"]
        motivation = accountability["motivation_summary"]

        assert accountability["consistency_status"] == "steady"
        assert motivation["motivation_state"] == "stable"
        assert motivation["confidence_state"] == "steady"
        assert motivation["burnout_signal"] == "none"
        assert motivation["guidance_mode"] == "protect_momentum"
        assert "holding steady" in motivation["encouragement"].lower()
        assert "manageable" in motivation["motivation_reason"].lower()
        assert "protect the current momentum" in motivation["guidance_message"].lower()
        assert motivation["confidence_rebuild_guidance"] is None
        assert motivation["overload_guidance"] is None
    finally:
        db.close()


def test_accountability_summary_keeps_restart_plan_quiet_for_stable_subjects() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Preamble", score=2, created_at=now - timedelta(days=5))
        create_attempt(db, topic="Preamble", score=3, created_at=now - timedelta(days=4))
        create_attempt(db, topic="Preamble", score=4, created_at=now - timedelta(days=3))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(days=2))
        create_attempt(db, topic="Parliament", score=5, created_at=now - timedelta(hours=4))

        summary = build_progress_summary_snapshot(db)

        assert summary["accountability_summary"]["restart_plan_details"] is None
    finally:
        db.close()


def test_accountability_summary_treats_light_recent_activity_as_irregular_not_slipping() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Preamble", score=4, created_at=now - timedelta(days=1, hours=6))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=6))

        summary = build_progress_summary_snapshot(db)
        accountability = summary["accountability_summary"]
        motivation = accountability["motivation_summary"]

        assert accountability["consistency_status"] == "irregular"
        assert accountability["warning_level"] == "quiet"
        assert accountability["warning_severity"] == "none"
        assert accountability["days_since_last_activity"] in {0, 1}
        assert motivation["motivation_state"] == "rebuilding"
        assert motivation["burnout_signal"] == "none"
        assert motivation["guidance_mode"] == "rebuild_confidence"
        assert "rebuild confidence" in motivation["guidance_message"].lower()
        assert motivation["confidence_rebuild_guidance"] is None
        assert motivation["overload_guidance"] is None
    finally:
        db.close()

def test_accountability_summary_reinforces_progress_when_work_is_stable_without_recovery_pressure() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Parliament", score=4, created_at=now - timedelta(days=4))
        create_attempt(db, topic="Parliament", score=4, created_at=now - timedelta(days=3))
        create_attempt(db, topic="Parliament", score=4, created_at=now - timedelta(days=2))
        create_attempt(db, topic="Parliament", score=4, created_at=now - timedelta(days=1))
        create_attempt(db, topic="Prime Minister", score=5, created_at=now - timedelta(hours=4))

        summary = build_progress_summary_snapshot(db)
        accountability = summary["accountability_summary"]
        motivation = accountability["motivation_summary"]

        assert accountability["consistency_status"] == "steady"
        assert motivation["motivation_state"] == "stable"
        assert motivation["guidance_mode"] == "reinforce_progress"
        assert "reinforce the current progress" in motivation["guidance_message"].lower()
        assert motivation["confidence_rebuild_guidance"] is None
        assert motivation["overload_guidance"] is None
    finally:
        db.close()

def test_accountability_summary_builds_confidence_rebuild_guidance_after_repeated_errors() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=4))
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=3))
        create_attempt(db, topic="Federalism", score=2, created_at=now - timedelta(days=2))
        create_attempt(db, topic="Federalism", score=2, created_at=now - timedelta(hours=8))
        create_attempt(db, topic="Preamble", score=4, created_at=now - timedelta(hours=2))

        summary = build_progress_summary_snapshot(db)
        accountability = summary["accountability_summary"]
        motivation = accountability["motivation_summary"]
        confidence_guidance = motivation["confidence_rebuild_guidance"]

        assert motivation["confidence_state"] == "rebuilding"
        assert motivation["guidance_mode"] in {"urge_recovery", "rebuild_confidence", "calm_overload"}
        assert confidence_guidance
        assert confidence_guidance["focus_topic"] == "Federalism"
        assert "federalism" in confidence_guidance["acknowledgement"].lower()
        assert "federalism" in confidence_guidance["smaller_next_step"].lower()
        assert "tutor" in confidence_guidance["repair_action"].lower()
        assert "quiz" in confidence_guidance["repair_action"].lower()
    finally:
        db.close()


def test_accountability_summary_marks_long_gap_as_slipping() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=3, created_at=now - timedelta(days=8))
        create_attempt(db, topic="Preamble", score=4, created_at=now - timedelta(days=6))

        summary = build_progress_summary_snapshot(db)
        accountability = summary["accountability_summary"]

        assert accountability["consistency_status"] == "slipping"
        assert accountability["days_since_last_activity"] >= 5
        assert accountability["warning_level"] in {"warning", "urgent"}
        assert accountability["warning_severity"] == "strong"
        assert "day(s) without tracked study activity" in accountability["consistency_reason"].lower()
    finally:
        db.close()


def test_accountability_summary_marks_slipping_motivation_after_long_gap() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=3, created_at=now - timedelta(days=8))
        create_attempt(db, topic="Preamble", score=4, created_at=now - timedelta(days=6))

        summary = build_progress_summary_snapshot(db)
        accountability = summary["accountability_summary"]
        motivation = accountability["motivation_summary"]

        assert accountability["consistency_status"] == "slipping"
        assert motivation["motivation_state"] == "slipping"
        assert motivation["confidence_state"] == "rebuilding"
        assert motivation["guidance_mode"] == "urge_recovery"
        assert motivation["next_support_step"]
        assert "heroic catch-up" in motivation["encouragement"].lower()
        assert "day(s)" in motivation["motivation_reason"].lower()
        assert "come straight back to the repair plan" in motivation["guidance_message"].lower()
    finally:
        db.close()


def test_accountability_summary_builds_restart_plan_after_long_gap() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=3, created_at=now - timedelta(days=8))
        create_attempt(db, topic="Preamble", score=4, created_at=now - timedelta(days=6))

        summary = build_progress_summary_snapshot(db)
        accountability = summary["accountability_summary"]
        restart_plan = accountability["restart_plan_details"]

        assert accountability["consistency_status"] == "slipping"
        assert restart_plan
        assert restart_plan["first_step"]
        assert "stop after" in restart_plan["first_step"].lower()
        assert restart_plan["easiest_reentry_point"]
        assert restart_plan["restart_reason"]
        assert restart_plan["next_stable_step"] == accountability["recovery_plan_details"]["next_stable_step"]
    finally:
        db.close()


def test_accountability_summary_flags_regaining_momentum_when_recovery_work_turns_upward() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=6))
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=5))
        create_attempt(db, topic="Federalism", score=2, created_at=now - timedelta(days=3))
        create_attempt(db, topic="Federalism", score=3, created_at=now - timedelta(days=2))
        create_attempt(db, topic="Federalism", score=4, created_at=now - timedelta(hours=3))

        summary = build_progress_summary_snapshot(db)
        accountability = summary["accountability_summary"]
        motivation = accountability["motivation_summary"]

        assert accountability["consistency_status"] == "steady"
        assert motivation["motivation_state"] == "regaining_momentum"
        assert motivation["confidence_state"] == "rebuilding"
        assert motivation["burnout_signal"] == "none"
        assert motivation["guidance_mode"] == "protect_momentum"
        assert "recover momentum" in motivation["encouragement"].lower()
        assert "protect the recovery turn" in motivation["guidance_message"].lower()
    finally:
        db.close()

def test_consistency_status_stays_subject_scoped() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Preamble", score=4, created_at=now - timedelta(days=2, hours=12), subject="polity")
        create_attempt(db, topic="Citizenship", score=5, created_at=now - timedelta(days=1, hours=12), subject="polity")
        create_attempt(db, topic="Parliament", score=4, created_at=now - timedelta(hours=20), subject="polity")
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=6), subject="polity")
        create_attempt(db, topic="Indian National Congress", score=3, created_at=now - timedelta(days=8), subject="history")
        create_attempt(db, topic="Revolt of 1857", score=4, created_at=now - timedelta(days=6), subject="history")

        polity_summary = build_progress_summary_snapshot(db, subject="polity")
        history_summary = build_progress_summary_snapshot(db, subject="history")

        assert polity_summary["accountability_summary"]["consistency_status"] == "steady"
        assert history_summary["accountability_summary"]["consistency_status"] == "slipping"
        assert polity_summary["accountability_summary"]["subject"] == "polity"
        assert history_summary["accountability_summary"]["subject"] == "history"
    finally:
        db.close()


def test_accountability_summary_marks_missed_revision_when_urgent_repair_is_ignored() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=4))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=8))
        create_attempt(db, topic="Citizenship", score=4, created_at=now - timedelta(hours=2))

        summary = build_progress_summary_snapshot(db)
        accountability = summary["accountability_summary"]

        assert accountability["missed_revision_signal"] == "missed"
        assert "Federalism" in accountability["missed_revision_topics"]
        assert accountability["missed_revision_reason"]
        assert "Federalism" in accountability["missed_revision_reason"]
        assert accountability["warning_level"] in {"warning", "urgent"}
        assert accountability["warning_severity"] == "moderate"
    finally:
        db.close()


def test_accountability_summary_builds_restart_plan_for_missed_revision_slippage() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=4))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=8))
        create_attempt(db, topic="Citizenship", score=4, created_at=now - timedelta(hours=2))

        summary = build_progress_summary_snapshot(db)
        accountability = summary["accountability_summary"]
        restart_plan = accountability["restart_plan_details"]

        assert accountability["missed_revision_signal"] == "missed"
        assert restart_plan
        assert "Federalism" in restart_plan["first_step"]
        assert restart_plan["urgent_catch_up_item"]
        assert "Federalism" in restart_plan["urgent_catch_up_item"]
    finally:
        db.close()



def test_accountability_summary_flags_repeated_weak_neglect_as_missed_plan() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=4))
        create_attempt(db, topic="Directive Principles", score=1, created_at=now - timedelta(days=3, hours=6))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=8))
        create_attempt(db, topic="Citizenship", score=4, created_at=now - timedelta(hours=2))

        summary = build_progress_summary_snapshot(db)
        accountability = summary["accountability_summary"]

        assert accountability["missed_plan_signal"] == "missed"
        assert accountability["missed_plan_reason"]
        assert accountability["neglected_weak_topics"]
        assert any(topic in {"Federalism", "Directive Principles"} for topic in accountability["neglected_weak_topics"])
    finally:
        db.close()



def test_accountability_summary_keeps_one_isolated_detour_at_watch() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=4))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=2))

        summary = build_progress_summary_snapshot(db)
        accountability = summary["accountability_summary"]

        assert accountability["missed_revision_signal"] == "watch"
        assert accountability["missed_plan_signal"] == "watch"
        assert accountability["warning_level"] == "watch"
        assert accountability["warning_severity"] == "gentle"

        warnings = build_accountability_warnings(db, summary=summary)
        due_revision_warning = next(item for item in warnings if item["title"] == "Due revision is being missed")
        assert due_revision_warning["severity"] == "gentle"
    finally:
        db.close()


def test_strict_mentor_mode_changes_warning_visibility_not_underlying_evidence() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=4))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=2))

        normal_summary = build_progress_summary_snapshot(db, mentor_mode="normal")
        strict_summary = build_progress_summary_snapshot(db, mentor_mode="strict")

        normal_accountability = normal_summary["accountability_summary"]
        strict_accountability = strict_summary["accountability_summary"]

        assert normal_accountability["mentor_mode"] == "normal"
        assert strict_accountability["mentor_mode"] == "strict"
        assert normal_accountability["missed_revision_signal"] == strict_accountability["missed_revision_signal"] == "watch"
        assert normal_accountability["missed_plan_signal"] == strict_accountability["missed_plan_signal"] == "watch"
        assert normal_accountability["warning_level"] == strict_accountability["warning_level"] == "watch"
        assert normal_accountability["warning_severity"] == "gentle"
        assert strict_accountability["warning_severity"] == "moderate"
        assert normal_accountability["motivation_summary"]["motivation_state"] == strict_accountability["motivation_summary"]["motivation_state"]
        assert normal_accountability["motivation_summary"]["motivation_reason"] == strict_accountability["motivation_summary"]["motivation_reason"]
        assert normal_accountability["motivation_summary"]["guidance_mode"] == strict_accountability["motivation_summary"]["guidance_mode"]
        assert normal_accountability["motivation_summary"]["guidance_message"] == strict_accountability["motivation_summary"]["guidance_message"]
        assert normal_accountability["motivation_summary"]["next_support_step"] == strict_accountability["motivation_summary"]["next_support_step"]
        assert strict_accountability["mentor_note"] != normal_accountability["mentor_note"]

        normal_warnings = build_accountability_warnings(db, summary=normal_summary, mentor_mode="normal")
        strict_warnings = build_accountability_warnings(db, summary=strict_summary, mentor_mode="strict")
        normal_due_revision_warning = next(item for item in normal_warnings if item["title"] == "Due revision is being missed")
        strict_due_revision_warning = next(item for item in strict_warnings if item["title"] == "Due revision is being missed")

        assert normal_due_revision_warning["severity"] == "gentle"
        assert strict_due_revision_warning["severity"] == "moderate"
        assert "Correct this before adding new breadth." in strict_due_revision_warning["message"]
    finally:
        db.close()


def test_accountability_summary_flags_overloaded_motivation_when_pressure_builds_without_progress() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="President", score=5, created_at=now - timedelta(days=6))
        create_attempt(db, topic="President", score=4, created_at=now - timedelta(days=5))
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=4))
        create_attempt(db, topic="President", score=2, created_at=now - timedelta(days=3))
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=2))
        create_attempt(db, topic="President", score=2, created_at=now - timedelta(days=1))

        summary = build_progress_summary_snapshot(db)
        accountability = summary["accountability_summary"]
        motivation = accountability["motivation_summary"]

        assert accountability["consistency_status"] == "steady"
        assert motivation["motivation_state"] == "overloaded"
        assert motivation["confidence_state"] == "rebuilding"
        assert motivation["burnout_signal"] == "watch"
        assert motivation["guidance_mode"] == "calm_overload"
        assert motivation["next_support_step"]
        assert "too much live pressure" in motivation["encouragement"].lower()
        assert "narrow the next block to one repair action" in motivation["guidance_message"].lower()
        assert motivation["overload_guidance"]
        assert motivation["overload_guidance"]["focus_topic"]
        assert "pause" in motivation["overload_guidance"]["reduce_breadth_note"].lower()
        assert "do not add a second repair topic" in motivation["overload_guidance"]["repair_action"].lower()
    finally:
        db.close()

def test_performance_trends_detect_improvement() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="President", score=1, created_at=now - timedelta(days=6))
        create_attempt(db, topic="President", score=1, created_at=now - timedelta(days=5))
        create_attempt(db, topic="President", score=2, created_at=now - timedelta(days=4))
        create_attempt(db, topic="President", score=4, created_at=now - timedelta(days=3))
        create_attempt(db, topic="President", score=5, created_at=now - timedelta(days=2))
        create_attempt(db, topic="President", score=5, created_at=now - timedelta(days=1))

        trends = build_performance_trends(db)

        assert trends["overall_trend"] == "improving"
        assert trends["topics"][0]["trend"] == "improving"
    finally:
        db.close()


def test_performance_trends_detect_stability() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Prime Minister", score=4, created_at=now - timedelta(days=6))
        create_attempt(db, topic="Prime Minister", score=4, created_at=now - timedelta(days=5))
        create_attempt(db, topic="Prime Minister", score=4, created_at=now - timedelta(days=4))
        create_attempt(db, topic="Prime Minister", score=4, created_at=now - timedelta(days=3))
        create_attempt(db, topic="Prime Minister", score=4, created_at=now - timedelta(days=2))
        create_attempt(db, topic="Prime Minister", score=4, created_at=now - timedelta(days=1))

        trends = build_performance_trends(db)

        assert trends["overall_trend"] == "stable"
        assert trends["topics"][0]["trend"] == "stable"
    finally:
        db.close()


def test_progress_summary_recommendation_returns_topic_name_from_corrected_snapshot() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=2))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=1))

        summary = build_progress_summary_snapshot(db)

        assert summary["recommended_next_topic"] == "Federalism"
        assert summary["recommended_next_reason"]
    finally:
        db.close()



def test_daily_plan_uses_corrected_recommendation_when_no_urgent_revision_exists() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="President", score=5, created_at=now - timedelta(hours=1))

        summary = build_progress_summary_snapshot(db)
        revision_due = build_revision_due_snapshot(db, summary=summary)
        plan = build_daily_plan(db, summary=summary, revision_due=revision_due)

        assert summary["recommended_next_topic"] != "Study President next."
        assert plan["focus_topic"] == summary["recommended_next_topic"]
        assert plan["focus_topic"] != "President"
    finally:
        db.close()

def test_progress_summary_is_scoped_by_subject() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=2), subject="polity")
        create_attempt(db, topic="Revolt of 1857", score=1, created_at=now - timedelta(hours=1), subject="history")

        polity_summary = build_progress_summary_snapshot(db, subject="polity")
        history_summary = build_progress_summary_snapshot(db, subject="history")

        assert polity_summary["subject"] == "polity"
        assert history_summary["subject"] == "history"
        assert polity_summary["topic_accuracy"][0]["accuracy"] == 100.0
        assert history_summary["topic_accuracy"][0]["accuracy"] == 20.0
        assert polity_summary["topic_accuracy"][0]["topic"] == "Preamble"
        assert history_summary["topic_accuracy"][0]["topic"] == "Revolt of 1857"
    finally:
        db.close()





def test_revision_due_is_scoped_by_subject() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=2), subject="polity")
        create_attempt(db, topic="Revolt of 1857", score=1, created_at=now - timedelta(days=2), subject="history")

        polity_revision = build_revision_due_snapshot(db, subject="polity")
        history_revision = build_revision_due_snapshot(db, subject="history")

        polity_topics = {
            item["topic"]
            for bucket in ("overdue", "due_now", "due_soon")
            for item in polity_revision[bucket]
        }
        history_topics = {
            item["topic"]
            for bucket in ("overdue", "due_now", "due_soon")
            for item in history_revision[bucket]
        }

        assert polity_revision["subject"] == "polity"
        assert history_revision["subject"] == "history"
        assert "Federalism" in polity_topics
        assert "Revolt of 1857" in history_topics
        assert "Federalism" not in history_topics
        assert "Revolt of 1857" not in polity_topics
    finally:
        db.close()


def test_daily_plan_and_coach_summary_are_scoped_by_subject() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=2), subject="polity")
        create_attempt(db, topic="Indian National Congress", score=5, created_at=now - timedelta(hours=2), subject="history")

        history_summary = build_progress_summary_snapshot(db, subject="history")
        history_revision = build_revision_due_snapshot(db, summary=history_summary, subject="history")
        history_trends = build_performance_trends(db, summary=history_summary, subject="history")
        history_plan = build_daily_plan(
            db,
            summary=history_summary,
            revision_due=history_revision,
            trends=history_trends,
            subject="history",
        )
        history_coach = build_coach_summary(
            db,
            summary=history_summary,
            revision_due=history_revision,
            trends=history_trends,
            daily_plan=history_plan,
            subject="history",
        )

        assert history_summary["subject"] == "history"
        assert history_plan["subject"] == "history"
        assert history_coach["subject"] == "history"
        assert history_plan["focus_topic"] != "Federalism"
        assert history_coach["study_today"] != "Federalism"
        assert "Federalism" not in history_coach["weak_areas"]
        assert "Federalism" not in history_coach["revise_today"]
    finally:
        db.close()

def test_daily_plan_prefers_incomplete_topic_before_continuation_for_medium_current_topic() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Indian Monsoon", score=3, created_at=now - timedelta(hours=1), subject="geography")

        summary = build_progress_summary_snapshot(db, subject="geography")
        revision_due = build_revision_due_snapshot(db, summary=summary, subject="geography")
        plan = build_daily_plan(db, summary=summary, revision_due=revision_due, subject="geography")

        assert summary["continuation_topic"] == "Indian Monsoon"
        assert summary["continuation_reason"]
        assert summary["recommendation_source"] == "incomplete_topic"
        assert summary["primary_study_signal"] == "continue_topic"
        assert summary["continuation_status"] == "recommended"
        assert summary["continue_study_topic"] == "Indian Monsoon"
        assert plan["plan_mode"] == "continuation"
        assert plan["focus_topic"] == "Indian Monsoon"
        assert plan["recommendation_source"] == "incomplete_topic"
        assert plan["primary_study_signal"] == "continue_topic"
        assert plan["continuation_status"] == "recommended"
        assert plan["continue_study_topic"] == "Indian Monsoon"
        assert plan["next_best_topic"] == summary["sequence_next_topic"]
    finally:
        db.close()


def test_recommendation_advances_to_next_subject_sequence_topic() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Revolt of 1857", score=5, created_at=now - timedelta(hours=1), subject="history")

        summary = build_progress_summary_snapshot(db, subject="history")
        coach_summary = build_coach_summary(db, summary=summary, subject="history")

        assert summary["sequence_next_topic"] == "Indian National Congress"
        assert summary["recommended_next_topic"] == "Indian National Congress"
        assert summary["sequence_next_reason"]
        assert coach_summary["next_best_topic"] == "Indian National Congress"
    finally:
        db.close()


def test_topic_priority_list_ranks_weak_topic_above_strong_topic_within_subject() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=2), subject="polity")
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=1), subject="polity")
        create_attempt(db, topic="Indian National Congress", score=1, created_at=now - timedelta(hours=1), subject="history")

        priority_topics = build_topic_priority_list(db, subject="polity")

        assert priority_topics
        assert priority_topics[0].topic == "Federalism"
        assert priority_topics[0].recommended_mode == "revise"
        assert all(item.subject == "polity" for item in priority_topics)
        assert all(item.topic != "Indian National Congress" for item in priority_topics)
    finally:
        db.close()


def test_topic_priority_list_changes_after_topic_improves() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Revolt of 1857", score=1, created_at=now - timedelta(days=2), subject="history")
        create_attempt(db, topic="Indian National Congress", score=2, created_at=now - timedelta(hours=1), subject="history")

        before_priority = build_topic_priority_list(db, subject="history")
        assert before_priority[0].topic == "Revolt of 1857"

        create_attempt(db, topic="Revolt of 1857", score=5, created_at=now, subject="history")

        after_priority = build_topic_priority_list(db, subject="history")
        assert after_priority[0].topic == "Indian National Congress"
    finally:
        db.close()


def test_study_recommendation_prioritizes_overdue_revision_before_recent_weak_area() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=2), subject="polity")
        create_attempt(db, topic="Parliament", score=2, created_at=now - timedelta(hours=1), subject="polity")

        recommendation = build_study_recommendation(db, subject="polity")

        assert recommendation.recommended_topic == "Federalism"
        assert recommendation.recommended_mode == "revise"
        assert recommendation.recommendation_source == "overdue_revision"
    finally:
        db.close()


def test_study_recommendation_prioritizes_overdue_revision_before_sequence() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=2), subject="polity")
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=1), subject="polity")

        recommendation = build_study_recommendation(db, subject="polity")

        assert recommendation.recommended_topic == "Federalism"
        assert recommendation.recommended_mode == "revise"
        assert recommendation.recommended_action == "Revise Federalism now."
        assert recommendation.reason
    finally:
        db.close()


def test_study_recommendation_prefers_incomplete_topic_before_sequence_advance() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Indian National Congress", score=3, created_at=now - timedelta(hours=2), subject="history")
        create_attempt(db, topic="Revolt of 1857", score=5, created_at=now - timedelta(hours=1), subject="history")

        recommendation = build_study_recommendation(db, current_topic="Revolt of 1857", subject="history")

        assert recommendation.recommended_topic == "Indian National Congress"
        assert recommendation.recommended_mode == "study"
        assert recommendation.reason
    finally:
        db.close()


def test_study_recommendation_falls_back_to_subject_sequence_without_history() -> None:
    db = build_test_session()
    try:
        recommendation = build_study_recommendation(db, subject="history")

        assert recommendation.subject == "history"
        assert recommendation.recommended_topic == "Revolt of 1857"
        assert recommendation.recommended_mode == "study"
        assert recommendation.reason
    finally:
        db.close()


def test_study_recommendation_stays_scoped_to_selected_subject() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=2), subject="polity")

        recommendation = build_study_recommendation(db, subject="history")

        assert recommendation.subject == "history"
        assert recommendation.recommended_topic != "Federalism"
        assert "Federalism" not in recommendation.recommended_action
    finally:
        db.close()


def test_daily_plan_uses_subject_specific_primary_and_secondary_actions() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=2), subject="polity")
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=1), subject="polity")

        plan = build_daily_plan(db, subject="polity")

        assert plan["recommended_action"] == "Revise Federalism now."
        assert plan["recommended_mode"] == "revise"
        assert plan["focus_topic"] == "Federalism"
        assert len(plan["secondary_suggestions"]) >= 1
        assert all(item["topic"] != "Indian National Congress" for item in plan["secondary_suggestions"])
    finally:
        db.close()


def test_daily_plan_primary_focus_tracks_central_recommendation() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=2), subject="polity")
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=1), subject="polity")

        summary = build_progress_summary_snapshot(db, subject="polity")
        revision_due = build_revision_due_snapshot(db, summary=summary, subject="polity")
        trends = build_performance_trends(db, summary=summary, subject="polity")
        plan = build_daily_plan(db, summary=summary, revision_due=revision_due, trends=trends, subject="polity")

        assert plan["focus_topic"] == summary["recommended_next_topic"]
        assert plan["focus_reason"] == summary["recommended_next_reason"]
        assert plan["recommended_action"] == summary["recommended_action"]
        assert plan["recommended_mode"] == summary["recommended_mode"]
        assert plan["recommendation_source"] == summary["recommendation_source"]
    finally:
        db.close()



def test_daily_plan_no_content_subject_uses_recommendation_engine_fallback() -> None:
    db = build_test_session()
    try:
        summary = build_progress_summary_snapshot(db, subject="environment")
        plan = build_daily_plan(db, summary=summary, subject="environment")

        assert summary["recommendation_source"] == "no_content"
        assert summary["recommended_next_topic"] == ""
        assert plan["subject"] == "environment"
        assert plan["focus_topic"] == ""
        assert plan["focus_reason"] == summary["recommended_next_reason"]
        assert plan["recommended_action"] == summary["recommended_action"]
        assert plan["recommended_mode"] == summary["recommended_mode"]
        assert plan["recommendation_source"] == "no_content"
    finally:
        db.close()



def test_daily_plan_for_new_subject_uses_sequence_default_without_stale_topics() -> None:
    db = build_test_session()
    try:
        create_attempt(db, topic="Federalism", score=1, created_at=datetime.now(UTC) - timedelta(days=1), subject="polity")

        plan = build_daily_plan(db, subject="history")

        assert plan["subject"] == "history"
        assert plan["focus_topic"] == "Revolt of 1857"
        assert plan["recommended_mode"] == "study"
        assert all(item["topic"] != "Federalism" for item in plan["secondary_suggestions"])
    finally:
        db.close()


def test_overdue_revision_overrides_recent_continuation() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Indian Monsoon", score=3, created_at=now - timedelta(hours=1), subject="geography")
        create_attempt(db, topic="Soil Types in India", score=1, created_at=now - timedelta(days=2), subject="geography")

        recommendation = build_study_recommendation(db, subject="geography")

        assert recommendation.recommended_topic == "Soil Types in India"
        assert recommendation.recommendation_source == "overdue_revision"
        assert recommendation.recommended_mode == "revise"
    finally:
        db.close()


def test_summary_and_plan_keep_continuation_available_when_urgent_revision_overrides_it() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Indian Monsoon", score=3, created_at=now - timedelta(hours=1), subject="geography")
        create_attempt(db, topic="Soil Types in India", score=1, created_at=now - timedelta(days=2), subject="geography")

        summary = build_progress_summary_snapshot(db, subject="geography")
        revision_due = build_revision_due_snapshot(db, summary=summary, subject="geography")
        plan = build_daily_plan(db, summary=summary, revision_due=revision_due, subject="geography")

        assert summary["recommended_next_topic"] == "Soil Types in India"
        assert summary["primary_study_signal"] == "priority_fix"
        assert summary["continuation_status"] == "available"
        assert summary["continue_study_topic"] == "Indian Monsoon"
        assert summary["continue_study_reason"]
        assert plan["focus_topic"] == "Soil Types in India"
        assert plan["next_best_topic"] == "Indian Monsoon"
        assert plan["continuation_status"] == "available"
        assert plan["continue_study_topic"] == "Indian Monsoon"
    finally:
        db.close()


def test_ranked_weak_topics_are_subject_scoped_and_reused_across_guidance() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(hours=2), subject="polity")
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=1), subject="polity")
        create_attempt(db, topic="Indian National Congress", score=1, created_at=now - timedelta(hours=1), subject="history")

        summary = build_progress_summary_snapshot(db, subject="polity")
        revision_due = build_revision_due_snapshot(db, summary=summary, subject="polity")
        plan = build_daily_plan(db, summary=summary, revision_due=revision_due, subject="polity")
        coach = build_coach_summary(db, summary=summary, revision_due=revision_due, daily_plan=plan, subject="polity")

        assert summary["ranked_weak_topics"]
        assert summary["ranked_weak_topics"][0]["topic"] == "Federalism"
        assert all(item["subject"] == "polity" for item in summary["ranked_weak_topics"])
        assert all(item["topic"] != "Indian National Congress" for item in summary["ranked_weak_topics"])
        assert plan["ranked_weak_topics"][0]["topic"] == summary["ranked_weak_topics"][0]["topic"]
        assert coach["ranked_weak_topics"][0]["topic"] == summary["ranked_weak_topics"][0]["topic"]
        assert coach["weak_areas"][0] == summary["ranked_weak_topics"][0]["topic"]
    finally:
        db.close()


def test_ranked_weak_topics_stay_empty_without_confident_signals() -> None:
    db = build_test_session()
    try:
        summary = build_progress_summary_snapshot(db, subject="history")
        plan = build_daily_plan(db, summary=summary, subject="history")
        coach = build_coach_summary(db, summary=summary, daily_plan=plan, subject="history")

        assert summary["ranked_weak_topics"] == []
        assert plan["ranked_weak_topics"] == []
        assert coach["ranked_weak_topics"] == []
    finally:
        db.close()


def test_coach_summary_makes_continuation_explicit_when_it_is_primary_signal() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Indian Monsoon", score=3, created_at=now - timedelta(hours=1), subject="geography")

        summary = build_progress_summary_snapshot(db, subject="geography")
        revision_due = build_revision_due_snapshot(db, summary=summary, subject="geography")
        daily_plan = build_daily_plan(db, summary=summary, revision_due=revision_due, subject="geography")
        coach_summary = build_coach_summary(db, summary=summary, revision_due=revision_due, daily_plan=daily_plan, subject="geography")

        assert coach_summary["study_today"] == "Indian Monsoon"
        assert coach_summary["primary_study_signal"] == "continue_topic"
        assert coach_summary["continuation_status"] == "recommended"
        assert coach_summary["continue_study_topic"] == "Indian Monsoon"
        assert coach_summary["coach_note"].startswith("Continue Indian Monsoon now")
        assert coach_summary["next_action"].startswith("Resume Indian Monsoon in Tutor")
        assert coach_summary["recommended_reason"]
    finally:
        db.close()


def test_coach_summary_keeps_resume_after_revision_override() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Indian Monsoon", score=3, created_at=now - timedelta(hours=1), subject="geography")
        create_attempt(db, topic="Soil Types in India", score=1, created_at=now - timedelta(days=2), subject="geography")

        summary = build_progress_summary_snapshot(db, subject="geography")
        revision_due = build_revision_due_snapshot(db, summary=summary, subject="geography")
        daily_plan = build_daily_plan(db, summary=summary, revision_due=revision_due, subject="geography")
        coach_summary = build_coach_summary(db, summary=summary, revision_due=revision_due, daily_plan=daily_plan, subject="geography")

        assert coach_summary["study_today"] == "Soil Types in India"
        assert coach_summary["continuation_status"] == "available"
        assert coach_summary["continue_study_topic"] == "Indian Monsoon"
        assert coach_summary["coach_note"].startswith("Fix Soil Types in India first. Resume Indian Monsoon after that.")
        assert "supportive" in coach_summary["coach_note"].lower()
        assert "After that, resume Indian Monsoon." in coach_summary["next_action"]
        assert coach_summary["recommended_reason"]
    finally:
        db.close()


def test_stale_subject_activity_does_not_present_as_continuation() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Indian Monsoon", score=3, created_at=now - timedelta(days=3), subject="geography")

        summary = build_progress_summary_snapshot(db, subject="geography")

        assert summary["continuation_topic"] in {None, ""}
        assert summary["recommendation_source"] != "continuation"
    finally:
        db.close()

def test_invalid_stored_topics_are_ignored_in_guidance_snapshots() -> None:
    db = build_test_session()
    try:
        quiz = create_quiz_row(db, topic="string", subject="polity")
        db.add(
            QuizAttempt(
                quiz_id=quiz.id,
                topic="string",
                chapter="General",
                subject="polity",
                difficulty="easy",
                submitted_answers_json="[]",
                score=0,
                total_questions=5,
                accuracy=0.0,
                incorrect_questions_json="[]",
                weak_areas_json='["string"]',
                next_recommendation="Review the topic once and try another quiz.",
            )
        )
        db.add(
            TopicStudy(
                topic="string",
                chapter="General",
                subject="polity",
                study_count=1,
                last_interaction_at=datetime.now(UTC),
            )
        )
        db.commit()

        summary = build_progress_summary_snapshot(db, subject="polity")
        revision_due = build_revision_due_snapshot(db, summary=summary, subject="polity")
        trends = build_performance_trends(db, summary=summary, subject="polity")
        coach_summary = build_coach_summary(db, summary=summary, revision_due=revision_due, trends=trends, subject="polity")

        assert summary["recent_quizzes"] == []
        assert "string" not in summary["recent_weak_areas"]
        assert "string" not in summary["weak_topics"]
        assert all(item["topic"] != "string" for item in summary["revision_recommendations"])
        assert all(item["topic"] != "string" for item in summary["priority_topics"])
        assert all(item["topic"] != "string" for item in summary["ranked_weak_topics"])
        assert summary["recommended_next_topic"] != "string"
        assert coach_summary["study_today"] != "string"
    finally:
        db.close()



def test_progress_summary_exposes_mastery_and_readiness_signals() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(days=6))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(days=4))
        create_attempt(db, topic="Preamble", score=4, created_at=now - timedelta(days=1))
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=2))
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(hours=8))

        summary = build_progress_summary_snapshot(db)

        preamble = next(item for item in summary["topic_accuracy"] if item["topic"] == "Preamble")
        federalism = next(item for item in summary["topic_accuracy"] if item["topic"] == "Federalism")

        assert preamble["mastery_score"] > federalism["mastery_score"]
        assert preamble["strength_classification"] in {"stable", "strong"}
        assert preamble["revision_readiness"] in {"building", "ready"}
        assert federalism["strength_classification"] == "fragile"
        assert federalism["revision_readiness"] == "needs_refresh"
        assert federalism["confidence_score"] > 0
        assert federalism["stability_score"] < preamble["stability_score"]
        assert summary["mastery_overview"]["fragile_count"] >= 1
        assert summary["mastery_overview"]["strong_count"] + summary["mastery_overview"]["stable_count"] >= 1
    finally:
        db.close()


def test_mastery_score_prefers_real_quiz_strength_over_extra_study_touches() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(days=2))
        create_attempt(db, topic="Preamble", score=4, created_at=now - timedelta(hours=12))
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(hours=6))

        db.query(TopicStudy).filter(TopicStudy.subject == "polity", TopicStudy.topic == "Federalism").update(
            {TopicStudy.study_count: 8}
        )
        db.commit()

        summary = build_progress_summary_snapshot(db)
        preamble = next(item for item in summary["topic_accuracy"] if item["topic"] == "Preamble")
        federalism = next(item for item in summary["topic_accuracy"] if item["topic"] == "Federalism")

        assert preamble["mastery_score"] > federalism["mastery_score"]
        assert preamble["confidence_score"] >= federalism["confidence_score"]
        assert federalism["strength_classification"] == "fragile"
    finally:
        db.close()


def test_mastery_score_penalizes_overdue_revision_pressure() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Preamble", score=4, created_at=now - timedelta(days=3))
        create_attempt(db, topic="Directive Principles", score=4, created_at=now - timedelta(hours=3))

        summary = build_progress_summary_snapshot(db)
        preamble = next(item for item in summary["topic_accuracy"] if item["topic"] == "Preamble")
        directive_principles = next(item for item in summary["topic_accuracy"] if item["topic"] == "Directive Principles")

        assert preamble["revision_status"] in {"overdue", "due_soon"}
        assert directive_principles["revision_status"] in {"none", "upcoming", "due_soon"}
        assert preamble["mastery_score"] < directive_principles["mastery_score"]
    finally:
        db.close()


def test_progress_summary_exposes_subject_scoped_topic_strength_buckets() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(days=4))
        create_attempt(db, topic="Preamble", score=4, created_at=now - timedelta(days=1))
        create_attempt(db, topic="Parliament", score=3, created_at=now - timedelta(hours=18))
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(hours=8))

        summary = build_progress_summary_snapshot(db)
        topic_strengths = {item["topic"]: item["topic_strength"] for item in summary["topic_accuracy"]}

        assert topic_strengths["Preamble"] == "strong"
        assert topic_strengths["Parliament"] == "medium"
        assert topic_strengths["Federalism"] == "weak"
        assert "Preamble" in summary["strong_topics"]
        assert "Parliament" in summary["medium_topics"]
        assert "Federalism" in summary["weak_topics"]
    finally:
        db.close()



def test_progress_summary_exposes_adaptive_difficulty_guidance() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(days=3))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=18))
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=2))
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(hours=6))
        create_attempt(db, topic="Directive Principles", score=1, created_at=now - timedelta(hours=4))

        summary = build_progress_summary_snapshot(db)
        topic_items = {item["topic"]: item for item in summary["topic_accuracy"]}

        assert topic_items["Preamble"]["recommended_difficulty_band"] == "hard"
        assert topic_items["Preamble"]["adaptive_state"] == "challenge"
        assert topic_items["Federalism"]["recommended_difficulty_band"] == "easy"
        assert topic_items["Federalism"]["adaptive_state"] == "recovery"
        assert "Preamble" in summary["challenge_topics"]
        assert "Federalism" in summary["recovery_topics"]
        assert summary["subject_difficulty_band"] == "easy"
        assert summary["subject_adaptive_state"] == "recovery"
        assert summary["subject_difficulty_reason"]
    finally:
        db.close()


def test_weak_topic_strength_aligns_with_ranked_weak_topics_when_evidence_is_strong() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=2))
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(hours=4))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=2))

        summary = build_progress_summary_snapshot(db)
        ranked_weak_topic_names = [item["topic"] for item in summary["ranked_weak_topics"]]
        topic_strengths = {item["topic"]: item["topic_strength"] for item in summary["topic_accuracy"]}

        assert topic_strengths["Federalism"] == "weak"
        assert ranked_weak_topic_names
        assert ranked_weak_topic_names[0] == "Federalism"
        assert "Federalism" in summary["weak_topics"]
        assert "Preamble" not in summary["weak_topics"]
    finally:
        db.close()


def test_revision_signal_and_retention_risk_distinguish_neglected_topics_from_recently_reinforced_topics() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(days=8))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(days=6))
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=2))
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(hours=6))
        create_attempt(db, topic="Parliament", score=5, created_at=now - timedelta(days=3))
        create_attempt(db, topic="Parliament", score=5, created_at=now - timedelta(hours=18))
        create_attempt(db, topic="Directive Principles", score=4, created_at=now - timedelta(hours=6))

        summary = build_progress_summary_snapshot(db)
        topic_items = {item["topic"]: item for item in summary["topic_accuracy"]}

        assert topic_items["Preamble"]["topic_strength"] in {"strong", "medium"}
        assert topic_items["Preamble"]["revision_signal"] in {"due_now", "at_risk"}
        assert topic_items["Preamble"]["retention_risk"] in {"moderate", "high"}
        assert topic_items["Preamble"]["reinforcement_state"] == "overdue_reinforcement"

        assert topic_items["Federalism"]["topic_strength"] == "weak"
        assert topic_items["Federalism"]["revision_signal"] in {"due_now", "at_risk"}
        assert topic_items["Federalism"]["retention_risk"] == "high"
        assert topic_items["Federalism"]["reinforcement_state"] in {"reinforce_now", "overdue_reinforcement"}

        assert topic_items["Parliament"]["revision_signal"] == "stable"
        assert topic_items["Parliament"]["retention_risk"] == "low"
        assert topic_items["Parliament"]["reinforcement_state"] == "stable"

        assert topic_items["Directive Principles"]["reinforcement_state"] == "newly_learned"
        assert "Federalism" in summary["at_risk_topics"] or "Federalism" in summary["due_now_topics"]
    finally:
        db.close()


def test_strong_topic_can_be_due_if_neglected_long_enough() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="President", score=5, created_at=now - timedelta(days=10))
        create_attempt(db, topic="President", score=5, created_at=now - timedelta(days=8))

        summary = build_progress_summary_snapshot(db)
        president = next(item for item in summary["topic_accuracy"] if item["topic"] == "President")

        assert president["topic_strength"] in {"strong", "medium"}
        assert president["revision_signal"] in {"due_now", "at_risk"}
        assert president["retention_risk"] in {"moderate", "high"}
    finally:
        db.close()


def test_performance_trends_stay_stable_for_thin_subject_history() -> None:
    db = build_test_session()
    try:
        create_attempt(db, topic="Preamble", score=5, created_at=datetime.now(UTC) - timedelta(hours=4))

        summary = build_progress_summary_snapshot(db)
        trends = build_performance_trends(db, summary=summary)

        assert trends["trend_stability"] == "thin_history"
        assert trends["overall_trend"] == "stable"
        assert trends["revision_pressure"] in {"light", "building"}
    finally:
        db.close()


def test_performance_trends_blend_accuracy_momentum_and_revision_pressure() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Parliament", score=1, created_at=now - timedelta(days=6))
        create_attempt(db, topic="Parliament", score=2, created_at=now - timedelta(days=5))
        create_attempt(db, topic="Preamble", score=4, created_at=now - timedelta(days=3))
        create_attempt(db, topic="Parliament", score=4, created_at=now - timedelta(days=2))
        create_attempt(db, topic="Parliament", score=5, created_at=now - timedelta(hours=12))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=6))

        summary = build_progress_summary_snapshot(db)
        trends = build_performance_trends(db, summary=summary)

        assert trends["overall_trend"] == "improving"
        assert trends["accuracy_delta"] > 0
        assert trends["trend_stability"] in {"emerging", "established"}
        assert trends["revision_pressure"] in {"light", "building"}
        assert trends["improving_topic_count"] >= 1
        assert trends["weak_topic_count"] == 0
        assert trends["topics"][0]["trend_stability"] in {"emerging", "established"}
        assert "topic_strength" in trends["topics"][0]
    finally:
        db.close()


def test_due_soon_low_risk_strong_topic_does_not_override_better_incomplete_topic() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        recommendation = build_study_recommendation(
            db,
            subject="polity",
            current_topic="Parliament",
            topic_accuracy_items=[
                {
                    "subject": "polity",
                    "chapter": "General",
                    "topic": "Preamble",
                    "attempts_count": 4,
                    "study_count": 1,
                    "accuracy": 92.0,
                    "difficulty_band": "hard",
                    "weak_topic": False,
                    "recent_accuracy": 95.0,
                    "recent_failed_attempts": 0,
                    "repeated_mistakes": 0,
                    "next_revision_at": now + timedelta(hours=36),
                    "revision_status": "upcoming",
                    "strong_topic": True,
                    "topic_strength": "strong",
                    "revision_signal": "due_soon",
                    "retention_risk": "low",
                    "last_reinforced_at": now - timedelta(days=1),
                    "revision_reason": "Preamble is due for a light reinforcement round.",
                    "recommended_in_days": 3,
                    "mastery_score": 88.0,
                    "confidence_score": 70.0,
                    "stability_score": 78.0,
                    "strength_classification": "strong",
                    "long_term_trend": "stable",
                    "revision_readiness": "ready",
                },
                {
                    "subject": "polity",
                    "chapter": "General",
                    "topic": "Parliament",
                    "attempts_count": 1,
                    "study_count": 1,
                    "accuracy": 60.0,
                    "difficulty_band": "medium",
                    "weak_topic": False,
                    "recent_accuracy": 60.0,
                    "recent_failed_attempts": 0,
                    "repeated_mistakes": 0,
                    "next_revision_at": None,
                    "revision_status": "none",
                    "strong_topic": False,
                    "topic_strength": "medium",
                    "revision_signal": "stable",
                    "retention_risk": "low",
                    "last_reinforced_at": None,
                    "revision_reason": "",
                    "recommended_in_days": None,
                    "mastery_score": 58.0,
                    "confidence_score": 24.0,
                    "stability_score": 46.0,
                    "strength_classification": "developing",
                    "long_term_trend": "stable",
                    "revision_readiness": "building",
                },
            ],
            revision_recommendations=[
                {
                    "subject": "polity",
                    "chapter": "General",
                    "topic": "Preamble",
                    "due_at": now + timedelta(hours=36),
                    "recommended_in_days": 3,
                    "status": "upcoming",
                    "reason": "Preamble is due for a light reinforcement round.",
                }
            ],
        )

        assert recommendation.recommended_topic == "Parliament"
        assert recommendation.recommendation_source == "incomplete_topic"
    finally:
        db.close()

def test_due_now_retention_pressure_overrides_generic_continuation() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Parliament", score=3, created_at=now - timedelta(hours=1), subject="polity")
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(days=3), subject="polity")
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(days=2, hours=6), subject="polity")

        summary = build_progress_summary_snapshot(db, subject="polity")
        preamble = next(item for item in summary["topic_accuracy"] if item["topic"] == "Preamble")
        recommendation = build_study_recommendation(db, subject="polity")

        assert summary["continuation_topic"] == "Parliament"
        assert preamble["revision_signal"] == "due_now"
        assert preamble["retention_risk"] in {"moderate", "high"}
        assert recommendation.recommended_topic == "Preamble"
        assert recommendation.recommendation_source == "overdue_revision"
        assert recommendation.recommended_mode == "revise"
    finally:
        db.close()





def test_study_recommendation_exposes_recovery_profile_for_weak_topic() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Directive Principles", score=1, created_at=now - timedelta(days=2))
        create_attempt(db, topic="Directive Principles", score=2, created_at=now - timedelta(days=1))

        recommendation = build_study_recommendation(db, subject="polity")

        assert recommendation.recommended_topic == "Directive Principles"
        assert recommendation.recommended_mode == "revise"
        assert recommendation.recommended_difficulty_band == "easy"
        assert recommendation.recommended_adaptive_state == "recovery"
        assert recommendation.recommended_explanation_depth == "foundational"
        assert recommendation.recommended_difficulty_reason
        assert recommendation.recommended_explanation_depth_reason
    finally:
        db.close()


def test_priority_topics_expose_challenge_profile_for_strong_quiz_ready_topics() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(days=4))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(days=3))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(days=2))
        create_attempt(db, topic="Citizenship", score=5, created_at=now - timedelta(days=3))
        create_attempt(db, topic="Citizenship", score=5, created_at=now - timedelta(days=2))
        create_attempt(db, topic="Citizenship", score=5, created_at=now - timedelta(days=1))

        priority_topics = build_topic_priority_list(db, subject="polity")
        strong_quiz_item = next(
            item
            for item in priority_topics
            if item.recommendation_source == "strong_topic_quiz" and item.topic in {"Preamble", "Citizenship"}
        )

        assert strong_quiz_item.recommended_mode == "quiz"
        assert strong_quiz_item.recommended_adaptive_state == "challenge"
        assert strong_quiz_item.recommended_difficulty_band == "hard"
        assert strong_quiz_item.recommended_explanation_depth == "advanced"
    finally:
        db.close()


def test_summary_plan_and_coach_share_adaptive_recommendation_fields() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=2))
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=1))

        summary = build_progress_summary_snapshot(db, subject="polity")
        revision_due = build_revision_due_snapshot(db, summary=summary, subject="polity")
        daily_plan = build_daily_plan(db, summary=summary, revision_due=revision_due, subject="polity")
        coach_summary = build_coach_summary(db, summary=summary, revision_due=revision_due, daily_plan=daily_plan, subject="polity")

        assert summary["recommended_adaptive_state"] == "recovery"
        assert summary["recommended_difficulty_band"] == "easy"
        assert summary["recommended_explanation_depth"] == "foundational"
        assert daily_plan["recommended_adaptive_state"] == summary["recommended_adaptive_state"]
        assert daily_plan["recommended_difficulty_band"] == summary["recommended_difficulty_band"]
        assert daily_plan["recommended_explanation_depth"] == summary["recommended_explanation_depth"]
        assert coach_summary["recommended_adaptive_state"] == summary["recommended_adaptive_state"]
        assert coach_summary["recommended_difficulty_band"] == summary["recommended_difficulty_band"]
        assert coach_summary["recommended_explanation_depth"] == summary["recommended_explanation_depth"]
    finally:
        db.close()


def test_version9_recovery_guidance_stays_supportive_across_summary_plan_and_coach() -> None:
    db = build_test_session()
    try:
        create_attempt(db, topic="Federalism", score=1, created_at=datetime.now(UTC) - timedelta(days=3))

        summary = build_progress_summary_snapshot(db)
        revision_due = build_revision_due_snapshot(db, summary=summary)
        daily_plan = build_daily_plan(db, summary=summary, revision_due=revision_due)
        coach_summary = build_coach_summary(db, summary=summary, revision_due=revision_due, daily_plan=daily_plan)

        assert "supportive" in summary["study_profile"]["profile_summary"].lower()
        assert "foundational tutor explanation" in summary["study_profile"]["profile_summary"].lower()
        assert daily_plan["recommended_adaptive_state"] == "recovery"
        assert daily_plan["recommended_difficulty_band"] == "easy"
        assert daily_plan["recommended_explanation_depth"] == "foundational"
        assert "supportive" in daily_plan["coach_note"].lower()
        assert "foundational tutor explanation" in daily_plan["practice_action"].lower()
        assert "easy repair quiz" in daily_plan["quiz_action"].lower()
        assert "supportive" in coach_summary["coach_note"].lower()
        assert "foundational tutor explanation" in coach_summary["next_action"].lower()
    finally:
        db.close()



def test_version9_challenge_guidance_sentence_uses_stretch_language() -> None:
    sentence = _build_adaptive_guidance_sentence(
        recommended_topic="Preamble",
        recommended_mode="quiz",
        recommended_difficulty_band="hard",
        recommended_adaptive_state="challenge",
        recommended_explanation_depth="advanced",
    )

    lowered = sentence.lower()
    assert "stretch" in lowered
    assert "advanced tutor explanation" in lowered
    assert "hard stretch quiz" in lowered


def test_revision_recommendations_raise_wrong_answer_driven_repair_topics() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=2))
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(hours=10))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(days=6))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(days=4))

        summary = build_progress_summary_snapshot(db)
        revisions = summary["revision_recommendations"]
        federalism = next(item for item in revisions if item["topic"] == "Federalism")
        preamble = next(item for item in revisions if item["topic"] == "Preamble")
        assert federalism["priority_score"] > preamble["priority_score"]
        assert federalism["revision_intensity"] == "intensive"
        assert federalism["recommended_session_mode"] == "full_revision"
        assert federalism["wrong_answer_signal"] == "repeated_errors"
        assert federalism["recent_incorrect_questions"] >= 2
        assert federalism["reinforcement_state"] in {"reinforce_now", "overdue_reinforcement"}
        assert federalism["reinforcement_reason"]
        assert "repair-focused revision" in federalism["reason"].lower()
    finally:
        db.close()



def test_revision_intensity_keeps_stable_due_topics_light() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Parliament", score=5, created_at=now - timedelta(days=3))
        create_attempt(db, topic="Parliament", score=5, created_at=now - timedelta(hours=18))

        summary = build_progress_summary_snapshot(db)
        parliament = next(item for item in summary["revision_recommendations"] if item["topic"] == "Parliament")

        assert parliament["topic_strength"] == "strong"
        assert parliament["retention_risk"] in {"low", "moderate"}
        assert parliament["revision_intensity"] == "light"
        assert parliament["recommended_session_mode"] == "short_revision"
        assert "short" in parliament["reason"].lower() or "memory-refresh" in parliament["reason"].lower()
    finally:
        db.close()


def test_reinforcement_state_uses_last_correct_performance_instead_of_latest_wrong_attempt() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="President", score=5, created_at=now - timedelta(days=5))
        create_attempt(db, topic="President", score=1, created_at=now - timedelta(hours=6))

        summary = build_progress_summary_snapshot(db)
        president = next(item for item in summary["topic_accuracy"] if item["topic"] == "President")
        revision_item = next(item for item in summary["revision_recommendations"] if item["topic"] == "President")

        assert president["last_correct_performance_at"] is not None
        assert president["revision_signal"] == "at_risk"
        assert president["reinforcement_state"] == "overdue_reinforcement"
        assert revision_item["reinforcement_state"] == "overdue_reinforcement"
    finally:
        db.close()


def test_newly_learned_topics_surface_for_short_reinforcement_before_stable_upcoming_topics() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Directive Principles", score=4, created_at=now - timedelta(hours=6))
        create_attempt(db, topic="Parliament", score=5, created_at=now - timedelta(days=3))
        create_attempt(db, topic="Parliament", score=5, created_at=now - timedelta(hours=18))

        summary = build_progress_summary_snapshot(db)
        revisions = summary["revision_recommendations"]
        directive_principles = next(item for item in revisions if item["topic"] == "Directive Principles")
        parliament = next(item for item in revisions if item["topic"] == "Parliament")

        assert directive_principles["reinforcement_state"] == "newly_learned"
        assert directive_principles["recommended_session_mode"] == "short_revision"
        assert directive_principles["priority_score"] > parliament["priority_score"]
        assert parliament["reinforcement_state"] == "stable"
    finally:
        db.close()



def test_repeated_wrong_concepts_raise_revision_priority_and_recent_error_topics() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(
            db,
            topic="Federalism",
            score=3,
            created_at=now - timedelta(days=2),
            weak_areas=["distribution of powers", "emergency bias"],
        )
        create_attempt(
            db,
            topic="Federalism",
            score=4,
            created_at=now - timedelta(hours=3),
            weak_areas=["distribution of powers"],
        )
        create_attempt(db, topic="Parliament", score=5, created_at=now - timedelta(days=3))
        create_attempt(db, topic="Parliament", score=5, created_at=now - timedelta(hours=18))

        summary = build_progress_summary_snapshot(db)
        topic_items = {item["topic"]: item for item in summary["topic_accuracy"]}
        revisions = {item["topic"]: item for item in summary["revision_recommendations"]}

        assert topic_items["Federalism"]["wrong_answer_signal"] == "repeated_errors"
        assert topic_items["Federalism"]["recent_incorrect_questions"] >= 3
        assert "distribution of powers" in topic_items["Federalism"]["repeated_wrong_concepts"]
        assert summary["recent_error_topics"][0] == "Federalism"
        assert revisions["Federalism"]["priority_score"] > revisions["Parliament"]["priority_score"]
        assert revisions["Federalism"]["wrong_answer_signal"] == "repeated_errors"
    finally:
        db.close()


def test_revision_intensity_flows_into_coach_revision_guidance() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=2))
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(hours=10))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(hours=2))

        summary = build_progress_summary_snapshot(db)
        daily_plan = build_daily_plan(db, summary=summary)
        coach_summary = build_coach_summary(db, summary=summary, daily_plan=daily_plan)
        federalism = next(item for item in summary["revision_recommendations"] if item["topic"] == "Federalism")

        assert federalism["revision_intensity"] == "intensive"
        assert "repair-focused" in federalism["reason"].lower()
        assert coach_summary["revise_now"] == "Federalism"
        assert coach_summary["revise_reason"]
        assert "repair-focused" in coach_summary["revise_reason"].lower()
    finally:
        db.close()


def test_single_isolated_wrong_answer_on_strong_topic_does_not_overdrive_revision_queue() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(days=6))
        create_attempt(db, topic="Preamble", score=5, created_at=now - timedelta(days=3))
        create_attempt(db, topic="Preamble", score=4, created_at=now - timedelta(hours=2), weak_areas=["basic structure doctrine"])

        summary = build_progress_summary_snapshot(db)
        preamble = next(item for item in summary["topic_accuracy"] if item["topic"] == "Preamble")
        revision_item = next(item for item in summary["revision_recommendations"] if item["topic"] == "Preamble")

        assert preamble["recent_incorrect_questions"] == 1
        assert preamble["wrong_answer_signal"] == "none"
        assert "Preamble" not in summary["recent_error_topics"]
        assert revision_item["wrong_answer_signal"] == "none"
    finally:
        db.close()



def test_revision_due_snapshot_uses_priority_score_within_same_bucket() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        revision_due = build_revision_due_snapshot(
            db,
            summary={
                "subject": "polity",
                "weak_topics": ["Federalism"],
                "revision_recommendations": [
                    {
                        "subject": "polity",
                        "chapter": "General",
                        "topic": "Preamble",
                        "due_at": now + timedelta(hours=8),
                        "recommended_in_days": 2,
                        "status": "due_soon",
                        "reason": "Preamble needs a quick memory refresh.",
                        "priority_score": 36,
                        "revision_intensity": "light",
                    },
                    {
                        "subject": "polity",
                        "chapter": "General",
                        "topic": "Federalism",
                        "due_at": now + timedelta(hours=10),
                        "recommended_in_days": 1,
                        "status": "due_soon",
                        "reason": "Federalism needs a repair-focused revision round.",
                        "priority_score": 84,
                        "revision_intensity": "intensive",
                    },
                ],
            },
        )

        assert [item["topic"] for item in revision_due["due_now"][:2]] == ["Federalism", "Preamble"]
        assert revision_due["due_now"][0]["revision_intensity"] == "intensive"
    finally:
        db.close()




def test_overdue_revision_recommendation_uses_revision_queue_priority() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(days=2))
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(hours=36))
        create_attempt(db, topic="Parliament", score=2, created_at=now - timedelta(days=3))

        summary = build_progress_summary_snapshot(db, subject="polity")
        recommendation = build_study_recommendation(
            db,
            revision_recommendations=summary["revision_recommendations"],
            weak_topics=summary["weak_topics"],
            topic_accuracy_items=summary["topic_accuracy"],
            subject="polity",
        )
        federalism = next(item for item in summary["revision_recommendations"] if item["topic"] == "Federalism")
        parliament = next(item for item in summary["revision_recommendations"] if item["topic"] == "Parliament")

        assert federalism["status"] == "overdue"
        assert parliament["status"] == "overdue"
        assert federalism["priority_score"] > parliament["priority_score"]
        assert recommendation.recommended_topic == "Federalism"
        assert recommendation.recommendation_source == "overdue_revision"
    finally:
        db.close()



def test_repeated_errors_can_force_revision_priority_before_due_bucket_catches_up() -> None:
    db = build_test_session()
    try:
        now = datetime.now(UTC)
        create_attempt(db, topic="Federalism", score=4, created_at=now - timedelta(hours=6))
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(hours=3))
        create_attempt(db, topic="Federalism", score=1, created_at=now - timedelta(hours=1))

        summary = build_progress_summary_snapshot(db, subject="polity")
        recommendation = build_study_recommendation(
            db,
            revision_recommendations=summary["revision_recommendations"],
            weak_topics=summary["weak_topics"],
            topic_accuracy_items=summary["topic_accuracy"],
            subject="polity",
        )
        federalism = next(item for item in summary["revision_recommendations"] if item["topic"] == "Federalism")

        assert federalism["wrong_answer_signal"] == "repeated_errors"
        assert federalism["revision_intensity"] == "intensive"
        assert federalism["reinforcement_state"] in {"reinforce_now", "overdue_reinforcement"}
        assert federalism["status"] in {"upcoming", "due_soon", "overdue"}
        assert recommendation.recommended_topic == "Federalism"
        assert recommendation.recommended_mode == "revise"
        assert recommendation.recommendation_source == "overdue_revision"
    finally:
        db.close()
