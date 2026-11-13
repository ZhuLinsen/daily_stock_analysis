# -*- coding: utf-8 -*-
"""API contract tests for market sentiment snapshot endpoints (issue #1939 W5).

Direct-call endpoint style (mirrors ``tests/test_analysis_api_contract.py``):
endpoint functions are invoked as plain Python callables so the assertions
cover exactly the §4 contract the endpoint itself owns (status codes, error
``error`` codes, response field sets, camelCase alias, background-task
submission parameters) without FastAPI's automatic 422 machinery.

Mandatory cases from the plan §6 Wave 5 / §5 test matrix:

- POST explicit ``trade_date`` in the future / in history -> 400
  ``invalid_target_date``; explicit == resolved target -> same effect as
  omitted (same task submission);
- POST with existing ``complete`` snapshot and ``force=false`` -> 200
  short-circuit + ``superseded_by_existing_complete=true``, no task cost;
- global trigger lock held -> 409 ``snapshot_running``;
- list ``limit=0/201`` / ``offset=-1`` -> 400; ``order`` outside enum -> 400;
- detail 404 ``snapshot_not_found`` / 400 ``invalid_date``; full response
  field set with ``payload["narrative"] is None``;
- trend invalid metric -> 400 ``invalid_metric``; ``days=0/367`` -> 400;
  empty series -> 200 with ``points: []`` + ``available_points: 0``;
  future-function assertion (rows beyond the clamped ``end_date`` never
  appear in the series);
- request body accepts camelCase alias (``tradeDate``).

DB runs on a temporary SQLite file via the Config + DatabaseManager
reset convention; the trigger target resolution clock is pinned to
2026-11-13 16:00 Asia/Shanghai so the single triggerable target is
2026-11-13 for every test.
"""

import os
import tempfile
import unittest
from contextlib import contextmanager
from datetime import date, datetime
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from starlette.responses import Response as StarletteResponse

from src.config import Config
from src.repositories.market_sentiment_repo import MarketSentimentRepository
from src.services import market_sentiment_service as mss
from src.storage import DatabaseManager

from api.v1.endpoints import market_sentiment as mse
from api.v1.router import router as v1_router

SHANGHAI = ZoneInfo("Asia/Shanghai")

# 交易日历 stub：与 W4 service 测试同款两周窗口（周一..周五）。
STUB_TRADE_DATES = [
    date(2026, 11, d) for d in (9, 10, 11, 12, 13, 16, 17, 18, 19, 20)
]
TARGET_DATE = "2026-11-13"   # 2026-11-13 16:00 上海时区解析出的唯一触发目标
FUTURE_DATE = "2026-11-20"   # 日历内的未来交易日
HISTORY_DATE = "2026-11-09"  # 日历内的历史交易日

PinnedNow = datetime(2026, 11, 13, 16, 0, tzinfo=SHANGHAI)

TREND_ENUM = [
    "advance_decline_diff",
    "turnover_mom",
    "limit_up_count",
    "failure_rate",
    "max_boards",
    "overall_promotion_rate",
    "feedback_avg_change_pct",
]


def _stub_calendar():
    return list(STUB_TRADE_DATES)


def _make_row_payload(
    trade_date,
    *,
    diff=-100,
    limit_up=5,
    max_boards=3,
    failure_rate=0.25,
    mom=1.5,
    overall=0.5,
    feedback=2.0,
    ok=True,
):
    """Minimal §3.2 payload carrying every trend metric extractor's key."""
    return {
        "schema_version": 1,
        "market": "cn",
        "trade_date": trade_date,
        "prev_trade_date": None,
        "required_groups": ["breadth", "limit_up_pool", "broken_pool",
                            "turnover", "promotion", "prev_feedback"],
        "metric_status": {
            g: ("ok" if ok else "source_error")
            for g in ("breadth", "limit_up_pool", "broken_pool",
                      "turnover", "promotion", "prev_feedback")
        },
        "narrative": None,
        "narrative_generated_at": None,
        "breadth": {"advance_decline_diff": diff if ok else None,
                    "missing_reason": None if ok else "source_error"},
        "limit_up": {"count": limit_up if ok else None,
                     "max_boards": max_boards if ok else None,
                     "missing_reason": None if ok else "source_error"},
        "broken_limit": {"failure_rate": failure_rate if ok else None,
                         "missing_reason": None if ok else "source_error"},
        "turnover": {"total_amount_yi": 120.0,
                     "mom_change_pct": mom if ok else None,
                     "missing_reason": None if ok else "source_error"},
        "promotion": {"overall": {"rate": overall if ok else None},
                      "missing_reason": None if ok else "source_error"},
        "yesterday_limit_feedback": {"avg_change_pct": feedback if ok else None,
                                     "missing_reason": None if ok else "source_error"},
    }


