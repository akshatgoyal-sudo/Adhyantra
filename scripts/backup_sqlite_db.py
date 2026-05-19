from __future__ import annotations

from local_db_tools import backup_sqlite_db


if __name__ == "__main__":
    created_path = backup_sqlite_db()
    print("Adhyantra SQLite backup complete.")
    print(f"Backup path: {created_path}")
