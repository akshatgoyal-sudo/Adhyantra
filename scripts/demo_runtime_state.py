from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
import sys
from typing import Any

from local_db_tools import (
    build_local_runtime_state_summary,
    ensure_non_deployed_local_operation,
    require_sqlite_db_path,
    reset_local_db,
    write_demo_seed_marker,
)

from backend.db import SessionLocal, init_db
from backend.services.demo_seed_service import (
    default_demo_seed_anchor,
    demo_account_keys,
    demo_learning_scenario_keys,
    seed_demo_accounts,
    seed_demo_scenarios,
)


def _parse_anchor_date(raw_value: str | None) -> datetime | None:
    candidate = str(raw_value or "").strip()
    if not candidate:
        return None
    parsed_date = datetime.strptime(candidate, "%Y-%m-%d").date()
    return datetime(parsed_date.year, parsed_date.month, parsed_date.day, 9, 0, 0, tzinfo=UTC)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage local Adhyantra reset and deterministic demo/runtime state safely."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status", help="Inspect the current local runtime and seeded-state marker.")
    status_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON only.")

    reset_parser = subparsers.add_parser("reset", help="Reset the active local SQLite DB after explicit confirmation.")
    reset_parser.add_argument("--yes", action="store_true", help="Required confirmation for destructive local reset.")
    reset_parser.add_argument(
        "--skip-backup",
        action="store_true",
        help="Do not create a SQLite backup before deleting the active local database.",
    )
    reset_parser.add_argument(
        "--no-recreate-schema",
        action="store_true",
        help="Delete local DB files without recreating schema.",
    )
    reset_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON only.")

    seed_parser = subparsers.add_parser(
        "seed-accounts",
        help="Seed deterministic demo accounts into the local DB with marker safety checks.",
    )
    seed_parser.add_argument(
        "--account",
        action="append",
        dest="account_keys",
        help=f"Seed only the specified demo account key. Available keys: {', '.join(demo_account_keys())}",
    )
    seed_parser.add_argument("--anchor-date", help="Optional UTC anchor date in YYYY-MM-DD form.")
    seed_parser.add_argument(
        "--reset-first",
        action="store_true",
        help="Reset the local DB before seeding demo accounts. Requires --yes.",
    )
    seed_parser.add_argument(
        "--allow-existing-state",
        action="store_true",
        help="Allow seeding on top of an existing demo marker without forcing a reset first.",
    )
    seed_parser.add_argument("--yes", action="store_true", help="Required when using --reset-first.")
    seed_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON only.")

    scenario_parser = subparsers.add_parser(
        "load-scenarios",
        help="Load one or more deterministic learning scenarios with default collision checks.",
    )
    scenario_parser.add_argument(
        "--scenario",
        action="append",
        dest="scenario_keys",
        required=True,
        help=(
            "Learning scenario key to load. "
            f"Available scenarios: {', '.join(demo_learning_scenario_keys())}"
        ),
    )
    scenario_parser.add_argument(
        "--account",
        action="append",
        dest="account_keys",
        help="Optional demo account override for a single-scenario load only.",
    )
    scenario_parser.add_argument("--anchor-date", help="Optional UTC anchor date in YYYY-MM-DD form.")
    scenario_parser.add_argument(
        "--reset-first",
        action="store_true",
        help="Reset the local DB before loading scenarios. Requires --yes.",
    )
    scenario_parser.add_argument(
        "--allow-existing-state",
        action="store_true",
        help="Allow loading scenarios on top of an existing demo marker without forcing a reset first.",
    )
    scenario_parser.add_argument("--yes", action="store_true", help="Required when using --reset-first.")
    scenario_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON only.")

    return parser


def _format_marker(marker: dict[str, Any]) -> str:
    if not marker.get("present"):
        return "none"
    if marker.get("invalid"):
        return f"invalid marker at {marker.get('path')}"
    mode = marker.get("mode") or "unknown"
    scenarios = marker.get("scenarios") or []
    scenario_text = f" scenarios={', '.join(scenarios)}" if scenarios else ""
    accounts = marker.get("account_keys") or []
    account_text = f" accounts={', '.join(accounts)}" if accounts else ""
    return f"{mode}{scenario_text}{account_text}"