def _make_trace(trade_date=TARGET_DATE):
    return [
        {"metric_group": "breadth", "provider": "akshare", "api": "seed",
         "params": {"date": trade_date}, "status": "ok", "elapsed_ms": 1,
         "error": None, "fetched_at": f"{trade_date}T16:00:00"},
    ]


class _StubFetcher:
    """Never called in contract tests; guards accidental network attempts."""

    def fetch_all(self, trade_date, prev_trade_date=None):
        raise AssertionError("contract tests must not fetch from network")


class _DbTestCase(unittest.TestCase):
    """Tmp-DB + env restore + trigger-lock cleanup convention (W2-W4 style)."""

    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(
            self._temp_dir.name, "test_market_sentiment_api.db"
        )
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
        self.service = mss.MarketSentimentService(
            repo=self.repo,
            fetcher_factory=_StubFetcher,
            trade_dates_provider=_stub_calendar,
        )

    def tearDown(self):
        mss._release_trigger_lock()
        mss._DEFAULT_SERVICE = None  # 防跨用例单例泄漏（持死 DB 引用）
        Config._instance = None
        DatabaseManager.reset_instance()
        for key, value in self._original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._temp_dir.cleanup()

    def _seed_row(self, trade_date, **payload_kwargs):
        payload = _make_row_payload(trade_date, **payload_kwargs)
        return self.repo.save_snapshot(
            payload, _make_trace(trade_date), market="cn", trade_date=trade_date
        )

    @staticmethod
    def _assert_http_error(exc, status_code, error_code):
        assert isinstance(exc, HTTPException), exc
        assert exc.status_code == status_code, exc.status_code
        assert exc.detail["error"] == error_code, exc.detail

    def _expect_http_error(self, fn, *args, **kwargs):
        """Run ``fn`` and return the raised HTTPException for code assertions."""
        with self.assertRaises(HTTPException) as ctx:
            fn(*args, **kwargs)
        return ctx.exception


# ---------------------------------------------------------------------------
# 0. API surface: four endpoint functions + router mounting (§4)
# ---------------------------------------------------------------------------

class TestApiSurface(unittest.TestCase):

    def test_four_endpoint_functions_expose_contract_signatures(self):
        import inspect

        expected = {
            "trigger_market_sentiment_snapshot": ["request", "response"],
            "list_market_sentiment_snapshots": ["limit", "offset", "order"],
            "get_market_sentiment_snapshot_detail": ["trade_date"],
            "get_market_sentiment_trend": ["metric", "days", "start_date", "end_date"],
        }
        for name, params in expected.items():
            func = getattr(mse, name, None)
            self.assertTrue(callable(func), f"missing endpoint: {name}")
            self.assertEqual(
                list(inspect.signature(func).parameters),
                params,
                f"{name} 参数表必须与 §4 契约一致",
            )

    def test_router_mounts_market_sentiment_prefix(self):
        # 经 OpenAPI schema 枚举扁平化路由（_IncludedRouter 惰性代理不暴露 path）
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(v1_router, prefix="/api/v1")
        paths = app.openapi()["paths"]
        expected = {
            "/api/v1/market-sentiment/snapshots": {"post", "get"},
            "/api/v1/market-sentiment/snapshots/{trade_date}": {"get"},
            "/api/v1/market-sentiment/trend": {"get"},
        }
        for path, methods in expected.items():
            self.assertIn(path, paths, f"router 缺少 {path}")
            self.assertTrue(
                methods.issubset(set(paths[path])),
                f"{path} 缺少方法: {methods - set(paths[path])}",
            )

    def test_trend_metric_enum_matches_plan(self):
        self.assertEqual(sorted(mss.TREND_METRICS), sorted(TREND_ENUM))


# ---------------------------------------------------------------------------
# 1. POST /snapshots — trigger (§4.1)
# ---------------------------------------------------------------------------

