# -*- coding: utf-8 -*-
"""Service-orchestration tests for market sentiment snapshots (issue #1939 Wave 4).

Covers the six contract functions from the implementation plan Wave 4 with
the six mandatory scenario families:

1. future rows (trade_date > resolved target) never leak into trend queries;
2. trade-date discontinuity (Friday -> Monday prev_trade_date is the previous
   TRADE day, not natural day -1; M6 MoM denominator = the previous trade
   day's own snapshot row, strict trade-date semantics);
3. missing sources -> snapshot saved as partial, missing_reason everywhere,
   never a fabricated 0;
4. orchestration integration (stub fetcher -> real repository -> payload and
   provider_trace assertions) plus full fail-open (job body never raises);
5. trigger target resolution (Asia/Shanghai fixed timezone, >=15:00 cutoff,
   explicit trade_date must equal the resolved target);
6. trigger short-circuit (existing complete + force=false) and the global
   in-process trigger lock (second concurrent trigger conflicts).

All network and calendar paths are stubbed; DB runs on a temporary SQLite
file using the Config + DatabaseManager.reset_instance() convention.
"""

import json
import os
import tempfile
import unittest
from datetime import date, datetime, time, timezone
from unittest import mock
from zoneinfo import ZoneInfo

import pandas as pd

from src.config import Config
from src.repositories.market_sentiment_repo import (
    DEFAULT_REQUIRED_GROUPS,
    MarketSentimentRepository,
)
from src.services import market_sentiment_service as mss
from src.storage import DatabaseManager

SHANGHAI = ZoneInfo("Asia/Shanghai")
UTC = timezone.utc

# 交易日历 stub：2026-11-09(一)..13(五)、16(一)..20(五) 两个完整交易周。
STUB_TRADE_DATES = [
    date(2026, 11, d) for d in (9, 10, 11, 12, 13, 16, 17, 18, 19, 20)
]
THURSDAY = date(2026, 11, 12)
FRIDAY = date(2026, 11, 13)
SATURDAY = date(2026, 11, 14)
MONDAY = date(2026, 11, 16)
TUESDAY_NEXT = date(2026, 11, 17)
FAR_FUTURE = date(2026, 11, 20)

FRIDAY_ISO = FRIDAY.isoformat()
MONDAY_ISO = MONDAY.isoformat()


def _sh(now: datetime) -> datetime:
    if now.tzinfo is None:
        return now.replace(tzinfo=SHANGHAI)
    return now.astimezone(SHANGHAI)


def _pool_df(boards, changes=None):
    n = len(boards)
    changes = changes if changes is not None else [9.99] * n
    return pd.DataFrame({
        "代码": ["00000%d" % i for i in range(1, n + 1)],
        "名称": ["股%d" % i for i in range(1, n + 1)],
        "涨跌幅": changes,
        "连板数": boards,
    })


def _stats_fixture(total_amount=120.0):
    return {
        "up_count": 765,
        "down_count": 4747,
        "flat_count": 58,
        "total_amount": total_amount,
        "limit_up_count": 30,
        "limit_down_count": 3,
    }


def _full_fetch_result(trade_compact="20261116", prev_compact="20261113"):
    """All-ok fetch fixture: every group source present."""
    trace = [
        {"metric_group": g, "provider": "akshare", "api": "stub", "params": {},
         "status": "ok", "elapsed_ms": 5, "error": None,
         "fetched_at": "2026-11-16T15:30:00"}
        for g in ("breadth", "turnover", "sector", "limit_up_pool",
                  "broken_pool", "promotion", "prev_feedback")
    ]
    return {
        "stats": _stats_fixture(),
        "sector_rankings": (
            [{"name": "行业A", "change_pct": 3.0}],
            [{"name": "行业B", "change_pct": -2.0}],
        ),
        "today_pool": _pool_df([1, 2]),           # count=2, max_boards=2
        "prev_pool": _pool_df([1]),               # 昨日 1 家 1 板
        "broken_pool": _pool_df([1]),             # 炸板 1 家 → failure_rate=1/3
        "limit_down_pool": _pool_df([1])[:0],     # 空=有效 0 家跌停
        "previous_pool": pd.DataFrame({
            "代码": ["000001", "000002"],
            "名称": ["股1", "股2"],
            "涨跌幅": [5.0, -2.0],
        }),
        "provider_trace": trace,
    }