def _print_runtime_status(summary: dict[str, Any]) -> None:
    print("Adhyantra local runtime state")
    print(f"- environment: {summary['environment']} (deployed={summary['deployed_mode']})")
    print(f"- sqlite path: {summary['sqlite_path'] or 'non-sqlite / unsupported'}")
    print(f"- sqlite exists: {summary['sqlite_exists']}")
    print(f"- local reset allowed: {summary['local_reset_allowed']}")
    print(f"- demo seed allowed: {summary['demo_seed_allowed']}")
    print(
        "- data lane: "
        f"{summary['runtime_hygiene']['label']} "
        f"({summary['runtime_hygiene']['lane']})"
    )
    print(f"- lane note: {summary['runtime_hygiene']['note']}")
    print(f"- current demo marker: {_format_marker(summary['marker'])}")
    profile = summary.get("data_profile") or {}
    print(
        "- data profile: "
        f"users={profile.get('user_count', 0)} "
        f"demo_users={profile.get('demo_user_count', 0)} "
        f"product_users={profile.get('product_user_count', 0)} "
        f"quiz_attempts={profile.get('quiz_attempt_count', 0)}"
    )


def _require_reset_confirmation(*, confirmed: bool, operation_name: str) -> None:
    if confirmed:
        return
    raise SystemExit(
        f"{operation_name} is destructive and requires --yes. "
        "This workflow only resets the local SQLite runtime, never staging or production."
    )


def _guard_existing_marker_state(
    *,
    operation_name: str,
    reset_first: bool,
    allow_existing_state: bool,
) -> None:
    marker = build_local_runtime_state_summary()["marker"]
    if not marker.get("present") or reset_first or allow_existing_state:
        return
    raise SystemExit(
        f"{operation_name} found existing seeded local state ({_format_marker(marker)}). "
        "Use --reset-first --yes to replace it, or --allow-existing-state if you intentionally want to build on top."
    )


def _run_status(*, as_json: bool) -> int:
    ensure_non_deployed_local_operation("Local runtime status inspection")
    summary = build_local_runtime_state_summary()
    if as_json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        _print_runtime_status(summary)
    return 0


