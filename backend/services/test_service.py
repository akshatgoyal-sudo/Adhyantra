from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.config import (
    get_exam_definition,
    get_exam_subject_label,
    get_exam_subject_mapping,
    list_subject_sequence,
    normalize_exam,
    normalize_exam_subject,
    normalize_subject,
    resolve_exam_content_subject,
)
from backend.models import Quiz, QuizAttempt
from backend.services.adaptive_service import (
    MIN_DIFFICULTY_EVIDENCE_ATTEMPTS,
    build_post_quiz_guidance,
    build_topic_difficulty_profile,
)
from backend.services.ai_service import AIService, AIServiceUnavailableError
from backend.services.coach_service import (
    build_coach_summary,
    build_daily_plan,
    build_performance_trends,
    build_progress_summary_snapshot,
    build_revision_due_snapshot,
)
from backend.services.knowledge_service import (
    build_content_sourcing_metadata,
    build_grounded_generation_context,
    get_topic_document,
    list_topic_documents,
)
from backend.services.progress_service import (
    apply_learning_exam_scope,
    apply_learning_owner_scope,
    determine_difficulty,
    record_attempt,
    sync_topic_progress,
)
from backend.services.recommendation_service import recommend_next_topic


ai_service = AIService()
logger = logging.getLogger(__name__)

_QUIZ_STYLE_PROFILES: dict[str, dict[str, str]] = {
    "mixed_conceptual_application": {
        "difficulty_emphasis": "balanced conceptual application",
        "balance_style": "concept-linked assessment balance",
        "prompt_note": "Keep the quiz balanced between core concept understanding and one applied check per cluster.",
    },
    "direct_plus_contextual_recall": {
        "difficulty_emphasis": "direct recall first, then light contextual application",
        "balance_style": "recall-forward with one contextual check",
        "prompt_note": "Favor direct recall with a light contextual extension instead of stacking multiple applied twists in the same question.",
    },
    "fast_recall_with_basic_elimination": {
        "difficulty_emphasis": "fast recall with basic elimination pressure",
        "balance_style": "high-yield recall with quick distractor elimination",
        "prompt_note": "Keep stems short, high-yield, and elimination-friendly so the quiz rewards fast, accurate recall.",
    },
    "speed_accuracy_and_financial_awareness": {
        "difficulty_emphasis": "speed-and-accuracy under practical awareness pressure",
        "balance_style": "compact awareness checks with practical recall anchors",
        "prompt_note": "Keep questions compact, practical, and awareness-oriented so the quiz rewards speed, accuracy, and precise recall.",
    },
}


def build_question_id(quiz_id: int, question: dict[str, Any]) -> str:
    signature = json.dumps(
        {
            "quiz_id": quiz_id,
            "concept": question.get("concept", ""),
            "question": question.get("question", ""),
            "options": question.get("options", []),
            "correct_answer": question.get("correct_answer", ""),
        },
        sort_keys=True,
        ensure_ascii=True,
    )
    digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:16]
    return f"question-{digest}"


