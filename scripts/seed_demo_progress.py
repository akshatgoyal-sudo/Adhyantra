from __future__ import annotations

import argparse
import json
from typing import Iterable

from sqlalchemy.orm import Session

from local_db_tools import ensure_non_deployed_local_operation, require_sqlite_db_path, reset_local_db, write_demo_seed_marker

from backend.db import SessionLocal, init_db
from backend.models import Quiz
from backend.services.test_service import generate_quiz, submit_quiz


DEMO_ATTEMPTS = (
    {"subject": "polity", "topic": "Fundamental Rights", "correct_indexes": {0, 2}},
    {"subject": "history", "topic": "Indian National Congress", "correct_indexes": {0, 1, 3}},
    {"subject": "geography", "topic": "Indian Monsoon", "correct_indexes": {0, 1, 2, 3}},
)


def _load_private_questions(db: Session, quiz_id: int) -> list[dict]:
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if quiz is None:
        raise RuntimeError(f"Quiz {quiz_id} was not found while seeding demo progress.")
    return json.loads(quiz.questions_json)


def _build_answer_payload(
    public_questions: list[dict],
    private_questions: list[dict],
    correct_indexes: Iterable[int],
) -> list[dict[str, str]]:
    private_by_id = {question["question_id"]: question for question in private_questions}
    correct_index_set = set(correct_indexes)
    answers: list[dict[str, str]] = []

    for index, public_question in enumerate(public_questions):
        private_question = private_by_id[public_question["question_id"]]
        if index in correct_index_set:
            selected_answer = private_question["correct_answer"]
        else:
            selected_answer = next(
                option for option in public_question["options"] if option != private_question["correct_answer"]
            )
        answers.append(
            {
                "question_id": private_question["question_id"],
                "selected_answer": selected_answer,
            }
        )

    return answers


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed explicit demo quiz/progress data for local development.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset the active local SQLite database before seeding demo progress.",
    )
    args = parser.parse_args()

    ensure_non_deployed_local_operation("Demo progress seeding")
    if args.reset:
        reset_local_db(recreate_schema=True)
    else:
        init_db()

    sqlite_db_path = require_sqlite_db_path()
    session = SessionLocal()
    seed_summary: list[dict[str, object]] = []
    try:
        for attempt in DEMO_ATTEMPTS:
            quiz = generate_quiz(
                session,
                topic=attempt["topic"],
                subject=attempt["subject"],
                question_count=5,
            )
            private_questions = _load_private_questions(session, quiz["quiz_id"])
            answers = _build_answer_payload(quiz["questions"], private_questions, attempt["correct_indexes"])
            result = submit_quiz(session, quiz["quiz_id"], answers, subject=attempt["subject"])
            seed_summary.append(
                {
                    "subject": attempt["subject"],
                    "topic": attempt["topic"],
                    "score": result["score"],
                    "accuracy": result["accuracy"],
                }
            )
    finally:
        session.close()

    marker_path = write_demo_seed_marker(
        {
            "db_path": sqlite_db_path.as_posix(),
            "mode": "demo_seed",
            "note": "Demo quiz/progress history was intentionally seeded for local development.",
            "attempts": seed_summary,
        }
    )

    print("Adhyantra demo progress seed complete.")
    print(f"Active DB path: {sqlite_db_path.as_posix()}")
    print(f"Demo marker: {marker_path.as_posix()}")
    print("Seeded attempts:")
    for item in seed_summary:
        print(f"- {item['subject']}: {item['topic']} -> {item['score']}/5 ({item['accuracy']}%)")


if __name__ == "__main__":
    main()
