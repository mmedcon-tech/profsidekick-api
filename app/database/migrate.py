"""
Bring the database schema up to date.

The Alembic history cannot build an empty database: the "init" revision
(b2a426365d8f) creates today's tables and later revisions, such as
8b5728efb47d ("added courses"), create some of them again. So an empty database
is built from the models and stamped at head (Alembic's documented recipe for
new databases), and every other database is upgraded normally. Old revision
files are never edited.

Usage:
    python -m app.database.migrate
"""

from __future__ import annotations

import os
from typing import Iterable

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _alembic_config() -> Config:
    cfg = Config(os.path.join(_BASE_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_BASE_DIR, "alembic"))
    return cfg


def is_empty_database(table_names: Iterable[str]) -> bool:
    """True when no application table exists yet (alembic_version may)."""
    return not (set(table_names) - {"alembic_version"})


def migrate(engine: Engine | None = None) -> str:
    """Return "created" for a new database, "upgraded" otherwise."""
    if engine is None:
        from app.database.connection import engine as default_engine

        engine = default_engine

    cfg = _alembic_config()
    if is_empty_database(inspect(engine).get_table_names()):
        from app.database.connection import Base
        import app.database.models  # noqa: F401  (registers every table)

        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(bind=engine)
        command.stamp(cfg, "head")
        return "created"

    command.upgrade(cfg, "head")
    return "upgraded"


if __name__ == "__main__":
    print(f"Database {migrate()}.")