class _StubFetcher:
    """Recording stand-in for MarketSentimentFetcher.fetch_all."""

    def __init__(self, result=None, error_groups=(), raise_exc=None):
        self.calls = []
        self._result = result if result is not None else _full_fetch_result()
        self._error_groups = set(error_groups)
        self._raise_exc = raise_exc

    def fetch_all(self, trade_date, prev_trade_date=None):
        self.calls.append({"trade_date": trade_date, "prev_trade_date": prev_trade_date})
        if self._raise_exc is not None:
            raise self._raise_exc
        result = {
            key: (value.copy() if isinstance(value, pd.DataFrame) else value)
            for key, value in self._result.items()
        }
        if prev_trade_date is None:
            # 对齐真 fetcher 契约：无 prev_trade_date 时不取昨日池。
            result["prev_pool"] = None
        if self._error_groups:
            result["today_pool"] = None
            result["prev_pool"] = None
            result["broken_pool"] = None
            for entry in result["provider_trace"]:
                if entry["metric_group"] in self._error_groups:
                    entry["status"] = "error"
                    entry["error"] = "stub failure"
        return result


def _stub_calendar():
    return list(STUB_TRADE_DATES)


def _make_row_payload(trade_date, *, total_amount=None, ok=True):
    """Minimal §3.2 payload for seeding rows (M6 denominator / trend tests)."""
    return {
        "schema_version": 1,
        "market": "cn",
        "trade_date": trade_date,
        "prev_trade_date": None,
        "required_groups": list(DEFAULT_REQUIRED_GROUPS),
        "metric_status": {g: ("ok" if ok else "source_error")
                          for g in DEFAULT_REQUIRED_GROUPS},
        "narrative": None,
        "narrative_generated_at": None,
        "breadth": {"advance_decline_diff": -100 if ok else None,
                    "missing_reason": None if ok else "source_error"},
        "limit_up": {"count": 5 if ok else None, "max_boards": 3 if ok else None,
                     "missing_reason": None if ok else "source_error"},
        "broken_limit": {"failure_rate": 0.25 if ok else None,
                         "missing_reason": None if ok else "source_error"},
        "turnover": {"total_amount_yi": total_amount,
                     "mom_change_pct": 1.5 if ok else None,
                     "missing_reason": None if ok else "source_error"},
        "promotion": {"overall": {"rate": 0.5 if ok else None},
                      "missing_reason": None if ok else "source_error"},
        "yesterday_limit_feedback": {"avg_change_pct": 2.0 if ok else None,
                                     "missing_reason": None if ok else "source_error"},
    }


class MarketSentimentServiceTestCase(unittest.TestCase):
    """Shared tmp-DB setup + stub wiring + module-lock teardown."""

    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(self._temp_dir.name, "test_market_sentiment_service.db")
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
        self.fetcher = _StubFetcher()
        self.service = mss.MarketSentimentService(
            repo=self.repo,
            fetcher_factory=lambda: self.fetcher,
            trade_dates_provider=_stub_calendar,
        )

    def tearDown(self):
        mss._release_trigger_lock()
        Config._instance = None
        DatabaseManager.reset_instance()
        for key, value in self._original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._temp_dir.cleanup()

    def _seed_row(self, trade_date, payload=None, trace_groups=("breadth",)):
        payload = payload or _make_row_payload(trade_date, ok=True)
        trace = [
            {"metric_group": g, "provider": "akshare", "api": "seed", "params": {},
             "status": "ok", "elapsed_ms": 1, "error": None,
             "fetched_at": "2026-11-13T16:00:00"}
            for g in trace_groups
        ]
        return self.repo.save_snapshot(payload, trace, trade_date=trade_date)


# ---------------------------------------------------------------------------
# 0. 六函数公开签名契约（W5 按此机械映射）
# ---------------------------------------------------------------------------

class TestPublicContract(unittest.TestCase):

    def test_six_module_functions_expose_contract_signatures(self):
        import inspect

        expected = {
            "resolve_latest_closed_trade_date": ["now"],
            "trigger_snapshot": ["trade_date", "force"],
            "run_snapshot_job": ["trade_date"],
            "get_snapshot": ["trade_date"],
            "list_snapshots": ["limit", "offset", "order"],
            "query_trend": ["metric", "days", "start_date", "end_date"],
        }
        for name, params in expected.items():
            func = getattr(mss, name, None)
            self.assertTrue(callable(func), name)
            signature = inspect.signature(func)
            self.assertEqual(
                list(signature.parameters), params,
                f"{name} 参数表必须与计划 Wave 4 契约一致",
            )


