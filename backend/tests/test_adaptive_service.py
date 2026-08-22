from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
import pytest
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / ".deps"))

from backend.db import Base
from backend.models import Quiz, QuizAttempt, TopicProgress, TopicStudy
from backend.services.adaptive_service import (
    MIN_DIFFICULTY_EVIDENCE_ATTEMPTS,
    build_explanation_depth_profile,
    build_subject_difficulty_profile,
    build_topic_difficulty_profile,
    choose_next_topic_recommendation,
    classify_revision_status,
    compute_revision_due_at,
    determine_difficulty,
    is_weak_topic,
)
from backend.services.progress_service import build_revision_recommendations, get_topic_accuracy, record_attempt, serialize_attempts, sync_topic_progress
from backend.services.recommendation_service import recommend_next_topic_with_reason
from backend.services.test_service import generate_quiz, submit_quiz


def build_test_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return testing_session()


def test_determine_difficulty_follows_adaptive_rules() -> None:
    assert determine_difficulty(None) == "medium"
    assert determine_difficulty(85.0) == "hard"
    assert determine_difficulty(72.0) == "medium"
    assert determine_difficulty(41.0) == "easy"
    assert determine_difficulty(88.0, recent_accuracies=[42.0, 45.0, 47.0]) == "hard"


@pytest.mark.parametrize(
    ("profile_overrides", "expected_difficulty", "expected_state"),
    [
        ({"accuracy": None, "recent_accuracy": 0.0, "attempts_count": 0}, "medium", "steady"),
        (
            {
                "accuracy": 100.0,
                "recent_accuracy": 100.0,
                "attempts_count": 1,
                "mastery_score": 92.0,
                "topic_strength": "strong",
            },
            "medium",
            "steady",
        ),
        (
            {
                "accuracy": 40.0,
                "recent_accuracy": 40.0,
                "attempts_count": 1,
                "mastery_score": 35.0,
                "topic_strength": "weak",
                "revision_signal": "at_risk",
                "retention_risk": "high",
            },
            "easy",
            "recovery",
        ),
        (
            {
                "accuracy": 95.0,
                "recent_accuracy": 95.0,
                "attempts_count": MIN_DIFFICULTY_EVIDENCE_ATTEMPTS,
                "mastery_score": 90.0,
                "confidence_score": 50.0,
                "stability_score": 75.0,
                "topic_strength": "strong",
                "revision_readiness": "ready",
            },
            "hard",
            "challenge",
        ),
        (
            {
                "accuracy": 30.0,
                "recent_accuracy": 25.0,
                "attempts_count": 3,
                "mastery_score": 28.0,
                "topic_strength": "weak",
                "recent_failed_attempts": 2,
                "repeated_mistakes": 2,
            },
            "easy",
            "recovery",
        ),
        (
            {
                "accuracy": 65.0,
                "recent_accuracy": 60.0,
                "attempts_count": 3,
                "mastery_score": 62.0,
                "confidence_score": 40.0,
                "stability_score": 60.0,
                "revision_signal": "due_soon",
                "retention_risk": "moderate",
            },
            "medium",
            "steady",
        ),
    ],
)
def test_topic_difficulty_boundaries_require_reliable_evidence(
    profile_overrides: dict,
    expected_difficulty: str,
    expected_state: str,
) -> None:
    profile_args = {
        "topic": "Preamble",
        "accuracy": 70.0,
        "recent_accuracy": 70.0,
        "attempts_count": 2,
        "mastery_score": 65.0,
        "confidence_score": 40.0,
        "stability_score": 60.0,
        "topic_strength": "medium",
        "revision_readiness": "building",
        "revision_signal": "stable",
        "retention_risk": "low",
        "long_term_trend": "stable",
        "recent_failed_attempts": 0,
        "repeated_mistakes": 0,
    }
    profile_args.update(profile_overrides)

    profile = build_topic_difficulty_profile(**profile_args)

    assert profile["difficulty_band"] == expected_difficulty
    assert profile["adaptive_state"] == expected_state


def test_weak_topic_detection_uses_multiple_signals() -> None:
    assert is_weak_topic(45.0, recent_failed_attempts=0, repeated_mistake_count=0) is True
    assert is_weak_topic(72.0, recent_failed_attempts=2, repeated_mistake_count=0) is True
    assert is_weak_topic(72.0, recent_failed_attempts=0, repeated_mistake_count=2) is True
    assert is_weak_topic(82.0, recent_failed_attempts=0, repeated_mistake_count=0) is False



