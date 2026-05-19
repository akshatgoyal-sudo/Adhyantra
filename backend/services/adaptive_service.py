from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
import json
from typing import Any, Iterable, Sequence

from backend.models import QuizAttempt


REVISION_INTERVALS = (1, 3, 7)


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_utc(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def determine_difficulty(accuracy: float | None, recent_accuracies: Sequence[float] | None = None) -> str:
    """Map corrected topic performance to a stable difficulty band.

    Difficulty is computed from the corrected aggregated topic accuracy only.
    The optional recent_accuracies parameter is accepted for compatibility,
    but it does not override the corrected topic accuracy.

    Rule:
    - above 80% -> hard
    - 50% to 80% -> medium
    - below 50% -> easy
    """
    del recent_accuracies
    if accuracy is None:
        return "medium"
    if accuracy > 80:
        return "hard"
    if accuracy < 50:
        return "easy"
    return "medium"


def _join_reason_parts(parts: Sequence[str]) -> str:
    cleaned_parts: list[str] = []
    seen: set[str] = set()
    for part in parts:
        cleaned = str(part or "").strip()
        normalized = cleaned.lower()
        if not cleaned or normalized in seen:
            continue
        seen.add(normalized)
        cleaned_parts.append(cleaned)
    if not cleaned_parts:
        return "the current history is still balancing out"
    if len(cleaned_parts) == 1:
        return cleaned_parts[0]
    if len(cleaned_parts) == 2:
        return f"{cleaned_parts[0]} and {cleaned_parts[1]}"
    return f"{', '.join(cleaned_parts[:-1])}, and {cleaned_parts[-1]}"


def build_topic_difficulty_profile(
    *,
    topic: str,
    accuracy: float | None,
    recent_accuracy: float,
    attempts_count: int,
    mastery_score: float,
    confidence_score: float,
    stability_score: float,
    topic_strength: str,
    revision_readiness: str,
    revision_signal: str,
    retention_risk: str,
    long_term_trend: str,
    recent_failed_attempts: int = 0,
    repeated_mistakes: int = 0,
) -> dict[str, Any]:
    topic_label = (topic or "This topic").strip() or "This topic"
    thin_history = attempts_count <= 1
    if accuracy is None and attempts_count <= 0:
        return {
            "difficulty_band": "medium",
            "adaptive_state": "steady",
            "reason": f"{topic_label} does not have enough submitted quiz history yet, so medium is the safest starting difficulty.",
        }

    normalized_accuracy = float(accuracy or 0.0)
    normalized_recent_accuracy = float(recent_accuracy or 0.0)
    normalized_mastery = float(mastery_score or 0.0)
    normalized_confidence = float(confidence_score or 0.0)
    normalized_stability = float(stability_score or 0.0)

    recovery_pressure = 0
    challenge_pressure = 0

    if topic_strength == "weak":
        recovery_pressure += 4
    elif topic_strength == "strong":
        challenge_pressure += 3

    if normalized_mastery < 45:
        recovery_pressure += 3
    elif normalized_mastery < 60:
        recovery_pressure += 1
    elif normalized_mastery >= 82:
        challenge_pressure += 3
    elif normalized_mastery >= 68:
        challenge_pressure += 1

    if normalized_accuracy < 45:
        recovery_pressure += 2
    elif normalized_accuracy < 60:
        recovery_pressure += 1
    elif normalized_accuracy >= 88 and attempts_count >= 3:
        challenge_pressure += 2
    elif normalized_accuracy >= 78 and attempts_count >= 2:
        challenge_pressure += 1

    if normalized_recent_accuracy and normalized_recent_accuracy < 55:
        recovery_pressure += 2
    elif normalized_recent_accuracy < 70 and attempts_count >= 2:
        recovery_pressure += 1
    elif normalized_recent_accuracy >= 85 and attempts_count >= 2:
        challenge_pressure += 2

    if recent_failed_attempts >= 2:
        recovery_pressure += 2

    if repeated_mistakes >= 2:
        recovery_pressure += 2

    if revision_signal == "at_risk":
        recovery_pressure += 3
    elif revision_signal == "due_now":
        recovery_pressure += 2

    if retention_risk == "high":
        recovery_pressure += 2

    if long_term_trend == "declining" and not thin_history:
        recovery_pressure += 1
    elif long_term_trend == "improving" and not thin_history:
        challenge_pressure += 1

    if normalized_stability < 45:
        recovery_pressure += 2
    elif normalized_stability < 60:
        recovery_pressure += 1
    elif normalized_stability >= 70:
        challenge_pressure += 1

    if normalized_confidence < 30 and attempts_count <= 2:
        recovery_pressure += 1
    elif normalized_confidence >= 45 and attempts_count >= 3:
        challenge_pressure += 1

    if revision_readiness == "needs_refresh":
        recovery_pressure += 1
    elif revision_readiness == "ready":
        challenge_pressure += 1

    easy_guard = (
        (
            revision_signal in {"at_risk", "due_now"}
            and (retention_risk != "low" or normalized_mastery < 65 or topic_strength == "weak")
        )
        or (
            normalized_accuracy < 45
            and (
                normalized_recent_accuracy < 60
                or recent_failed_attempts >= 1
                or repeated_mistakes >= 1
                or topic_strength == "weak"
            )
        )
    )

    if easy_guard or recovery_pressure >= challenge_pressure + 3:
        reason_parts: list[str] = []
        if revision_signal in {"at_risk", "due_now"}:
            reason_parts.append("revision pressure is already high")
        if retention_risk == "high":
            reason_parts.append("retention risk is high")
        if topic_strength == "weak" or normalized_mastery < 45:
            reason_parts.append("quiz mastery is still weak")
        if recent_failed_attempts >= 1:
            reason_parts.append("recent quiz misses are still showing up")
        if repeated_mistakes >= 2:
            reason_parts.append("mistakes are repeating in the same area")
        if normalized_recent_accuracy and normalized_recent_accuracy < 60:
            reason_parts.append("recent quiz accuracy is still low")
        if thin_history:
            reason_parts.append("history is still thin, so the safer band is better for now")
        return {
            "difficulty_band": "easy",
            "adaptive_state": "recovery",
            "reason": f"{topic_label} stays on easy because {_join_reason_parts(reason_parts)}.",
        }

    if (
        challenge_pressure >= recovery_pressure + 3
        and attempts_count >= 2
        and revision_signal == "stable"
        and retention_risk == "low"
        and topic_strength == "strong"
        and normalized_mastery >= 78
        and normalized_stability >= 60
        and normalized_recent_accuracy >= 80
        and recent_failed_attempts == 0
        and repeated_mistakes == 0
    ):
        reason_parts = []
        if topic_strength == "strong" or normalized_mastery >= 80:
            reason_parts.append("mastery is holding up strongly")
        if normalized_recent_accuracy >= 80:
            reason_parts.append("recent quiz accuracy is strong")
        if normalized_stability >= 60:
            reason_parts.append("performance is stable")
        if normalized_confidence >= 40:
            reason_parts.append("there is enough quiz history to support a harder step")
        return {
            "difficulty_band": "hard",
            "adaptive_state": "challenge",
            "reason": f"{topic_label} is ready for hard questions because {_join_reason_parts(reason_parts)}.",
        }

    steady_reasons: list[str] = []
    if thin_history:
        steady_reasons.append("history is still thin")
    if revision_signal == "due_soon" or retention_risk == "moderate":
        steady_reasons.append("revision pressure is building")
    if topic_strength == "medium" or revision_readiness == "building":
        steady_reasons.append("the topic is still consolidating")
    if recent_failed_attempts == 1 or repeated_mistakes == 1:
        steady_reasons.append("recent mistakes suggest staying in a controlled band")
    if not steady_reasons:
        steady_reasons.append("medium keeps the topic stable without overreacting to short-term swings")
    return {
        "difficulty_band": "medium",
        "adaptive_state": "steady",
        "reason": f"{topic_label} stays on medium because {_join_reason_parts(steady_reasons)}.",
    }



def build_explanation_depth_profile(
    *,
    topic: str,
    mastery_score: float | None,
    topic_strength: str | None,
    adaptive_state: str | None,
    recent_accuracy: float | None,
    attempts_count: int,
    confidence_score: float = 0.0,
    stability_score: float = 0.0,
    retention_risk: str | None = None,
    long_term_trend: str | None = None,
    subject_adaptive_state: str | None = None,
) -> dict[str, str]:
    topic_label = (topic or "This topic").strip() or "This topic"
    normalized_mastery = float(mastery_score or 0.0)
    normalized_recent_accuracy = float(recent_accuracy or 0.0)
    normalized_confidence = float(confidence_score or 0.0)
    normalized_stability = float(stability_score or 0.0)
    normalized_topic_strength = str(topic_strength or "medium")
    normalized_adaptive_state = str(adaptive_state or "steady")
    normalized_retention_risk = str(retention_risk or "low")
    normalized_long_term_trend = str(long_term_trend or "stable")
    normalized_subject_adaptive_state = str(subject_adaptive_state or "steady")
    thin_history = attempts_count <= 1

    def build_profile(*, explanation_depth: str, teaching_support: str, teaching_pacing: str, conceptual_density: str, reason_parts: Sequence[str]) -> dict[str, str]:
        return {
            "explanation_depth": explanation_depth,
            "teaching_support": teaching_support,
            "teaching_pacing": teaching_pacing,
            "conceptual_density": conceptual_density,
            "reason": f"{topic_label} gets a {explanation_depth} explanation because {_join_reason_parts(reason_parts)}.",
        }

    if attempts_count <= 0:
        reason_parts = ["there is not enough quiz-backed history yet"]
        if normalized_subject_adaptive_state == "recovery":
            reason_parts.append("the subject is still in a recovery phase")
        return build_profile(
            explanation_depth="foundational",
            teaching_support="supportive",
            teaching_pacing="gentle",
            conceptual_density="low",
            reason_parts=reason_parts,
        )

    foundational_reasons: list[str] = []
    if normalized_adaptive_state == "recovery":
        foundational_reasons.append("the topic is in recovery mode")
    if normalized_topic_strength == "weak":
        foundational_reasons.append("the topic is still weak")
    if normalized_mastery < 45:
        foundational_reasons.append("mastery is still low")
    if normalized_recent_accuracy and normalized_recent_accuracy < 55:
        foundational_reasons.append("recent quiz accuracy is still low")
    if normalized_retention_risk == "high":
        foundational_reasons.append("retention risk is high")
    if normalized_long_term_trend == "declining" and not thin_history:
        foundational_reasons.append("recent performance is slipping")
    if normalized_confidence < 30 and attempts_count <= 2:
        foundational_reasons.append("there is not enough stable quiz evidence yet")
    if normalized_stability < 45 and not thin_history:
        foundational_reasons.append("the understanding is still unstable")
    if normalized_subject_adaptive_state == "recovery" and thin_history:
        foundational_reasons.append("the subject is under recovery pressure while topic history is still thin")
    if foundational_reasons:
        return build_profile(
            explanation_depth="foundational",
            teaching_support="supportive",
            teaching_pacing="gentle",
            conceptual_density="low",
            reason_parts=foundational_reasons,
        )

    if (
        normalized_adaptive_state == "challenge"
        and attempts_count >= 2
        and normalized_topic_strength == "strong"
        and normalized_mastery >= 78
        and normalized_recent_accuracy >= 80
        and normalized_stability >= 60
        and normalized_confidence >= 35
        and normalized_retention_risk == "low"
        and normalized_subject_adaptive_state != "recovery"
    ):
        advanced_reasons: list[str] = ["the topic is challenge-ready"]
        if normalized_mastery >= 80:
            advanced_reasons.append("mastery is already strong")
        if normalized_recent_accuracy >= 85:
            advanced_reasons.append("recent quiz performance is strong")
        if normalized_stability >= 65:
            advanced_reasons.append("the understanding looks stable enough for deeper distinctions")
        return build_profile(
            explanation_depth="advanced",
            teaching_support="stretch",
            teaching_pacing="accelerated",
            conceptual_density="high",
            reason_parts=advanced_reasons,
        )

    standard_reasons: list[str] = []
    if thin_history:
        standard_reasons.append("history is still emerging")
    if normalized_topic_strength == "medium":
        standard_reasons.append("the topic is still consolidating")
    if normalized_adaptive_state == "steady":
        standard_reasons.append("the topic is in a steady learning band")
    if normalized_retention_risk == "moderate":
        standard_reasons.append("some revision pressure is building")
    if normalized_confidence < 35 and attempts_count <= 2:
        standard_reasons.append("there is not enough evidence for denser teaching yet")
    if not standard_reasons:
        standard_reasons.append("a balanced explanation is the safest fit for the current evidence")
    return build_profile(
        explanation_depth="standard",
        teaching_support="balanced",
        teaching_pacing="balanced",
        conceptual_density="medium",
        reason_parts=standard_reasons,
    )


def build_subject_difficulty_profile(
    *,
    subject: str,
    overall_mastery_score: float,
    overall_confidence_score: float,
    overall_stability_score: float,
    strong_count: int,
    medium_count: int,
    weak_count: int,
    ready_count: int,
    needs_refresh_count: int,
    at_risk_topic_count: int,
    due_now_topic_count: int,
    overall_trend: str,
    trend_stability: str,
    recent_average: float = 0.0,
    previous_average: float = 0.0,
    accuracy_delta: float = 0.0,
    revision_pressure: str = "light",
    ranked_weak_topic_count: int = 0,
) -> dict[str, Any]:
    subject_label = (subject or "This subject").replace("_", " ").strip().title() or "This subject"
    total_topics = max(strong_count + medium_count + weak_count, ready_count + needs_refresh_count)
    if total_topics <= 0:
        return {
            "difficulty_band": "medium",
            "adaptive_state": "steady",
            "reason": f"{subject_label} does not have enough submitted quiz history yet, so medium is the safest overall subject difficulty for now.",
        }

    recovery_pressure = (
        weak_count * 2
        + ranked_weak_topic_count
        + at_risk_topic_count * 3
        + due_now_topic_count * 2
        + needs_refresh_count
        + (2 if revision_pressure == "heavy" else 1 if revision_pressure == "building" else 0)
        + (2 if overall_trend == "declining" and trend_stability != "thin_history" else 0)
        + (1 if accuracy_delta <= -8 and trend_stability != "thin_history" else 0)
        + (1 if recent_average and recent_average < 55 else 0)
        + (1 if overall_mastery_score < 55 else 0)
        + (1 if overall_stability_score < 50 else 0)
    )
    challenge_pressure = (
        strong_count * 2
        + ready_count * 2
        + (1 if revision_pressure == "light" and at_risk_topic_count == 0 and due_now_topic_count == 0 else 0)
        + (1 if overall_trend == "improving" and trend_stability == "established" else 0)
        + (1 if accuracy_delta >= 6 and trend_stability != "thin_history" else 0)
        + (1 if recent_average >= 78 else 0)
        + (1 if overall_mastery_score >= 72 else 0)
        + (1 if overall_stability_score >= 60 else 0)
        + (1 if overall_confidence_score >= 45 else 0)
        + (1 if weak_count == 0 and ranked_weak_topic_count == 0 else 0)
    )

    if recovery_pressure >= challenge_pressure + 3:
        reasons: list[str] = []
        if at_risk_topic_count or due_now_topic_count:
            reasons.append("revision pressure is already high")
        if ranked_weak_topic_count >= max(1, total_topics // 3):
            reasons.append("high-priority weak topics are stacking up")
        if weak_count > strong_count:
            reasons.append("weak topics currently outweigh strong ones")
        if overall_trend == "declining" and trend_stability != "thin_history":
            reasons.append("recent subject trend is slipping")
        if accuracy_delta <= -8 and trend_stability != "thin_history":
            reasons.append("recent quiz accuracy is dropping")
        if not reasons:
            reasons.append("the subject still needs reinforcement before a harder step")
        return {
            "difficulty_band": "easy",
            "adaptive_state": "recovery",
            "reason": f"{subject_label} should stay in recovery difficulty because {_join_reason_parts(reasons)}.",
        }

    if (
        challenge_pressure >= recovery_pressure + 4
        and strong_count >= max(weak_count, 1)
        and at_risk_topic_count == 0
        and due_now_topic_count == 0
        and needs_refresh_count <= ready_count
        and overall_mastery_score >= 70
        and recent_average >= 72
        and overall_trend != "declining"
    ):
        reasons = []
        if strong_count:
            reasons.append("strong topics are carrying the subject")
        if ready_count >= weak_count:
            reasons.append("most tracked topics are ready for harder recall")
        if recent_average >= 78:
            reasons.append("recent quiz accuracy is holding up well")
        if overall_trend == "improving":
            reasons.append("the subject trend is moving up")
        return {
            "difficulty_band": "hard",
            "adaptive_state": "challenge",
            "reason": f"{subject_label} is ready for more challenge because {_join_reason_parts(reasons)}.",
        }

    steady_reasons = []
    if trend_stability == "thin_history":
        steady_reasons.append("history is still thin")
    if due_now_topic_count or at_risk_topic_count:
        steady_reasons.append("revision load needs monitoring")
    elif revision_pressure == "building":
        steady_reasons.append("revision pressure is starting to build")
    if medium_count >= max(strong_count, weak_count):
        steady_reasons.append("most topics are still consolidating")
    if ranked_weak_topic_count > 0 and not due_now_topic_count and not at_risk_topic_count:
        steady_reasons.append("a few priority weak topics still need controlled reinforcement")
    if abs(accuracy_delta) >= 6 and trend_stability != "thin_history":
        if accuracy_delta > 0:
            steady_reasons.append("recent accuracy is improving, but not enough to force a harder jump")
        else:
            steady_reasons.append("recent accuracy dipped, but not enough to collapse the whole subject band")
    if not steady_reasons:
        steady_reasons.append("medium keeps the subject balanced while progress stabilizes")
    return {
        "difficulty_band": "medium",
        "adaptive_state": "steady",
        "reason": f"{subject_label} should stay on medium because {_join_reason_parts(steady_reasons)}.",
    }



def compute_recent_accuracy(attempts: Sequence[QuizAttempt], limit: int = 3) -> float:
    if not attempts:
        return 0.0
    recent = [attempt.accuracy for attempt in attempts[:limit]]
    if not recent:
        return 0.0
    return round(sum(recent) / len(recent), 2)


def compute_recent_failed_attempts(attempts: Sequence[QuizAttempt], threshold: float = 50.0, limit: int = 3) -> int:
    return sum(1 for attempt in attempts[:limit] if attempt.accuracy < threshold)


def extract_repeated_mistake_areas(attempts: Sequence[QuizAttempt], limit: int = 5) -> list[str]:
    counter: Counter[str] = Counter()
    for attempt in attempts[:limit]:
        try:
            weak_areas = json.loads(attempt.weak_areas_json or "[]")
        except (TypeError, json.JSONDecodeError):
            weak_areas = []
        for item in weak_areas:
            if isinstance(item, str) and item.strip():
                counter[item.strip()] += 1
    return sorted(area for area, count in counter.items() if count >= 2)


def is_weak_topic(accuracy: float, recent_failed_attempts: int, repeated_mistake_count: int) -> bool:
    return accuracy < 50 or recent_failed_attempts >= 2 or repeated_mistake_count >= 2


def is_strong_topic(accuracy: float, recent_failed_attempts: int) -> bool:
    return accuracy >= 80 and recent_failed_attempts == 0


def recommend_revision_interval_days(*, weak_topic: bool, study_count: int, attempts_count: int) -> int:
    if weak_topic:
        return REVISION_INTERVALS[0]

    interaction_depth = max(min(study_count, 1) + min(attempts_count, 3), 0)
    if interaction_depth <= 1:
        return REVISION_INTERVALS[0]
    if interaction_depth <= 3:
        return REVISION_INTERVALS[1]
    return REVISION_INTERVALS[2]


def classify_revision_status(due_at: datetime | None, *, now: datetime | None = None) -> str:
    if due_at is None:
        return "none"

    current_time = ensure_utc(now) or utc_now()
    normalized_due_at = ensure_utc(due_at)
    if normalized_due_at is None:
        return "none"
    if normalized_due_at <= current_time:
        return "overdue"
    if normalized_due_at <= current_time + timedelta(days=1):
        return "due_soon"
    return "upcoming"


def compute_revision_due_at(
    *,
    last_interaction_at: datetime | None,
    weak_topic: bool,
    study_count: int,
    attempts_count: int,
    last_correct_at: datetime | None = None,
) -> tuple[int | None, datetime | None]:
    anchor_at = ensure_utc(last_correct_at) or ensure_utc(last_interaction_at)
    if anchor_at is None:
        return None, None

    interval_days = recommend_revision_interval_days(
        weak_topic=weak_topic,
        study_count=study_count,
        attempts_count=attempts_count,
    )
    return interval_days, anchor_at + timedelta(days=interval_days)


def build_revision_reason(
    *,
    topic: str,
    weak_topic: bool,
    repeated_mistake_areas: Sequence[str],
    recent_failed_attempts: int,
) -> str:
    if weak_topic and repeated_mistake_areas:
        highlighted = ", ".join(repeated_mistake_areas[:2])
        return f"{topic} needs a short revision because mistakes are repeating around {highlighted}."
    if weak_topic and recent_failed_attempts:
        return f"{topic} is slipping in recent attempts, so a quick revision should come before the next quiz."
    if repeated_mistake_areas:
        highlighted = ", ".join(repeated_mistake_areas[:2])
        return f"Revise {topic} briefly to lock in the areas that still repeat: {highlighted}."
    return f"Use spaced revision on {topic} to keep the concept fresh before accuracy drops."


def select_unseen_topics(all_topics: Sequence[str], attempted_or_studied_topics: Iterable[str]) -> list[str]:
    seen = {topic.strip().lower() for topic in attempted_or_studied_topics if topic}
    return [topic for topic in all_topics if topic.strip().lower() not in seen]


def choose_next_topic_recommendation(
    *,
    weak_topics: Sequence[str],
    revision_recommendations: Sequence[dict],
    unseen_topics: Sequence[str],
    strong_topics: Sequence[str],
) -> tuple[str, str]:
    weak_set = {topic.lower() for topic in weak_topics}
    overdue_weak = next(
        (
            item
            for item in revision_recommendations
            if item.get("topic", "").lower() in weak_set and item.get("status") in {"overdue", "due_soon"}
        ),
        None,
    )
    if overdue_weak:
        topic = overdue_weak["topic"]
        return topic, overdue_weak.get("reason") or f"{topic} is weak and already due for revision."

    if weak_topics:
        topic = weak_topics[0]
        return topic, f"{topic} is still one of your weakest areas based on recent quiz performance."

    if unseen_topics:
        topic = unseen_topics[0]
        return topic, f"{topic} has not been practiced yet, so it is the best next topic for breadth."

    if strong_topics:
        topic = strong_topics[0]
        return topic, f"{topic} is currently strong, so it is ready for a tougher round of practice."

    return "Fundamental Rights", "It gives you a reliable base for understanding many other Polity topics."


def build_post_quiz_guidance(topic: str, accuracy: float, weak_areas: Sequence[str]) -> str:
    focus_area = weak_areas[0] if weak_areas else topic
    if accuracy < 50:
        return f"Stay on easy mode, revise {focus_area}, and schedule a 1-day revision before your next quiz."
    if accuracy <= 80:
        return f"Keep {topic} on medium mode, review {focus_area}, and revisit the topic again in 3 days."
    return f"Move {topic} to hard mode and schedule a 7-day revision to retain the gains."
