"""Startup migration safety and fresh-database detection. No database."""

from __future__ import annotations

import pytest

from app import main
from app.config import settings
from app.database.migrate import is_empty_database


@pytest.mark.parametrize(
    "tables,expected",
    [
        ([], True),
        (["alembic_version"], True),
        (["alembic_version", "users"], False),
        (["users"], False),
    ],
)
def test_is_empty_database(tables, expected):
    assert is_empty_database(tables) is expected


def test_tests_never_run_startup_migrations():
    # tests/conftest.py sets RUN_MIGRATIONS_ON_STARTUP=false before app import.
    assert settings.run_migrations_on_startup is False


def test_startup_skips_migrations_when_disabled(monkeypatch):
    import app.database.migrate as migrate_module

    def _fail(*args, **kwargs):
        raise AssertionError("migrate() must not run when disabled")

    monkeypatch.setattr(migrate_module, "migrate", _fail)
    monkeypatch.setattr(settings, "run_migrations_on_startup", False)
    main._run_migrations()
