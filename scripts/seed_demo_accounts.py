from __future__ import annotations

import argparse
from datetime import UTC, datetime

from local_db_tools import ensure_non_deployed_local_operation, require_sqlite_db_path, reset_local_db, write_demo_seed_marker

from backend.db import SessionLocal, init_db
from backend.services.demo_seed_service import (
    default_demo_seed_anchor,
    demo_account_keys,
    demo_learning_scenario_keys,
    seed_demo_accounts,
)


def _parse_anchor_date(raw_value: str | None) -> datetime | None:
    candidate = str(raw_value or "").strip()
    if not candidate:
        return None
    parsed_date = datetime.strptime(candidate, "%Y-%m-%d").date()
    return datetime(parsed_date.year, parsed_date.month, parsed_date.day, 9, 0, 0, tzinfo=UTC)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed deterministic Adhyantra demo accounts for local QA and demos.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset the active local SQLite database before seeding demo accounts.",
    )
    parser.add_argument(
        "--account",
        action="append",
        dest="account_keys",
        help=f"Seed only the specified demo account key. Available keys: {', '.join(demo_account_keys())}",
    )
    parser.add_argument(
        "--scenario",
        dest="scenario_key",
        help=(
            "Optional deterministic learning scenario to apply. "
            f"Available scenarios: {', '.join(demo_learning_scenario_keys())}"
        ),
    )
    parser.add_argument(
        "--anchor-date",
        help="Optional UTC anchor date in YYYY-MM-DD form for reproducible seeded timestamps.",
    )
    args = parser.parse_args()

    ensure_non_deployed_local_operation("Demo account seeding")
    if args.reset:
        reset_local_db(recreate_schema=True)
    else:
        init_db()

    anchor_time = default_demo_seed_anchor(_parse_anchor_date(args.anchor_date))
    sqlite_db_path = require_sqlite_db_path()
    session = SessionLocal()
    try:
        seeded_accounts = seed_demo_accounts(
            session,
            account_keys=args.account_keys,
            scenario_key=args.scenario_key,
            anchor_time=anchor_time,
        )
    finally:
        session.close()

    marker_mode = "demo_learning_scenario_seed" if args.scenario_key else "demo_accounts_seed"
    marker_note = (
        f"Deterministic Adhyantra learning scenario '{args.scenario_key}' was intentionally seeded for local QA/demo use."
        if args.scenario_key
        else "Deterministic Adhyantra demo accounts were intentionally seeded for local QA/demo use."
    )
    marker_path = write_demo_seed_marker(
        {
            "db_path": sqlite_db_path.as_posix(),
            "mode": marker_mode,
            "note": marker_note,
            "anchor_time": anchor_time.isoformat(),
            "scenario": args.scenario_key,
            "accounts": seeded_accounts,
        }
    )

    print("Adhyantra deterministic demo seed complete.")
    print(f"Active DB path: {sqlite_db_path.as_posix()}")
    print(f"Anchor time (UTC): {anchor_time.isoformat()}")
    print(f"Demo marker: {marker_path.as_posix()}")
    print("Seeded accounts:")
    for item in seeded_accounts:
        study_state = item["study_state"]
        history = item["history"]
        scenario = item.get("scenario") or {}
        print(
            "- "
            f"{item['key']} -> {item['email']} "
            f"[current={item['current_exam']}/{item['current_subject']}, "
            f"mentor={item['mentor_mode']}, attempts={history['quiz_attempts']}, "
            f"scenario={scenario.get('key') or 'default'}, "
            f"mode={study_state.get('recommended_mode')}, "
            f"motivation={study_state.get('motivation_state')}, warning={study_state.get('warning_level')}]"
        )


if __name__ == "__main__":
    main()