def _run_reset(args: argparse.Namespace) -> int:
    ensure_non_deployed_local_operation("Local runtime reset")
    _require_reset_confirmation(confirmed=bool(args.yes), operation_name="Local runtime reset")
    result = reset_local_db(
        recreate_schema=not bool(args.no_recreate_schema),
        backup_before_reset=not bool(args.skip_backup),
    )
    payload = {
        "operation": "reset",
        "result": result,
        "runtime_state": build_local_runtime_state_summary(),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        runtime_state = payload["runtime_state"]
        print("Adhyantra local runtime reset complete.")
        print(f"- active db path: {result['active_db_path']}")
        if result["backup_path"]:
            print(f"- backup created: {result['backup_path']}")
        elif args.skip_backup:
            print("- backup skipped by request")
        else:
            print("- no backup created because the SQLite file did not exist yet")
        print(f"- schema recreated: {not args.no_recreate_schema}")
        print(f"- demo marker removed: {result['marker_removed']}")
        print(
            "- resulting data lane: "
            f"{runtime_state['runtime_hygiene']['label']} "
            f"({runtime_state['runtime_hygiene']['lane']})"
        )
    return 0


def _maybe_reset_before_seed(args: argparse.Namespace, *, operation_name: str) -> dict[str, Any] | None:
    if not bool(getattr(args, "reset_first", False)):
        return None
    _require_reset_confirmation(confirmed=bool(args.yes), operation_name=operation_name)
    return reset_local_db(recreate_schema=True, backup_before_reset=True)


def _write_seed_marker(*, mode: str, note: str, anchor_time: datetime, scenario: str | None, scenarios: list[str], accounts: list[dict[str, Any]]) -> str:
    marker_path = write_demo_seed_marker(
        {
            "db_path": require_sqlite_db_path().as_posix(),
            "mode": mode,
            "note": note,
            "anchor_time": anchor_time.isoformat(),
            "scenario": scenario,
            "scenarios": scenarios,
            "accounts": accounts,
        }
    )
    return marker_path.as_posix()


def _run_seed_accounts(args: argparse.Namespace) -> int:
    ensure_non_deployed_local_operation("Demo account seeding")
    _guard_existing_marker_state(
        operation_name="Demo account seeding",
        reset_first=bool(args.reset_first),
        allow_existing_state=bool(args.allow_existing_state),
    )
    reset_result = _maybe_reset_before_seed(args, operation_name="Demo account seeding")
    if not args.reset_first:
        init_db()

    anchor_time = default_demo_seed_anchor(_parse_anchor_date(args.anchor_date))
    session = SessionLocal()
    try:
        accounts = seed_demo_accounts(
            session,
            account_keys=args.account_keys,
            anchor_time=anchor_time,
        )
    finally:
        session.close()

    marker_path = _write_seed_marker(
        mode="demo_accounts_seed",
        note="Deterministic Adhyantra demo accounts were intentionally seeded for local QA/demo use.",
        anchor_time=anchor_time,
        scenario=None,
        scenarios=[],
        accounts=accounts,
    )

    payload = {
        "operation": "seed_accounts",
        "reset_result": reset_result,
        "marker_path": marker_path,
        "accounts": accounts,
        "runtime_state": build_local_runtime_state_summary(),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        runtime_state = payload["runtime_state"]
        print("Adhyantra deterministic demo accounts loaded.")
        if reset_result:
            print("- local DB was reset first")
        print(f"- marker: {marker_path}")
        print(
            "- resulting data lane: "
            f"{runtime_state['runtime_hygiene']['label']} "
            f"({runtime_state['runtime_hygiene']['lane']})"
        )
        for item in accounts:
            print(
                "- "
                f"{item['key']} -> {item['email']} "
                f"[current={item['current_exam']}/{item['current_subject']}, "
                f"mode={item['study_state'].get('recommended_mode')}, "
                f"warning={item['study_state'].get('warning_level')}]"
            )
    return 0


def _run_load_scenarios(args: argparse.Namespace) -> int:
    ensure_non_deployed_local_operation("Demo learning scenario load")
    _guard_existing_marker_state(
        operation_name="Demo learning scenario load",
        reset_first=bool(args.reset_first),
        allow_existing_state=bool(args.allow_existing_state),
    )
    reset_result = _maybe_reset_before_seed(args, operation_name="Demo learning scenario load")
    if not args.reset_first:
        init_db()

    anchor_time = default_demo_seed_anchor(_parse_anchor_date(args.anchor_date))
    session = SessionLocal()
    try:
        accounts = seed_demo_scenarios(
            session,
            scenario_keys=args.scenario_keys,
            account_keys=args.account_keys,
            anchor_time=anchor_time,
        )
    finally:
        session.close()

    normalized_scenarios = [str(key or "").strip().lower() for key in args.scenario_keys if str(key or "").strip()]
    marker_mode = "demo_learning_scenario_seed" if len(normalized_scenarios) == 1 else "demo_learning_scenario_set_seed"
    marker_path = _write_seed_marker(
        mode=marker_mode,
        note=(
            f"Deterministic Adhyantra learning scenario '{normalized_scenarios[0]}' was intentionally loaded for local QA/demo use."
            if len(normalized_scenarios) == 1
            else "Deterministic Adhyantra learning scenarios were intentionally loaded for local QA/demo use."
        ),
        anchor_time=anchor_time,
        scenario=normalized_scenarios[0] if len(normalized_scenarios) == 1 else None,
        scenarios=normalized_scenarios,
        accounts=accounts,
    )

    payload = {
        "operation": "load_scenarios",
        "reset_result": reset_result,
        "marker_path": marker_path,
        "scenarios": normalized_scenarios,
        "accounts": accounts,
        "runtime_state": build_local_runtime_state_summary(),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        runtime_state = payload["runtime_state"]
        print("Adhyantra deterministic learning scenarios loaded.")
        if reset_result:
            print("- local DB was reset first")
        print(f"- scenarios: {', '.join(normalized_scenarios)}")
        print(f"- marker: {marker_path}")
        print(
            "- resulting data lane: "
            f"{runtime_state['runtime_hygiene']['label']} "
            f"({runtime_state['runtime_hygiene']['lane']})"
        )
        for item in accounts:
            scenario = item.get("scenario") or {}
            print(
                "- "
                f"{item['key']} -> {scenario.get('key') or 'default'} "
                f"[current={item['current_exam']}/{item['current_subject']}, "
                f"focus={item['study_state'].get('plan_focus_topic')}, "
                f"mode={item['study_state'].get('recommended_mode')}, "
                f"warning={item['study_state'].get('warning_level')}]"
            )
    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        if args.command == "status":
            return _run_status(as_json=bool(args.json))
        if args.command == "reset":
            return _run_reset(args)
        if args.command == "seed-accounts":
            return _run_seed_accounts(args)
        if args.command == "load-scenarios":
            return _run_load_scenarios(args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