# ---------------------------------------------------------------------------
# 1. 触发目标解析（Asia/Shanghai 固定时区 + 15:00 收盘门）
# ---------------------------------------------------------------------------

class TestResolveLatestClosedTradeDate(MarketSentimentServiceTestCase):

    def test_after_close_on_trade_day_targets_same_day(self):
        resolved = self.service.resolve_latest_closed_trade_date(
            datetime.combine(FRIDAY, time(15, 0), tzinfo=SHANGHAI)
        )
        self.assertEqual(resolved, FRIDAY)

    def test_before_close_on_trade_day_targets_previous_trade_day(self):
        resolved = self.service.resolve_latest_closed_trade_date(
            datetime.combine(FRIDAY, time(14, 59, 59), tzinfo=SHANGHAI)
        )
        self.assertEqual(resolved, THURSDAY)

    def test_weekend_targets_friday(self):
        resolved = self.service.resolve_latest_closed_trade_date(
            datetime.combine(SATURDAY, time(20, 0), tzinfo=SHANGHAI)
        )
        self.assertEqual(resolved, FRIDAY)

    def test_monday_morning_targets_friday_not_sunday(self):
        resolved = self.service.resolve_latest_closed_trade_date(
            datetime.combine(MONDAY, time(9, 0), tzinfo=SHANGHAI)
        )
        self.assertEqual(resolved, FRIDAY)

    def test_monday_after_close_targets_monday(self):
        resolved = self.service.resolve_latest_closed_trade_date(
            datetime.combine(MONDAY, time(16, 0), tzinfo=SHANGHAI)
        )
        self.assertEqual(resolved, MONDAY)

    def test_naive_datetime_treated_as_shanghai(self):
        resolved = self.service.resolve_latest_closed_trade_date(
            datetime.combine(MONDAY, time(9, 30))
        )
        self.assertEqual(resolved, FRIDAY)

    def test_aware_datetime_converted_from_utc(self):
        # UTC 07:00 == Shanghai 15:00（周五）→ 目标当日。
        resolved = self.service.resolve_latest_closed_trade_date(
            datetime.combine(FRIDAY, time(7, 0), tzinfo=UTC)
        )
        self.assertEqual(resolved, FRIDAY)

    def test_module_function_uses_injectable_calendar(self):
        with mock.patch.object(mss, "_load_trade_dates", return_value=list(STUB_TRADE_DATES)):
            resolved = mss.resolve_latest_closed_trade_date(
                datetime.combine(MONDAY, time(9, 0), tzinfo=SHANGHAI)
            )
        self.assertEqual(resolved, FRIDAY)

    def test_unavailable_calendar_raises(self):
        with self.assertRaises(mss.TradeCalendarUnavailableError):
            self.service.resolve_latest_closed_trade_date(
                datetime.combine(MONDAY, time(9, 0), tzinfo=SHANGHAI),
                trade_dates_provider=lambda: [],
            )


# ---------------------------------------------------------------------------
# 2. 触发目标语义 + 短路 + 全局锁
# ---------------------------------------------------------------------------

