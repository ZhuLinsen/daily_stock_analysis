# -*- coding: utf-8 -*-
"""Startup-migration regression for the cash-ledger ``source_uid`` unique index.

Covers the upgrade path from a ledger that already has the ``source_uid`` column
and the first (non-unique) index, which is what an existing deployment looks
like after the initial version of this feature shipped.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from src.config import Config
from src.storage import DatabaseManager

INDEX_NAME = "ix_portfolio_cash_source_uid"


def _create_legacy_ledger(db_path: Path) -> None:
    """Create the pre-unique-index schema with one existing cash row."""
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE portfolio_cash_ledger (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              account_id INTEGER NOT NULL,
              event_date DATE NOT NULL,
              direction VARCHAR(8) NOT NULL,
              amount FLOAT NOT NULL,
              currency VARCHAR(8) NOT NULL DEFAULT 'CNY',
              note VARCHAR(255),
              source_uid VARCHAR(128),
              created_at DATETIME
            )
            """
        )
        connection.execute(
            "CREATE INDEX ix_portfolio_cash_account_date "
            "ON portfolio_cash_ledger (account_id, event_date)"
        )
        connection.execute(
            f"CREATE INDEX {INDEX_NAME} ON portfolio_cash_ledger (account_id, source_uid)"
        )
        connection.execute(
            "INSERT INTO portfolio_cash_ledger "
            "(account_id, event_date, direction, amount, currency) "
            "VALUES (1, '2026-01-01', 'in', 100, 'EUR')"
        )
        connection.commit()
    finally:
        connection.close()


class CashSourceUidMigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "legacy.db"
        _create_legacy_ledger(self.db_path)
        env_path = Path(self.temp_dir.name) / ".env"
        env_path.write_text(
            "\n".join(
                [
                    "STOCK_LIST=600519",
                    "GEMINI_API_KEY=test",
                    "ADMIN_AUTH_ENABLED=false",
                    f"DATABASE_PATH={self.db_path}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        os.environ["ENV_FILE"] = str(env_path)
        os.environ["DATABASE_PATH"] = str(self.db_path)
        Config.reset_instance()
        DatabaseManager.reset_instance()

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        os.environ.pop("DATABASE_PATH", None)
        self.temp_dir.cleanup()

    def _indexes(self) -> dict:
        manager = DatabaseManager.get_instance()
        return {
            index["name"]: index
            for index in inspect(manager._engine).get_indexes("portfolio_cash_ledger")
        }

    def test_upgrades_legacy_index_to_unique(self) -> None:
        DatabaseManager.get_instance()

        index = self._indexes()[INDEX_NAME]
        self.assertTrue(index["unique"])
        self.assertEqual(
            [column.lower() for column in index["column_names"]],
            ["account_id", "source_uid"],
        )

    def test_preserves_existing_rows(self) -> None:
        manager = DatabaseManager.get_instance()
        with manager._engine.connect() as connection:
            total = connection.exec_driver_sql(
                "SELECT COUNT(*) FROM portfolio_cash_ledger"
            ).scalar()
        self.assertEqual(total, 1)

    def test_rejects_duplicate_source_uid_but_allows_nulls(self) -> None:
        manager = DatabaseManager.get_instance()
        insert = (
            "INSERT INTO portfolio_cash_ledger "
            "(account_id, event_date, direction, amount, currency, source_uid) "
            "VALUES (1, :event_date, 'in', 1, 'EUR', :source_uid)"
        )
        with manager._engine.begin() as connection:
            connection.exec_driver_sql(
                insert.replace(":event_date", "'2026-01-02'").replace(":source_uid", "'UID-1'")
            )
            connection.exec_driver_sql(
                insert.replace(":event_date", "'2026-01-03'").replace(":source_uid", "NULL")
            )
            connection.exec_driver_sql(
                insert.replace(":event_date", "'2026-01-04'").replace(":source_uid", "NULL")
            )

        with self.assertRaises(IntegrityError):
            with manager._engine.begin() as connection:
                connection.exec_driver_sql(
                    insert.replace(":event_date", "'2026-01-05'").replace(":source_uid", "'UID-1'")
                )

    def test_second_startup_is_a_noop(self) -> None:
        DatabaseManager.get_instance()
        first = self._indexes()[INDEX_NAME]

        DatabaseManager.reset_instance()
        DatabaseManager.get_instance()
        second = self._indexes()[INDEX_NAME]

        self.assertTrue(second["unique"])
        self.assertEqual(first["column_names"], second["column_names"])


if __name__ == "__main__":
    unittest.main()