def test_topic_adaptive_profile_prefers_recovery_for_weak_risky_topic() -> None:
    profile = build_topic_difficulty_profile(
        topic="Federalism",
        accuracy=35.0,
        recent_accuracy=40.0,
        attempts_count=2,
        mastery_score=32.0,
        confidence_score=24.0,
        stability_score=34.0,
        topic_strength="weak",
        revision_readiness="needs_refresh",
        revision_signal="at_risk",
        retention_risk="high",
        long_term_trend="declining",
    )

    assert profile["difficulty_band"] == "easy"
    assert profile["adaptive_state"] == "recovery"
    assert "Federalism" in profile["reason"]



def test_topic_adaptive_profile_needs_stable_history_before_challenge() -> None:
    thin_history_profile = build_topic_difficulty_profile(
        topic="Preamble",
        accuracy=95.0,
        recent_accuracy=95.0,
        attempts_count=1,
        mastery_score=88.0,
        confidence_score=28.0,
        stability_score=74.0,
        topic_strength="strong",
        revision_readiness="ready",
        revision_signal="stable",
        retention_risk="low",
        long_term_trend="improving",
    )
    established_profile = build_topic_difficulty_profile(
        topic="Preamble",
        accuracy=92.0,
        recent_accuracy=90.0,
        attempts_count=3,
        mastery_score=86.0,
        confidence_score=52.0,
        stability_score=76.0,
        topic_strength="strong",
        revision_readiness="ready",
        revision_signal="stable",
        retention_risk="low",
        long_term_trend="improving",
    )

    assert thin_history_profile["difficulty_band"] == "medium"
    assert thin_history_profile["adaptive_state"] == "steady"
    assert established_profile["difficulty_band"] == "hard"
    assert established_profile["adaptive_state"] == "challenge"

def test_topic_adaptive_profile_keeps_medium_for_in_progress_topic() -> None:
    profile = build_topic_difficulty_profile(
        topic="Parliament",
        accuracy=68.0,
        recent_accuracy=66.0,
        attempts_count=3,
        mastery_score=63.0,
        confidence_score=40.0,
        stability_score=58.0,
        topic_strength="medium",
        revision_readiness="building",
        revision_signal="due_soon",
        retention_risk="moderate",
        long_term_trend="stable",
        recent_failed_attempts=1,
        repeated_mistakes=1,
    )

    assert profile["difficulty_band"] == "medium"
    assert profile["adaptive_state"] == "steady"


def test_explanation_depth_profile_prefers_foundational_for_thin_history() -> None:
    profile = build_explanation_depth_profile(
        topic="Federalism",
        mastery_score=None,
        topic_strength=None,
        adaptive_state="steady",
        recent_accuracy=None,
        attempts_count=0,
        subject_adaptive_state="steady",
    )

    assert profile["explanation_depth"] == "foundational"
    assert profile["teaching_support"] == "supportive"
    assert profile["teaching_pacing"] == "gentle"
    assert profile["conceptual_density"] == "low"
    assert "Federalism" in profile["reason"]



def test_explanation_depth_profile_prefers_foundational_for_recovery_topics() -> None:
    profile = build_explanation_depth_profile(
        topic="Directive Principles",
        mastery_score=34.0,
        topic_strength="weak",
        adaptive_state="recovery",
        recent_accuracy=42.0,
        attempts_count=3,
        confidence_score=28.0,
        stability_score=32.0,
        retention_risk="high",
        long_term_trend="declining",
        subject_adaptive_state="recovery",
    )

    assert profile["explanation_depth"] == "foundational"
    assert profile["teaching_support"] == "supportive"
    assert profile["teaching_pacing"] == "gentle"
    assert profile["conceptual_density"] == "low"



def test_explanation_depth_profile_prefers_advanced_for_strong_challenge_topics() -> None:
    profile = build_explanation_depth_profile(
        topic="Preamble",
        mastery_score=88.0,
        topic_strength="strong",
        adaptive_state="challenge",
        recent_accuracy=90.0,
        attempts_count=3,
        confidence_score=48.0,
        stability_score=74.0,
        retention_risk="low",
        long_term_trend="improving",
        subject_adaptive_state="steady",
    )

    assert profile["explanation_depth"] == "advanced"
    assert profile["teaching_support"] == "stretch"
    assert profile["teaching_pacing"] == "accelerated"
    assert profile["conceptual_density"] == "high"