class TestTriggerEndpoint(_DbTestCase):

    def _post(self, body=None):
        request = None
        if body is not None:
            request = mse.MarketSentimentTriggerRequest.model_validate(body)
        response = StarletteResponse()
        model = mse.trigger_market_sentiment_snapshot(
            request=request, response=response
        )
        return model, response

    @contextmanager
    def _wired_trigger(self):
        """Pin clock/target, wire stub service + capturing task queue."""
        queue = mock.MagicMock()
        state = {"task_fn": None, "kwargs": None}

        def _capture(task_fn, **kwargs):
            state["task_fn"] = task_fn
            state["kwargs"] = kwargs
            return SimpleNamespace(task_id=kwargs.get("task_id", "task-1"))

        queue.submit_background_task.side_effect = _capture
        with mock.patch.object(
            mss, "_now_shanghai", return_value=PinnedNow
        ), mock.patch.object(
            mss, "_DEFAULT_SERVICE", self.service
        ), mock.patch.object(
            mse, "get_task_queue", return_value=queue
        ):
            yield queue, state

    def test_explicit_future_trade_date_rejected(self):
        with self._wired_trigger():
            exc = self._expect_http_error(
                self._post, {"trade_date": FUTURE_DATE}
            )
            self._assert_http_error(exc, 400, "invalid_target_date")
            self.assertIn(TARGET_DATE, exc.detail["message"])

    def test_explicit_history_trade_date_rejected(self):
        with self._wired_trigger():
            exc = self._expect_http_error(
                self._post, {"trade_date": HISTORY_DATE}
            )
            self._assert_http_error(exc, 400, "invalid_target_date")

    def test_malformed_trade_date_rejected_as_invalid_date(self):
        with self._wired_trigger() as (queue, _state):
            exc = self._expect_http_error(
                self._post, {"trade_date": "not-a-date"}
            )
            self._assert_http_error(exc, 400, "invalid_date")
            queue.submit_background_task.assert_not_called()

    def test_explicit_target_date_same_effect_as_omitted(self):
        # 缺省触发
        with self._wired_trigger() as (_queue, state):
            model_default, _response = self._post()
            self.assertEqual(model_default.status, "accepted")
            self.assertEqual(model_default.trade_date, TARGET_DATE)
            self.assertIsNotNone(model_default.task_id)
            self.assertFalse(model_default.superseded_by_existing_complete)
        mss._release_trigger_lock()

        # 显式触发解析目标日（snake_case 与 camelCase alias 各一遍）
        for body in ({"trade_date": TARGET_DATE}, {"tradeDate": TARGET_DATE}):
            with self._wired_trigger() as (_queue, state):
                model_explicit, _response = self._post(body)
                self.assertEqual(model_explicit.status, "accepted")
                self.assertEqual(model_explicit.trade_date, TARGET_DATE)
                self.assertIsNotNone(state["task_fn"])
                # 必须打补丁后再执行提交体：绝不触发真实抓取/默认单例
                with mock.patch.object(mse, "run_snapshot_job") as run_job:
                    state["task_fn"]()
                run_job.assert_called_once_with(TARGET_DATE)
            mss._release_trigger_lock()

        self.assertEqual(model_explicit.trade_date, model_default.trade_date)

    def test_submitted_background_task_targets_resolved_trade_date(self):
        with self._wired_trigger() as (_queue, state):
            model, _response = self._post()
            self.assertEqual(model.status, "accepted")
            submitted_task_id = state["kwargs"].get("task_id")
            self.assertEqual(submitted_task_id, model.task_id)
            with mock.patch.object(
                mse, "run_snapshot_job"
            ) as run_snapshot_job:
                state["task_fn"]()
            run_snapshot_job.assert_called_once_with(TARGET_DATE)

    def test_existing_complete_short_circuits_with_200(self):
        self._seed_row(TARGET_DATE)
        with self._wired_trigger() as (queue, _state):
            model, response = self._post()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(model.status, "short_circuited")
            self.assertTrue(model.superseded_by_existing_complete)
            self.assertEqual(model.trade_date, TARGET_DATE)
            self.assertIsNone(model.task_id)
            self.assertIsNotNone(model.existing_snapshot)
            self.assertEqual(model.existing_snapshot.trade_date, TARGET_DATE)
            self.assertEqual(model.existing_snapshot.quality_status, "complete")
            queue.submit_background_task.assert_not_called()

    def test_force_true_bypasses_complete_short_circuit(self):
        self._seed_row(TARGET_DATE)
        with self._wired_trigger() as (queue, _state):
            model, response = self._post({"force": True})
            self.assertEqual(model.status, "accepted")
            self.assertFalse(model.superseded_by_existing_complete)
            queue.submit_background_task.assert_called_once()

    def test_held_trigger_lock_returns_409_snapshot_running(self):
        token = mss._try_acquire_trigger_lock(TARGET_DATE)
        self.assertIsNotNone(token)
        with self._wired_trigger():
            exc = self._expect_http_error(self._post)
            self._assert_http_error(exc, 409, "snapshot_running")

    def test_submit_failure_maps_to_500_submit_failed_and_releases_lock(self):
        with mock.patch.object(
            mss, "_now_shanghai", return_value=PinnedNow
        ), mock.patch.object(
            mss, "_DEFAULT_SERVICE", self.service
        ), mock.patch.object(
            mse, "get_task_queue", side_effect=RuntimeError("queue down")
        ):
            exc = self._expect_http_error(self._post)
            self._assert_http_error(exc, 500, "submit_failed")
        # 入队失败不得泄漏全局锁：后续触发可以重新拿到锁
        token = mss._try_acquire_trigger_lock(TARGET_DATE)
        self.assertIsNotNone(token)
        mss._release_trigger_lock()

    def test_calendar_unavailable_maps_to_503(self):
        # 只有未注入 trade_dates_provider 的服务才走 mss._load_trade_dates
        # （stub 过日历的服务打桩不到该函数）；日历先于抓取失败，无需 fetcher。
        calendarless = mss.MarketSentimentService(repo=self.repo)
        with mock.patch.object(
            mss, "_DEFAULT_SERVICE", calendarless
        ), mock.patch.object(
            mss, "_load_trade_dates",
            side_effect=mss.TradeCalendarUnavailableError("calendar down"),
        ), mock.patch.object(
            mse, "get_task_queue", return_value=mock.MagicMock()
        ):
            exc = self._expect_http_error(self._post)
            self._assert_http_error(exc, 503, "trade_calendar_unavailable")


