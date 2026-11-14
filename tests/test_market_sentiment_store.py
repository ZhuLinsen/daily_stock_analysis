# -*- coding: utf-8 -*-
"""Storage-layer tests for market sentiment snapshots (issue #1939 Wave 2).

Covers the five idempotent-merge rules from the implementation plan §3.4,
plus the pagination/ordering helpers and the inclusive/strict trend-range
query semantics from §4.4. Runs against a temporary SQLite DB using the
Config + DatabaseManager.reset_instance() setUp/tearDown convention.
"""

import json
import os
import tempfile
import time
import unittest

from sqlalchemy.exc import IntegrityError

from src.config import Config
from src.repositories.market_sentiment_repo import (
    DEFAULT_REQUIRED_GROUPS,
    MarketSentimentRepository,
)
from src.storage import DatabaseManager, MarketSentimentSnapshot

REQUIRED_GROUPS = list(DEFAULT_REQUIRED_GROUPS)
TRADE_DATE = "2026-11-13"
PREV_TRADE_DATE = "2026-11-12"
SECTION_FOR_GROUP = {
    "breadth": "breadth",
    "limit_up_pool": "limit_up",
    "broken_pool": "broken_limit",
    "turnover": "turnover",
    "promotion": "promotion",
    "prev_feedback": "yesterday_limit_feedback",
    "sector": "sector_strength",
}


def _make_payload(trade_date, ok_groups, prev_trade_date=PREV_TRADE_DATE):
    """Build a §3.2-shaped payload; group section data embeds the trade_date
    so old-vs-new section provenance is assertable after merges."""
    ok_groups = set(ok_groups)
    groups = list(REQUIRED_GROUPS) + ["sector"]
    metric_status = {
        group: ("ok" if group in ok_groups else "source_error") for group in groups
    }
    section_for_group = SECTION_FOR_GROUP
    payload = {
        "schema_version": 1,
        "market": "cn",
        "trade_date": trade_date,
        "prev_trade_date": prev_trade_date,
        "required_groups": list(REQUIRED_GROUPS),
        "metric_status": metric_status,
        "narrative": None,
        "narrative_generated_at": None,
    }
    for group, section in section_for_group.items():
        if group in ok_groups:
            payload[section] = {"value": f"{group}-data@{trade_date}"}
        else:
            payload[section] = {"missing_reason": "source_error", "value": None}
    return payload


def _make_trace(groups, date_str=TRADE_DATE, status="ok"):
    return [
        {
            "metric_group": group,
            "provider": "akshare",
            "api": f"api.{group}",
            "params": {"date": date_str},
            "status": status,
            "elapsed_ms": 5,
            "error": None,
            "fetched_at": f"{date_str}T15:30:00",
        }
        for group in groups
    ]


def _count_rows(repo):
    with repo.db.get_session() as session:
        return session.query(MarketSentimentSnapshot).count()