def test_explanation_depth_profile_uses_standard_for_consolidating_topics() -> None:
    profile = build_explanation_depth_profile(
        topic="Parliament",
        mastery_score=62.0,
        topic_strength="medium",
        adaptive_state="steady",
        recent_accuracy=66.0,
        attempts_count=3,
        confidence_score=36.0,
        stability_score=58.0,
        retention_risk="moderate",
        long_term_trend="stable",
        subject_adaptive_state="steady",
    )

    assert profile["explanation_depth"] == "standard"
    assert profile["teaching_support"] == "balanced"
    assert profile["teaching_pacing"] == "balanced"
    assert profile["conceptual_density"] == "medium"



def test_topic_adaptive_profile_uses_repeated_mistakes_to_hold_recovery() -> None:
    profile = build_topic_difficulty_profile(
        topic="Federalism",
        accuracy=62.0,
        recent_accuracy=52.0,
        attempts_count=4,
        mastery_score=56.0,
        confidence_score=38.0,
        stability_score=46.0,
        topic_strength="weak",
        revision_readiness="needs_refresh",
        revision_signal="due_now",
        retention_risk="high",
        long_term_trend="declining",
        recent_failed_attempts=1,
        repeated_mistakes=3,
    )

    assert profile["difficulty_band"] == "easy"
    assert profile["adaptive_state"] == "recovery"




def test_subject_adaptive_profile_prefers_recovery_when_revision_pressure_is_high() -> None:
    profile = build_subject_difficulty_profile(
        subject="polity",
        overall_mastery_score=51.0,
        overall_confidence_score=41.0,
        overall_stability_score=44.0,
        strong_count=1,
        medium_count=1,
        weak_count=3,
        ready_count=1,
        needs_refresh_count=3,
        at_risk_topic_count=2,
        due_now_topic_count=1,
        overall_trend="declining",
        trend_stability="established",
    )

    assert profile["difficulty_band"] == "easy"
    assert profile["adaptive_state"] == "recovery"
    assert "Polity" in profile["reason"]

def test_subject_adaptive_profile_can_recommend_challenge_for_stable_subject() -> None:
    profile = build_subject_difficulty_profile(
        subject="history",
        overall_mastery_score=79.0,
        overall_confidence_score=56.0,
        overall_stability_score=68.0,
        strong_count=4,
        medium_count=1,
        weak_count=0,
        ready_count=4,
        needs_refresh_count=1,
        at_risk_topic_count=0,
        due_now_topic_count=0,
        overall_trend="improving",
        trend_stability="established",
        recent_average=84.0,
        previous_average=75.0,
        accuracy_delta=9.0,
        revision_pressure="light",
        ranked_weak_topic_count=0,
    )

    assert profile["difficulty_band"] == "hard"
    assert profile["adaptive_state"] == "challenge"



def test_revision_recommendation_logic_uses_shorter_cycle_for_weak_topics() -> None:
    now = datetime.now(UTC)
    interval_days, due_at = compute_revision_due_at(
        last_interaction_at=now - timedelta(days=2),
        weak_topic=True,
        study_count=1,
        attempts_count=1,
    )

    assert interval_days == 1
    assert due_at is not None
    assert classify_revision_status(due_at, now=now) == "overdue"


def test_recommendation_logic_prefers_overdue_weak_revisions() -> None:
    message, reason = choose_next_topic_recommendation(
        weak_topics=["Federalism"],
        revision_recommendations=[
            {
                "topic": "Federalism",
                "status": "overdue",
                "reason": "Federalism is overdue for revision after repeated recent mistakes.",
            }
        ],
        unseen_topics=["Preamble"],
        strong_topics=["Parliament"],
    )

    assert "Federalism" in message
    assert "Federalism" in reason


def test_generate_quiz_keeps_medium_difficulty_for_thin_but_strong_topic_history() -> None:
    db = build_test_session()
    try:
        create_attempt(db, topic="Fundamental Rights", score=5, total_questions=5)

        quiz = generate_quiz(db=db, topic="Fundamental Rights", question_count=5)

        assert quiz["difficulty"] == "medium"
        assert quiz["adaptive_state"] == "steady"
    finally:
        db.close()


def test_generate_quiz_starts_at_medium_without_history() -> None:
    db = build_test_session()
    try:
        quiz = generate_quiz(db=db, topic="Federalism", question_count=5)

        assert quiz["difficulty"] == "medium"
        assert quiz["adaptive_state"] == "steady"
    finally:
        db.close()