class TestTriggerSnapshot(MarketSentimentServiceTestCase):

    def _now(self):
        return datetime.combine(MONDAY, time(9, 0), tzinfo=SHANGHAI)  # 目标=周五

    def test_default_trigger_resolves_target(self):
        with mock.patch.object(mss, "_now_shanghai", return_value=self._now()):
            result = self.service.trigger_snapshot()
        self.assertEqual(result.status, "accepted")
        self.assertEqual(result.trade_date, FRIDAY_ISO)
        self.assertTrue(result.task_id)

    def test_explicit_trade_date_equal_to_target_accepted(self):
        with mock.patch.object(mss, "_now_shanghai", return_value=self._now()):
            result = self.service.trigger_snapshot(trade_date=FRIDAY_ISO)
        self.assertEqual(result.status, "accepted")
        self.assertEqual(result.trade_date, FRIDAY_ISO)

    def test_explicit_future_trade_date_rejected(self):
        with mock.patch.object(mss, "_now_shanghai", return_value=self._now()):
            with self.assertRaises(mss.InvalidTargetDateError):
                self.service.trigger_snapshot(trade_date=FAR_FUTURE.isoformat())

    def test_explicit_historical_trade_date_rejected(self):
        with mock.patch.object(mss, "_now_shanghai", return_value=self._now()):
            with self.assertRaises(mss.InvalidTargetDateError):
                self.service.trigger_snapshot(trade_date=THURSDAY.isoformat())

    def test_malformed_trade_date_rejected(self):
        with mock.patch.object(mss, "_now_shanghai", return_value=self._now()):
            with self.assertRaises(ValueError):
                self.service.trigger_snapshot(trade_date="2026-13-99")

    def test_short_circuit_when_complete_exists_and_no_force(self):
        self._seed_row(FRIDAY_ISO, _make_row_payload(FRIDAY_ISO, ok=True))
        with mock.patch.object(mss, "_now_shanghai", return_value=self._now()):
            result = self.service.trigger_snapshot()
        self.assertEqual(result.status, "short_circuited")
        self.assertEqual(result.trade_date, FRIDAY_ISO)
        self.assertIsNotNone(result.existing_snapshot_summary)
        self.assertEqual(result.existing_snapshot_summary["quality_status"], "complete")
        self.assertEqual(self.fetcher.calls, [])  # 不产生抓取成本

    def test_force_bypasses_short_circuit(self):
        self._seed_row(FRIDAY_ISO, _make_row_payload(FRIDAY_ISO, ok=True))
        with mock.patch.object(mss, "_now_shanghai", return_value=self._now()):
            result = self.service.trigger_snapshot(force=True)
        self.assertEqual(result.status, "accepted")
        self.assertEqual(self.fetcher.calls, [])  # trigger 本身仍不抓取

    def test_partial_existing_row_does_not_short_circuit(self):
        payload = _make_row_payload(FRIDAY_ISO, ok=False)
        self._seed_row(FRIDAY_ISO, payload)
        with mock.patch.object(mss, "_now_shanghai", return_value=self._now()):
            result = self.service.trigger_snapshot()
        self.assertEqual(result.status, "accepted")


class TestTriggerGlobalLock(MarketSentimentServiceTestCase):

    def test_second_trigger_conflicts_until_job_finishes(self):
        now = datetime.combine(MONDAY, time(9, 0), tzinfo=SHANGHAI)
        with mock.patch.object(mss, "_now_shanghai", return_value=now):
            first = self.service.trigger_snapshot()
            self.assertEqual(first.status, "accepted")
            with self.assertRaises(mss.SnapshotTriggerConflictError):
                self.service.trigger_snapshot()

            # 任务体执行完成后锁释放，可再次触发
            self.service.run_snapshot_job(first.trade_date)
            third = self.service.trigger_snapshot(force=True)
            self.assertEqual(third.status, "accepted")

    def test_short_circuit_does_not_hold_lock(self):
        now = datetime.combine(MONDAY, time(9, 0), tzinfo=SHANGHAI)
        self._seed_row(FRIDAY_ISO, _make_row_payload(FRIDAY_ISO, ok=True))
        with mock.patch.object(mss, "_now_shanghai", return_value=now):
            first = self.service.trigger_snapshot()  # short_circuited
            self.assertEqual(first.status, "short_circuited")
            second = self.service.trigger_snapshot()  # 仍可短路，无锁冲突
            self.assertEqual(second.status, "short_circuited")


# ---------------------------------------------------------------------------
# 3. 交易日不连续 + M6 环比分母（上一"交易日"快照）
# ---------------------------------------------------------------------------

class TestTradeDateDiscontinuity(MarketSentimentServiceTestCase):

    def test_prev_trade_date_is_previous_trade_day_not_natural_day(self):
        self.service.run_snapshot_job(MONDAY_ISO)
        self.assertEqual(
            self.fetcher.calls,
            [{"trade_date": "20261116", "prev_trade_date": "20261113"}],
        )
        row = self.repo.get_by_market_date("cn", MONDAY_ISO)
        payload = json.loads(row.payload)
        self.assertEqual(payload["prev_trade_date"], FRIDAY_ISO)
        self.assertEqual(payload["promotion"]["prev_pool_date"], FRIDAY_ISO)

    def test_m6_denominator_uses_prev_trade_day_snapshot_strictly(self):
        # 周五（total=100）与周六（total=555，异常行）都存在 → 分母必须取周五。
        self._seed_row(FRIDAY_ISO, _make_row_payload(FRIDAY_ISO, total_amount=100.0))
        self._seed_row(
            SATURDAY.isoformat(), _make_row_payload(SATURDAY.isoformat(), total_amount=555.0)
        )
        self.service.run_snapshot_job(MONDAY_ISO)
        payload = json.loads(self.repo.get_by_market_date("cn", MONDAY_ISO).payload)
        self.assertEqual(payload["turnover"]["prev_total_amount_yi"], 100.0)
        self.assertAlmostEqual(payload["turnover"]["mom_change_pct"], 20.0, places=6)
        self.assertEqual(payload["turnover"]["prev_source"], "snapshot_table")

    def test_m6_cold_start_marks_missing_prev(self):
        self.service.run_snapshot_job(MONDAY_ISO)
        payload = json.loads(self.repo.get_by_market_date("cn", MONDAY_ISO).payload)
        self.assertIsNone(payload["turnover"]["mom_change_pct"])
        self.assertEqual(payload["turnover"]["mom_missing_reason"], "missing_prev")