class MarketSentimentStoreTestCase(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(self._temp_dir.name, "test_market_sentiment_store.db")
        self._original_env = {
            key: os.environ.get(key) for key in ("ENV_FILE", "DATABASE_PATH")
        }
        env_path = os.path.join(self._temp_dir.name, ".env")
        with open(env_path, "w", encoding="utf-8") as env_file:
            env_file.write("STOCK_LIST=600519\n")
        os.environ["ENV_FILE"] = env_path
        os.environ["DATABASE_PATH"] = self._db_path
        Config._instance = None
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()
        self.repo = MarketSentimentRepository(self.db)

    def tearDown(self):
        Config._instance = None
        DatabaseManager.reset_instance()
        for key, value in self._original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._temp_dir.cleanup()

    # --- §3.4 rule 1: no existing row -> direct insert -------------------

    def test_first_save_partial_persists_row(self):
        payload = _make_payload(TRADE_DATE, ok_groups=["breadth", "turnover"])
        result = self.repo.save_snapshot(payload, _make_trace(["breadth", "turnover"]))

        self.assertEqual(result.action, "inserted")
        self.assertFalse(result.superseded_by_existing_complete)
        row = self.repo.get_by_market_date("cn", TRADE_DATE)
        self.assertIsNotNone(row)
        self.assertEqual(row.market, "cn")
        self.assertEqual(row.trade_date, TRADE_DATE)
        self.assertEqual(row.quality_status, "partial")
        self.assertAlmostEqual(row.completeness, 2 / 6, places=5)
        self.assertEqual(json.loads(row.payload)["breadth"], payload["breadth"])
        self.assertEqual(
            [entry["metric_group"] for entry in json.loads(row.provider_trace)],
            ["breadth", "turnover"],
        )

    def test_first_save_complete_allowed(self):
        payload = _make_payload(TRADE_DATE, ok_groups=REQUIRED_GROUPS)
        result = self.repo.save_snapshot(payload, _make_trace(REQUIRED_GROUPS))

        self.assertEqual(result.action, "inserted")
        row = self.repo.get_by_market_date("cn", TRADE_DATE)
        self.assertEqual(row.quality_status, "complete")
        self.assertAlmostEqual(row.completeness, 1.0)

    def test_first_save_without_trace_defaults_to_empty_list(self):
        payload = _make_payload(TRADE_DATE, ok_groups=["breadth"])
        self.repo.save_snapshot(payload)
        row = self.repo.get_by_market_date("cn", TRADE_DATE)
        self.assertEqual(json.loads(row.provider_trace), [])

    def test_save_rejects_missing_trade_date(self):
        payload = _make_payload(TRADE_DATE, ok_groups=["breadth"])
        payload.pop("trade_date")
        with self.assertRaises(ValueError):
            self.repo.save_snapshot(payload)

    # --- §3.4 rule 2: incoming complete -> full replacement --------------

    def test_complete_replaces_existing_partial(self):
        old_payload = _make_payload(TRADE_DATE, ok_groups=["breadth"])
        self.repo.save_snapshot(old_payload, _make_trace(["breadth"]))
        old_row = self.repo.get_by_market_date("cn", TRADE_DATE)
        time.sleep(0.02)

        new_payload = _make_payload(TRADE_DATE, ok_groups=REQUIRED_GROUPS)
        new_trace = _make_trace(REQUIRED_GROUPS)
        result = self.repo.save_snapshot(new_payload, new_trace)

        self.assertEqual(result.action, "replaced")
        row = self.repo.get_by_market_date("cn", TRADE_DATE)
        self.assertEqual(row.quality_status, "complete")
        self.assertAlmostEqual(row.completeness, 1.0)
        self.assertEqual(json.loads(row.payload), new_payload)
        self.assertEqual(json.loads(row.provider_trace), new_trace)
        self.assertGreater(row.updated_at, old_row.updated_at)

    # --- §3.4 rule 3: partial must NOT overwrite complete ----------------

    def test_partial_does_not_overwrite_complete(self):
        complete_payload = _make_payload(TRADE_DATE, ok_groups=REQUIRED_GROUPS)
        complete_trace = _make_trace(REQUIRED_GROUPS)
        self.repo.save_snapshot(complete_payload, complete_trace)
        existing = self.repo.get_by_market_date("cn", TRADE_DATE)
        time.sleep(0.02)

        partial_payload = _make_payload(TRADE_DATE, ok_groups=["breadth"])
        result = self.repo.save_snapshot(partial_payload, _make_trace(["breadth"]))

        self.assertEqual(result.action, "superseded_by_existing_complete")
        self.assertTrue(result.superseded_by_existing_complete)
        row = self.repo.get_by_market_date("cn", TRADE_DATE)
        self.assertEqual(row.payload, existing.payload)
        self.assertEqual(row.provider_trace, existing.provider_trace)
        self.assertEqual(row.updated_at, existing.updated_at)
        self.assertEqual(row.quality_status, "complete")
        self.assertEqual(json.loads(row.payload), complete_payload)

        self.assertEqual(_count_rows(self.repo), 1)

    # --- §3.4 rule 4: partial + partial -> group-level fill-in merge -----

    def test_partial_partial_group_fill_merge(self):
        old_ok = ["breadth", "turnover"]
        new_ok = ["limit_up_pool"]
        old_payload = _make_payload(TRADE_DATE, ok_groups=old_ok)
        self.repo.save_snapshot(old_payload, _make_trace(old_ok))
        old_row = self.repo.get_by_market_date("cn", TRADE_DATE)
        time.sleep(0.02)

        new_payload = _make_payload(TRADE_DATE, ok_groups=new_ok)
        result = self.repo.save_snapshot(new_payload, _make_trace(new_ok))

        self.assertEqual(result.action, "merged")
        self.assertFalse(result.superseded_by_existing_complete)
        row = self.repo.get_by_market_date("cn", TRADE_DATE)
        merged_payload = json.loads(row.payload)
        # old ok groups keep their data (first-writer-wins)
        self.assertEqual(merged_payload["breadth"], old_payload["breadth"])
        self.assertEqual(merged_payload["turnover"], old_payload["turnover"])
        # newly filled group takes the new data
        self.assertEqual(merged_payload["limit_up"], new_payload["limit_up"])
        # non-ok groups untouched by the new partial
        self.assertEqual(merged_payload["promotion"], old_payload["promotion"])
        metric_status = merged_payload["metric_status"]
        for group in old_ok + new_ok:
            self.assertEqual(metric_status[group], "ok")
        self.assertEqual(metric_status["broken_pool"], "source_error")
        self.assertEqual(row.quality_status, "partial")
        self.assertAlmostEqual(row.completeness, 3 / 6)
        # trace keeps old entries for kept groups and adds new entries for filled ones
        trace_groups = [entry["metric_group"] for entry in json.loads(row.provider_trace)]
        self.assertEqual(sorted(trace_groups), sorted(old_ok + new_ok))
        self.assertGreater(row.updated_at, old_row.updated_at)

    def test_partial_partial_merge_upgrades_to_complete(self):
        missing_group = "limit_up_pool"
        old_ok = [group for group in REQUIRED_GROUPS if group != missing_group]
        old_payload = _make_payload(TRADE_DATE, ok_groups=old_ok)
        self.repo.save_snapshot(old_payload, _make_trace(old_ok))

        new_payload = _make_payload(TRADE_DATE, ok_groups=[missing_group])
        result = self.repo.save_snapshot(new_payload, _make_trace([missing_group]))

        self.assertEqual(result.action, "merged")
        row = self.repo.get_by_market_date("cn", TRADE_DATE)
        self.assertEqual(row.quality_status, "complete")
        self.assertAlmostEqual(row.completeness, 1.0)
        merged_payload = json.loads(row.payload)
        # old ok groups must survive the merge untouched
        for group in old_ok:
            section = SECTION_FOR_GROUP[group]
            self.assertEqual(merged_payload[section], old_payload[section])
        self.assertEqual(merged_payload["limit_up"], new_payload["limit_up"])

    def test_partial_partial_merge_no_new_info_keeps_updated_at(self):
        old_payload = _make_payload(TRADE_DATE, ok_groups=["breadth"])
        self.repo.save_snapshot(old_payload, _make_trace(["breadth"]))
        existing = self.repo.get_by_market_date("cn", TRADE_DATE)
        time.sleep(0.02)

        # same partial again: nothing new to fill
        result = self.repo.save_snapshot(old_payload, _make_trace(["breadth"]))
        self.assertEqual(result.action, "merged")
        row = self.repo.get_by_market_date("cn", TRADE_DATE)
        self.assertEqual(row.updated_at, existing.updated_at)

    def test_partial_partial_merge_enhancement_group_ignored_for_completeness(self):
        old_ok = []
        new_ok = ["sector"]
        old_payload = _make_payload(TRADE_DATE, ok_groups=old_ok)
        self.repo.save_snapshot(old_payload, _make_trace(old_ok))

        new_payload = _make_payload(TRADE_DATE, ok_groups=new_ok)
        self.repo.save_snapshot(new_payload, _make_trace(new_ok))

        row = self.repo.get_by_market_date("cn", TRADE_DATE)
        # sector is an enhancement group: filled into the payload but never
        # counted towards completeness / quality_status
        merged_payload = json.loads(row.payload)
        self.assertEqual(merged_payload["sector_strength"], new_payload["sector_strength"])
        self.assertEqual(merged_payload["metric_status"]["sector"], "ok")
        self.assertEqual(row.quality_status, "partial")
        self.assertAlmostEqual(row.completeness, 0.0)

    # --- §3.4 rule 5: IntegrityError -> retry once -> idempotent return ---

    def test_integrity_error_retries_merge_once(self):
        # Simulate a cross-process race: between our SELECT and INSERT another
        # writer commits a competing partial row for the same (market, trade_date).
        competitor_payload = _make_payload(TRADE_DATE, ok_groups=["breadth"])
        competitor_trace = _make_trace(["breadth"])
        repo = self.repo

        def racing_insert(session, row):
            other_session = repo.db.get_session()
            try:
                other_session.add(
                    MarketSentimentSnapshot(
                        market="cn",
                        trade_date=TRADE_DATE,
                        quality_status="partial",
                        completeness=1 / 6,
                        payload=json.dumps(competitor_payload, ensure_ascii=False),
                        provider_trace=json.dumps(competitor_trace, ensure_ascii=False),
                    )
                )
                other_session.commit()
            finally:
                other_session.close()
            raise IntegrityError("UNIQUE constraint failed: market_sentiment_snapshots.market", None, None)

        repo._insert_snapshot = racing_insert
        new_payload = _make_payload(TRADE_DATE, ok_groups=["limit_up_pool"])
        result = repo.save_snapshot(new_payload, _make_trace(["limit_up_pool"]))

        self.assertEqual(result.action, "merged")
        row = repo.get_by_market_date("cn", TRADE_DATE)
        merged_payload = json.loads(row.payload)
        # competitor kept its group, the late partial still filled its hole
        self.assertEqual(merged_payload["breadth"], competitor_payload["breadth"])
        self.assertEqual(merged_payload["limit_up"], new_payload["limit_up"])
        self.assertAlmostEqual(row.completeness, 2 / 6, places=5)
        self.assertEqual(_count_rows(repo), 1)

    def test_double_integrity_error_returns_existing_idempotently(self):
        # Both attempts lose the race (SELECT blinded, INSERT hits the unique
        # constraint): the fallback must read the existing row and return it.
        existing_payload = _make_payload(TRADE_DATE, ok_groups=REQUIRED_GROUPS)
        existing_trace = _make_trace(REQUIRED_GROUPS)
        self.repo.save_snapshot(existing_payload, existing_trace)
        existing = self.repo.get_by_market_date("cn", TRADE_DATE)

        real_load = self.repo._load_existing
        calls = {"n": 0}

        def blinded_load(session, market, trade_date):
            calls["n"] += 1
            if calls["n"] <= 2:
                return None
            return real_load(session, market, trade_date)

        def failing_insert(session, row):
            raise IntegrityError("UNIQUE constraint failed: market_sentiment_snapshots.market", None, None)

        self.repo._load_existing = blinded_load
        self.repo._insert_snapshot = failing_insert

        partial_payload = _make_payload(TRADE_DATE, ok_groups=["breadth"])
        result = self.repo.save_snapshot(partial_payload, _make_trace(["breadth"]))

        self.assertEqual(result.action, "idempotent_return")
        self.assertTrue(result.superseded_by_existing_complete)
        # two blinded attempts + one fallback read; later get_by_market_date
        # calls would go through the patched seam too, so assert count here
        self.assertEqual(calls["n"], 3)
        row = self.repo.get_by_market_date("cn", TRADE_DATE)
        self.assertEqual(row.payload, existing.payload)
        self.assertEqual(row.updated_at, existing.updated_at)
        self.assertEqual(row.quality_status, "complete")
        self.assertEqual(_count_rows(self.repo), 1)

    # --- unique constraint actually exists on the table -------------------

    def test_unique_constraint_enforced_by_schema(self):
        with self.db.get_session() as session:
            session.add(
                MarketSentimentSnapshot(
                    market="cn",
                    trade_date=TRADE_DATE,
                    quality_status="partial",
                    completeness=0.0,
                    payload="{}",
                    provider_trace="[]",
                )
            )
            session.commit()
        with self.db.get_session() as session:
            session.add(
                MarketSentimentSnapshot(
                    market="cn",
                    trade_date=TRADE_DATE,
                    quality_status="partial",
                    completeness=0.0,
                    payload="{}",
                    provider_trace="[]",
                )
            )
            with self.assertRaises(IntegrityError):
                session.commit()

    # --- get_by_market_date ------------------------------------------------

    def test_get_by_market_date_missing_returns_none(self):
        self.assertIsNone(self.repo.get_by_market_date("cn", "2030-01-01"))

    def test_get_by_market_date_scopes_by_market(self):
        payload = _make_payload(TRADE_DATE, ok_groups=["breadth"])
        self.repo.save_snapshot(payload)
        self.assertIsNotNone(self.repo.get_by_market_date("cn", TRADE_DATE))
        self.assertIsNone(self.repo.get_by_market_date("us", TRADE_DATE))

    # --- list_snapshots: pagination + ordering ------------------------------

    def test_list_snapshots_pagination_and_order(self):
        for day in ("2026-11-11", "2026-11-12", "2026-11-13"):
            payload = _make_payload(day, ok_groups=["breadth"])
            payload["prev_trade_date"] = "2026-11-10"
            self.repo.save_snapshot(payload)

        items, total = self.repo.list_snapshots("cn", limit=2, offset=0, order="desc")
        self.assertEqual(total, 3)
        self.assertEqual([row.trade_date for row in items], ["2026-11-13", "2026-11-12"])

        items, _ = self.repo.list_snapshots("cn", limit=2, offset=2, order="desc")
        self.assertEqual([row.trade_date for row in items], ["2026-11-11"])

        items, _ = self.repo.list_snapshots("cn", limit=2, offset=0, order="asc")
        self.assertEqual([row.trade_date for row in items], ["2026-11-11", "2026-11-12"])

    def test_list_snapshots_rejects_unknown_order(self):
        with self.assertRaises(ValueError):
            self.repo.list_snapshots("cn", limit=10, offset=0, order="sideways")

    # --- query_trend_range: <= inclusive vs < strict (§4.4) ------------------

    def test_query_trend_range_inclusive_end(self):
        for day in ("2026-11-11", "2026-11-12", "2026-11-13"):
            payload = _make_payload(day, ok_groups=["breadth"])
            payload["prev_trade_date"] = "2026-11-10"
            self.repo.save_snapshot(payload)

        rows = self.repo.query_trend_range("cn", start_date="2026-11-11", end_date="2026-11-12")
        self.assertEqual([row.trade_date for row in rows], ["2026-11-11", "2026-11-12"])

    def test_query_trend_range_strict_before_excludes_target(self):
        for day in ("2026-11-11", "2026-11-12", "2026-11-13"):
            payload = _make_payload(day, ok_groups=["breadth"])
            payload["prev_trade_date"] = "2026-11-10"
            self.repo.save_snapshot(payload)

        rows = self.repo.query_trend_range("cn", start_date="2026-11-11", strict_before="2026-11-12")
        self.assertEqual([row.trade_date for row in rows], ["2026-11-11"])

        rows = self.repo.query_trend_range("cn", strict_before="2026-11-14")
        self.assertEqual([row.trade_date for row in rows], ["2026-11-11", "2026-11-12", "2026-11-13"])

    def test_query_trend_range_no_bounds_returns_all_ascending(self):
        for day in ("2026-11-13", "2026-11-11", "2026-11-12"):
            payload = _make_payload(day, ok_groups=["breadth"])
            payload["prev_trade_date"] = "2026-11-10"
            self.repo.save_snapshot(payload)

        rows = self.repo.query_trend_range("cn")
        self.assertEqual([row.trade_date for row in rows], ["2026-11-11", "2026-11-12", "2026-11-13"])


if __name__ == "__main__":
    unittest.main()