def ensure_question_ids(quiz_id: int, questions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    normalized_questions: list[dict[str, Any]] = []
    changed = False

    for question in questions:
        normalized_question = dict(question)
        question_id = normalized_question.get("question_id")
        if not isinstance(question_id, str) or not question_id.strip():
            normalized_question["question_id"] = build_question_id(quiz_id, normalized_question)
            changed = True
        else:
            normalized_question["question_id"] = question_id.strip()
        normalized_questions.append(normalized_question)

    return normalized_questions, changed


def normalize_submitted_answers(raw_answers: list[Any], questions: list[dict[str, Any]]) -> tuple[dict[str, str], list[str]]:
    if not isinstance(raw_answers, list):
        raise HTTPException(status_code=400, detail="Answers must be submitted as a list.")

    question_ids = [str(question["question_id"]).strip() for question in questions]
    if all(isinstance(item, str) for item in raw_answers):
        if len(raw_answers) != len(questions):
            raise HTTPException(status_code=400, detail="Answer count must match question count.")
        ordered_answers = [str(item).strip() for item in raw_answers]
        return dict(zip(question_ids, ordered_answers, strict=False)), ordered_answers

    if all(isinstance(item, dict) or hasattr(item, "question_id") for item in raw_answers):
        answer_map: dict[str, str] = {}
        for item in raw_answers:
            normalized_item = item
            if not isinstance(normalized_item, dict):
                if hasattr(normalized_item, "model_dump"):
                    normalized_item = normalized_item.model_dump()
                else:
                    normalized_item = {
                        "question_id": getattr(normalized_item, "question_id", ""),
                        "selected_answer": getattr(normalized_item, "selected_answer", ""),
                    }

            question_id = str(normalized_item.get("question_id", "")).strip()
            selected_answer = str(normalized_item.get("selected_answer", "")).strip()
            if not question_id:
                raise HTTPException(status_code=400, detail="Each submitted answer must include a question_id.")
            if question_id in answer_map:
                raise HTTPException(status_code=400, detail="Duplicate question_id found in submitted answers.")
            answer_map[question_id] = selected_answer

        if set(answer_map.keys()) != set(question_ids):
            raise HTTPException(status_code=400, detail="Submitted answers must cover every quiz question exactly once.")

        ordered_answers = [answer_map[question_id] for question_id in question_ids]
        return answer_map, ordered_answers

    raise HTTPException(status_code=400, detail="Answers must be a list of strings or question/answer mappings.")


def normalize_quiz_mode(quiz_mode: str | None) -> str:
    normalized_mode = (quiz_mode or "test").strip().lower()
    if normalized_mode == "standard":
        return "test"
    if normalized_mode in {"practice", "test", "revision", "weak_area_drill"}:
        return normalized_mode
    return "test"


def normalize_revision_session_mode(revision_session_mode: str | None) -> str:
    normalized_mode = (revision_session_mode or "full_revision").strip().lower()
    if normalized_mode in {"short_revision", "full_revision"}:
        return normalized_mode
    return "full_revision"


def _resolve_requested_quiz_mode(
    *,
    requested_mode: str | None,
    requested_topic: str,
    summary: dict[str, Any],
) -> tuple[str, str | None]:
    explicit_mode = str(requested_mode or "").strip()
    if explicit_mode:
        return normalize_quiz_mode(explicit_mode), None

    normalized_requested_topic = _topic_key(requested_topic)
    recommended_mode = str(summary.get("recommended_mode") or "study").strip().lower()
    recommendation_source = str(summary.get("recommendation_source") or "fallback").strip().lower()
    recommended_topic = str(summary.get("recommended_next_topic") or "").strip() or requested_topic
    weak_topic_keys = {
        _topic_key(topic)
        for topic in summary.get("weak_topics", [])
        if _topic_key(topic)
    }
    due_topic_keys = {
        _topic_key(item.get("topic"))
        for item in summary.get("revision_recommendations", [])
        if isinstance(item, dict) and _topic_key(item.get("topic"))
    }
    recent_error_topic_keys = {
        _topic_key(topic)
        for topic in summary.get("recent_error_topics", [])
        if _topic_key(topic)
    }

    if (
        recommended_mode == "revise"
        or recommendation_source in {"overdue_revision", "weak_area", "weak_topic"}
        or normalized_requested_topic in weak_topic_keys
        or normalized_requested_topic in due_topic_keys
        or normalized_requested_topic in recent_error_topic_keys
    ):
        focus_topic = recommended_topic.strip() or requested_topic.strip() or "this topic"
        return (
            "revision",
            f"No quiz mode was specified, so Adhyantra used revision mode because {focus_topic} is currently sitting inside the live repair or revision path.",
        )

    return "test", None


def _build_exam_quiz_profile(*, subject: str | None, exam: str | None) -> dict[str, str | None]:
    resolved_exam = normalize_exam(exam)
    exam_definition = get_exam_definition(resolved_exam)
    resolved_subject = normalize_exam_subject(subject, resolved_exam)
    content_subject = resolve_exam_content_subject(resolved_subject, resolved_exam)
    subject_label = get_exam_subject_label(resolved_subject, resolved_exam)
    subject_mapping = get_exam_subject_mapping(resolved_subject, resolved_exam)
    style_profile = _QUIZ_STYLE_PROFILES.get(
        str(exam_definition.quiz_style_hint or "").strip().lower(),
        _QUIZ_STYLE_PROFILES["mixed_conceptual_application"],
    )
    emphasis_hint = str(subject_mapping.emphasis_hint or "").strip() if subject_mapping is not None else ""

    exam_focus_note_parts: list[str] = []
    if resolved_exam != "upsc":
        exam_focus_note_parts.append(
            f"{exam_definition.label} quiz framing keeps {style_profile['difficulty_emphasis']} for {subject_label}."
        )
    if emphasis_hint:
        exam_focus_note_parts.append(emphasis_hint)

    prompt_note_parts = [style_profile["prompt_note"]]
    if emphasis_hint:
        prompt_note_parts.append(emphasis_hint)

    return {
        "exam": resolved_exam,
        "subject": resolved_subject,
        "content_subject": content_subject,
        "subject_label": subject_label,
        "difficulty_emphasis": style_profile["difficulty_emphasis"],
        "balance_style": style_profile["balance_style"],
        "exam_focus_note": " ".join(exam_focus_note_parts).strip() or None,
        "quiz_profile_note": " ".join(prompt_note_parts).strip() or None,
    }


def _append_exam_quiz_framing(message: str, framing: str | None, *, enabled: bool) -> str:
    if not enabled:
        return message
    cleaned_framing = str(framing or "").strip()
    if not cleaned_framing:
        return message
    cleaned_message = str(message or "").strip()
    if cleaned_framing.lower() in cleaned_message.lower():
        return cleaned_message
    return f"{cleaned_message} {cleaned_framing}".strip()


def _extract_quiz_exam_context(
    *,
    quiz: Quiz,
    questions: list[dict[str, Any]],
    exam: str | None = None,
) -> dict[str, str]:
    first_question = questions[0] if questions else {}
    stored_question_exam = str(first_question.get("source_exam") or "").strip() or None
    stored_quiz_exam = str(getattr(quiz, "exam", None) or "").strip() or None
    resolved_exam = normalize_exam(stored_question_exam or stored_quiz_exam or exam)
    stored_subject = str(first_question.get("source_subject") or "").strip()
    stored_content_subject = str(first_question.get("source_content_subject") or "").strip()
    content_subject = normalize_subject(stored_content_subject or quiz.subject)
    display_subject = stored_subject or normalize_exam_subject(content_subject, resolved_exam)
    return {
        "exam": resolved_exam,
        "subject": display_subject,
        "content_subject": content_subject,
    }


def _topic_key(topic: str | None) -> str:
    return (topic or "").strip().lower()


def _topic_accuracy_for(summary: dict[str, Any], topic: str) -> dict[str, Any] | None:
    normalized_topic = _topic_key(topic)
    for item in summary.get("topic_accuracy", []):
        if _topic_key(item.get("topic")) == normalized_topic:
            return item
    return None


def _first_topic(topics: list[str]) -> str | None:
    for topic in topics:
        cleaned = str(topic or "").strip()
        if cleaned:
            return cleaned
    return None


def _first_ranked_topic(items: list[dict[str, Any]]) -> str | None:
    for item in items:
        topic = str(item.get("topic") or "").strip()
        if topic:
            return topic
    return None


def _topic_in_collection(topic: str, values: list[str]) -> bool:
    normalized_topic = _topic_key(topic)
    return any(_topic_key(value) == normalized_topic for value in values if value)


def _topic_adaptive_profile(topic_accuracy_item: dict[str, Any] | None, topic: str) -> dict[str, str]:
    if topic_accuracy_item:
        return {
            "difficulty_band": str(topic_accuracy_item.get("recommended_difficulty_band") or topic_accuracy_item.get("difficulty_band") or "medium"),
            "adaptive_state": str(topic_accuracy_item.get("adaptive_state") or "steady"),
            "reason": str(
                topic_accuracy_item.get("adaptive_difficulty_reason")
                or f"{topic} is staying on medium until more quiz-backed history sharpens the recommendation."
            ),
        }

    fallback_profile = build_topic_difficulty_profile(
        topic=topic,
        accuracy=None,
        recent_accuracy=0.0,
        attempts_count=0,
        mastery_score=0.0,
        confidence_score=0.0,
        stability_score=0.0,
        topic_strength="medium",
        revision_readiness="building",
        revision_signal="stable",
        retention_risk="low",
        long_term_trend="stable",
    )
    return {
        "difficulty_band": str(fallback_profile["difficulty_band"]),
        "adaptive_state": str(fallback_profile["adaptive_state"]),
        "reason": str(fallback_profile["reason"]),
    }

def _normalized_difficulty_band(value: str | None) -> str:
    normalized = str(value or "medium").strip().lower()
    if normalized not in {"easy", "medium", "hard"}:
        return "medium"
    return normalized


def _normalized_adaptive_state(value: str | None) -> str:
    normalized = str(value or "steady").strip().lower()
    if normalized not in {"recovery", "steady", "challenge"}:
        return "steady"
    return normalized


def _join_unique_sentences(*parts: str) -> str:
    ordered_parts: list[str] = []
    seen: set[str] = set()
    for part in parts:
        cleaned = str(part or "").strip()
        normalized = cleaned.lower()
        if not cleaned or normalized in seen:
            continue
        seen.add(normalized)
        ordered_parts.append(cleaned)
    return " ".join(ordered_parts).strip()


def _subject_adaptive_profile(summary: dict[str, Any], subject: str) -> dict[str, str]:
    difficulty_band = _normalized_difficulty_band(summary.get("subject_difficulty_band"))
    adaptive_state = _normalized_adaptive_state(summary.get("subject_adaptive_state"))
    reason = str(
        summary.get("subject_difficulty_reason")
        or f"{subject} is staying on {difficulty_band} until more subject-level history sharpens the recommendation."
    ).strip()
    return {
        "difficulty_band": difficulty_band,
        "adaptive_state": adaptive_state,
        "reason": reason,
    }


def _resolve_effective_quiz_adaptation(
    *,
    requested_mode: str,
    target_topic: str,
    subject: str,
    adaptive_profile: dict[str, Any],
    subject_adaptive_profile: dict[str, Any],
    topic_accuracy_item: dict[str, Any] | None,
    weak_concepts: list[str],
) -> dict[str, str]:
    normalized_mode = normalize_quiz_mode(requested_mode)
    topic_difficulty = _normalized_difficulty_band(adaptive_profile.get("difficulty_band"))
    topic_state = _normalized_adaptive_state(adaptive_profile.get("adaptive_state"))
    topic_reason = str(adaptive_profile.get("reason") or "").strip()
    subject_difficulty = _normalized_difficulty_band(subject_adaptive_profile.get("difficulty_band"))
    subject_state = _normalized_adaptive_state(subject_adaptive_profile.get("adaptive_state"))
    subject_reason = str(subject_adaptive_profile.get("reason") or "").strip()

    accuracy = topic_accuracy_item.get("accuracy") if topic_accuracy_item else None
    normalized_accuracy = float(accuracy) if isinstance(accuracy, (int, float)) else None
    mastery_score = float(topic_accuracy_item.get("mastery_score", 0.0) or 0.0) if topic_accuracy_item else 0.0
    confidence_score = float(topic_accuracy_item.get("confidence_score", 0.0) or 0.0) if topic_accuracy_item else 0.0
    stability_score = float(topic_accuracy_item.get("stability_score", 0.0) or 0.0) if topic_accuracy_item else 0.0
    attempts_count = int(topic_accuracy_item.get("attempts_count", 0) or 0) if topic_accuracy_item else 0
    recent_failed_attempts = int(topic_accuracy_item.get("recent_failed_attempts", 0) or 0) if topic_accuracy_item else 0
    repeated_mistakes = int(topic_accuracy_item.get("repeated_mistakes", 0) or 0) if topic_accuracy_item else 0
    topic_strength = str(topic_accuracy_item.get("topic_strength") or "medium") if topic_accuracy_item else "medium"
    revision_signal = str(topic_accuracy_item.get("revision_signal") or "stable") if topic_accuracy_item else "stable"
    retention_risk = str(topic_accuracy_item.get("retention_risk") or "low") if topic_accuracy_item else "low"

    thin_history = attempts_count < MIN_DIFFICULTY_EVIDENCE_ATTEMPTS
    topic_recovery = (
        topic_state == "recovery"
        or revision_signal in {"at_risk", "due_now"}
        or retention_risk == "high"
        or recent_failed_attempts >= 2
        or repeated_mistakes >= 2
        or bool(weak_concepts)
        or (normalized_accuracy is not None and normalized_accuracy < 50)
    )
    subject_recovery = subject_state == "recovery"
    topic_challenge = (
        topic_state == "challenge"
        and attempts_count >= 2
        and topic_strength == "strong"
        and revision_signal == "stable"
        and retention_risk == "low"
        and mastery_score >= 78
        and stability_score >= 60
        and recent_failed_attempts == 0
        and repeated_mistakes == 0
        and (normalized_accuracy is None or normalized_accuracy >= 78)
    )
    subject_challenge = subject_state == "challenge" and subject_difficulty == "hard"

    if normalized_mode == "weak_area_drill":
        return {
            "difficulty": "easy",
            "adaptive_state": "recovery",
            "difficulty_reason": _join_unique_sentences(
                f"{target_topic} stays on easy because weak-area drill is for recovery and correction work first.",
                topic_reason,
                subject_reason if subject_recovery else "",
            ),
        }

    if thin_history and normalized_accuracy is not None and normalized_accuracy >= 50:
        return {
            "difficulty": "medium",
            "adaptive_state": "steady",
            "difficulty_reason": _join_unique_sentences(
                f"{target_topic} stays on medium because one non-weak attempt is not enough evidence to change the baseline difficulty.",
                topic_reason,
            ),
        }

    if normalized_mode == "revision":
        allow_medium_revision = (
            topic_challenge
            and not subject_recovery
            and not weak_concepts
            and revision_signal == "stable"
            and retention_risk == "low"
        )
        if allow_medium_revision:
            return {
                "difficulty": "medium",
                "adaptive_state": "steady",
                "difficulty_reason": _join_unique_sentences(
                    f"{target_topic} is revision-ready but stable enough for medium recall practice.",
                    topic_reason,
                ),
            }

        revision_state = "recovery" if topic_recovery or subject_recovery or revision_signal in {"at_risk", "due_now"} else "steady"
        return {
            "difficulty": "easy",
            "adaptive_state": revision_state,
            "difficulty_reason": _join_unique_sentences(
                (
                    f"{target_topic} stays on easy because revision mode is reinforcing due or recently weak material."
                    if revision_state == "recovery"
                    else f"{target_topic} stays on easy because revision mode is keeping recall controlled while the topic is still consolidating."
                ),
                topic_reason,
                subject_reason if subject_recovery else "",
            ),
        }

    if normalized_mode == "practice":
        if topic_recovery or subject_recovery or normalized_accuracy is None or (normalized_accuracy is not None and normalized_accuracy < 50):
            return {
                "difficulty": "easy",
                "adaptive_state": "recovery",
                "difficulty_reason": _join_unique_sentences(
                    f"{target_topic} stays on easy in practice mode because the safer band supports recovery and clearer learning reps.",
                    topic_reason,
                    subject_reason if subject_recovery else "",
                ),
            }
        if topic_challenge and subject_challenge and not thin_history:
            return {
                "difficulty": "medium",
                "adaptive_state": "challenge",
                "difficulty_reason": _join_unique_sentences(
                    f"{target_topic} is challenge-ready, but practice mode caps it at medium so the quiz can stretch you without turning into a full test.",
                    topic_reason,
                ),
            }
        return {
            "difficulty": "medium",
            "adaptive_state": "steady",
            "difficulty_reason": _join_unique_sentences(
                f"{target_topic} stays on medium in practice mode so you keep learning depth without overreacting to short-term swings.",
                topic_reason,
                subject_reason if subject_recovery and not topic_reason else "",
            ),
        }

    if topic_challenge:
        if subject_recovery and not thin_history:
            return {
                "difficulty": "medium",
                "adaptive_state": "steady",
                "difficulty_reason": _join_unique_sentences(
                    f"{target_topic} is personally challenge-ready, but {subject} is under recovery pressure overall, so test mode is capping this quiz at medium.",
                    topic_reason,
                    subject_reason,
                ),
            }
        return {
            "difficulty": "hard",
            "adaptive_state": "challenge",
            "difficulty_reason": _join_unique_sentences(
                f"{target_topic} is ready for a harder test because the topic is stable enough to take a bigger stretch.",
                topic_reason,
            ),
        }

    if subject_recovery:
        if (
            topic_strength == "strong"
            and retention_risk == "low"
            and revision_signal == "stable"
            and mastery_score >= 70
            and stability_score >= 55
            and recent_failed_attempts == 0
            and repeated_mistakes == 0
        ):
            return {
                "difficulty": "medium",
                "adaptive_state": "steady",
                "difficulty_reason": _join_unique_sentences(
                    f"{subject} is under recovery pressure overall, so test mode is keeping {target_topic} at medium even though this topic is relatively steady.",
                    subject_reason,
                    topic_reason,
                ),
            }
        return {
            "difficulty": "easy",
            "adaptive_state": "recovery",
            "difficulty_reason": _join_unique_sentences(
                f"{subject} is under recovery pressure overall, so test mode is easing {target_topic} down instead of pushing full challenge.",
                subject_reason,
                topic_reason,
            ),
        }

    if topic_recovery:
        return {
            "difficulty": "easy",
            "adaptive_state": "recovery",
            "difficulty_reason": _join_unique_sentences(
                f"{target_topic} stays on easy in test mode because the topic still needs support before harder assessment is useful.",
                topic_reason,
            ),
        }

    if (
        subject_challenge
        and topic_difficulty == "medium"
        and not thin_history
        and topic_strength != "weak"
        and revision_signal == "stable"
        and retention_risk == "low"
        and mastery_score >= 68
        and stability_score >= 60
        and recent_failed_attempts == 0
        and repeated_mistakes == 0
        and (normalized_accuracy is None or normalized_accuracy >= 72)
    ):
        return {
            "difficulty": "hard",
            "adaptive_state": "challenge",
            "difficulty_reason": _join_unique_sentences(
                f"{subject} is holding up well overall and {target_topic} is stable enough to stretch further, so test mode is stepping up to hard selectively.",
                subject_reason,
                topic_reason,
            ),
        }

    return {
        "difficulty": topic_difficulty,
        "adaptive_state": topic_state if topic_state != "recovery" else "steady",
        "difficulty_reason": _join_unique_sentences(
            topic_reason,
            subject_reason if subject_challenge and topic_state != "challenge" else "",
        ) or f"{target_topic} is staying on {topic_difficulty} based on the current adaptive quiz profile.",
    }


def build_revision_quiz_targets(
    *,
    requested_topic: str,
    summary: dict[str, Any],
    revision_due_snapshot: dict[str, Any],
    subject: str,
    exam: str | None = None,
    revision_session_mode: str = "full_revision",
    limit: int = 3,
    db: Session | None = None,
) -> tuple[list[str], str]:
    document_lookup = {
        _topic_key(document.topic): document
        for document in list_topic_documents(subject=subject, exam=exam, db=db)
        if _topic_key(document.topic)
    }
    if not document_lookup:
        return [], ""

    normalized_revision_session_mode = normalize_revision_session_mode(revision_session_mode)
    session_limit = 2 if normalized_revision_session_mode == "short_revision" else limit
    requested_key = _topic_key(requested_topic)
    ranked_lookup = {
        _topic_key(item.get("topic")): item
        for item in summary.get("ranked_weak_topics", [])
        if _topic_key(item.get("topic"))
    }
    queue_lookup = {
        _topic_key(item.get("topic")): item
        for item in summary.get("revision_recommendations", [])
        if _topic_key(item.get("topic"))
    }
    recent_error_keys = {_topic_key(topic) for topic in summary.get("recent_error_topics", []) if _topic_key(topic)}
    scored_targets: dict[str, dict[str, Any]] = {}

    def register_candidate(topic: str | None, *, score: int, reason: str) -> None:
        topic_key = _topic_key(topic)
        document = document_lookup.get(topic_key)
        if document is None:
            return
        ranked_item = ranked_lookup.get(topic_key, {})
        queue_item = queue_lookup.get(topic_key, {})
        repeated_mistakes = int(ranked_item.get("repeated_mistakes", 0) or 0)
        recent_failed_attempts = int(ranked_item.get("recent_failed_attempts", 0) or 0)
        accuracy = ranked_item.get("accuracy")
        recent_incorrect_questions = int(queue_item.get("recent_incorrect_questions", 0) or 0)
        priority_score = int(queue_item.get("priority_score", 0) or 0)
        wrong_answer_signal = str(queue_item.get("wrong_answer_signal") or "none")
        reinforcement_state = str(queue_item.get("reinforcement_state") or "stable")
        revision_intensity = str(queue_item.get("revision_intensity") or "standard")
        queue_session_mode = normalize_revision_session_mode(queue_item.get("recommended_session_mode"))
        adjusted_score = score + (repeated_mistakes * 10) + (recent_failed_attempts * 7)
        adjusted_score += min(priority_score // 3, 48)
        adjusted_score += min(max(recent_incorrect_questions - 1, 0) * 3, 12)
        adjusted_score += {"repeated_errors": 18, "recent_errors": 8, "none": 0}.get(wrong_answer_signal, 0)
        adjusted_score += {"overdue_reinforcement": 16, "reinforce_now": 12, "newly_learned": 8, "reinforce_soon": 4, "stable": 0}.get(reinforcement_state, 0)
        if isinstance(accuracy, (int, float)) and float(accuracy) < 75:
            adjusted_score += max(0, int((75 - float(accuracy)) // 5))
        if topic_key in recent_error_keys:
            adjusted_score += 10
        if normalized_revision_session_mode == "short_revision":
            if queue_session_mode == "short_revision":
                adjusted_score += 14
            adjusted_score += {"light": 8, "standard": 3, "intensive": -2}.get(revision_intensity, 0)
            if wrong_answer_signal != "none":
                adjusted_score += 6
            if reinforcement_state in {"reinforce_now", "overdue_reinforcement", "newly_learned"}:
                adjusted_score += 6
        else:
            adjusted_score += {"intensive": 6, "standard": 2, "light": 0}.get(revision_intensity, 0)
            if queue_session_mode == "full_revision":
                adjusted_score += 4
        if topic_key == requested_key:
            adjusted_score += 8
        candidate = {"topic": document.topic, "score": adjusted_score, "reason": reason, "requested": topic_key == requested_key}
        existing = scored_targets.get(topic_key)
        if existing is None or int(candidate["score"]) > int(existing["score"]):
            scored_targets[topic_key] = candidate

    for index, item in enumerate(revision_due_snapshot.get("overdue", [])[:4]):
        topic = str(item.get("topic") or "").strip()
        if topic:
            register_candidate(topic, score=260 - (index * 18), reason=str(item.get("reason") or f"{topic} is overdue for revision in {subject}, so revision quiz mode is focusing on it first."))

    for index, item in enumerate(revision_due_snapshot.get("due_now", [])[:4]):
        topic = str(item.get("topic") or "").strip()
        if topic:
            register_candidate(topic, score=224 - (index * 16), reason=str(item.get("reason") or f"{topic} is due now for revision in {subject}, so this quiz is locking it in before it slips."))

    for index, item in enumerate(summary.get("revision_recommendations", [])[:6]):
        topic = str(item.get("topic") or "").strip()
        status = str(item.get("status") or "none")
        if not topic or status not in {"overdue", "due_soon", "upcoming"}:
            continue
        score = 176 - (index * 12)
        if status == "overdue":
            score += 16
        elif status == "due_soon":
            score += 8
        register_candidate(topic, score=score, reason=str(item.get("reason") or f"{topic} is an active revision item in {subject}, so revision mode is keeping it in the drill set."))

    for index, topic in enumerate(summary.get("recent_error_topics", [])[:4]):
        cleaned_topic = str(topic or "").strip()
        if cleaned_topic:
            register_candidate(cleaned_topic, score=166 - (index * 12), reason=f"{cleaned_topic} has recent wrong answers in {subject}, so revision mode is reinforcing it before those mistakes settle in.")

    for index, topic in enumerate(summary.get("recent_weak_areas", [])[:4]):
        cleaned_topic = str(topic or "").strip()
        if cleaned_topic:
            register_candidate(cleaned_topic, score=154 - (index * 12), reason=f"{cleaned_topic} came out weak in a recent {subject} quiz, so revision mode is revisiting it now.")

    for index, item in enumerate(summary.get("ranked_weak_topics", [])[:5]):
        topic = str(item.get("topic") or "").strip()
        if not topic:
            continue
        repeated_mistakes = int(item.get("repeated_mistakes", 0) or 0)
        recent_failed_attempts = int(item.get("recent_failed_attempts", 0) or 0)
        revision_status = str(item.get("revision_status") or "none")
        if repeated_mistakes <= 0 and recent_failed_attempts <= 0 and revision_status not in {"overdue", "due_soon"}:
            continue
        reason = str(item.get("reason") or "")
        if not reason:
            if repeated_mistakes > 0:
                reason = f"{topic} keeps repeating as a mistake in {subject}, so revision mode is reinforcing it again."
            elif recent_failed_attempts > 0:
                reason = f"{topic} has recent failed attempts in {subject}, so it stays inside your revision set."
            else:
                reason = f"{topic} is a weak topic that is already due for revision in {subject}."
        register_candidate(topic, score=142 - (index * 10), reason=reason)

    ordered_targets = sorted(scored_targets.values(), key=lambda item: (-int(item["score"]), 0 if item["requested"] else 1, str(item["topic"]).lower()))
    if not ordered_targets:
        return [], ""

    targets = [str(item["topic"]) for item in ordered_targets[:session_limit]]
    return targets, str(ordered_targets[0]["reason"])


def build_revision_session_note(*, revision_session_mode: str, subject: str, targets: list[str], question_count: int, target_reason: str) -> str:
    normalized_revision_session_mode = normalize_revision_session_mode(revision_session_mode)
    if normalized_revision_session_mode == "short_revision":
        if len(targets) >= 2:
            return _join_unique_sentences(f"Short revision session is focusing on {targets[0]} and {targets[1]} for a quick {question_count}-question reinforcement round in {subject}.", target_reason)
        anchor_topic = targets[0] if targets else "your highest-priority revision topic"
        return _join_unique_sentences(f"Short revision session is focusing on {anchor_topic} for a quick {question_count}-question reinforcement round in {subject}.", target_reason)

    anchor_topic = targets[0] if targets else "your strongest revision target"
    return _join_unique_sentences(f"Full revision session is keeping {anchor_topic} as the main recall target for a deeper revision round in {subject}.", target_reason)


def build_revision_session_documents(
    *,
    primary_document: Any,
    revision_targets: list[str],
    subject: str,
    question_count: int,
    revision_session_mode: str,
    exam: str | None = None,
    db: Session | None = None,
) -> tuple[list[Any], str, int]:
    normalized_revision_session_mode = normalize_revision_session_mode(revision_session_mode)
    effective_question_count = min(question_count, 5) if normalized_revision_session_mode == "short_revision" else question_count
    if normalized_revision_session_mode != "short_revision":
        return [primary_document], "", effective_question_count

    document_lookup = {
        _topic_key(document.topic): document
        for document in list_topic_documents(subject=subject, exam=exam, db=db)
        if _topic_key(document.topic)
    }
    if not document_lookup:
        return [primary_document], "", effective_question_count

    selected_topics = [primary_document.topic]
    for topic in revision_targets[1:]:
        if len(selected_topics) >= 2:
            break
        topic_key = _topic_key(topic)
        if topic_key and topic_key in document_lookup and not _topic_in_collection(topic, selected_topics):
            selected_topics.append(document_lookup[topic_key].topic)

    covered_documents = [document_lookup.get(_topic_key(topic), primary_document) for topic in selected_topics]
    if len(covered_documents) > 1:
        balance_note = f"Short revision session keeps the scope tight by concentrating on {covered_documents[0].topic} and {covered_documents[1].topic} for quick recall."
    else:
        balance_note = f"Short revision session keeps the scope tight by concentrating on {covered_documents[0].topic} for quick recall."
    if effective_question_count < question_count:
        balance_note = f"{balance_note} The session is capped at {effective_question_count} questions so it stays quick."
    return covered_documents, balance_note, effective_question_count


def allocate_revision_session_question_counts(*, covered_documents: list[Any], question_count: int) -> list[int]:
    if len(covered_documents) <= 1:
        return [question_count]

    counts = [0] * len(covered_documents)
    counts[0] = max(3, question_count - (len(covered_documents) - 1))
    remaining = question_count - counts[0]
    index = 1
    while remaining > 0 and len(covered_documents) > 1:
        counts[index] += 1
        remaining -= 1
        index += 1
        if index >= len(covered_documents):
            index = 1
    return counts

def build_weak_area_drill_targets(
    *,
    requested_topic: str,
    summary: dict[str, Any],
    subject: str,
    exam: str | None = None,
    limit: int = 3,
    db: Session | None = None,
) -> tuple[list[str], str]:
    document_lookup = {
        _topic_key(document.topic): document
        for document in list_topic_documents(subject=subject, exam=exam, db=db)
        if _topic_key(document.topic)
    }
    if not document_lookup:
        return [], ""

    requested_key = _topic_key(requested_topic)
    scored_targets: dict[str, dict[str, Any]] = {}

    def register_candidate(topic: str | None, *, score: int, reason: str) -> None:
        topic_key = _topic_key(topic)
        document = document_lookup.get(topic_key)
        if document is None:
            return
        existing = scored_targets.get(topic_key)
        candidate = {
            "topic": document.topic,
            "score": score,
            "reason": reason,
            "requested": topic_key == requested_key,
        }
        if existing is None or int(candidate["score"]) > int(existing["score"]):
            scored_targets[topic_key] = candidate

    for index, item in enumerate(summary.get("ranked_weak_topics", [])[:5]):
        topic = str(item.get("topic") or "").strip()
        if not topic:
            continue
        repeated_mistakes = int(item.get("repeated_mistakes", 0) or 0)
        recent_failed_attempts = int(item.get("recent_failed_attempts", 0) or 0)
        revision_status = str(item.get("revision_status") or "none")
        accuracy = item.get("accuracy")
        score = 220 - (index * 18) + (repeated_mistakes * 12) + (recent_failed_attempts * 9)
        if revision_status == "overdue":
            score += 24
        elif revision_status == "due_soon":
            score += 12
        if isinstance(accuracy, (int, float)) and float(accuracy) < 70:
            score += max(0, int((70 - float(accuracy)) // 5))
        if _topic_key(topic) == requested_key:
            score += 8
        if repeated_mistakes > 0:
            reason = f"{topic} keeps repeating as a mistake in {subject}, so weak-area drill is locking onto it first."
        elif recent_failed_attempts > 0:
            reason = f"{topic} has recent failed quiz attempts in {subject}, so drill mode is focusing on it."
        elif revision_status in {"overdue", "due_soon"}:
            reason = f"{topic} is both weak and due for revision in {subject}, so it should be drilled before broader practice."
        else:
            reason = f"{topic} is the strongest ranked weak topic in {subject} right now."
        register_candidate(topic, score=score, reason=reason)

    for index, topic in enumerate(summary.get("recent_weak_areas", [])[:4]):
        cleaned_topic = str(topic or "").strip()
        if not cleaned_topic:
            continue
        score = 170 - (index * 14)
        if _topic_key(cleaned_topic) == requested_key:
            score += 10
        register_candidate(
            cleaned_topic,
            score=score,
            reason=f"{cleaned_topic} came out weak in a recent {subject} quiz, so drill mode is focusing on it.",
        )

    for index, item in enumerate(summary.get("priority_topics", [])[:6]):
        topic = str(item.get("topic") or "").strip()
        if not topic or str(item.get("recommended_mode") or "") != "revise":
            continue
        recommendation_source = str(item.get("recommendation_source") or "")
        if recommendation_source not in {"weak_area", "weak_topic", "overdue_revision", "incomplete_topic"}:
            continue
        raw_priority_score = item.get("priority_score")
        priority_score = int(raw_priority_score) if isinstance(raw_priority_score, (int, float)) else 0
        score = max(92, priority_score + 52 - (index * 6))
        if _topic_key(topic) == requested_key:
            score += 6
        register_candidate(
            topic,
            score=score,
            reason=str(item.get("reason") or f"{topic} is one of the strongest weak priorities in {subject} right now."),
        )

    for index, topic in enumerate(summary.get("weak_topics", [])[:4]):
        cleaned_topic = str(topic or "").strip()
        if not cleaned_topic:
            continue
        score = 112 - (index * 10)
        if _topic_key(cleaned_topic) == requested_key:
            score += 6
        register_candidate(
            cleaned_topic,
            score=score,
            reason=f"{cleaned_topic} is currently marked weak in {subject}, so it is a valid drill target.",
        )

    for index, item in enumerate(summary.get("revision_recommendations", [])[:4]):
        topic = str(item.get("topic") or "").strip()
        status = str(item.get("status") or "none")
        if not topic or status not in {"overdue", "due_soon"}:
            continue
        score = 98 - (index * 8) if status == "overdue" else 86 - (index * 6)
        register_candidate(
            topic,
            score=score,
            reason=str(item.get("reason") or f"{topic} is due for revision in {subject}, so it is also a safe drill target."),
        )

    ordered_targets = sorted(
        scored_targets.values(),
        key=lambda item: (-int(item["score"]), 0 if item["requested"] else 1, str(item["topic"]).lower()),
    )
    if not ordered_targets:
        return [], ""

    targets = [str(item["topic"]) for item in ordered_targets[:limit]]
    return targets, str(ordered_targets[0]["reason"])


def choose_quiz_target_topic(
    *,
    requested_topic: str,
    requested_mode: str,
    summary: dict[str, Any],
    subject: str,
    exam: str | None = None,
    db: Session | None = None,
) -> tuple[str, str, list[str]]:
    revision_topics = [
        str(item.get("topic") or "").strip()
        for item in summary.get("revision_recommendations", [])
        if str(item.get("topic") or "").strip()
    ]
    recent_weak_topics = [
        str(item or "").strip()
        for item in summary.get("recent_weak_areas", [])
        if str(item or "").strip()
    ]
    ranked_weak_topics = [
        str(item.get("topic") or "").strip()
        for item in summary.get("ranked_weak_topics", [])
        if str(item.get("topic") or "").strip()
    ]
    weak_topics = [
        str(item or "").strip()
        for item in summary.get("weak_topics", [])
        if str(item or "").strip()
    ]

    if requested_mode == "revision":
        if _topic_in_collection(requested_topic, revision_topics + recent_weak_topics + weak_topics):
            return requested_topic, f"{requested_topic} is already due or recently weak in {subject}, so revision mode is staying on it.", []
        candidate = (
            _first_topic(revision_topics)
            or _first_topic(recent_weak_topics)
            or _first_topic(ranked_weak_topics)
            or _first_topic(weak_topics)
        )
        if candidate:
            return candidate, f"{candidate} is the strongest revision priority in {subject} right now.", []
        return requested_topic, f"No stronger revision priority was found in {subject}, so revision mode is staying on {requested_topic}.", []

    if requested_mode == "weak_area_drill":
        drill_targets, drill_reason = build_weak_area_drill_targets(
            requested_topic=requested_topic,
            summary=summary,
            subject=subject,
            exam=exam,
            db=db,
        )
        if drill_targets:
            target_topic = drill_targets[0]
            return target_topic, drill_reason or f"{target_topic} is the strongest weak-area target in {subject} right now.", drill_targets
        return requested_topic, f"No stronger weak-area target was found in {subject}, so drill mode is staying on {requested_topic}.", []

    return requested_topic, "", []


def load_quiz_target_document(
    *,
    requested_document: Any,
    requested_mode: str,
    summary: dict[str, Any],
    exam: str | None = None,
    db: Session | None = None,
) -> tuple[Any, str, list[str]]:
    target_topic, target_reason, drill_targets = choose_quiz_target_topic(
        requested_topic=requested_document.topic,
        requested_mode=requested_mode,
        summary=summary,
        subject=requested_document.subject,
        exam=exam,
        db=db,
    )
    if _topic_key(target_topic) == _topic_key(requested_document.topic):
        return requested_document, target_reason, drill_targets
    try:
        return get_topic_document(
            target_topic,
            subject=requested_document.subject,
            exam=exam,
            db=db,
        ), target_reason, drill_targets
    except ValueError:
        return requested_document, target_reason, drill_targets


def load_recent_topic_weak_concepts(
    db: Session,
    *,
    topic: str,
    subject: str,
    chapter: str,
    limit: int = 3,
    exam: str | None = None,
    user_id: int | None = None,
) -> list[str]:
    resolved_exam = normalize_exam(exam)
    recent_attempts = (
        apply_learning_exam_scope(apply_learning_owner_scope(db.query(QuizAttempt), QuizAttempt, user_id), QuizAttempt, resolved_exam)
        .filter(
            QuizAttempt.subject == subject,
            QuizAttempt.chapter == chapter,
            QuizAttempt.topic == topic,
        )
        .order_by(QuizAttempt.created_at.desc(), QuizAttempt.id.desc())
        .limit(6)
        .all()
    )
    concepts: list[str] = []
    seen: set[str] = set()
    for attempt in recent_attempts:
        try:
            weak_areas = json.loads(attempt.weak_areas_json or "[]")
        except (TypeError, json.JSONDecodeError):
            weak_areas = []
        for weak_area in weak_areas:
            concept = str(weak_area or "").strip()
            normalized_concept = concept.lower()
            if not concept or normalized_concept in seen or normalized_concept == topic.lower():
                continue
            seen.add(normalized_concept)
            concepts.append(concept)
            if len(concepts) >= limit:
                return concepts
    return concepts


def resolve_quiz_profile(
    *,
    requested_mode: str,
    requested_topic: str,
    target_topic: str,
    subject: str,
    adaptive_profile: dict[str, Any],
    subject_adaptive_profile: dict[str, Any],
    topic_accuracy_item: dict[str, Any] | None,
    weak_concepts: list[str],
    target_reason: str,
    drill_targets: list[str] | None = None,
) -> tuple[str, str, list[str], str, str, str]:
    switched_topic = _topic_key(requested_topic) != _topic_key(target_topic)
    effective_adaptation = _resolve_effective_quiz_adaptation(
        requested_mode=requested_mode,
        target_topic=target_topic,
        subject=subject,
        adaptive_profile=adaptive_profile,
        subject_adaptive_profile=subject_adaptive_profile,
        topic_accuracy_item=topic_accuracy_item,
        weak_concepts=weak_concepts,
    )
    difficulty = str(effective_adaptation["difficulty"])
    effective_adaptive_state = str(effective_adaptation["adaptive_state"])
    difficulty_reason = str(effective_adaptation["difficulty_reason"])
    topic_accuracy = topic_accuracy_item["accuracy"] if topic_accuracy_item else None

    if requested_mode == "weak_area_drill":
        if weak_concepts:
            if switched_topic:
                return (
                    "weak_area_drill",
                    difficulty,
                    weak_concepts[:3],
                    f"Weak-area drill switched from {requested_topic} to {target_topic}. {target_reason}",
                    difficulty_reason,
                    effective_adaptive_state,
                )
            return (
                "weak_area_drill",
                difficulty,
                weak_concepts[:3],
                target_reason or f"Weak-area drill is targeting recent mistake patterns inside {target_topic}.",
                difficulty_reason,
                effective_adaptive_state,
            )
        if drill_targets:
            if switched_topic:
                return (
                    "weak_area_drill",
                    difficulty,
                    [],
                    f"Weak-area drill switched from {requested_topic} to {target_topic}. {target_reason}",
                    difficulty_reason,
                    effective_adaptive_state,
                )
            return (
                "weak_area_drill",
                difficulty,
                [],
                target_reason or f"Weak-area drill is targeting {target_topic} from your current subject-level weak-topic ranking.",
                difficulty_reason,
                effective_adaptive_state,
            )
        fallback_note = f"{target_reason} " if target_reason else ""
        fallback_reason = _join_unique_sentences(
            f"{target_topic} stays on easy because the drill signal was too thin and revision mode is safer for reinforcement.",
            difficulty_reason,
        )
        if switched_topic:
            return (
                "revision",
                "easy",
                [],
                f"Weak-area drill switched from {requested_topic} to {target_topic}, but no trustworthy weak-area signals were stored yet. {fallback_note}This quiz fell back to revision mode.".strip(),
                fallback_reason,
                "recovery",
            )
        return (
            "revision",
            "easy",
            [],
            f"Weak-area drill could not find trustworthy weak-area signals for {target_topic}, so this quiz fell back to revision mode. {fallback_note}".strip(),
            fallback_reason,
            "recovery",
        )

    if requested_mode == "revision":
        if switched_topic:
            return (
                "revision",
                difficulty,
                weak_concepts[:2],
                f"Revision mode switched from {requested_topic} to {target_topic}. {target_reason}",
                difficulty_reason,
                effective_adaptive_state,
            )
        return (
            "revision",
            difficulty,
            weak_concepts[:2],
            target_reason or f"Revision mode is keeping {target_topic} focused on due or recently weak material.",
            difficulty_reason,
            effective_adaptive_state,
        )

    if requested_mode == "practice":
        practice_focus = weak_concepts[:1] if topic_accuracy is not None and topic_accuracy < 50 else []
        return (
            "practice",
            difficulty,
            practice_focus,
            f"Practice mode keeps {target_topic} learning-oriented with an adaptive difficulty band.",
            difficulty_reason,
            effective_adaptive_state,
        )

    return (
        "test",
        difficulty,
        [],
        f"Test mode balances {target_topic} for assessment using your current adaptive difficulty.",
        difficulty_reason,
        effective_adaptive_state,
    )


def _recent_quiz_topic_counts(summary: dict[str, Any], limit: int = 5) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in summary.get("recent_quizzes", [])[:limit]:
        topic = _topic_key(item.get("topic"))
        if topic:
            counts[topic] = counts.get(topic, 0) + 1
    return counts


def build_balanced_topic_documents(
    *,
    primary_document: Any,
    effective_mode: str,
    summary: dict[str, Any],
    question_count: int,
    exam: str | None = None,
    db: Session | None = None,
) -> tuple[list[Any], str]:
    if effective_mode not in {"practice", "test"}:
        return [primary_document], ""

    subject_documents = list_topic_documents(subject=primary_document.subject, exam=exam, db=db)
    document_lookup = {
        _topic_key(document.topic): document
        for document in subject_documents
        if _topic_key(document.topic)
    }
    if len(document_lookup) <= 1:
        return [primary_document], ""

    anchor_topic = primary_document.topic
    anchor_key = _topic_key(anchor_topic)
    available_topics = [document.topic for document in subject_documents]
    sequence_subject = str(
        getattr(primary_document, "content_subject", None) or primary_document.subject
    )
    ordered_topics = list_subject_sequence(sequence_subject, available_topics=available_topics)
    order_index = {
        _topic_key(topic): index
        for index, topic in enumerate(ordered_topics)
        if _topic_key(topic)
    }
    ranked_weak_topics = [
        str(item.get("topic") or "").strip()
        for item in summary.get("ranked_weak_topics", [])
        if str(item.get("topic") or "").strip()
    ][:3]
    revision_topics = [
        str(item.get("topic") or "").strip()
        for item in summary.get("revision_recommendations", [])
        if str(item.get("topic") or "").strip()
    ][:3]
    recommended_topic = str(summary.get("recommended_next_topic") or "").strip()
    continuation_topic = str(summary.get("continue_study_topic") or summary.get("continuation_topic") or "").strip()
    ranked_weak_index = {_topic_key(topic): index for index, topic in enumerate(ranked_weak_topics) if _topic_key(topic)}
    revision_index = {_topic_key(topic): index for index, topic in enumerate(revision_topics) if _topic_key(topic)}
    recent_topic_counts = _recent_quiz_topic_counts(summary)
    priority_topic_keys = {
        key
        for key in [
            _topic_key(recommended_topic),
            _topic_key(continuation_topic),
            *ranked_weak_index.keys(),
            *revision_index.keys(),
        ]
        if key
    }

    candidate_keys: list[str] = []
    seen_candidate_keys: set[str] = set()
    for topic in [*ordered_topics, *ranked_weak_topics, *revision_topics, recommended_topic, continuation_topic]:
        topic_key = _topic_key(topic)
        if not topic_key or topic_key == anchor_key or topic_key in seen_candidate_keys or topic_key not in document_lookup:
            continue
        seen_candidate_keys.add(topic_key)
        candidate_keys.append(topic_key)

    scored_candidates: list[tuple[int, int, str]] = []
    for topic_key in candidate_keys:
        topic = document_lookup[topic_key].topic
        distance = None
        if topic_key in order_index and anchor_key in order_index:
            distance = abs(order_index[topic_key] - order_index[anchor_key])
        score = 0
        if effective_mode == "practice":
            if distance is not None:
                if distance == 1:
                    score += 60
                elif distance == 2:
                    score += 30
                else:
                    score += max(0, 14 - (distance * 3))
            if topic_key == _topic_key(continuation_topic):
                score += 30
            if topic_key == _topic_key(recommended_topic):
                score += 20
            if topic_key in ranked_weak_index:
                score += 8
            if topic_key in revision_index:
                score += 6
        else:
            if topic_key in ranked_weak_index:
                score += max(28, 60 - (ranked_weak_index[topic_key] * 12))
            if topic_key in revision_index:
                score += max(10, 26 - (revision_index[topic_key] * 6))
            if topic_key == _topic_key(recommended_topic):
                score += 30
            if topic_key == _topic_key(continuation_topic):
                score += 18
            if distance is not None:
                if distance == 1:
                    score += 32
                elif distance == 2:
                    score += 18
                else:
                    score += max(0, 12 - (distance * 2))

        is_priority_topic = topic_key in priority_topic_keys
        recent_penalty = recent_topic_counts.get(topic_key, 0)
        score -= recent_penalty * (8 if is_priority_topic else 18)
        if recent_penalty and not is_priority_topic and distance is None:
            score -= 10

        scored_candidates.append((score, order_index.get(topic_key, 999), topic))

    scored_candidates.sort(key=lambda item: (-item[0], item[1], item[2].lower()))

    max_topics = 2 if question_count <= 5 else 3
    selected_topics = [anchor_topic]
    for score, _, topic in scored_candidates:
        if len(selected_topics) >= max_topics:
            break
        if score <= 0 and len(selected_topics) > 1:
            continue
        if not _topic_in_collection(topic, selected_topics):
            selected_topics.append(topic)

    if len(selected_topics) < min(max_topics, len(document_lookup)):
        for topic in ordered_topics:
            topic_key = _topic_key(topic)
            if len(selected_topics) >= max_topics:
                break
            if not topic_key or topic_key == anchor_key or topic_key not in document_lookup or _topic_in_collection(topic, selected_topics):
                continue
            if recent_topic_counts.get(topic_key, 0):
                continue
            selected_topics.append(document_lookup[topic_key].topic)

    if len(selected_topics) < min(max_topics, len(document_lookup)):
        for topic in ordered_topics:
            topic_key = _topic_key(topic)
            if len(selected_topics) >= max_topics:
                break
            if not topic_key or topic_key == anchor_key or topic_key not in document_lookup or _topic_in_collection(topic, selected_topics):
                continue
            selected_topics.append(document_lookup[topic_key].topic)

    covered_documents = [document_lookup.get(_topic_key(topic), primary_document) for topic in selected_topics]
    if len(covered_documents) <= 1:
        return covered_documents, ""

    other_topics = ", ".join(document.topic for document in covered_documents[1:])
    if effective_mode == "practice":
        balance_note = (
            f"Practice mode is anchored on {anchor_topic} and broadens into {other_topics} to keep the quiz relevant without repeating one area too heavily."
        )
    else:
        balance_note = (
            f"Test mode balances {anchor_topic} with {other_topics} using your current recommendation, weak-topic, and recent-history signals."
        )
    return covered_documents, balance_note


def allocate_balanced_question_counts(*, covered_documents: list[Any], question_count: int, effective_mode: str) -> list[int]:
    if len(covered_documents) <= 1:
        return [question_count]

    topic_count = len(covered_documents)
    if effective_mode == "practice":
        counts = [0] * topic_count
        counts[0] = max(2, (question_count + 1) // 2)
        remaining = question_count - counts[0]
        for index in range(1, topic_count):
            counts[index] = 1
            remaining -= 1
        index = 1
        while remaining > 0 and topic_count > 1:
            counts[index] += 1
            remaining -= 1
            index += 1
            if index >= topic_count:
                index = 1
        return counts

    base = question_count // topic_count
    remainder = question_count % topic_count
    counts = [base] * topic_count
    for index in range(remainder):
        counts[index] += 1
    return counts


def _merge_generation_metadata(payloads: list[dict[str, Any]]) -> tuple[str, str]:
    if not payloads:
        return "mock", "Generated by Adhyantra's local mock fallback, not a live AI call."

    generation_modes = {str(payload.get("generation_mode") or "mock") for payload in payloads}
    if "mock" in generation_modes:
        live_providers = [
            str(payload.get("generation_provider") or payload.get("generation_mode") or "").strip()
            for payload in payloads
            if str(payload.get("generation_provider") or payload.get("generation_mode") or "").strip()
            and str(payload.get("generation_provider") or payload.get("generation_mode") or "").strip() != "mock"
        ]
        if live_providers:
            return (
                "mock",
                "Some quiz batches used live AI, but at least one batch degraded to Adhyantra's local mock fallback; this quiz is marked as mock-assisted rather than fully live.",
            )
        first_note = str(payloads[0].get("generation_note") or "").strip()
        return "mock", first_note or "Generated by Adhyantra's local mock fallback, not a live AI call."

    live_mode = next((str(payload.get("generation_mode") or "").strip() for payload in payloads if str(payload.get("generation_mode") or "").strip()), "gemini")
    first_note = str(payloads[0].get("generation_note") or "").strip()
    return live_mode, first_note or f"Generated by the live {live_mode.replace('_', ' ').title()} provider."


def _merge_provider_metadata(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    if not payloads:
        return {
            "generation_provider": "mock",
            "generation_model": None,
            "provider_chain": ["mock"],
            "provider_fallback_used": False,
            "provider_fallback_reason": None,
        }

    has_mock_payload = any(
        str(payload.get("generation_provider") or payload.get("generation_mode") or "mock").strip() == "mock"
        for payload in payloads
    )
    live_provider = next(
        (
            str(payload.get("generation_provider") or payload.get("generation_mode") or "").strip()
            for payload in payloads
            if str(payload.get("generation_provider") or payload.get("generation_mode") or "").strip() != "mock"
        ),
        "mock",
    )
    provider = "mock" if has_mock_payload else live_provider
    model = next(
        (str(payload.get("generation_model") or "").strip() for payload in payloads if not has_mock_payload and str(payload.get("generation_model") or "").strip()),
        "",
    )
    provider_chain: list[str] = []
    for payload in payloads:
        for item in payload.get("provider_chain") or []:
            item_text = str(item or "").strip()
            if item_text and item_text not in provider_chain:
                provider_chain.append(item_text)
    if has_mock_payload and "mock" not in provider_chain:
        provider_chain.append("mock")
    fallback_reasons = [
        str(payload.get("provider_fallback_reason") or "").strip()
        for payload in payloads
        if str(payload.get("provider_fallback_reason") or "").strip()
    ]
    return {
        "generation_provider": provider,
        "generation_model": model or None,
        "provider_chain": provider_chain or [provider],
        "provider_fallback_used": any(bool(payload.get("provider_fallback_used")) for payload in payloads),
        "provider_fallback_reason": "; ".join(dict.fromkeys(fallback_reasons)) or None,
    }


def generate_quiz(
    db: Session,
    topic: str,
    question_count: int,
    subject: str | None = None,
    exam: str | None = None,
    quiz_mode: str | None = None,
    revision_session_mode: str | None = None,
    user_id: int | None = None,
) -> dict:
    quiz_exam_profile = _build_exam_quiz_profile(subject=subject, exam=exam)
    resolved_exam = str(quiz_exam_profile["exam"] or "upsc")
    resolved_subject = str(quiz_exam_profile["subject"] or normalize_subject(subject))
    content_subject = str(quiz_exam_profile["content_subject"] or normalize_subject(subject))
    try:
        requested_document = get_topic_document(topic, subject=resolved_subject, exam=resolved_exam, db=db)
    except ValueError as exc:
        logger.warning("Quiz generation requested for unknown topic '%s' in subject '%s'.", topic, resolved_subject)
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    summary = build_progress_summary_snapshot(
        db,
        subject=resolved_subject,
        exam=resolved_exam,
        user_id=user_id,
    )
    requested_mode, auto_mode_reason = _resolve_requested_quiz_mode(
        requested_mode=quiz_mode,
        requested_topic=requested_document.topic,
        summary=summary,
    )
    requested_revision_session_mode = normalize_revision_session_mode(revision_session_mode) if requested_mode == "revision" else "full_revision"
    revision_due_snapshot = (
        build_revision_due_snapshot(
            db,
            summary=summary,
            subject=resolved_subject,
            exam=resolved_exam,
            user_id=user_id,
        )
        if requested_mode == "revision"
        else None
    )
    revision_targets: list[str] = []
    revision_target_reason = ""
    if requested_mode == "revision" and revision_due_snapshot is not None:
        revision_targets, revision_target_reason = build_revision_quiz_targets(
            requested_topic=requested_document.topic,
            summary=summary,
            revision_due_snapshot=revision_due_snapshot,
            subject=resolved_subject,
            exam=resolved_exam,
            revision_session_mode=requested_revision_session_mode,
            db=db,
        )

    if requested_mode == "revision" and revision_targets:
        target_reason = revision_target_reason or (
            f"{revision_targets[0]} is the strongest revision target in {quiz_exam_profile['subject_label']} right now."
        )
        drill_targets = []
        if _topic_key(revision_targets[0]) == _topic_key(requested_document.topic):
            document = requested_document
        else:
            try:
                document = get_topic_document(revision_targets[0], subject=resolved_subject, exam=resolved_exam, db=db)
            except ValueError:
                document = requested_document
    else:
        document, target_reason, drill_targets = load_quiz_target_document(
            requested_document=requested_document,
            requested_mode=requested_mode,
            summary=summary,
            exam=resolved_exam,
            db=db,
        )
    subject_adaptive_profile = _subject_adaptive_profile(summary, content_subject)
    topic_accuracy_item = _topic_accuracy_for(summary, document.topic)
    adaptive_profile = _topic_adaptive_profile(topic_accuracy_item, document.topic)
    weak_concepts = load_recent_topic_weak_concepts(
        db,
        topic=document.topic,
        subject=content_subject,
        chapter=document.chapter,
        exam=resolved_exam,
        user_id=user_id,
    )
    effective_mode, difficulty, focus_concepts, quiz_mode_note, difficulty_reason, effective_adaptive_state = resolve_quiz_profile(
        requested_mode=requested_mode,
        requested_topic=requested_document.topic,
        target_topic=document.topic,
        subject=content_subject,
        adaptive_profile=adaptive_profile,
        subject_adaptive_profile=subject_adaptive_profile,
        topic_accuracy_item=topic_accuracy_item,
        weak_concepts=weak_concepts,
        target_reason=target_reason,
        drill_targets=drill_targets,
    )
    revision_session_note = None
    effective_question_count = question_count
    if requested_mode == "revision":
        covered_documents, balance_note, effective_question_count = build_revision_session_documents(
            primary_document=document,
            revision_targets=revision_targets,
            subject=resolved_subject,
            question_count=question_count,
            revision_session_mode=requested_revision_session_mode,
            exam=resolved_exam,
            db=db,
        )
        question_allocations = (
            allocate_revision_session_question_counts(
                covered_documents=covered_documents,
                question_count=effective_question_count,
            )
            if requested_revision_session_mode == "short_revision"
            else [effective_question_count]
        )
        revision_session_note = build_revision_session_note(
            revision_session_mode=requested_revision_session_mode,
            subject=resolved_subject,
            targets=revision_targets or [document.topic],
            question_count=effective_question_count,
            target_reason=revision_target_reason or target_reason,
        )
    else:
        covered_documents, balance_note = build_balanced_topic_documents(
            primary_document=document,
            effective_mode=effective_mode,
            summary=summary,
            question_count=question_count,
            exam=resolved_exam,
            db=db,
        )
        question_allocations = allocate_balanced_question_counts(
            covered_documents=covered_documents,
            question_count=question_count,
            effective_mode=effective_mode,
        )

    payloads: list[dict[str, Any]] = []
    combined_questions: list[dict[str, Any]] = []
    combined_focus_concepts: list[str] = []
    for index, (batch_document, batch_count) in enumerate(zip(covered_documents, question_allocations, strict=False)):
        if batch_count <= 0:
            continue

        batch_accuracy_item = _topic_accuracy_for(summary, batch_document.topic)
        batch_accuracy = batch_accuracy_item["accuracy"] if batch_accuracy_item else None
        batch_adaptive_profile = _topic_adaptive_profile(batch_accuracy_item, batch_document.topic)
        batch_weak_concepts = load_recent_topic_weak_concepts(
            db,
            topic=batch_document.topic,
            subject=content_subject,
            chapter=batch_document.chapter,
            exam=resolved_exam,
            user_id=user_id,
        )
        if index == 0:
            batch_difficulty = difficulty
            batch_focus_concepts = focus_concepts
            batch_adaptive_state = effective_adaptive_state
            batch_difficulty_reason = difficulty_reason
        else:
            batch_effective_adaptation = _resolve_effective_quiz_adaptation(
                requested_mode=effective_mode,
                target_topic=batch_document.topic,
                subject=content_subject,
                adaptive_profile=batch_adaptive_profile,
                subject_adaptive_profile=subject_adaptive_profile,
                topic_accuracy_item=batch_accuracy_item,
                weak_concepts=batch_weak_concepts,
            )
            batch_difficulty = str(batch_effective_adaptation["difficulty"] or determine_difficulty(batch_accuracy))
            batch_adaptive_state = str(batch_effective_adaptation["adaptive_state"] or "steady")
            batch_difficulty_reason = str(batch_effective_adaptation["difficulty_reason"] or "")
            if effective_mode == "practice" and batch_effective_adaptation["adaptive_state"] == "recovery":
                batch_focus_concepts = batch_weak_concepts[:1] if batch_weak_concepts else []
            else:
                batch_focus_concepts = []

        for concept in batch_focus_concepts:
            cleaned_concept = str(concept or "").strip()
            if cleaned_concept and cleaned_concept not in combined_focus_concepts:
                combined_focus_concepts.append(cleaned_concept)

        batch_context = build_grounded_generation_context(
            [batch_document],
            exam=resolved_exam,
            subject=resolved_subject,
            content_subject=content_subject,
            target_topic=batch_document.topic,
            flow="quiz_generation",
            signals={
                "requested_topic": requested_document.topic,
                "quiz_mode": effective_mode,
                "revision_session_mode": requested_revision_session_mode if requested_mode == "revision" else None,
                "difficulty": batch_difficulty,
                "adaptive_state": batch_adaptive_state,
                "difficulty_reason": batch_difficulty_reason,
                "focus_concepts": batch_focus_concepts,
                "weak_concepts": batch_weak_concepts,
                "revision_targets": revision_targets if requested_mode == "revision" else [],
                "revision_target_reason": revision_target_reason if requested_mode == "revision" else None,
                "revision_session_note": revision_session_note,
                "drill_targets": drill_targets if requested_mode == "weak_area_drill" else [],
                "covered_topics": [document.topic for document in covered_documents],
                "batch_question_count": batch_count,
                "exam_quiz_profile": quiz_exam_profile.get("quiz_profile_note"),
                "balance_note": balance_note,
            },
        )
        try:
            batch_payload = ai_service.generate_quiz(
                topic=batch_document.topic,
                difficulty=batch_difficulty,
                question_count=batch_count,
                context=batch_context,
                quiz_mode=effective_mode,
                focus_concepts=batch_focus_concepts,
                quiz_profile_note=str(quiz_exam_profile["quiz_profile_note"] or ""),
            )
        except AIServiceUnavailableError:
            raise
        except Exception:
            logger.exception(
                "Quiz generation failed for topic '%s' in subject '%s'. Returning default quiz.",
                batch_document.topic,
                batch_document.subject,
            )
            batch_payload = ai_service.default_quiz_response(
                topic=batch_document.topic,
                difficulty=batch_difficulty,
                question_count=batch_count,
                context=batch_context,
                quiz_mode=effective_mode,
                focus_concepts=batch_focus_concepts,
                quiz_profile_note=str(quiz_exam_profile["quiz_profile_note"] or ""),
            )

        payloads.append(batch_payload)
        batch_questions = []
        for generated_question in batch_payload["questions"][:batch_count]:
            normalized_question = dict(generated_question)
            normalized_question["source_topic"] = batch_document.topic
            normalized_question["source_subject"] = resolved_subject
            normalized_question["source_content_subject"] = content_subject
            normalized_question["source_chapter"] = batch_document.chapter
            normalized_question["source_exam"] = resolved_exam
            normalized_question["source_content_corpus_id"] = batch_document.corpus_id
            normalized_question["source_content_root"] = batch_document.content_root
            normalized_question["source_content_source_scope"] = batch_document.source_scope
            normalized_question["source_content_fallback_used"] = batch_document.fallback_used
            batch_questions.append(normalized_question)
        combined_questions.extend(batch_questions)

    overall_generation_mode, overall_generation_note = _merge_generation_metadata(payloads)
    overall_provider_metadata = _merge_provider_metadata(payloads)
    covered_topics = [document.topic for document in covered_documents]
    content_source_metadata = build_content_sourcing_metadata(
        covered_documents,
        exam=resolved_exam,
        subject=resolved_subject,
        content_subject=content_subject,
    )
    actual_question_count = len(combined_questions)
    if actual_question_count == 0:
        raise HTTPException(status_code=500, detail="Quiz generation returned no questions.")

    final_quiz_mode_note = quiz_mode_note
    if auto_mode_reason:
        final_quiz_mode_note = f"{auto_mode_reason} {final_quiz_mode_note}".strip()
    if balance_note:
        final_quiz_mode_note = f"{final_quiz_mode_note} {balance_note}".strip()
    final_quiz_mode_note = _append_exam_quiz_framing(
        final_quiz_mode_note,
        str(quiz_exam_profile["exam_focus_note"] or ""),
        enabled=resolved_exam != "upsc",
    )
    final_difficulty_reason = _append_exam_quiz_framing(
        difficulty_reason,
        (
            f"{str(quiz_exam_profile['difficulty_emphasis'] or '').capitalize()} keeps this quiz aligned with "
            f"{get_exam_definition(resolved_exam).label} expectations."
        ),
        enabled=resolved_exam != "upsc",
    )

    quiz = Quiz(
        user_id=user_id,
        exam=resolved_exam,
        topic=document.topic,
        chapter=document.chapter,
        subject=content_subject,
        quiz_mode=effective_mode,
        difficulty=difficulty,
        question_count=actual_question_count,
        questions_json=json.dumps(combined_questions),
    )
    db.add(quiz)
    db.commit()
    db.refresh(quiz)

    questions_with_ids, changed = ensure_question_ids(quiz.id, combined_questions)
    if changed:
        quiz.questions_json = json.dumps(questions_with_ids)
        db.add(quiz)
        db.commit()
        db.refresh(quiz)

    public_questions = [
        {
            "question_id": question["question_id"],
            "question": question["question"],
            "options": question["options"],
            "concept": question.get("concept"),
        }
        for question in questions_with_ids
    ]

    return {
        "quiz_id": quiz.id,
        "subject": resolved_subject,
        "exam": resolved_exam,
        "content_subject": content_subject,
        **content_source_metadata,
        "chapter": document.chapter,
        "generation_mode": overall_generation_mode,
        "generation_note": overall_generation_note,
        **overall_provider_metadata,
        "quiz_mode": effective_mode,
        "quiz_mode_note": final_quiz_mode_note,
        "focus_concepts": combined_focus_concepts,
        "covered_topics": covered_topics,
        "revision_targets": revision_targets if requested_mode == "revision" and revision_targets else [],
        "revision_target_reason": revision_target_reason if requested_mode == "revision" and revision_targets else None,
        "revision_session_mode": requested_revision_session_mode if requested_mode == "revision" else None,
        "revision_session_note": revision_session_note if requested_mode == "revision" else None,
        "drill_targets": drill_targets if requested_mode == "weak_area_drill" else [],
        "drill_target_reason": target_reason if requested_mode == "weak_area_drill" and drill_targets else None,
        "topic": document.topic,
        "difficulty": difficulty,
        "adaptive_state": effective_adaptive_state,
        "difficulty_reason": final_difficulty_reason,
        "difficulty_emphasis": quiz_exam_profile["difficulty_emphasis"],
        "balance_style": quiz_exam_profile["balance_style"],
        "exam_focus_note": quiz_exam_profile["exam_focus_note"],
        "questions": public_questions,
    }


def _unique_strings(values: list[str], *, limit: int | None = None, exclude: set[str] | None = None) -> list[str]:
    normalized_exclude = {item.strip().lower() for item in (exclude or set()) if item}
    items: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        normalized = cleaned.lower()
        if not cleaned or normalized in seen or normalized in normalized_exclude:
            continue
        seen.add(normalized)
        items.append(cleaned)
        if limit is not None and len(items) >= limit:
            break
    return items



def _build_attempt_topic_breakdown(
    *,
    quiz: Quiz,
    questions: list[dict[str, Any]],
    review_questions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    topic_stats: dict[str, dict[str, Any]] = {}
    topic_order: list[str] = []

    for question, review in zip(questions, review_questions, strict=False):
        question_topic = str(question.get("source_topic") or quiz.topic or "").strip() or quiz.topic
        question_chapter = str(question.get("source_chapter") or quiz.chapter or "General").strip() or "General"
        topic_key = f"{question_chapter}::{question_topic}"
        if topic_key not in topic_stats:
            topic_stats[topic_key] = {
                "subject": str(question.get("source_subject") or normalize_subject(quiz.subject)).strip() or normalize_subject(quiz.subject),
                "chapter": question_chapter,
                "topic": question_topic,
                "question_count": 0,
                "correct_count": 0,
                "incorrect_count": 0,
                "weak_areas": [],
                "strong_areas": [],
            }
            topic_order.append(topic_key)

        stats = topic_stats[topic_key]
        stats["question_count"] += 1
        concept = str(question.get("concept") or "").strip()
        if review.get("is_correct"):
            stats["correct_count"] += 1
            if concept:
                stats["strong_areas"].append(concept)
        else:
            stats["incorrect_count"] += 1
            if concept:
                stats["weak_areas"].append(concept)

    topic_breakdown: list[dict[str, Any]] = []
    for topic_key in topic_order:
        stats = topic_stats[topic_key]
        question_count = int(stats["question_count"] or 0)
        correct_count = int(stats["correct_count"] or 0)
        topic_breakdown.append(
            {
                "subject": stats["subject"],
                "chapter": stats["chapter"],
                "topic": stats["topic"],
                "question_count": question_count,
                "correct_count": correct_count,
                "incorrect_count": int(stats["incorrect_count"] or 0),
                "accuracy": round((correct_count / question_count) * 100, 2) if question_count else 0.0,
                "weak_areas": _unique_strings(stats["weak_areas"], limit=3),
                "strong_areas": _unique_strings(stats["strong_areas"], limit=3, exclude=set(item.lower() for item in stats["weak_areas"] if item)),
            }
        )
    return topic_breakdown


def build_quiz_result_analysis(
    *,
    quiz: Quiz,
    questions: list[dict[str, Any]],
    review_questions: list[dict[str, Any]],
    weak_areas: list[str],
    accuracy: float,
    summary: dict[str, Any],
    daily_plan: dict[str, Any],
    coach_summary: dict[str, Any],
    next_recommendation: str,
) -> dict[str, Any]:
    performance_band = "strong" if accuracy >= 80 else "mixed" if accuracy >= 50 else "needs_revision"
    weak_area_exclude = {item.strip().lower() for item in weak_areas if item}
    topic_breakdown = _build_attempt_topic_breakdown(quiz=quiz, questions=questions, review_questions=review_questions)
    strongest_concepts_raw = [
        concept
        for item in topic_breakdown
        for concept in item.get("strong_areas", [])
        if isinstance(concept, str) and concept.strip()
    ]
    strongest_areas = _unique_strings(strongest_concepts_raw, limit=3, exclude=weak_area_exclude)
    next_focus_topic = (
        str(daily_plan.get("focus_topic") or "").strip()
        or str(coach_summary.get("next_best_topic") or "").strip()
        or str(summary.get("recommended_next_topic") or "").strip()
        or quiz.topic
    )
    next_focus_reason = (
        str(coach_summary.get("recommended_reason") or "").strip()
        or str(daily_plan.get("focus_reason") or "").strip()
        or str(summary.get("recommended_next_reason") or "").strip()
        or next_recommendation
    )
    next_step = (
        str(coach_summary.get("recommended_action") or "").strip()
        or str(daily_plan.get("recommended_action") or "").strip()
        or next_recommendation
    )

    weak_label = ", ".join(weak_areas[:2])
    strong_label = ", ".join(strongest_areas[:2])
    if performance_band == "needs_revision":
        summary_text = (
            f"This round exposed clear gaps in {weak_label or quiz.topic}. "
            f"Revise {next_focus_topic} next."
        )
    elif performance_band == "mixed":
        summary_text = (
            f"This was a mixed round. You held {strong_label or quiz.topic} better than "
            f"{weak_label or 'the weaker areas'} in this quiz."
        )
    else:
        summary_text = (
            f"This was a strong round on {quiz.topic}. "
            f"Keep {strong_label or quiz.topic} warm and move to {next_focus_topic} next."
        )

    return {
        "performance_band": performance_band,
        "summary": summary_text,
        "weak_areas_hit": weak_areas,
        "strongest_areas": strongest_areas,
        "topic_breakdown": topic_breakdown,
        "next_focus_topic": next_focus_topic or None,
        "next_focus_reason": next_focus_reason or None,
        "next_step": next_step,
    }


def submit_quiz(
    db: Session,
    quiz_id: int,
    answers: List[Any],
    subject: str | None = None,
    exam: str | None = None,
    user_id: int | None = None,
) -> Dict[str, Any]:
    quiz = apply_learning_owner_scope(db.query(Quiz), Quiz, user_id).filter(Quiz.id == quiz_id).first()
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz not found.")

    stored_questions = json.loads(quiz.questions_json)
    questions, changed = ensure_question_ids(quiz.id, stored_questions)
    if changed:
        quiz.questions_json = json.dumps(questions)
        db.add(quiz)
        db.commit()
        db.refresh(quiz)

    quiz_exam_context = _extract_quiz_exam_context(quiz=quiz, questions=questions, exam=exam)
    effective_exam = quiz_exam_context["exam"]
    display_subject = quiz_exam_context["subject"]
    content_subject = quiz_exam_context["content_subject"]

    if subject is not None:
        submitted_display_subject: str | None
        submitted_content_subject: str | None
        try:
            submitted_display_subject = normalize_exam_subject(subject, effective_exam)
        except ValueError:
            submitted_display_subject = None
        try:
            submitted_content_subject = resolve_exam_content_subject(subject, effective_exam)
        except ValueError:
            submitted_content_subject = None

        if submitted_display_subject != display_subject and submitted_content_subject != content_subject:
            raise HTTPException(status_code=400, detail="Submitted subject does not match the quiz subject.")

    answer_map, ordered_answers = normalize_submitted_answers(answers, questions)

    score = 0
    incorrect_questions: List[Dict[str, Any]] = []
    review_questions: List[Dict[str, Any]] = []
    weak_area_candidates: List[str] = []
    for question in questions:
        question_id = question["question_id"]
        selected_answer = answer_map.get(question_id, "")
        is_correct = selected_answer == question["correct_answer"]
        if is_correct:
            score += 1

        review_questions.append(
            {
                "question_id": question_id,
                "question": question["question"],
                "topic": str(question.get("source_topic") or quiz.topic or "").strip() or quiz.topic,
                "chapter": str(question.get("source_chapter") or quiz.chapter or "General").strip() or "General",
                "concept": str(question.get("concept") or "").strip() or None,
                "selected_answer": selected_answer,
                "correct_answer": question["correct_answer"],
                "explanation": question["explanation"],
                "is_correct": is_correct,
                "review_tags": [],
            }
        )

        if is_correct:
            continue

        incorrect_questions.append(
            {
                "question": question["question"],
                "selected_answer": selected_answer,
                "correct_answer": question["correct_answer"],
                "explanation": question["explanation"],
            }
        )
        concept = question.get("concept")
        if concept:
            weak_area_candidates.append(concept)

    weak_areas = sorted(set(weak_area_candidates)) or ([quiz.topic] if incorrect_questions else [])
    accuracy = round((score / len(questions)) * 100, 2) if questions else 0.0
    attempt_topic_breakdown = _build_attempt_topic_breakdown(quiz=quiz, questions=questions, review_questions=review_questions)
    immediate_guidance = build_post_quiz_guidance(topic=quiz.topic, accuracy=accuracy, weak_areas=weak_areas)

    attempt = record_attempt(
        db=db,
        quiz_id=quiz.id,
        topic=quiz.topic,
        chapter=quiz.chapter,
        quiz_mode=quiz.quiz_mode or "test",
        difficulty=quiz.difficulty,
        answers=ordered_answers,
        score=score,
        total_questions=len(questions),
        incorrect_questions=incorrect_questions,
        weak_areas=weak_areas,
        next_recommendation=immediate_guidance,
        subject=content_subject,
        topic_breakdown=attempt_topic_breakdown,
        user_id=user_id,
        exam=effective_exam,
    )

    summary = build_progress_summary_snapshot(db, subject=display_subject, exam=effective_exam, user_id=user_id)
    revision_due = build_revision_due_snapshot(db, summary=summary, subject=display_subject, exam=effective_exam, user_id=user_id)
    trends = build_performance_trends(db, summary=summary, subject=display_subject, exam=effective_exam, user_id=user_id)
    daily_plan = build_daily_plan(
        db,
        summary=summary,
        revision_due=revision_due,
        trends=trends,
        subject=display_subject,
        exam=effective_exam,
        user_id=user_id,
    )
    coach_summary = build_coach_summary(
        db,
        summary=summary,
        revision_due=revision_due,
        trends=trends,
        daily_plan=daily_plan,
        subject=display_subject,
        exam=effective_exam,
        user_id=user_id,
    )

    topic_accuracy_lookup = {
        _topic_key(item.get("topic")): item
        for item in summary.get("topic_accuracy", [])
        if _topic_key(item.get("topic"))
    }
    due_topic_keys: set[str] = set()
    for bucket in ("overdue", "due_now"):
        for item in revision_due.get(bucket, []):
            normalized_topic = _topic_key(item.get("topic"))
            if normalized_topic:
                due_topic_keys.add(normalized_topic)

    for review_item in review_questions:
        topic_key = _topic_key(review_item.get("topic"))
        accuracy_item = topic_accuracy_lookup.get(topic_key)
        review_tags: list[str] = []
        if accuracy_item and bool(accuracy_item.get("weak_topic")):
            review_tags.append("Weak topic")
        if topic_key in due_topic_keys:
            review_tags.append("Revision due")
        attempts_count = int(accuracy_item.get("attempts_count", 0) or 0) if accuracy_item else 0
        if attempts_count <= 1:
            review_tags.append("New topic")
        review_item["review_tags"] = review_tags

    overall_recommendation = (
        coach_summary.get("recommended_action")
        or summary.get("recommended_action")
        or recommend_next_topic(
            db,
            weak_areas=weak_areas if accuracy < 80 else None,
            subject=content_subject,
            user_id=user_id,
            exam=effective_exam,
        )
    )
    recommended_reason = (
        coach_summary.get("recommended_reason")
        or summary.get("recommended_next_reason")
        or ""
    )
    if overall_recommendation:
        if accuracy < 80:
            next_recommendation = f"{immediate_guidance} Next: {overall_recommendation}"
        else:
            next_recommendation = overall_recommendation
            if recommended_reason and recommended_reason not in next_recommendation:
                next_recommendation = f"{next_recommendation} {recommended_reason}"
    else:
        next_recommendation = immediate_guidance

    attempt.next_recommendation = next_recommendation
    db.add(attempt)
    db.commit()

    result_analysis = build_quiz_result_analysis(
        quiz=quiz,
        questions=questions,
        review_questions=review_questions,
        weak_areas=weak_areas,
        accuracy=accuracy,
        summary=summary,
        daily_plan=daily_plan,
        coach_summary=coach_summary,
        next_recommendation=next_recommendation,
    )
    first_question = questions[0] if questions else {}
    content_corpus_id = str(first_question.get("source_content_corpus_id") or "").strip() or None
    content_source_scope = str(first_question.get("source_content_source_scope") or "").strip() or None
    content_fallback_used = bool(first_question.get("source_content_fallback_used"))

    return {
        "subject": display_subject,
        "exam": effective_exam,
        "content_subject": content_subject,
        "content_corpus_id": content_corpus_id,
        "content_source_scope": content_source_scope,
        "content_fallback_used": content_fallback_used,
        "chapter": quiz.chapter or "General",
        "topic": quiz.topic,
        "quiz_mode": quiz.quiz_mode or "test",
        "score": score,
        "accuracy": accuracy,
        "incorrect_questions": incorrect_questions,
        "review_questions": review_questions,
        "weak_areas": weak_areas,
        "next_recommendation": next_recommendation,
        "result_analysis": result_analysis,
        "progress_summary": summary,
        "today_plan": daily_plan,
        "coach_summary": coach_summary,
    }