# ---------------------------------------------------------------------------
# 2. GET /snapshots — date list (§4.2)
# ---------------------------------------------------------------------------

class TestListEndpoint(_DbTestCase):

    def test_limit_zero_rejected(self):
        exc = self._expect_http_error(mse.list_market_sentiment_snapshots, 0)
        self._assert_http_error(exc, 400, "invalid_limit")

    def test_limit_above_200_rejected(self):
        exc = self._expect_http_error(mse.list_market_sentiment_snapshots, 201)
        self._assert_http_error(exc, 400, "invalid_limit")

    def test_negative_offset_rejected(self):
        exc = self._expect_http_error(
            mse.list_market_sentiment_snapshots, 30, -1
        )
        self._assert_http_error(exc, 400, "invalid_offset")

    def test_unknown_order_rejected(self):
        exc = self._expect_http_error(
            mse.list_market_sentiment_snapshots, 30, 0, "sideways"
        )
        self._assert_http_error(exc, 400, "invalid_order")

    def test_lists_real_snapshots_desc_with_total(self):
        for trade_date in ("2026-11-11", "2026-11-12", "2026-11-13"):
            self._seed_row(trade_date)

        model = mse.list_market_sentiment_snapshots()
        self.assertEqual(model.total, 3)
        self.assertEqual(
            [item.trade_date for item in model.items],
            ["2026-11-13", "2026-11-12", "2026-11-11"],
        )
        first = model.items[0]
        self.assertEqual(first.quality_status, "complete")
        self.assertEqual(first.completeness, 1.0)
        self.assertIsNotNone(first.created_at)
        self.assertIsNotNone(first.updated_at)

        paged = mse.list_market_sentiment_snapshots(limit=1, offset=1)
        self.assertEqual(paged.total, 3)
        self.assertEqual(
            [item.trade_date for item in paged.items], ["2026-11-12"]
        )

        asc = mse.list_market_sentiment_snapshots(order="asc")
        self.assertEqual(
            [item.trade_date for item in asc.items],
            ["2026-11-11", "2026-11-12", "2026-11-13"],
        )

    def test_empty_list_returns_empty_items_with_zero_total(self):
        model = mse.list_market_sentiment_snapshots()
        self.assertEqual(model.items, [])
        self.assertEqual(model.total, 0)


# ---------------------------------------------------------------------------
# 3. GET /snapshots/{trade_date} — detail (§4.3)
# ---------------------------------------------------------------------------