# ---------------------------------------------------------------------------
# 4. 源缺失 → partial 落库（missing_reason 齐全、无 0 值）
# ---------------------------------------------------------------------------

class TestSourceMissingPartial(MarketSentimentServiceTestCase):

    def test_failing_groups_save_partial_with_reasons(self):
        self.fetcher = _StubFetcher(
            error_groups={"limit_up_pool", "broken_pool", "promotion"}
        )
        self.service = mss.MarketSentimentService(
            repo=self.repo,
            fetcher_factory=lambda: self.fetcher,
            trade_dates_provider=_stub_calendar,
        )
        summary = self.service.run_snapshot_job(MONDAY_ISO)

        row = self.repo.get_by_market_date("cn", MONDAY_ISO)
        # partial 快照正常落库 → 摘要 status="partial"（非任务失败）
        self.assertEqual(summary["status"], "partial")
        self.assertEqual(summary["quality_status"], "partial")
        self.assertAlmostEqual(summary["completeness"], 3 / 6, places=5)
        self.assertEqual(summary["trade_date"], MONDAY_ISO)
        self.assertIsNone(summary["error"])
        self.assertIsNotNone(row, "快照必须以 partial 落库，而不是不写")
        self.assertEqual(row.quality_status, "partial")
        self.assertAlmostEqual(row.completeness, 3 / 6, places=5)

        payload = json.loads(row.payload)
        status = payload["metric_status"]
        self.assertEqual(status["limit_up_pool"], "source_error")
        self.assertEqual(status["broken_pool"], "source_error")
        self.assertEqual(status["promotion"], "source_error")
        self.assertEqual(status["breadth"], "ok")
        self.assertEqual(status["turnover"], "ok")
        self.assertEqual(status["prev_feedback"], "ok")

        # 无 0 值：缺失组数值为 None + missing_reason，而非伪造 0
        self.assertIsNone(payload["limit_up"]["count"])
        self.assertIsNone(payload["limit_up"]["max_boards"])
        self.assertEqual(payload["limit_up"]["missing_reason"], "source_error")
        self.assertIsNone(payload["broken_limit"]["failure_rate"])
        self.assertIsNone(payload["promotion"]["overall"]["rate"])

        # provider_trace 落迹：失败组带 error 状态
        trace = json.loads(row.provider_trace)
        by_group = {e["metric_group"]: e for e in trace}
        self.assertEqual(by_group["limit_up_pool"]["status"], "error")
        self.assertEqual(by_group["promotion"]["status"], "error")

    def test_fetch_all_raising_never_propagates(self):
        self.fetcher = _StubFetcher(raise_exc=RuntimeError("boom"))
        self.service = mss.MarketSentimentService(
            repo=self.repo,
            fetcher_factory=lambda: self.fetcher,
            trade_dates_provider=_stub_calendar,
        )
        self.assertIsNone(self.repo.get_by_market_date("cn", MONDAY_ISO))
        # fail-open 返回 status="failed" 摘要（非 None），队列据此判任务成功
        summary = self.service.run_snapshot_job(MONDAY_ISO)
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["trade_date"], MONDAY_ISO)
        self.assertIsNone(summary["quality_status"])
        self.assertIsNone(summary["completeness"])
        self.assertIn("RuntimeError: boom", summary["error"])

    def test_unparseable_trade_date_returns_failed_summary_without_fetch(self):
        summary = self.service.run_snapshot_job("not-a-date")  # 不抛
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["trade_date"], "not-a-date")
        self.assertIn("invalid trade_date", summary["error"])
        self.assertEqual(self.fetcher.calls, [])  # 解析失败不产生抓取成本

    def test_calendar_failure_degrades_prev_groups_only(self):
        self.service = mss.MarketSentimentService(
            repo=self.repo,
            fetcher_factory=lambda: self.fetcher,
            trade_dates_provider=lambda: [],  # 日历不可用
        )
        self.service.run_snapshot_job(MONDAY_ISO)
        row = self.repo.get_by_market_date("cn", MONDAY_ISO)
        self.assertIsNotNone(row)
        payload = json.loads(row.payload)
        self.assertIsNone(payload["prev_trade_date"])
        self.assertEqual(payload["metric_status"]["promotion"], "source_error")
        # previous_em 自含 T-1 语义，不受日历缺失影响
        self.assertEqual(payload["metric_status"]["prev_feedback"], "ok")