def test_generate_quiz_uses_hard_only_after_repeated_strong_history() -> None:
    db = build_test_session()
    try:
        for _ in range(3):
            create_attempt(db, topic="Fundamental Rights", score=5, total_questions=5)

        quiz = generate_quiz(db=db, topic="Fundamental Rights", question_count=5, quiz_mode="test")

        assert quiz["difficulty"] == "hard"
        assert quiz["adaptive_state"] == "challenge"
    finally:
        db.close()


def test_generate_quiz_keeps_easy_for_repeated_weak_history() -> None:
    db = build_test_session()
    try:
        for _ in range(2):
            create_attempt(db, topic="Directive Principles", score=1, total_questions=5)

        quiz = generate_quiz(db=db, topic="Directive Principles", question_count=5)

        assert quiz["difficulty"] == "easy"
        assert quiz["adaptive_state"] == "recovery"
    finally:
        db.close()



def test_generate_quiz_uses_medium_difficulty_for_mid_topic_performance() -> None:
    db = build_test_session()
    try:
        create_attempt(db, topic="Preamble", score=4, total_questions=5)

        quiz = generate_quiz(db=db, topic="Preamble", question_count=5)

        assert quiz["difficulty"] == "medium"
    finally:
        db.close()

def test_generate_quiz_uses_easy_difficulty_for_weak_topic_performance() -> None:
    db = build_test_session()
    try:
        create_attempt(db, topic="Directive Principles", score=2, total_questions=5)

        quiz = generate_quiz(db=db, topic="Directive Principles", question_count=5)

        assert quiz["difficulty"] == "easy"
    finally:
        db.close()


def test_generate_quiz_practice_mode_caps_challenge_topics_at_medium() -> None:
    db = build_test_session()
    try:
        for _ in range(3):
            create_attempt(db, topic="Fundamental Rights", score=5, total_questions=5)
            create_attempt(db, topic="Preamble", score=5, total_questions=5)

        quiz = generate_quiz(db=db, topic="Fundamental Rights", question_count=5, quiz_mode="practice")

        assert quiz["difficulty"] == "medium"
        assert quiz["adaptive_state"] == "challenge"
    finally:
        db.close()



def test_generate_quiz_test_mode_caps_challenge_topics_when_subject_is_in_recovery() -> None:
    db = build_test_session()
    try:
        for _ in range(3):
            create_attempt(db, topic="Fundamental Rights", score=5, total_questions=5)
            create_attempt(db, topic="Directive Principles", score=1, total_questions=5)
            create_attempt(db, topic="Citizenship", score=2, total_questions=5)

        quiz = generate_quiz(db=db, topic="Fundamental Rights", question_count=5, quiz_mode="test")

        assert quiz["difficulty"] == "medium"
        assert quiz["adaptive_state"] == "steady"
    finally:
        db.close()



def test_generate_quiz_revision_mode_keeps_revision_focus_even_for_strong_topics() -> None:
    db = build_test_session()
    try:
        for _ in range(3):
            create_attempt(db, topic="Fundamental Rights", score=5, total_questions=5)
            create_attempt(db, topic="Preamble", score=5, total_questions=5)

        quiz = generate_quiz(db=db, topic="Fundamental Rights", question_count=5, quiz_mode="revision")

        assert quiz["quiz_mode"] == "revision"
        assert quiz["difficulty"] == "medium"
        assert quiz["adaptive_state"] == "steady"
        assert quiz["covered_topics"] == [quiz["topic"]]
    finally:
        db.close()



def test_generate_quiz_weak_area_drill_stays_easy_recovery() -> None:
    db = build_test_session()
    try:
        for _ in range(2):
            create_attempt(db, topic="Directive Principles", score=1, total_questions=5)

        quiz = generate_quiz(db=db, topic="Fundamental Rights", question_count=5, quiz_mode="weak_area_drill")

        assert quiz["quiz_mode"] == "weak_area_drill"
        assert quiz["difficulty"] == "easy"
        assert quiz["adaptive_state"] == "recovery"
    finally:
        db.close()


def test_recommendation_engine_can_keep_student_on_recent_topic_for_consolidation() -> None:
    db = build_test_session()
    try:
        db.add(
            TopicProgress(
                topic="Parliament",
                subject="polity",
                attempts_count=2,
                correct_answers=6,
                total_answers=10,
                accuracy=60.0,
                difficulty_band="medium",
                weak_topic=False,
            )
        )
        db.add(TopicStudy(topic="Parliament", subject="polity", study_count=1))
        db.commit()

        message, reason = recommend_next_topic_with_reason(
            db=db,
            current_topic="Parliament",
            weak_topics=[],
            revision_recommendations=[],
            strong_topics=[],
        )

        assert "Parliament" in message
        assert "Parliament" in reason
    finally:
        db.close()