class TestDetailEndpoint(_DbTestCase):

    def test_detail_returns_full_payload_and_null_narrative(self):
        self._seed_row(TARGET_DATE)
        model = mse.get_market_sentiment_snapshot_detail(TARGET_DATE)
        self.assertEqual(model.trade_date, TARGET_DATE)
        self.assertEqual(model.market, "cn")
        self.assertEqual(model.quality_status, "complete")
        self.assertEqual(model.completeness, 1.0)
        # 响应字段齐全（计划 §5 api_contract 行）
        self.assertIn("narrative", model.payload)
        self.assertIsNone(model.payload["narrative"])
        self.assertIsNone(model.payload["narrative_generated_at"])
        self.assertIn("breadth", model.payload)
        self.assertEqual(
            [entry["metric_group"] for entry in model.provider_trace],
            ["breadth"],
        )
        self.assertIsNotNone(model.created_at)
        self.assertIsNotNone(model.updated_at)

    def test_missing_snapshot_returns_404_snapshot_not_found(self):
        exc = self._expect_http_error(
            mse.get_market_sentiment_snapshot_detail, "2026-11-12"
        )
        self._assert_http_error(exc, 404, "snapshot_not_found")

    def test_malformed_date_returns_400_invalid_date(self):
        exc = self._expect_http_error(
            mse.get_market_sentiment_snapshot_detail, "2026/11/13"
        )
        self._assert_http_error(exc, 400, "invalid_date")


# ---------------------------------------------------------------------------
# 4. GET /trend — metric series (§4.4)
# ---------------------------------------------------------------------------

class TestTrendEndpoint(_DbTestCase):

    def test_invalid_metric_rejected(self):
        exc = self._expect_http_error(
            mse.get_market_sentiment_trend, "not_a_metric"
        )
        self._assert_http_error(exc, 400, "invalid_metric")

    def test_days_bounds_enforced(self):
        for days in (0, 367, -5):
            exc = self._expect_http_error(
                mse.get_market_sentiment_trend,
                "advance_decline_diff", days,
            )
            self._assert_http_error(exc, 400, "invalid_days")

    def test_malformed_range_dates_rejected(self):
        exc = self._expect_http_error(
            mse.get_market_sentiment_trend,
            "advance_decline_diff", None, "2026-11-99",
        )
        self._assert_http_error(exc, 400, "invalid_date")

    def test_reversed_range_rejected(self):
        exc = self._expect_http_error(
            mse.get_market_sentiment_trend,
            "advance_decline_diff", None, "2026-11-13", "2026-11-12",
        )
        self._assert_http_error(exc, 400, "invalid_date_range")

    def test_empty_series_returns_200_with_zero_points(self):
        model = mse.get_market_sentiment_trend("advance_decline_diff", 30)
        self.assertEqual(model.metric, "advance_decline_diff")
        self.assertEqual(model.points, [])
        self.assertEqual(model.available_points, 0)

    def test_explicit_end_date_excludes_future_rows(self):
        # 未来函数：预置 trade_date > end_date 的行（11-18）不得出现
        self._seed_row("2026-11-12", diff=-100)
        self._seed_row("2026-11-16", diff=-80)
        self._seed_row("2026-11-18", diff=-50)

        model = mse.get_market_sentiment_trend(
            "advance_decline_diff", None, "2026-11-09", "2026-11-16"
        )
        self.assertEqual(model.available_points, 2)
        self.assertEqual(
            [(p.trade_date, p.value) for p in model.points],
            [("2026-11-12", -100.0), ("2026-11-16", -80.0)],
        )
        self.assertTrue(all(p.quality_status == "complete" for p in model.points))

    def test_days_mode_clamps_end_to_min_today_latest_snapshot(self):
        # 预置行到 11-18，但当前时钟钉在 11-17：clamp end=11-17，11-18 不出现
        self._seed_row("2026-11-12", limit_up=5)
        self._seed_row("2026-11-16", limit_up=7)
        self._seed_row("2026-11-18", limit_up=9)
        clamped_now = datetime(2026, 11, 17, 16, 0, tzinfo=SHANGHAI)
        with mock.patch.object(mss, "_now_shanghai", return_value=clamped_now):
            model = mse.get_market_sentiment_trend("limit_up_count", 30)
        self.assertEqual(model.available_points, 2)
        self.assertEqual(
            [p.trade_date for p in model.points], ["2026-11-12", "2026-11-16"]
        )
        self.assertEqual([p.value for p in model.points], [5.0, 7.0])

    def test_all_enum_metrics_accepted_on_seeded_data(self):
        self._seed_row(TARGET_DATE)
        for metric in TREND_ENUM:
            model = mse.get_market_sentiment_trend(metric, None, None, TARGET_DATE)
            self.assertEqual(model.metric, metric)
            self.assertEqual(model.available_points, 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