# ---------------------------------------------------------------------------
# 5. 编排集成（stub fetcher → 真 repo → payload/trace 断言）
# ---------------------------------------------------------------------------

class TestOrchestrationIntegration(MarketSentimentServiceTestCase):

    def test_full_chain_produces_complete_snapshot(self):
        result = self.service.run_snapshot_job(MONDAY_ISO)
        # 后台任务体契约：返回摘要 dict（status="ok"），供任务队列判定 SUCCESS
        self.assertEqual(result, {
            "status": "ok",
            "trade_date": MONDAY_ISO,
            "quality_status": "complete",
            "completeness": 1.0,
            "error": None,
        })
        row = self.repo.get_by_market_date("cn", MONDAY_ISO)
        self.assertIsNotNone(row)
        self.assertEqual(row.quality_status, "complete")
        self.assertAlmostEqual(row.completeness, 1.0, places=6)

        payload = json.loads(row.payload)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["market"], "cn")
        self.assertEqual(payload["trade_date"], MONDAY_ISO)
        self.assertEqual(payload["prev_trade_date"], FRIDAY_ISO)
        self.assertIsNone(payload["narrative"])
        self.assertIsNone(payload["narrative_generated_at"])
        self.assertEqual(set(payload["required_groups"]), set(DEFAULT_REQUIRED_GROUPS))
        self.assertTrue(all(v == "ok" for v in payload["metric_status"].values()))

        # 口径抽检（与 metrics golden fixture 一致）
        self.assertEqual(payload["breadth"]["up_count"], 765)
        self.assertEqual(payload["breadth"]["advance_decline_diff"], 765 - 4747)
        self.assertEqual(payload["limit_up"]["count"], 2)  # 池主口径
        self.assertEqual(payload["limit_up"]["max_boards"], 2)
        self.assertEqual(payload["limit_up"]["limit_down_count"], 0)  # 空池=有效 0
        self.assertEqual(payload["limit_up"]["limit_down_source"], "pool")
        self.assertEqual(payload["yesterday_limit_feedback"]["sample_size"], 2)
        self.assertAlmostEqual(
            payload["yesterday_limit_feedback"]["avg_change_pct"], 1.5, places=6
        )
        self.assertEqual(
            payload["yesterday_limit_feedback"]["auction_missing_reason"],
            "field_unavailable",
        )
        self.assertEqual(payload["sector_strength"]["top5"][0]["name"], "行业A")

        # provider_trace 每组至少一条
        trace = json.loads(row.provider_trace)
        traced_groups = {e["metric_group"] for e in trace}
        self.assertTrue(set(DEFAULT_REQUIRED_GROUPS) <= traced_groups)

    def test_get_snapshot_record_round_trip(self):
        self.service.run_snapshot_job(MONDAY_ISO)
        record = self.service.get_snapshot(MONDAY_ISO)
        self.assertIsNotNone(record)
        self.assertEqual(record.trade_date, MONDAY_ISO)
        self.assertEqual(record.quality_status, "complete")
        self.assertIsInstance(record.payload, dict)
        self.assertEqual(record.payload["market"], "cn")
        self.assertIsInstance(record.provider_trace, list)
        self.assertIsNone(self.service.get_snapshot("2020-01-01"))

    def test_list_snapshots_pagination_and_order(self):
        self._seed_row("2026-11-11", _make_row_payload("2026-11-11"))
        self._seed_row(FRIDAY_ISO, _make_row_payload(FRIDAY_ISO))
        listing = self.service.list_snapshots()
        self.assertEqual(listing.total, 2)
        self.assertEqual([i.trade_date for i in listing.items], [FRIDAY_ISO, "2026-11-11"])
        asc = self.service.list_snapshots(order="asc")
        self.assertEqual([i.trade_date for i in asc.items], ["2026-11-11", FRIDAY_ISO])
        page = self.service.list_snapshots(limit=1, offset=1)
        self.assertEqual([i.trade_date for i in page.items], ["2026-11-11"])
        self.assertEqual(page.total, 2)