def test_recently_studied_topic_gets_revision_suggestion_even_without_quiz_attempt() -> None:
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

        recommendations = build_revision_recommendations(db, topic_accuracy_items=[])
        preamble = next((item for item in recommendations if item["topic"] == "Preamble"), None)

        assert preamble is not None
        assert preamble["recommended_in_days"] == 1
        assert preamble["status"] in {"due_soon", "upcoming"}
        assert "Preamble" in preamble["reason"]
    finally:
        db.close()



def create_quiz_row(db, topic: str, difficulty: str = "medium", question_count: int = 5, questions_json: str = "[]") -> Quiz:
    quiz = Quiz(topic=topic, subject="polity", difficulty=difficulty, question_count=question_count, questions_json=questions_json)
    db.add(quiz)
    db.commit()
    db.refresh(quiz)
    return quiz


def create_attempt(db, topic: str, score: int, total_questions: int = 5, difficulty: str = "medium"):
    quiz = create_quiz_row(db, topic=topic, difficulty=difficulty, question_count=total_questions)
    return record_attempt(
        db=db,
        quiz_id=quiz.id,
        topic=topic,
        difficulty=difficulty,
        answers=[f"Answer {index}" for index in range(total_questions)],
        score=score,
        total_questions=total_questions,
        incorrect_questions=[],
        weak_areas=[] if score == total_questions else [topic],
        next_recommendation="Review the topic once and try another quiz.",
    )


def test_submit_quiz_scores_using_actual_correct_answer_not_first_option() -> None:
    db = build_test_session()
    try:
        questions = [
            {
                "question": "Q1",
                "options": ["Wrong A", "Correct A", "Wrong B", "Wrong C"],
                "correct_answer": "Correct A",
                "explanation": "Explanation A",
            },
            {
                "question": "Q2",
                "options": ["Wrong D", "Wrong E", "Wrong F", "Correct B"],
                "correct_answer": "Correct B",
                "explanation": "Explanation B",
            },
        ]
        quiz = create_quiz_row(db, topic="Fundamental Rights", question_count=2, questions_json=json.dumps(questions))

        result = submit_quiz(db=db, quiz_id=quiz.id, answers=["Wrong A", "Correct B"])

        assert result["score"] == 1
        assert result["accuracy"] == 50.0
        assert len(result["incorrect_questions"]) == 1
        assert result["incorrect_questions"][0]["selected_answer"] == "Wrong A"
        assert result["incorrect_questions"][0]["correct_answer"] == "Correct A"
        assert result["incorrect_questions"][0]["explanation"] == "Explanation A"
    finally:
        db.close()


def test_progress_sync_removes_stale_rows_without_attempts() -> None:
    db = build_test_session()
    try:
        db.add(
            TopicProgress(
                topic="Preamble",
                subject="polity",
                attempts_count=5,
                correct_answers=25,
                total_answers=25,
                accuracy=100.0,
                difficulty_band="hard",
                weak_topic=False,
            )
        )
        db.commit()

        accuracy_rows = get_topic_accuracy(db)

        assert accuracy_rows == []
        assert db.query(TopicProgress).filter(TopicProgress.topic == "Preamble").first() is None
    finally:
        db.close()


@pytest.mark.parametrize(
    ("topic", "score", "expected_accuracy", "expected_difficulty"),
    [
        ("Fundamental Duties", 3, 60.0, "medium"),
        ("Preamble", 4, 80.0, "medium"),
        ("Citizenship", 5, 100.0, "hard"),
    ],
)
def test_progress_accuracy_matches_submitted_results(topic: str, score: int, expected_accuracy: float, expected_difficulty: str) -> None:
    db = build_test_session()
    try:
        create_attempt(db, topic=topic, score=score, total_questions=5)

        progress = sync_topic_progress(db, topic=topic)

        assert progress is not None
        assert progress.attempts_count == 1
        assert progress.correct_answers == score
        assert progress.total_answers == 5
        assert progress.accuracy == expected_accuracy
        assert progress.difficulty_band == expected_difficulty
    finally:
        db.close()



