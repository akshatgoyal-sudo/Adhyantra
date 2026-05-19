from __future__ import annotations

import argparse

from local_db_tools import reset_local_db


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reset the local Adhyantra SQLite database.")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Required confirmation for deleting the active local SQLite database.",
    )
    parser.add_argument(
        "--skip-backup",
        action="store_true",
        help="Do not create a SQLite backup before deleting the active local database.",
    )
    parser.add_argument(
        "--no-recreate-schema",
        action="store_true",
        help="Delete local DB files without recreating schema.",
    )
    args = parser.parse_args()

    if not args.yes:
        raise SystemExit(
            "Refusing to reset the local SQLite database without --yes. "
            "Use the local-only workflow intentionally, for example: "
            "python scripts/reset_local_db.py --yes"
        )

    result = reset_local_db(
        recreate_schema=not args.no_recreate_schema,
        backup_before_reset=not args.skip_backup,
    )
    print("Adhyantra local database reset complete.")
    print(f"Active DB path: {result['active_db_path']}")
    if result["backup_path"]:
        print(f"Backup created before reset: {result['backup_path']}")
    elif args.skip_backup:
        print("Backup skipped by request.")
    else:
        print("No backup created because the active SQLite file did not exist yet.")
    if result["removed_paths"]:
        print("Removed files:")
        for path in result["removed_paths"]:
            print(f"- {path}")
    else:
        print("No existing SQLite files needed removal.")
    if result["marker_removed"]:
        print("Removed existing demo-seed marker.")
    if args.no_recreate_schema:
        print("Schema recreation skipped.")
    else:
        print("Schema recreated and ready for a fresh local run.")