# ---------------------------------------------------------------------------
# 6. 趋势查询：未来行不泄漏 + 指标抽取 + 边界语义
# ---------------------------------------------------------------------------

class TestQueryTrend(MarketSentimentServiceTestCase):

    def _seed_trend_rows(self):
        self._seed_row("2026-11-11", _make_row_payload("2026-11-11"))
        self._seed_row(FRIDAY_ISO, _make_row_payload(FRIDAY_ISO))
        self._seed_row(FAR_FUTURE.isoformat(), _make_row_payload(FAR_FUTURE.isoformat()))

    def _now(self):
        return datetime.combine(MONDAY, time(9, 0), tzinfo=SHANGHAI)  # 上海周一早

    def test_future_rows_never_leak_into_trend(self):
        self._seed_trend_rows()
        with mock.patch.object(mss, "_now_shanghai", return_value=self._now()):
            result = self.service.query_trend("advance_decline_diff", days=30)
        self.assertEqual(
            [p.trade_date for p in result.points], ["2026-11-11", FRIDAY_ISO]
        )
        self.assertEqual(result.available_points, 2)
        self.assertEqual(result.metric, "advance_decline_diff")
        self.assertTrue(all(p.value == -100 for p in result.points))

    def test_explicit_end_date_is_inclusive(self):
        self._seed_trend_rows()
        result = self.service.query_trend(
            "advance_decline_diff", start_date="2026-11-11", end_date=FRIDAY_ISO
        )
        self.assertEqual([p.trade_date for p in result.points], ["2026-11-11", FRIDAY_ISO])

    def test_days_window_bounds_by_now_and_latest_snapshot(self):
        self._seed_trend_rows()
        with mock.patch.object(mss, "_now_shanghai", return_value=self._now()):
            result = self.service.query_trend("limit_up_count", days=4)
        # end = min(now 周一 11-16, 最新快照 11-20) = 11-16；start = 11-13
        # → 窗口 [11-13, 11-16] 只有周五一行；11-11 在窗外、未来行 11-20 被钳制排除
        self.assertEqual([p.trade_date for p in result.points], [FRIDAY_ISO])
        self.assertEqual(result.points[0].value, 5)
        self.assertEqual(result.points[0].quality_status, "complete")

    def test_all_metric_extractions(self):
        self._seed_row(FRIDAY_ISO, _make_row_payload(FRIDAY_ISO))
        end = FRIDAY_ISO
        cases = {
            "advance_decline_diff": -100,
            "turnover_mom": 1.5,
            "limit_up_count": 5,
            "failure_rate": 0.25,
            "max_boards": 3,
            "overall_promotion_rate": 0.5,
            "feedback_avg_change_pct": 2.0,
        }
        for metric, expected in cases.items():
            result = self.service.query_trend(metric, start_date=end, end_date=end)
            self.assertEqual(len(result.points), 1, metric)
            self.assertEqual(result.points[0].value, expected, metric)

    def test_unknown_metric_rejected(self):
        with self.assertRaises(ValueError):
            self.service.query_trend("not_a_metric", days=5)

    def test_empty_series_returns_200_semantics(self):
        result = self.service.query_trend("limit_up_count", days=30)
        self.assertEqual(result.points, [])
        self.assertEqual(result.available_points, 0)
        self.assertEqual(result.metric, "limit_up_count")


# ---------------------------------------------------------------------------
# 7. 真实任务队列契约（复审 blocker OR-COR-70b15038 / OR-COR-ea7e538d）
# ---------------------------------------------------------------------------