def test_progress_merges_legacy_topic_variants_under_one_canonical_topic() -> None:
    db = build_test_session()
    try:
        quiz = create_quiz_row(db, topic="Preamble", question_count=5)
        db.add_all(
            [
                QuizAttempt(
                    quiz_id=quiz.id,
                    topic="preamble",
                    subject="polity",
                    difficulty="medium",
                    submitted_answers_json=json.dumps(["A", "B", "C", "D", "E"]),
                    score=3,
                    total_questions=5,
                    accuracy=60.0,
                    incorrect_questions_json=json.dumps([]),
                    weak_areas_json=json.dumps(["Preamble"]),
                    next_recommendation="Revise Preamble.",
                ),
                QuizAttempt(
                    quiz_id=quiz.id,
                    topic=" Preamble ",
                    subject="polity",
                    difficulty="medium",
                    submitted_answers_json=json.dumps(["A", "B", "C", "D", "E"]),
                    score=5,
                    total_questions=5,
                    accuracy=100.0,
                    incorrect_questions_json=json.dumps([]),
                    weak_areas_json=json.dumps([]),
                    next_recommendation="Move Preamble to hard mode.",
                ),
            ]
        )
        db.commit()

        accuracy_rows = get_topic_accuracy(db)
        serialized_history = serialize_attempts(
            db.query(QuizAttempt).order_by(QuizAttempt.created_at.desc(), QuizAttempt.id.desc()).all()
        )

        assert len(accuracy_rows) == 1
        progress = accuracy_rows[0]
        assert progress.topic == "Preamble"
        assert progress.correct_answers == 8
        assert progress.total_answers == 10
        assert progress.accuracy == 80.0
        assert {item["topic"] for item in serialized_history} == {"Preamble"}
    finally:
        db.close()

def test_generate_quiz_recomputes_difficulty_from_actual_attempt_history() -> None:
    db = build_test_session()
    try:
        create_attempt(db, topic="Directive Principles", score=0, total_questions=5)
        stale_progress = db.query(TopicProgress).filter(TopicProgress.topic == "Directive Principles").first()
        assert stale_progress is not None
        stale_progress.correct_answers = 25
        stale_progress.total_answers = 25
        stale_progress.accuracy = 100.0
        stale_progress.difficulty_band = "hard"
        stale_progress.weak_topic = False
        db.commit()

        quiz = generate_quiz(db=db, topic="Directive Principles", question_count=5)
        refreshed_progress = db.query(TopicProgress).filter(TopicProgress.topic == "Directive Principles").first()

        assert quiz["difficulty"] == "easy"
        assert refreshed_progress is not None
        assert refreshed_progress.accuracy == 0.0
        assert refreshed_progress.difficulty_band == "easy"
    finally:
        db.close()



@pytest.mark.parametrize(
    ("answers", "expected_score", "expected_accuracy"),
    [
        (["Correct A", "Correct B", "Correct C", "Wrong D", "Wrong E"], 3, 60.0),
        (["Correct A", "Correct B", "Correct C", "Correct D", "Wrong E"], 4, 80.0),
        (["Correct A", "Correct B", "Correct C", "Correct D", "Correct E"], 5, 100.0),
    ],
)
def test_submit_quiz_reports_expected_score_percentages(answers: list[str], expected_score: int, expected_accuracy: float) -> None:
    db = build_test_session()
    try:
        questions = [
            {
                "question": "Q1",
                "options": ["Wrong 1", "Correct A", "Wrong 2", "Wrong 3"],
                "correct_answer": "Correct A",
                "explanation": "Explanation A",
            },
            {
                "question": "Q2",
                "options": ["Wrong 4", "Wrong 5", "Correct B", "Wrong 6"],
                "correct_answer": "Correct B",
                "explanation": "Explanation B",
            },
            {
                "question": "Q3",
                "options": ["Correct C", "Wrong 7", "Wrong 8", "Wrong 9"],
                "correct_answer": "Correct C",
                "explanation": "Explanation C",
            },
            {
                "question": "Q4",
                "options": ["Wrong 10", "Correct D", "Wrong 11", "Wrong 12"],
                "correct_answer": "Correct D",
                "explanation": "Explanation D",
            },
            {
                "question": "Q5",
                "options": ["Wrong 13", "Wrong 14", "Wrong 15", "Correct E"],
                "correct_answer": "Correct E",
                "explanation": "Explanation E",
            },
        ]
        quiz = create_quiz_row(db, topic="Parliament", question_count=5, questions_json=json.dumps(questions))

        result = submit_quiz(db=db, quiz_id=quiz.id, answers=answers)

        assert result["score"] == expected_score
        assert result["accuracy"] == expected_accuracy
    finally:
        db.close()







