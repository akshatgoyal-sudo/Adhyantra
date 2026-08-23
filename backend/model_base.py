from __future__ import annotations

from sqlalchemy.orm import declarative_base


# Kept separate from backend.db so migration metadata can be imported without
# constructing the application engine or loading runtime database settings.
Base = declarative_base()