class TestRealTaskQueueContract(MarketSentimentServiceTestCase):
    """submit_background_task 真实路径（不 mock 队列）的契约测试。

    语义边界（复审明确）：
    - 任务失败 = job 本身抛未捕获异常（fail-open 下不可能发生）；
    - 快照失败 = job 正常完成但摘要 ``status="failed"``，任务仍是 SUCCESS；
    - ``run_snapshot_job`` 必须返回摘要 dict —— 返回 None 会被
      ``_execute_background_task`` 判为 RuntimeError("任务返回空结果")，
      把成功落库的快照任务误标 FAILED（本次修复的 blocker 根因）。
    """

    TIMEOUT_SECONDS = 30.0

    def _run_via_real_queue(self, task_fn):
        """真实 AnalysisTaskQueue 执行 task_fn，返回 (job 返回值, 终态 TaskInfo)。"""
        from src.services.task_queue import AnalysisTaskQueue

        original_instance = AnalysisTaskQueue._instance
        AnalysisTaskQueue._instance = None
        queue = AnalysisTaskQueue(max_workers=1)
        try:
            with mock.patch.object(mss, "_DEFAULT_SERVICE", self.service):
                task_info = queue.submit_background_task(
                    task_fn,
                    stock_code="market_sentiment",
                    stock_name="市场情绪快照",
                    message="市场情绪快照任务已提交",
                    task_id="sentiment-contract-task",
                )
                job_result = queue._futures[task_info.task_id].result(
                    timeout=self.TIMEOUT_SECONDS
                )
                final = queue.get_task(task_info.task_id)
        finally:
            executor = getattr(queue, "_executor", None)
            if executor is not None and hasattr(executor, "shutdown"):
                executor.shutdown(wait=False, cancel_futures=True)
            AnalysisTaskQueue._instance = original_instance
        return job_result, final

    def test_success_path_task_completes_with_ok_summary(self):
        from src.services.task_queue import TaskStatus

        now = datetime.combine(MONDAY, time(9, 0), tzinfo=SHANGHAI)
        with mock.patch.object(mss, "_now_shanghai", return_value=now):
            trigger = mss.trigger_snapshot()
        self.assertEqual(trigger.status, "accepted")

        job_result, final = self._run_via_real_queue(
            lambda: mss.run_snapshot_job(trigger.trade_date)
        )

        self.assertEqual(final.status, TaskStatus.COMPLETED)
        # 周一 09:00 触发 → 目标日 = 上一交易日周五（§4.1）
        self.assertEqual(job_result, {
            "status": "ok",
            "trade_date": FRIDAY_ISO,
            "quality_status": "complete",
            "completeness": 1.0,
            "error": None,
        })
        self.assertEqual(final.result, job_result)
        self.assertEqual(final.error, None)
        # 快照确实落库，且全局锁已由 worker 线程中的任务体释放
        row = self.repo.get_by_market_date("cn", FRIDAY_ISO)
        self.assertIsNotNone(row)
        self.assertEqual(row.quality_status, "complete")
        self.assertIsNone(mss._TRIGGER_ACTIVE)

    def test_fail_open_fetcher_error_task_still_completes_failed_summary(self):
        from src.services.task_queue import TaskStatus

        self.fetcher = _StubFetcher(raise_exc=RuntimeError("boom"))
        self.service = mss.MarketSentimentService(
            repo=self.repo,
            fetcher_factory=lambda: self.fetcher,
            trade_dates_provider=_stub_calendar,
        )

        job_result, final = self._run_via_real_queue(
            lambda: mss.run_snapshot_job(MONDAY_ISO)
        )

        # fail-open 是设计语义：job 不抛错 → 任务 SUCCESS；
        # 快照失败只体现在摘要 status="failed"，不是任务失败。
        self.assertEqual(final.status, TaskStatus.COMPLETED)
        self.assertEqual(job_result["status"], "failed")
        self.assertEqual(job_result["trade_date"], MONDAY_ISO)
        self.assertIsNone(job_result["quality_status"])
        self.assertIsNone(job_result["completeness"])
        self.assertIn("RuntimeError", job_result["error"])
        self.assertIn("boom", job_result["error"])
        self.assertEqual(final.result, job_result)
        self.assertIsNone(self.repo.get_by_market_date("cn", MONDAY_ISO))

    def test_unparseable_trade_date_task_completes_failed_summary(self):
        from src.services.task_queue import TaskStatus

        job_result, final = self._run_via_real_queue(
            lambda: mss.run_snapshot_job("not-a-date")
        )

        self.assertEqual(final.status, TaskStatus.COMPLETED)
        self.assertEqual(job_result["status"], "failed")
        self.assertEqual(job_result["trade_date"], "not-a-date")
        self.assertIn("invalid trade_date", job_result["error"])
        self.assertIsNone(self.repo.get_by_market_date("cn", "not-a-date"))


if __name__ == "__main__":
    unittest.main()
