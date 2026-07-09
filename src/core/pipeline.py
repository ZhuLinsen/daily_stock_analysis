# -*- coding: utf-8 -*-
"""
===================================
台美股自選股智慧分析系統 - 核心分析流水線
===================================

職責：
1. 管理整個分析流程
2. 協調資料獲取、儲存、搜尋、分析、通知等模組
3. 實現併發控制和異常處理
4. 提供股票分析的核心功能
"""

import logging
import threading
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple, Callable

import pandas as pd

from src.config import FUNDAMENTAL_STAGE_TIMEOUT_SECONDS_DEFAULT, get_config, Config
from src.storage import get_db
from data_provider import DataFetcherManager
from data_provider.base import normalize_stock_code
from data_provider.realtime_types import ChipDistribution
from src.analyzer import (
    GeminiAnalyzer,
    AnalysisResult,
    fill_price_position_if_needed,
    normalize_chip_structure_availability,
    stabilize_decision_with_structure,
)
from src.notification import NotificationService, NotificationChannel
from src.report_language import (
    infer_decision_type_from_advice,
    localize_confidence_level,
    localize_operation_advice,
    localize_trend_prediction,
    normalize_report_language,
)
from src.search_service import (
    DEFAULT_NEWS_CONTEXT_MAX_TOTAL_CHARS,
    SearchService,
    cap_news_context,
)
from src.analysis_context_pack_prompt import format_analysis_context_pack_prompt_section
from src.analysis_context_pack_overview import render_analysis_context_pack_overview
from src.market_phase_summary import MARKET_PHASE_SUMMARY_KEY, render_market_phase_summary
from src.phase_decision_guardrail import apply_phase_decision_guardrails
from src.services.social_sentiment_service import SocialSentimentService
from src.services.symbol_universe import resolve_report_instrument_type
from src.services.analysis_context_builder import (
    AnalysisContextBuilder,
    PipelineAnalysisArtifacts,
)
from src.services.run_diagnostics import (
    activate_run_diagnostic_context,
    current_diagnostic_snapshot,
    get_current_diagnostic_context,
    record_history_run,
    record_llm_run,
    record_notification_run,
    reset_run_diagnostic_context,
    sanitize_diagnostic_text,
)
from src.enums import ReportType
from src.stock_analyzer import StockTrendAnalyzer, TrendAnalysisResult
from src.core.trading_calendar import (
    build_market_phase_context,
    get_effective_trading_date,
    get_market_for_stock,
    get_market_now,
    is_market_open,
)
from data_provider.us_index_mapping import is_us_stock_code
from bot.models import BotMessage


logger = logging.getLogger(__name__)


def _cap_news_context(
    text: Optional[str],
    max_chars: Optional[int] = DEFAULT_NEWS_CONTEXT_MAX_TOTAL_CHARS,
) -> Optional[str]:
    """Compatibility wrapper for callers that imported the old private helper."""
    return cap_news_context(text, max_chars=max_chars)


# 防禦性 guard：當例項繞過 __init__（如測試中 __new__）構造時，
# double-check 初始化 _single_stock_notify_lock 仍然執行緒安全。
_SINGLE_STOCK_NOTIFY_LOCK_INIT_GUARD = threading.Lock()


class StockAnalysisPipeline:
    """
    股票分析主流程排程器
    
    職責：
    1. 管理整個分析流程
    2. 協調資料獲取、儲存、搜尋、分析、通知等模組
    3. 實現併發控制和異常處理
    """
    
    def __init__(
        self,
        config: Optional[Config] = None,
        max_workers: Optional[int] = None,
        source_message: Optional[BotMessage] = None,
        query_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        query_source: Optional[str] = None,
        save_context_snapshot: Optional[bool] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        analysis_skills: Optional[List[str]] = None,
        analysis_phase: str = "auto",
    ):
        """
        初始化排程器
        
        Args:
            config: 配置物件（可選，預設使用全域性配置）
            max_workers: 最大併發執行緒數（可選，預設從配置讀取）
        """
        self.config = config or get_config()
        self.max_workers = max_workers or self.config.max_workers
        self.source_message = source_message
        self.query_id = query_id
        self.trace_id = trace_id or query_id
        self.query_source = self._resolve_query_source(query_source)
        self.save_context_snapshot = (
            self.config.save_context_snapshot if save_context_snapshot is None else save_context_snapshot
        )
        self.progress_callback = progress_callback
        self.analysis_skills = list(analysis_skills) if analysis_skills is not None else None
        self.analysis_phase = analysis_phase or "auto"
        
        # 初始化各模組
        self.db = get_db()
        self.fetcher_manager = DataFetcherManager()
        # 不再單獨建立 akshare_fetcher，統一使用 fetcher_manager 獲取增強資料
        self.trend_analyzer = StockTrendAnalyzer()  # 技術分析器
        self.analyzer = GeminiAnalyzer(config=self.config, skills=self.analysis_skills)
        self.notifier = NotificationService(source_message=source_message)
        self._single_stock_notify_lock = threading.Lock()
        
        # 初始化搜尋服務（可選，初始化失敗不應阻斷主分析流程）
        try:
            self.search_service = SearchService(
                bocha_keys=self.config.bocha_api_keys,
                tavily_keys=self.config.tavily_api_keys,
                anspire_keys=self.config.anspire_api_keys,
                brave_keys=self.config.brave_api_keys,
                serpapi_keys=self.config.serpapi_keys,
                minimax_keys=self.config.minimax_api_keys,
                searxng_base_urls=self.config.searxng_base_urls,
                searxng_public_instances_enabled=self.config.searxng_public_instances_enabled,
                news_max_age_days=self.config.news_max_age_days,
                news_strategy_profile=getattr(self.config, "news_strategy_profile", "short"),
            )
        except Exception as exc:
            logger.warning("搜尋服務初始化失敗，將以無搜尋模式執行: %s", exc, exc_info=True)
            self.search_service = None
        
        logger.info(f"排程器初始化完成，最大併發數: {self.max_workers}")
        logger.info("已啟用技術分析引擎（均線/趨勢/量價指標）")
        # 列印實時行情/籌碼配置狀態
        if self.config.enable_realtime_quote:
            logger.info(f"實時行情已啟用 (優先順序: {self.config.realtime_source_priority})")
        else:
            logger.info("實時行情已禁用，將使用歷史收盤價")
        if self.config.enable_chip_distribution:
            logger.info("籌碼分佈分析已啟用")
        else:
            logger.info("籌碼分佈分析已禁用")
        if self.search_service is None:
            logger.warning("搜尋服務未啟用（初始化失敗或依賴缺失）")
        elif self.search_service.is_available:
            logger.info("搜尋服務已啟用")
        else:
            logger.warning("搜尋服務未啟用（未配置搜尋能力）")

        # 初始化社交輿情服務（僅美股，可選）
        try:
            self.social_sentiment_service = SocialSentimentService(
                api_key=self.config.social_sentiment_api_key,
                api_url=self.config.social_sentiment_api_url,
            )
            if self.social_sentiment_service.is_available:
                logger.info("Social sentiment service enabled (Reddit/X/Polymarket, US stocks only)")
        except Exception as exc:
            logger.warning(
                "社交輿情服務初始化失敗，將跳過輿情分析: %s",
                exc,
                exc_info=True,
            )
            self.social_sentiment_service = None

    def _emit_progress(self, progress: int, message: str, *, stage: Optional[str] = None, stage_label: Optional[str] = None) -> None:
        """Best-effort bridge from pipeline stages to task SSE progress."""
        callback = getattr(self, "progress_callback", None)
        if callback is None:
            return
        try:
            if stage:
                logger.debug("[pipeline] emit stage=%s label=%s", stage, stage_label)
            callback(progress, message, stage=stage, stage_label=stage_label)
        except TypeError:
            try:
                callback(progress, message)
            except Exception as exc:
                query_id = getattr(self, "query_id", None)
                logger.warning(
                    "[pipeline] progress callback failed (fallback): %s (progress=%s, message=%r, query_id=%s)",
                    exc, progress, message, query_id,
                    extra={"progress": progress, "progress_message": message, "query_id": query_id},
                )
        except Exception as exc:
            query_id = getattr(self, "query_id", None)
            logger.warning(
                "[pipeline] progress callback failed: %s (progress=%s, message=%r, query_id=%s)",
                exc, progress, message, query_id,
                extra={"progress": progress, "progress_message": message, "query_id": query_id},
            )

    def fetch_and_save_stock_data(
        self, 
        code: str,
        force_refresh: bool = False,
        current_time: Optional[datetime] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        獲取並儲存單隻股票資料
        
        斷點續傳邏輯：
        1. 檢查資料庫是否已有最新可複用交易日資料
        2. 如果有且不強制重新整理，則跳過網路請求
        3. 否則從資料來源獲取並儲存
        
        Args:
            code: 股票程式碼
            force_refresh: 是否強制重新整理（忽略本地快取）
            current_time: 本輪執行凍結的參考時間，用於統一斷點續傳目標交易日判斷
            
        Returns:
            Tuple[是否成功, 錯誤資訊]
        """
        stock_name = code
        try:
            # 首先獲取股票名稱
            stock_name = self.fetcher_manager.get_stock_name(code, allow_realtime=False)

            target_date = self._resolve_resume_target_date(
                code, current_time=current_time
            )

            # 斷點續傳檢查：如果最新可複用交易日的資料已存在，則跳過
            if not force_refresh and self.db.has_today_data(code, target_date):
                logger.info(
                    f"{stock_name}({code}) {target_date} 資料已存在，跳過獲取（斷點續傳）"
                )
                return True, None

            # 從資料來源獲取資料
            logger.info(f"{stock_name}({code}) 開始從資料來源獲取資料...")
            data_fetch_timeout = getattr(getattr(self, 'config', None), 'data_fetch_timeout_seconds', 20) or 20
            import concurrent.futures
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            try:
                future = executor.submit(
                    self.fetcher_manager.get_daily_data, code, days=10
                )
                df, source_name = future.result(timeout=data_fetch_timeout)
            except concurrent.futures.TimeoutError:
                logger.warning(
                    f"{stock_name}({code}) 資料獲取超時 ({data_fetch_timeout}s)"
                )
                executor.shutdown(wait=False, cancel_futures=True)
                return False, f"資料獲取超時 ({data_fetch_timeout}s)"
            except Exception as e:
                logger.error(f"{stock_name}({code}) 資料獲取異常: {e}")
                executor.shutdown(wait=False, cancel_futures=True)
                return False, str(e)
            else:
                executor.shutdown(wait=False)

            if df is None or df.empty:
                return False, "獲取資料為空"

            # 儲存到資料庫
            saved_count = self.db.save_daily_data(df, code, source_name)
            logger.info(f"{stock_name}({code}) 資料儲存成功（來源: {source_name}，新增 {saved_count} 條）")

            return True, None

        except Exception as e:
            error_msg = f"獲取/儲存資料失敗: {str(e)}"
            logger.error(f"{stock_name}({code}) {error_msg}")
            return False, error_msg
    
    def analyze_stock(
        self,
        code: str,
        report_type: ReportType,
        query_id: str,
        current_time: Optional[datetime] = None,
    ) -> Optional[AnalysisResult]:
        """
        分析單隻股票（增強版：含量比、換手率、多維度情報）
        
        流程：
        1. 獲取實時行情（量比、換手率）- 透過 DataFetcherManager 自動故障切換
        2. 進行趨勢分析（基於交易理念）
        3. 多維度情報搜尋（最新訊息+風險排查+業績預期）
        4. 從資料庫獲取分析上下文
        5. 呼叫 AI 進行綜合分析
        
        Args:
            query_id: 查詢鏈路關聯 id
            code: 股票程式碼
            report_type: 報告型別
            current_time: 本輪執行凍結的參考時間，用於統一市場階段上下文
            
        Returns:
            AnalysisResult 或 None（如果分析失敗）
        """
        stock_name = code
        try:
            market = get_market_for_stock(normalize_stock_code(code))
            market_phase_context = build_market_phase_context(
                market=market,
                current_time=current_time,
                trigger_source=self.query_source,
                analysis_phase=getattr(self, "analysis_phase", "auto"),
            )
            market_phase_context_dict = market_phase_context.to_dict()
            market_phase_summary = render_market_phase_summary(market_phase_context_dict)

            self._emit_progress(18, f"{code}：正在獲取行情資料", stage="data_fetching", stage_label="正在擷取股價與基本資料")
            # 獲取股票名稱（先走輕量名稱路徑，後續若 realtime_quote 有 name 再覆蓋）
            stock_name = self.fetcher_manager.get_stock_name(code, allow_realtime=False)

            # Step 1: 獲取實時行情（量比、換手率等）- 使用統一入口，自動故障切換
            realtime_quote = None
            try:
                if self.config.enable_realtime_quote:
                    realtime_quote = self.fetcher_manager.get_realtime_quote(code, log_final_failure=False)
                    if realtime_quote:
                        # 使用實時行情返回的真實股票名稱
                        if realtime_quote.name:
                            stock_name = realtime_quote.name
                        # 相容不同資料來源的欄位（有些資料來源可能沒有 volume_ratio）
                        volume_ratio = getattr(realtime_quote, 'volume_ratio', None)
                        turnover_rate = getattr(realtime_quote, 'turnover_rate', None)
                        logger.info(f"{stock_name}({code}) 實時行情: 價格={realtime_quote.price}, "
                                  f"量比={volume_ratio}, 換手率={turnover_rate}% "
                                  f"(來源: {realtime_quote.source.value if hasattr(realtime_quote, 'source') else 'unknown'})")
                    else:
                        logger.warning(f"{stock_name}({code}) 所有實時行情資料來源均不可用，已降級為歷史收盤價繼續分析")
                else:
                    logger.info(f"{stock_name}({code}) 實時行情已禁用，使用歷史收盤價繼續分析")
            except Exception as e:
                logger.warning(f"{stock_name}({code}) 實時行情鏈路異常，已降級為歷史收盤價繼續分析: {e}")

            # 如果還是沒有名稱，使用程式碼作為名稱
            if not stock_name:
                stock_name = f'股票{code}'

            # Route B TW/US analysis no longer fetches chip-distribution data.
            chip_data = None

            # If agent mode is explicitly enabled, or specific agent skills are configured, use the Agent analysis pipeline.
            # NOTE: use config.agent_mode (explicit opt-in) instead of
            # config.is_agent_available() so that users who only configured an
            # API Key for the traditional analysis path are not silently
            # switched to Agent mode (which is slower and more expensive).
            use_agent = getattr(self.config, 'agent_mode', False)
            if not use_agent:
                if self.analysis_skills:
                    use_agent = True
                    logger.info(f"{stock_name}({code}) Auto-enabled agent mode due to request skills: {self.analysis_skills}")
            if not use_agent:
                # Auto-enable agent mode when specific skills are configured (e.g., scheduled task with strategy)
                configured_skills = getattr(self.config, 'agent_skills', [])
                if configured_skills and configured_skills != ['all']:
                    use_agent = True
                    logger.info(f"{stock_name}({code}) Auto-enabled agent mode due to configured skills: {configured_skills}")

            self._emit_progress(32, f"{stock_name}：正在聚合基本面與趨勢資料")

            # Step 2.5: 基本面能力聚合（統一入口，異常降級）
            # - 失敗時返回 partial/failed，不影響既有技術面/新聞鏈路
            # - 關閉開關時仍返回 not_supported 結構
            fundamental_context = None
            try:
                fundamental_context = self.fetcher_manager.get_fundamental_context(
                    code,
                    budget_seconds=getattr(
                        self.config,
                        'fundamental_stage_timeout_seconds',
                        FUNDAMENTAL_STAGE_TIMEOUT_SECONDS_DEFAULT,
                    ),
                )
            except Exception as e:
                logger.warning(f"{stock_name}({code}) 基本面聚合失敗: {e}")
                fundamental_context = self.fetcher_manager.build_failed_fundamental_context(code, str(e))

            fundamental_context = self._attach_belong_boards_to_fundamental_context(
                code,
                fundamental_context,
            )

            # P0: write-only snapshot, fail-open, no read dependency on this table.
            try:
                self.db.save_fundamental_snapshot(
                    query_id=query_id,
                    code=code,
                    payload=fundamental_context,
                    source_chain=fundamental_context.get("source_chain", []),
                    coverage=fundamental_context.get("coverage", {}),
                )
            except Exception as e:
                logger.debug(f"{stock_name}({code}) 基本面快照寫入失敗: {e}")

            # Step 3: 趨勢分析（基於交易理念）— 在 Agent 分支之前執行，供兩條路徑共用
            trend_result: Optional[TrendAnalysisResult] = None
            try:
                from src.services.history_loader import get_frozen_target_date
                _mkt = get_market_for_stock(normalize_stock_code(code))
                frozen = get_frozen_target_date()
                end_date = frozen if frozen else get_market_now(_mkt).date()
                start_date = end_date - timedelta(days=89)  # ~60 trading days for MA60
                historical_bars = self.db.get_data_range(code, start_date, end_date)
                if historical_bars:
                    df = pd.DataFrame([bar.to_dict() for bar in historical_bars])
                    # Issue #234: Augment with realtime for intraday MA calculation
                    if self.config.enable_realtime_quote and realtime_quote:
                        df = self._augment_historical_with_realtime(df, realtime_quote, code)
                    trend_result = self.trend_analyzer.analyze(df, code)
                    logger.info(f"{stock_name}({code}) 趨勢分析: {trend_result.trend_status.value}, "
                              f"買進訊號={trend_result.buy_signal.value}, 評分={trend_result.signal_score}")
            except Exception as e:
                logger.warning(f"{stock_name}({code}) 趨勢分析失敗: {e}", exc_info=True)

            if use_agent:
                logger.info(f"{stock_name}({code}) 啟用 Agent 模式進行分析")
                self._emit_progress(58, f"{stock_name}：正在切換 Agent 分析鏈路")
                return self._analyze_with_agent(
                    code,
                    report_type,
                    query_id,
                    stock_name,
                    realtime_quote,
                    chip_data,
                    fundamental_context,
                    trend_result,
                    market_phase_context=market_phase_context_dict,
                    market_phase_summary=market_phase_summary,
                )

            # Step 4: 多維度情報搜尋（最新訊息+風險排查+業績預期）
            news_context = None
            news_result_count: Optional[int] = None
            news_search_diagnostics: Optional[Dict[str, Any]] = None
            self._emit_progress(46, f"{stock_name}：正在檢索新聞與輿情", stage="optional_context", stage_label="正在整理新聞與延伸資料")
            if self.search_service is not None and self.search_service.is_available:
                logger.info(f"{stock_name}({code}) 開始多維度情報搜尋...")

                import concurrent.futures
                search_budget = getattr(self.config, 'search_total_timeout_seconds', 8)
                executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                try:
                    future = executor.submit(
                        self.search_service.search_comprehensive_intel,
                        stock_code=code,
                        stock_name=stock_name,
                        max_searches=5,
                    )
                    intel_results = future.result(timeout=search_budget)
                except concurrent.futures.TimeoutError:
                    logger.warning(
                        f"{stock_name}({code}) 情報搜尋超時 ({search_budget}s)，降級為無新聞模式"
                    )
                    executor.shutdown(wait=False, cancel_futures=True)
                    intel_results = None
                except Exception as e:
                    logger.warning(f"{stock_name}({code}) 情報搜尋異常: {e}")
                    executor.shutdown(wait=False, cancel_futures=True)
                    intel_results = None
                else:
                    executor.shutdown(wait=False)

                # 格式化情報報告
                if intel_results:
                    news_context = self.search_service.format_intel_report(intel_results, stock_name)
                    total_results = sum(
                        len(r.results) for r in intel_results.values() if r.success
                    )
                    latest_news_response = intel_results.get("latest_news")
                    if latest_news_response is not None:
                        response_diagnostics = getattr(latest_news_response, "diagnostics", None)
                        if isinstance(response_diagnostics, dict):
                            search_diagnostics = response_diagnostics.get("news_search")
                            if isinstance(search_diagnostics, dict):
                                news_search_diagnostics = search_diagnostics
                    news_result_count = total_results
                    logger.info(f"{stock_name}({code}) 情報搜尋完成: 共 {total_results} 條結果")
                    logger.debug(f"{stock_name}({code}) 情報搜尋結果:\n{news_context}")

                    # 儲存新聞情報到資料庫（用於後續覆盤與查詢）
                    try:
                        query_context = self._build_query_context(query_id=query_id)
                        for dim_name, response in intel_results.items():
                            if response and response.success and response.results:
                                self.db.save_news_intel(
                                    code=code,
                                    name=stock_name,
                                    dimension=dim_name,
                                    query=response.query,
                                    response=response,
                                    query_context=query_context
                                )
                    except Exception as e:
                        logger.warning(f"{stock_name}({code}) 儲存新聞情報失敗: {e}")
            else:
                logger.info(f"{stock_name}({code}) 搜尋服務不可用，跳過情報搜尋")

            # Step 4.5: Social sentiment intelligence (US stocks only)
            if self.social_sentiment_service is not None and self.social_sentiment_service.is_available and is_us_stock_code(code):
                try:
                    social_context = self.social_sentiment_service.get_social_context(code)
                    if social_context:
                        logger.info(f"{stock_name}({code}) Social sentiment data retrieved")
                        if news_context:
                            news_context = news_context + "\n\n" + social_context
                        else:
                            news_context = social_context
                except Exception as e:
                    logger.warning(f"{stock_name}({code}) Social sentiment fetch failed: {e}")

            news_context = cap_news_context(news_context)

            # Step 5: 獲取分析上下文（技術面資料）
            self._emit_progress(58, f"{stock_name}：正在整理分析上下文")
            context = self.db.get_analysis_context(code)

            if context is None:
                logger.warning(f"{stock_name}({code}) 無法獲取歷史行情資料，將僅基於新聞和實時行情分析")
                _mkt_date = get_market_now(
                    get_market_for_stock(normalize_stock_code(code))
                ).date()
                context = {
                    'code': code,
                    'stock_name': stock_name,
                    'date': _mkt_date.isoformat(),
                    'data_missing': True,
                    'today': {},
                    'yesterday': {}
                }
            
            # Step 6: 增強上下文資料（新增實時行情、籌碼、趨勢分析結果、股票名稱）
            enhanced_context = self._enhance_context(
                context, 
                realtime_quote, 
                chip_data,
                trend_result,
                stock_name,  # 傳入股票名稱
                fundamental_context,
                market_phase_context=market_phase_context_dict,
            )
            enhanced_context["market_phase_context"] = market_phase_context_dict
            
            # Step 7: 呼叫 AI 分析（傳入增強的上下文和新聞）
            report_language = normalize_report_language(getattr(self.config, "report_language", "zh"))
            (
                analysis_context_pack_summary,
                analysis_context_pack_overview,
            ) = self._build_analysis_context_pack_outputs(
                self._build_legacy_analysis_artifacts(
                    code=code,
                    stock_name=stock_name,
                    market=market,
                    phase=market_phase_context_dict,
                    context=context,
                    enhanced_context=enhanced_context,
                    realtime_quote=realtime_quote,
                    trend_result=trend_result,
                    chip_data=chip_data,
                    fundamental_context=fundamental_context,
                    news_context=news_context,
                    news_result_count=news_result_count,
                    query_id=query_id,
                ),
                report_language=report_language,
                code=code,
                query_id=query_id,
            )
            llm_progress_state = {"last_progress": 64}

            def _on_llm_stream(chars_received: int) -> None:
                dynamic_progress = min(92, 64 + min(chars_received // 80, 28))
                if dynamic_progress <= llm_progress_state["last_progress"]:
                    return
                llm_progress_state["last_progress"] = dynamic_progress
                self._emit_progress(
                    dynamic_progress,
                    f"{stock_name}：LLM 正在生成分析結果（已接收 {chars_received} 字元）",
                )

                self._emit_progress(64, f"{stock_name}：正在請求 LLM 生成報告", stage="llm_analyzing", stage_label="正在生成完整分析報告")
            llm_started_at = time.monotonic()
            try:
                result = self.analyzer.analyze(
                    enhanced_context,
                    news_context=news_context,
                    progress_callback=self._emit_progress,
                    stream_progress_callback=_on_llm_stream,
                    analysis_context_pack_summary=analysis_context_pack_summary,
                )
                llm_duration_ms = int((time.monotonic() - llm_started_at) * 1000)
                record_llm_run(
                    success=bool(result and getattr(result, "success", True)),
                    model=getattr(result, "model_used", None) if result else None,
                    call_type="analysis",
                    duration_ms=llm_duration_ms,
                    error_type=(
                        None
                        if result and getattr(result, "success", True)
                        else "AnalysisResultError"
                    ),
                    error_message=(
                        getattr(result, "error_message", None)
                        if result and not getattr(result, "success", True)
                        else ("LLM returned empty result" if result is None else None)
                    ),
                )
            except Exception as exc:
                record_llm_run(
                    success=False,
                    model=getattr(self.config, "litellm_model", None),
                    call_type="analysis",
                    duration_ms=int((time.monotonic() - llm_started_at) * 1000),
                    error_type=type(exc).__name__,
                    error_message=exc,
                )
                raise

            # Step 7.5: 填充分析時的價格資訊到 result
            if result:
                self._emit_progress(94, f"{stock_name}：正在校驗並整理分析結果")
                result.query_id = query_id
                result.instrument_type = resolve_report_instrument_type(normalize_stock_code(code))
                self._attach_valuation_fundamental_snapshot(result, code, fundamental_context)
                self._attach_exposure_and_market_risk_snapshot(result, code, fundamental_context)
                self._attach_market_fear_index_snapshot(result, code)
                self._attach_multi_period_trend_snapshot(result, code)
                realtime_data = enhanced_context.get('realtime', {})
                result.current_price = realtime_data.get('price')
                result.change_pct = realtime_data.get('change_pct')
                if result.current_price is None:
                    fallback_price, fallback_change_pct = self._fallback_quote_from_context(
                        enhanced_context
                    )
                    if fallback_price is not None:
                        result.current_price = fallback_price
                        result.change_pct = fallback_change_pct

            # Step 7.6: chip_structure fallback (Issue #589) and unavailable collapse
            if result:
                normalize_chip_structure_availability(result, chip_data)

            # Step 7.7: price_position fallback
            if result:
                fill_price_position_if_needed(result, trend_result, realtime_quote)
                stabilize_decision_with_structure(result, trend_result, fundamental_context)
                adjustments = apply_phase_decision_guardrails(
                    result,
                    market_phase_summary=market_phase_summary,
                    analysis_context_pack_overview=analysis_context_pack_overview,
                    report_language=getattr(result, "report_language", None)
                    or getattr(self.config, "report_language", "zh"),
                )
                if adjustments:
                    logger.info("[phase_decision_guardrail] Applied adjustments for %s: %s", code, adjustments)
                if isinstance(fundamental_context, dict):
                    result.fundamental_context = fundamental_context

            # Step 8: 儲存分析歷史記錄
            if result and result.success:
                try:
                    self._emit_progress(97, f"{stock_name}：正在儲存分析報告")
                    context_snapshot = self._build_context_snapshot(
                        enhanced_context=enhanced_context,
                        news_content=news_context,
                        news_result_count=news_result_count,
                        news_search_diagnostics=news_search_diagnostics,
                        realtime_quote=realtime_quote,
                        chip_data=chip_data,
                        analysis_context_pack_overview=analysis_context_pack_overview,
                        market_phase_summary=market_phase_summary,
                    )
                    result.diagnostic_context_snapshot = context_snapshot
                    saved_count = self.db.save_analysis_history(
                        result=result,
                        query_id=query_id,
                        report_type=report_type.value,
                        news_content=news_context,
                        context_snapshot=context_snapshot,
                        save_snapshot=self.save_context_snapshot
                    )
                    record_history_run(
                        report_saved=bool(saved_count),
                        metadata_saved=bool(saved_count),
                    )
                except Exception as e:
                    record_history_run(
                        report_saved=False,
                        metadata_saved=False,
                        error_message=e,
                    )
                    logger.warning(f"{stock_name}({code}) 儲存分析歷史失敗: {e}")

            return result

        except Exception as e:
            logger.error(f"{stock_name}({code}) 分析失敗: {e}")
            logger.exception(f"{stock_name}({code}) 詳細錯誤資訊:")
            return None
    
    def _enhance_context(
        self,
        context: Dict[str, Any],
        realtime_quote,
        chip_data: Optional[ChipDistribution],
        trend_result: Optional[TrendAnalysisResult],
        stock_name: str = "",
        fundamental_context: Optional[Dict[str, Any]] = None,
        market_phase_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        增強分析上下文
        
        將實時行情、趨勢分析結果、股票名稱新增到上下文中
        
        Args:
            context: 原始上下文
            realtime_quote: 實時行情資料（UnifiedRealtimeQuote 或 None）
            chip_data: 籌碼分佈資料
            trend_result: 趨勢分析結果
            stock_name: 股票名稱
            market_phase_context: 已構建的市場階段上下文，用於標記盤中 partial bar
            
        Returns:
            增強後的上下文
        """
        enhanced = context.copy()
        enhanced["report_language"] = normalize_report_language(getattr(self.config, "report_language", "zh"))
        
        # 新增股票名稱
        if stock_name:
            enhanced['stock_name'] = stock_name
        elif realtime_quote and getattr(realtime_quote, 'name', None):
            enhanced['stock_name'] = realtime_quote.name

        # 將執行時搜尋視窗透傳給 analyzer，避免與全域性配置重新讀取產生視窗不一致
        enhanced['news_window_days'] = getattr(self.search_service, "news_window_days", 3)
        
        # 新增實時行情（相容不同資料來源的欄位差異）
        if realtime_quote:
            # 使用 getattr 安全獲取欄位，缺失欄位返回 None 或預設值
            volume_ratio = getattr(realtime_quote, 'volume_ratio', None)
            quote_source = getattr(realtime_quote, 'source', None)
            quote_source_name = getattr(quote_source, 'value', quote_source)
            quote_source_name = str(quote_source_name) if quote_source_name is not None else None
            enhanced['realtime'] = {
                'name': getattr(realtime_quote, 'name', ''),
                'price': getattr(realtime_quote, 'price', None),
                'change_pct': getattr(realtime_quote, 'change_pct', None),
                'volume_ratio': volume_ratio,
                'volume_ratio_desc': self._describe_volume_ratio(volume_ratio) if volume_ratio else '無資料',
                'turnover_rate': getattr(realtime_quote, 'turnover_rate', None),
                'pe_ratio': getattr(realtime_quote, 'pe_ratio', None),
                'pb_ratio': getattr(realtime_quote, 'pb_ratio', None),
                'total_mv': getattr(realtime_quote, 'total_mv', None),
                'circ_mv': getattr(realtime_quote, 'circ_mv', None),
                'change_60d': getattr(realtime_quote, 'change_60d', None),
                'source': quote_source_name,
                'fetched_at': getattr(realtime_quote, 'fetched_at', None),
                'provider_timestamp': getattr(realtime_quote, 'provider_timestamp', None),
                'is_stale': getattr(realtime_quote, 'is_stale', None),
                'stale_seconds': getattr(realtime_quote, 'stale_seconds', None),
                'fallback_from': getattr(realtime_quote, 'fallback_from', None),
            }
            # 移除 None 值以減少上下文大小
            enhanced['realtime'] = {k: v for k, v in enhanced['realtime'].items() if v is not None}
        
        # 新增籌碼分佈
        if chip_data:
            current_price = getattr(realtime_quote, 'price', 0) if realtime_quote else 0
            enhanced['chip'] = {
                'profit_ratio': chip_data.profit_ratio,
                'avg_cost': chip_data.avg_cost,
                'concentration_90': chip_data.concentration_90,
                'concentration_70': chip_data.concentration_70,
                'chip_status': chip_data.get_chip_status(current_price or 0),
            }
        
        # 新增趨勢分析結果
        if trend_result:
            enhanced['trend_analysis'] = {
                'trend_status': trend_result.trend_status.value,
                'ma_alignment': trend_result.ma_alignment,
                'trend_strength': trend_result.trend_strength,
                'bias_ma5': trend_result.bias_ma5,
                'bias_ma10': trend_result.bias_ma10,
                'volume_status': trend_result.volume_status.value,
                'volume_trend': trend_result.volume_trend,
                'buy_signal': trend_result.buy_signal.value,
                'signal_score': trend_result.signal_score,
                'signal_reasons': trend_result.signal_reasons,
                'risk_factors': trend_result.risk_factors,
            }

        # Issue #234：盤中分析使用實時 OHLC 與趨勢 MA 覆蓋 today。
        # 防護條件：trend_result.ma5 > 0 表示 MA 計算已成功且資料量充足。
        if realtime_quote and trend_result and trend_result.ma5 > 0:
            price = getattr(realtime_quote, 'price', None)
            if price is not None and price > 0:
                yesterday_close = None
                if enhanced.get('yesterday') and isinstance(enhanced['yesterday'], dict):
                    yesterday_close = enhanced['yesterday'].get('close')
                orig_today = enhanced.get('today') or {}
                market_today = get_market_now(
                    get_market_for_stock(normalize_stock_code(enhanced.get('code', '')))
                ).date().isoformat()
                source = getattr(realtime_quote, 'source', None)
                source_name = getattr(source, 'value', source)
                source_name = str(source_name) if source_name is not None else 'unknown'
                open_p = getattr(realtime_quote, 'open_price', None) or getattr(
                    realtime_quote, 'pre_close', None
                ) or yesterday_close or orig_today.get('open') or price
                high_p = getattr(realtime_quote, 'high', None) or price
                low_p = getattr(realtime_quote, 'low', None) or price
                vol = getattr(realtime_quote, 'volume', None)
                amt = getattr(realtime_quote, 'amount', None)
                pct = getattr(realtime_quote, 'change_pct', None)
                fetched_at = getattr(realtime_quote, 'fetched_at', None)
                provider_timestamp = getattr(realtime_quote, 'provider_timestamp', None)
                fallback_from = getattr(realtime_quote, 'fallback_from', None)
                realtime_today = {
                    'close': price,
                    'open': open_p,
                    'high': high_p,
                    'low': low_p,
                    'ma5': trend_result.ma5,
                    'ma10': trend_result.ma10,
                    'ma20': trend_result.ma20,
                    'date': market_today,
                    'data_source': f"realtime:{source_name}",
                    'realtime_source': source_name,
                    'is_estimated': True,
                }
                estimated_fields = [
                    'close', 'open', 'high', 'low', 'ma5', 'ma10', 'ma20',
                ]
                if vol is not None:
                    realtime_today['volume'] = vol
                    estimated_fields.append('volume')
                if amt is not None:
                    realtime_today['amount'] = amt
                    estimated_fields.append('amount')
                if pct is not None:
                    realtime_today['pct_chg'] = pct
                    estimated_fields.append('pct_chg')
                realtime_today['estimated_fields'] = estimated_fields
                if isinstance(market_phase_context, dict) and "is_partial_bar" in market_phase_context:
                    realtime_today['is_partial_bar'] = market_phase_context.get("is_partial_bar")
                if fetched_at is not None:
                    realtime_today['fetched_at'] = fetched_at
                if provider_timestamp is not None:
                    realtime_today['provider_timestamp'] = provider_timestamp
                if fallback_from is not None:
                    realtime_today['fallback_from'] = fallback_from
                realtime_owned_fields = {
                    'open', 'high', 'low', 'close',
                    'volume', 'amount', 'pct_chg', 'pctChg',
                    'date', 'data_source', 'dataSource', 'source',
                    'realtime_source', 'realtimeSource',
                    'is_partial_bar', 'isPartialBar', 'is_estimated',
                    'isEstimated', 'estimated_fields', 'estimatedFields',
                    'fetched_at', 'fetchedAt', 'provider_timestamp',
                    'providerTimestamp', 'fallback_from', 'fallbackFrom',
                }
                for k, v in orig_today.items():
                    if k not in realtime_today and k not in realtime_owned_fields and v is not None:
                        realtime_today[k] = v
                enhanced['today'] = realtime_today
                enhanced['ma_status'] = self._compute_ma_status(
                    price, trend_result.ma5, trend_result.ma10, trend_result.ma20
                )
                enhanced['date'] = market_today
                if yesterday_close is not None:
                    try:
                        yc = float(yesterday_close)
                        if yc > 0:
                            enhanced['price_change_ratio'] = round(
                                (price - yc) / yc * 100, 2
                            )
                    except (TypeError, ValueError):
                        pass
                if vol is not None and enhanced.get('yesterday'):
                    yest_vol = enhanced['yesterday'].get('volume') if isinstance(
                        enhanced['yesterday'], dict
                    ) else None
                    if yest_vol is not None:
                        try:
                            yv = float(yest_vol)
                            if yv > 0:
                                enhanced['volume_change_ratio'] = round(
                                    float(vol) / yv, 2
                                )
                        except (TypeError, ValueError):
                            pass

        # ETF/index flag for analyzer prompt (Fixes #274)
        enhanced['is_index_etf'] = SearchService.is_index_or_etf(
            context.get('code', ''), enhanced.get('stock_name', stock_name)
        )

        # P0: append unified fundamental block; keep as additional context only
        enhanced["fundamental_context"] = (
            fundamental_context
            if isinstance(fundamental_context, dict)
            else self.fetcher_manager.build_failed_fundamental_context(
                context.get("code", ""),
                "invalid fundamental context",
            )
        )

        return enhanced

    def _attach_belong_boards_to_fundamental_context(
        self,
        code: str,
        fundamental_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Attach A-share board membership as a top-level supplemental field.

        Keep this as a shallow copy so cached fundamental contexts are not
        mutated in place after retrieval.
        """
        if isinstance(fundamental_context, dict):
            enriched_context = dict(fundamental_context)
        else:
            enriched_context = self.fetcher_manager.build_failed_fundamental_context(
                code,
                "invalid fundamental context",
            )

        existing_boards = enriched_context.get("belong_boards")
        if isinstance(existing_boards, list):
            enriched_context["belong_boards"] = list(existing_boards)
            return enriched_context

        boards_block = enriched_context.get("boards")
        boards_status = boards_block.get("status") if isinstance(boards_block, dict) else None
        coverage = enriched_context.get("coverage")
        boards_coverage = coverage.get("boards") if isinstance(coverage, dict) else None
        market = enriched_context.get("market")
        if not isinstance(market, str) or not market.strip():
            market = get_market_for_stock(normalize_stock_code(code))

        # For HK/US: the offshore adapter already populates belong_boards from
        # yfinance sector/industry. Don't overwrite it (and we have no AkShare
        # 板塊 endpoint for those markets anyway). Default to [] when callers
        # pass a minimal context without the key.
        if market != "cn":
            enriched_context.setdefault("belong_boards", [])
            return enriched_context

        if boards_status == "not_supported" or boards_coverage == "not_supported":
            enriched_context["belong_boards"] = []
            return enriched_context

        boards: List[Dict[str, Any]] = []
        try:
            raw_boards = self.fetcher_manager.get_belong_boards(code)
            if isinstance(raw_boards, list):
                boards = raw_boards
        except Exception as e:
            logger.debug("%s attach belong_boards failed (fail-open): %s", code, e)

        enriched_context["belong_boards"] = boards
        return enriched_context

    def _attach_valuation_fundamental_snapshot(
        self,
        result: Any,
        code: str,
        fundamental_context: Optional[Dict[str, Any]],
    ) -> None:
        """
        Phase 19B.2: attach deterministic `valuation_snapshot` / `fundamental_snapshot`.

        Stock-only (etf/index/unknown render nothing — Phase 19B.3 scope).
        TW market triggers one additional, narrowly-scoped FinMind fetch
        (TaiwanStockPER + TaiwanStockMonthRevenue only). US market reuses the
        yfinance `info` dict already fetched into `fundamental_context` by
        `get_fundamental_context()` — no extra network call. Never raises;
        any failure degrades to "no snapshot" rather than aborting the report.
        """
        if getattr(result, "instrument_type", "unknown") != "stock":
            return
        try:
            market = get_market_for_stock(normalize_stock_code(code))
            valuation_raw: Dict[str, Any] = {}
            fundamental_raw: Dict[str, Any] = {}
            source: Optional[str] = None

            if market == "tw":
                from src.finmind.tw_stock_analysis import (
                    build_tw_valuation_fundamental_snapshot,
                    normalize_tw_symbol,
                )

                stock_id, err = normalize_tw_symbol(code)
                if err or not stock_id:
                    return
                from src.services.history_loader import get_frozen_target_date

                frozen = get_frozen_target_date()
                end_date = (frozen if frozen else get_market_now(market).date()).isoformat()
                valuation_raw, fundamental_raw = build_tw_valuation_fundamental_snapshot(
                    stock_id, end_date=end_date,
                )
                source = "finmind"
            elif market == "us":
                ctx = fundamental_context if isinstance(fundamental_context, dict) else {}
                valuation_block = ctx.get("valuation") or {}
                growth_block = ctx.get("growth") or {}
                # _build_fundamental_block wraps numeric fields under "data"; fall back
                # to the block itself for callers that pass raw dicts directly.
                valuation_data = valuation_block.get("data") or valuation_block
                growth_data = growth_block.get("data") or growth_block
                valuation_raw = {
                    "pe_ttm": valuation_data.get("pe_ttm"),
                    "pe_forward": valuation_data.get("pe_forward"),
                    "pb": valuation_data.get("pb"),
                    "dividend_yield": valuation_data.get("dividend_yield"),
                    "market_cap": valuation_data.get("market_cap"),
                }
                fundamental_raw = {
                    "revenue_yoy": growth_data.get("revenue_yoy"),
                    "earnings_yoy": growth_data.get("net_profit_yoy"),
                    "net_profit_yoy": growth_data.get("net_profit_yoy"),
                    "roe": growth_data.get("roe"),
                    "gross_margin": growth_data.get("gross_margin"),
                }
                source = "yfinance"
            else:
                return

            from src.services.valuation_fundamental_snapshot import (
                build_fundamental_snapshot,
                build_valuation_snapshot,
            )

            result.valuation_snapshot = build_valuation_snapshot(valuation_raw, source=source)
            result.fundamental_snapshot = build_fundamental_snapshot(fundamental_raw, source=source)
        except Exception as exc:
            logger.warning("[valuation_fundamental_snapshot] skipped for %s: %s", code, exc)

    def _attach_exposure_and_market_risk_snapshot(
        self,
        result: Any,
        code: str,
        fundamental_context: Optional[Dict[str, Any]],
    ) -> None:
        """
        Phase 19B.3 / 19B.3A: attach deterministic `exposure_snapshot` /
        `market_risk_snapshot`.

        `exposure_snapshot` is ETF/index-only. `market_risk_snapshot` is
        stock/ETF/index (broadened in 19B.3A — a stock report still benefits
        from a market-risk thermometer even without an exposure summary).
        `unknown` remains a no-op for both fields.

        US market reuses the existing `fetcher_manager.get_realtime_quote()`
        dispatcher (already circuit-breaker protected) to read VIX/SPX —
        no new provider, no new cache. TW market makes no fetch attempt at
        all this phase (security constraint following the 19B.2A FinMind
        token-leak incident) and always renders a deterministic data-gap
        snapshot. Never raises; any failure degrades to "no snapshot"
        rather than aborting the report.
        """
        instrument_type = getattr(result, "instrument_type", "unknown")
        should_build_exposure = instrument_type in ("etf", "index")
        should_build_market_risk = instrument_type in ("stock", "etf", "index")
        if not should_build_exposure and not should_build_market_risk:
            return
        try:
            from src.services.exposure_market_risk_snapshot import (
                TW_MARKET_RISK_GAP_REASON,
                build_exposure_snapshot,
                build_market_risk_snapshot,
                classify_vix_status,
            )

            market = get_market_for_stock(normalize_stock_code(code))
            exposure_raw: Dict[str, Any] = {}

            if market == "us":
                market_risk_raw: Dict[str, Any] = {}
                vix_quote = self.fetcher_manager.get_realtime_quote("VIX", log_final_failure=False)
                if vix_quote:
                    vix_level = getattr(vix_quote, "price", None)
                    market_risk_raw["vix_level"] = vix_level
                    market_risk_raw["vix_status"] = classify_vix_status(vix_level)
                spx_quote = self.fetcher_manager.get_realtime_quote("SPX", log_final_failure=False)
                if spx_quote:
                    market_risk_raw["spx_change_pct"] = getattr(spx_quote, "change_pct", None)
                if should_build_exposure:
                    result.exposure_snapshot = build_exposure_snapshot(exposure_raw, source=None)
                if should_build_market_risk:
                    result.market_risk_snapshot = build_market_risk_snapshot(
                        market_risk_raw, source="yfinance" if (vix_quote or spx_quote) else None,
                    )
            elif market == "tw":
                if should_build_exposure:
                    result.exposure_snapshot = build_exposure_snapshot(exposure_raw, source=None)
                if should_build_market_risk:
                    result.market_risk_snapshot = build_market_risk_snapshot(
                        {}, source=None, gap_reason=TW_MARKET_RISK_GAP_REASON,
                    )
            else:
                return
        except Exception as exc:
            logger.warning("[exposure_market_risk_snapshot] skipped for %s: %s", code, exc)

    def _attach_market_fear_index_snapshot(self, result: Any, code: str) -> None:
        """Attach latest market-level fear index snapshot at analysis time only."""
        instrument_type = getattr(result, "instrument_type", "unknown")
        if instrument_type not in ("stock", "etf", "index"):
            return
        try:
            from src.services.market_fear_index_snapshot import (
                build_tw_vixtwn_market_fear_snapshot,
                build_us_vix_market_fear_snapshot,
            )

            market = get_market_for_stock(normalize_stock_code(code))
            if market == "us":
                market_risk = getattr(result, "market_risk_snapshot", None)
                value = market_risk.get("vix_level") if isinstance(market_risk, dict) else None
                as_of = market_risk.get("as_of") if isinstance(market_risk, dict) else None
                vix_quote = None
                if value is None:
                    vix_quote = self.fetcher_manager.get_realtime_quote("VIX", log_final_failure=False)
                    value = getattr(vix_quote, "price", None) if vix_quote else None
                if vix_quote and as_of is None:
                    as_of = (
                        getattr(vix_quote, "date", None)
                        or getattr(vix_quote, "trade_date", None)
                        or getattr(vix_quote, "timestamp", None)
                    )
                result.market_fear_index_snapshot = build_us_vix_market_fear_snapshot(
                    value,
                    as_of=str(as_of)[:10] if as_of else None,
                )
            elif market == "tw":
                from src.services.taifex_vixtwn_fetcher import fetch_latest_vixtwn

                result.market_fear_index_snapshot = build_tw_vixtwn_market_fear_snapshot(
                    fetch_latest_vixtwn()
                )
        except Exception as exc:
            logger.warning("[market_fear_index_snapshot] skipped for %s: %s", code, exc)
            try:
                if get_market_for_stock(normalize_stock_code(code)) == "tw":
                    from src.services.market_fear_index_snapshot import build_tw_vixtwn_gap_snapshot

                    result.market_fear_index_snapshot = build_tw_vixtwn_gap_snapshot()
            except Exception:
                return

    def _attach_multi_period_trend_snapshot(
        self,
        result: Any,
        code: str,
    ) -> None:
        """
        Phase 19B.4: attach deterministic `multi_period_trend_snapshot`.

        stock/etf/index only (unknown is a no-op). Computes 5D/20D/60D/120D/
        252D return, drawdown-from-high, and MA-position rows from OHLC rows
        loaded via `src.services.history_loader.load_history_df` — a DB-first
        helper already reused elsewhere (Issue #1066), so this adds at most
        one additional network fetch (only on a DB-cache miss) and never
        widens or otherwise touches the existing ~89-day window that feeds
        MA60/trend_result (this class's main fetch, see the `timedelta(days=89)`
        window above). Periods without enough rows degrade to
        `insufficient_data` with `data_gap_fields` populated — never a
        hallucinated 52W number. Never raises; any failure degrades to
        "no snapshot" rather than aborting the report.
        """
        if getattr(result, "instrument_type", "unknown") not in ("stock", "etf", "index"):
            return
        try:
            from src.services.history_loader import load_history_df
            from src.services.multi_period_trend_snapshot import (
                build_multi_period_trend_snapshot,
            )

            # `days=252` is a trading-day-count request, not a calendar-day
            # window: load_history_df() internally converts it to a
            # ~1.8x + 10 calendar-day DB lookback buffer (~463 calendar days
            # for 252), the same convention already used by
            # `_ensure_agent_history()`'s `min_days * 1.8` above and by
            # `data_tools._handle_get_daily_history()`. Pinned by
            # tests/test_history_loader.py::test_252_trading_days_uses_wide_calendar_buffer.
            df, source = load_history_df(code, days=252)
            result.multi_period_trend_snapshot = build_multi_period_trend_snapshot(
                df, source=(source if df is not None else None),
            )
        except Exception as exc:
            logger.warning("[multi_period_trend_snapshot] skipped for %s: %s", code, exc)

    def _ensure_agent_history(self, code: str, min_days: int = 240) -> None:
        """Ensure at least *min_days* of K-line history is in DB for agent tools."""
        from src.services.history_loader import get_frozen_target_date

        target = get_frozen_target_date()
        if target is None:
            target = self._resolve_resume_target_date(code)
        start = target - timedelta(days=int(min_days * 1.8))
        bars = self.db.get_data_range(code, start, target)
        if bars and len(bars) >= min(min_days, 200):
            logger.debug("[%s] Agent history: %d bars in DB, sufficient", code, len(bars))
            return
        try:
            df, source = self.fetcher_manager.get_daily_data(code, days=min_days)
            if df is not None and not df.empty:
                self.db.save_daily_data(df, code, source)
                logger.info("[%s] Prefetched %d rows of history for agent (source: %s)", code, len(df), source)
        except Exception as e:
            logger.warning("[%s] Agent history prefetch failed: %s", code, e)

    def _analyze_with_agent(
        self, 
        code: str, 
        report_type: ReportType, 
        query_id: str,
        stock_name: str,
        realtime_quote: Any,
        chip_data: Optional[ChipDistribution],
        fundamental_context: Optional[Dict[str, Any]] = None,
        trend_result: Optional[TrendAnalysisResult] = None,
        *,
        market_phase_context: Optional[Dict[str, Any]] = None,
        market_phase_summary: Optional[Dict[str, Any]] = None,
    ) -> Optional[AnalysisResult]:
        """
        使用 Agent 模式分析單隻股票。
        """
        try:
            from src.agent.factory import build_agent_executor
            report_language = normalize_report_language(getattr(self.config, "report_language", "zh"))

            requested_skills = (
                self.analysis_skills
                if self.analysis_skills is not None
                else (getattr(self.config, 'agent_skills', None) or None)
            )
            # Build executor from shared factory (ToolRegistry and SkillManager prototype are cached)
            executor = build_agent_executor(self.config, requested_skills)

            # Build initial context to avoid redundant tool calls
            initial_context = {
                "stock_code": code,
                "stock_name": stock_name,
                "report_type": report_type.value,
                "report_language": report_language,
                "fundamental_context": fundamental_context,
            }
            if self.analysis_skills is not None:
                initial_context["skills"] = self.analysis_skills
            if market_phase_context is not None:
                initial_context["market_phase_context"] = market_phase_context
            
            if realtime_quote:
                initial_context["realtime_quote"] = self._safe_to_dict(realtime_quote)
            if chip_data:
                initial_context["chip_distribution"] = self._safe_to_dict(chip_data)
            if trend_result:
                initial_context["trend_result"] = self._safe_to_dict(trend_result)

            # Agent path: inject social sentiment as news_context so both
            # executor (_build_user_message) and orchestrator (ctx.set_data)
            # can consume it through the existing news_context channel
            if self.social_sentiment_service is not None and self.social_sentiment_service.is_available and is_us_stock_code(code):
                try:
                    social_context = self.social_sentiment_service.get_social_context(code)
                    if social_context:
                        existing = initial_context.get("news_context")
                        if existing:
                            initial_context["news_context"] = existing + "\n\n" + social_context
                        else:
                            initial_context["news_context"] = social_context
                        logger.info(f"[{code}] Agent mode: social sentiment data injected into news_context")
                except Exception as e:
                    logger.warning(f"[{code}] Agent mode: social sentiment fetch failed: {e}")

            # Issue #1066: ensure deep history is in DB before agent tools run
            self._ensure_agent_history(code)

            analysis_context = self._load_agent_analysis_context(code, stock_name)
            market = get_market_for_stock(normalize_stock_code(code))
            (
                analysis_context_pack_summary,
                analysis_context_pack_overview,
            ) = self._build_analysis_context_pack_outputs(
                self._build_agent_analysis_artifacts(
                    code=code,
                    stock_name=stock_name,
                    market=market,
                    phase=market_phase_context,
                    initial_context=initial_context,
                    fundamental_context=fundamental_context,
                    query_id=query_id,
                    base_context=analysis_context,
                ),
                report_language=report_language,
                code=code,
                query_id=query_id,
            )
            if analysis_context_pack_summary:
                initial_context["analysis_context_pack_summary"] = analysis_context_pack_summary

            # 執行 Agent
            if report_language == "en":
                message = f"Analyze stock {code} ({stock_name}) and return the full decision dashboard JSON in English."
            else:
                message = f"請分析股票 {code} ({stock_name})，並生成決策儀表盤報告。"
            llm_started_at = time.monotonic()
            try:
                agent_result = executor.run(message, context=initial_context)
            except Exception as exc:
                record_llm_run(
                    success=False,
                    model=getattr(self.config, "agent_litellm_model", None),
                    call_type="agent_analysis",
                    duration_ms=int((time.monotonic() - llm_started_at) * 1000),
                    error_type=type(exc).__name__,
                    error_message=exc,
                )
                raise

            # 轉換為 AnalysisResult
            result = self._agent_result_to_analysis_result(
                agent_result,
                code,
                stock_name,
                report_type,
                query_id,
                trend_result=trend_result,
            )
            record_llm_run(
                success=bool(result and getattr(result, "success", True)),
                model=getattr(result, "model_used", None) if result else getattr(agent_result, "model", None),
                call_type="agent_analysis",
                duration_ms=int((time.monotonic() - llm_started_at) * 1000),
                error_type=(
                    None
                    if result and getattr(result, "success", True)
                    else "AgentResultError"
                ),
                error_message=(
                    getattr(result, "error_message", None)
                    if result and not getattr(result, "success", True)
                    else ("Agent returned empty result" if result is None else None)
                ),
            )
            if result:
                result.query_id = query_id
                result.instrument_type = resolve_report_instrument_type(normalize_stock_code(code))
                self._attach_valuation_fundamental_snapshot(result, code, fundamental_context)
                self._attach_exposure_and_market_risk_snapshot(result, code, fundamental_context)
                self._attach_market_fear_index_snapshot(result, code)
                self._attach_multi_period_trend_snapshot(result, code)
            # Agent weak integrity: placeholder fill only, no LLM retry
            if result and getattr(self.config, "report_integrity_enabled", False):
                from src.analyzer import check_content_integrity, apply_placeholder_fill

                pass_integrity, missing = check_content_integrity(
                    result,
                    require_phase_decision=isinstance(market_phase_summary, dict),
                )
                if not pass_integrity:
                    apply_placeholder_fill(result, missing)
                    logger.info(
                        "[LLM完整性] integrity_mode=agent_weak 必填欄位缺失 %s，已佔位補全",
                        missing,
                    )
            # chip_structure fallback (Issue #589), before save_analysis_history
            if result and chip_data is not None:
                normalize_chip_structure_availability(result, chip_data)

            # price_position fallback (same as non-agent path Step 7.7)
            if result:
                fill_price_position_if_needed(result, trend_result, realtime_quote)
                realtime_data = initial_context.get("realtime_quote", {})
                if isinstance(realtime_data, dict):
                    result.current_price = realtime_data.get("price")
                    result.change_pct = realtime_data.get("change_pct")
                if result.current_price is None:
                    fallback_price, fallback_change_pct = self._fallback_quote_from_context(
                        analysis_context
                    )
                    if fallback_price is not None:
                        result.current_price = fallback_price
                        result.change_pct = fallback_change_pct
                stabilize_decision_with_structure(result, trend_result, fundamental_context)
                adjustments = apply_phase_decision_guardrails(
                    result,
                    market_phase_summary=market_phase_summary,
                    analysis_context_pack_overview=analysis_context_pack_overview,
                    report_language=getattr(result, "report_language", None)
                    or getattr(self.config, "report_language", "zh"),
                )
                if adjustments:
                    logger.info("[phase_decision_guardrail] Applied agent adjustments for %s: %s", code, adjustments)
                if isinstance(fundamental_context, dict):
                    result.fundamental_context = fundamental_context

            resolved_stock_name = result.name if result and result.name else stock_name
            news_search_diagnostics: Optional[Dict[str, Any]] = None

            # 儲存新聞情報到資料庫（Agent 工具結果僅用於 LLM 上下文，未持久化，Fixes #396）
            # 使用 search_stock_news（與 Agent 工具呼叫邏輯一致），僅 1 次 API 呼叫，無額外延遲
            if self.search_service is not None and self.search_service.is_available:
                try:
                    news_response = self.search_service.search_stock_news(
                        stock_code=code,
                        stock_name=resolved_stock_name,
                        max_results=5
                    )
                    response_diagnostics = getattr(news_response, "diagnostics", None)
                    if isinstance(response_diagnostics, dict):
                        search_diagnostics = response_diagnostics.get("news_search")
                        if isinstance(search_diagnostics, dict):
                            news_search_diagnostics = search_diagnostics
                    if news_response.success and news_response.results:
                        query_context = self._build_query_context(query_id=query_id)
                        self.db.save_news_intel(
                            code=code,
                            name=resolved_stock_name,
                            dimension="latest_news",
                            query=news_response.query,
                            response=news_response,
                            query_context=query_context
                        )
                        logger.info(f"[{code}] Agent 模式: 新聞情報已儲存 {len(news_response.results)} 條")
                except Exception as e:
                    logger.warning(f"[{code}] Agent 模式儲存新聞情報失敗: {e}")

            # 儲存分析歷史記錄
            if result and result.success:
                try:
                    agent_context_snapshot = self._build_context_snapshot(
                        enhanced_context={
                            **analysis_context,
                            **self._without_runtime_prompt_context(initial_context),
                            "stock_name": resolved_stock_name,
                        },
                        news_content=initial_context.get("news_context"),
                        realtime_quote=realtime_quote,
                        chip_data=chip_data,
                        analysis_context_pack_overview=analysis_context_pack_overview,
                        market_phase_summary=market_phase_summary,
                        news_search_diagnostics=news_search_diagnostics,
                    )
                    result.diagnostic_context_snapshot = agent_context_snapshot
                    agent_context_snapshot["stock_name"] = resolved_stock_name
                    saved_count = self.db.save_analysis_history(
                        result=result,
                        query_id=query_id,
                        report_type=report_type.value,
                        news_content=None,
                        context_snapshot=agent_context_snapshot,
                        save_snapshot=self.save_context_snapshot,
                    )
                    record_history_run(
                        report_saved=bool(saved_count),
                        metadata_saved=bool(saved_count),
                    )
                    latest_diagnostic_snapshot = current_diagnostic_snapshot()
                    if latest_diagnostic_snapshot is not None:
                        agent_context_snapshot["diagnostics"] = latest_diagnostic_snapshot
                        result.diagnostic_context_snapshot = agent_context_snapshot
                except Exception as e:
                    record_history_run(
                        report_saved=False,
                        metadata_saved=False,
                        error_message=e,
                    )
                    logger.warning(f"[{code}] 儲存 Agent 分析歷史失敗: {e}")

            return result

        except Exception as e:
            logger.error(f"[{code}] Agent 分析失敗: {e}")
            logger.exception(f"[{code}] Agent 詳細錯誤資訊:")
            return None

    def _load_agent_analysis_context(self, code: str, stock_name: str) -> Dict[str, Any]:
        """Load daily-bar context for Agent pack summaries without blocking analysis."""
        try:
            context = self.db.get_analysis_context(code)
        except Exception as exc:
            logger.warning(
                "[%s] Agent analysis context load failed; daily_bars will be marked missing: %s",
                code,
                exc,
            )
            context = None

        if isinstance(context, dict) and context:
            enriched = dict(context)
            enriched.setdefault("code", code)
            if stock_name:
                enriched.setdefault("stock_name", stock_name)
            return enriched

        return {
            "code": code,
            "stock_name": stock_name,
            "data_missing": True,
            "today": {},
            "yesterday": {},
        }

    def _agent_result_to_analysis_result(
        self,
        agent_result,
        code: str,
        stock_name: str,
        report_type: ReportType,
        query_id: str,
        trend_result: Optional[TrendAnalysisResult] = None,
    ) -> AnalysisResult:
        """
        將 AgentResult 轉換為 AnalysisResult。
        """
        report_language = normalize_report_language(getattr(self.config, "report_language", "zh"))
        result = AnalysisResult(
            code=code,
            name=stock_name,
            sentiment_score=50,
            trend_prediction="Unknown" if report_language == "en" else "未知",
            operation_advice=localize_operation_advice("watch", report_language),
            confidence_level=localize_confidence_level("medium", report_language),
            report_language=report_language,
            success=agent_result.success,
            error_message=agent_result.error or None,
            data_sources=f"agent:{agent_result.provider}",
            model_used=agent_result.model or None,
        )

        if agent_result.success and agent_result.dashboard:
            dash = agent_result.dashboard
            ai_stock_name = str(dash.get("stock_name", "")).strip()
            if ai_stock_name and self._is_placeholder_stock_name(stock_name, code):
                result.name = ai_stock_name

            nested_dashboard = dash.get("dashboard") if isinstance(dash, dict) else None

            raw_score = self._agent_dashboard_value(
                dash,
                nested_dashboard,
                "sentiment_score",
                scalar=True,
            )
            if self._is_agent_field_missing(raw_score, scalar=True):
                fallback_score = self._trend_score_fallback(trend_result)
                if fallback_score is not None:
                    result.sentiment_score = fallback_score
                    self._mark_trend_fallback_source(result)
            else:
                result.sentiment_score = self._safe_int(raw_score, 50)

            raw_trend = self._agent_dashboard_value(
                dash,
                nested_dashboard,
                "trend_prediction",
                scalar=True,
                expect_text=True,
            )
            if self._is_agent_field_missing(raw_trend, scalar=True, expect_text=True):
                trend_label = self._trend_label_fallback(
                    trend_result,
                    report_language,
                )
                if trend_label:
                    result.trend_prediction = trend_label
                    self._mark_trend_fallback_source(result)
            else:
                result.trend_prediction = str(raw_trend)

            raw_advice = self._agent_dashboard_value(
                dash,
                nested_dashboard,
                "operation_advice",
                scalar=True,
                allow_dict=True,
                expect_text=True,
            )
            extracted_advice = ""
            if isinstance(raw_advice, dict):
                # LLM may return {"no_position": "...", "has_position": "..."}
                extracted_advice = self._extract_advice_text_from_dict(raw_advice)
                if extracted_advice:
                    result.operation_advice = localize_operation_advice(
                        extracted_advice,
                        report_language,
                    )
                else:
                    signal_label = self._trend_signal_fallback(
                        trend_result,
                        report_language,
                    )
                    if signal_label:
                        result.operation_advice = signal_label
                        self._mark_trend_fallback_source(result)
            elif not self._is_agent_field_missing(
                raw_advice,
                scalar=True,
                allow_dict=True,
                expect_text=True,
            ):
                result.operation_advice = localize_operation_advice(str(raw_advice), report_language) if raw_advice else localize_operation_advice("watch", report_language)
            else:
                signal_label = self._trend_signal_fallback(trend_result, report_language)
                if signal_label:
                    result.operation_advice = signal_label
                    self._mark_trend_fallback_source(result)
            from src.agent.protocols import normalize_decision_signal

            raw_decision = self._agent_dashboard_value(
                dash,
                nested_dashboard,
                "decision_type",
                scalar=True,
                expect_text=True,
            )
            if self._is_agent_field_missing(raw_decision, scalar=True, expect_text=True):
                trend_decision = self._trend_decision_fallback(trend_result)
                decision_from_advice = infer_decision_type_from_advice(
                    result.operation_advice,
                    default="",
                )
                if decision_from_advice:
                    result.decision_type = decision_from_advice
                    if (
                        self._is_agent_field_missing(
                            raw_advice,
                            scalar=True,
                            allow_dict=True,
                            expect_text=True,
                        )
                        and not extracted_advice
                        and trend_decision
                    ):
                        self._mark_trend_fallback_source(result)
                else:
                    result.decision_type = trend_decision or "hold"
                    if trend_decision:
                        self._mark_trend_fallback_source(result)
            else:
                result.decision_type = normalize_decision_signal(raw_decision)
            result.confidence_level = localize_confidence_level(
                self._agent_dashboard_value(dash, nested_dashboard, "confidence_level")
                or result.confidence_level,
                report_language,
            )
            raw_summary = self._agent_dashboard_value(
                dash,
                nested_dashboard,
                "analysis_summary",
                scalar=True,
                expect_text=True,
            )
            if not self._is_agent_field_missing(raw_summary, scalar=True, expect_text=True):
                result.analysis_summary = str(raw_summary)
            else:
                result.analysis_summary = self._summary_fallback_from_result(result, report_language)
            top_level_phase_decision = dash.get("phase_decision") if isinstance(dash, dict) else None
            if isinstance(nested_dashboard, dict) and isinstance(top_level_phase_decision, dict):
                nested_dashboard = dict(nested_dashboard)
                nested_dashboard.setdefault("phase_decision", top_level_phase_decision)

            # The AI returns a top-level dict that contains a nested 'dashboard' sub-key
            # with core_conclusion / battle_plan / intelligence.  AnalysisResult's helper
            # methods (get_sniper_points, get_core_conclusion, etc.) expect that inner
            # structure, so we unwrap it here.
            result.dashboard = nested_dashboard or dash
            if isinstance(dash, dict):
                result.value_network_mermaid = dash.get("value_network_mermaid")
                fm_commentary = dash.get("four_masters_commentary")
                result.four_masters_commentary = fm_commentary if isinstance(fm_commentary, dict) else None
            self._backfill_agent_dashboard_fields(result, trend_result, report_language)
        else:
            self._apply_trend_fallback(result, trend_result, report_language)
            if trend_result is not None:
                result.analysis_summary = (
                    result.analysis_summary
                    or self._summary_fallback_from_result(result, report_language)
                )
                self._backfill_agent_dashboard_fields(result, trend_result, report_language)
            if not result.error_message:
                result.error_message = "Agent failed to generate a valid decision dashboard" if report_language == "en" else "Agent 未能生成有效的決策儀表盤"

        return result

    @staticmethod
    def _agent_dashboard_value(
        dash: Dict[str, Any],
        nested_dashboard: Any,
        key: str,
        *,
        scalar: bool = False,
        allow_dict: bool = False,
        expect_text: bool = False,
    ) -> Any:
        """Read a scalar from top-level agent payload, then nested dashboard fallback."""
        value = dash.get(key) if isinstance(dash, dict) else None
        if isinstance(nested_dashboard, dict) and StockAnalysisPipeline._is_agent_field_missing(
            value,
            scalar=scalar,
            allow_dict=allow_dict,
            expect_text=expect_text,
        ):
            nested_value = nested_dashboard.get(key)
            if not StockAnalysisPipeline._is_agent_field_missing(
                nested_value,
                scalar=scalar,
                allow_dict=allow_dict,
                expect_text=expect_text,
            ):
                value = nested_value
        return value

    @staticmethod
    def _extract_advice_text_from_dict(raw_advice: dict) -> str:
        for field in ("has_position", "no_position"):
            if isinstance(raw_advice.get(field), str):
                text = raw_advice[field].strip()
                if not StockAnalysisPipeline._is_agent_placeholder_text(text):
                    return text

        for value in raw_advice.values():
            if isinstance(value, str):
                text = value.strip()
                if not StockAnalysisPipeline._is_agent_placeholder_text(text):
                    return text

        return ""

    @staticmethod
    def _is_agent_placeholder_text(text: str) -> bool:
        if not text:
            return True
        return text.lower() in {"n/a", "na", "none", "null", "unknown", "tbd"} or text in {
            "未知",
            "待補充",
            "資料缺失",
            "無",
        }

    @staticmethod
    def _is_agent_field_missing(
        value: Any,
        *,
        scalar: bool = False,
        allow_dict: bool = False,
        expect_text: bool = False,
    ) -> bool:
        if scalar and isinstance(value, dict):
            if not allow_dict or not value:
                return True
            return not StockAnalysisPipeline._extract_advice_text_from_dict(value)
        if value is None:
            return True
        if expect_text and scalar:
            if not isinstance(value, str):
                return True
        if isinstance(value, str):
            text = value.strip()
            return StockAnalysisPipeline._is_agent_placeholder_text(text)
        if isinstance(value, dict):
            if scalar:
                return not allow_dict
            return not value
        if scalar and isinstance(value, (list, tuple, set)):
            return True
        return False

    @staticmethod
    def _trend_score_fallback(trend_result: Optional[TrendAnalysisResult]) -> Optional[int]:
        if trend_result is None:
            return None
        try:
            score = int(getattr(trend_result, "signal_score", 0))
        except (TypeError, ValueError):
            return None
        return score if score > 0 else None

    @staticmethod
    def _trend_label_fallback(
        trend_result: Optional[TrendAnalysisResult],
        report_language: str = "zh",
    ) -> str:
        if trend_result is None:
            return ""
        trend_status = getattr(trend_result, "trend_status", None)
        value = getattr(trend_status, "value", None) or str(trend_status or "").strip()
        if report_language != "en":
            return value
        return localize_trend_prediction(value, report_language)

    @staticmethod
    def _trend_signal_fallback(
        trend_result: Optional[TrendAnalysisResult],
        report_language: str = "zh",
    ) -> str:
        if trend_result is None:
            return ""
        buy_signal = getattr(trend_result, "buy_signal", None)
        value = getattr(buy_signal, "value", None) or str(buy_signal or "").strip()
        return localize_operation_advice(value, report_language)

    @staticmethod
    def _trend_decision_fallback(trend_result: Optional[TrendAnalysisResult]) -> Optional[str]:
        if trend_result is None:
            return None
        signal_name = getattr(getattr(trend_result, "buy_signal", None), "name", "").lower()
        return {
            "strong_buy": "buy",
            "buy": "buy",
            "hold": "hold",
            "wait": "hold",
            "sell": "sell",
            "strong_sell": "sell",
        }.get(signal_name)

    @staticmethod
    def _mark_trend_fallback_source(result: AnalysisResult) -> None:
        if "trend:fallback" in (result.data_sources or ""):
            return
        result.data_sources = (
            f"{result.data_sources},trend:fallback"
            if result.data_sources
            else "trend:fallback"
        )

    @staticmethod
    def _summary_fallback_from_result(result: AnalysisResult, report_language: str) -> str:
        trend = (result.trend_prediction or "").strip()
        advice = (result.operation_advice or "").strip()
        if trend and advice:
            if report_language == "en":
                return f"Trend view: {trend}; action advice: {advice}."
            return f"趨勢結論：{trend}；操作建議：{advice}。"
        return ""

    def _backfill_agent_dashboard_fields(
        self,
        result: AnalysisResult,
        trend_result: Optional[TrendAnalysisResult],
        report_language: str,
    ) -> None:
        if not isinstance(result.dashboard, dict):
            result.dashboard = {}
        dashboard = result.dashboard

        for key in (
            "sentiment_score",
            "trend_prediction",
            "operation_advice",
            "decision_type",
            "confidence_level",
            "analysis_summary",
        ):
            current = dashboard.get(key)
            if key == "sentiment_score":
                if self._is_agent_field_missing(current, scalar=True):
                    dashboard[key] = getattr(result, key)
            elif self._is_agent_field_missing(current, scalar=True, expect_text=True):
                dashboard[key] = getattr(result, key)

        core = dashboard.get("core_conclusion")
        if not isinstance(core, dict):
            core = {}
            dashboard["core_conclusion"] = core
        if self._is_agent_field_missing(core.get("one_sentence"), scalar=True):
            core["one_sentence"] = result.analysis_summary or self._summary_fallback_from_result(
                result,
                report_language,
            ) or ("Analysis pending" if report_language == "en" else "分析待補充")

        intelligence = dashboard.get("intelligence")
        if not isinstance(intelligence, dict):
            intelligence = {}
            dashboard["intelligence"] = intelligence
        risk_alerts = intelligence.get("risk_alerts")
        if (
            "risk_alerts" not in intelligence
            or self._is_agent_field_missing(risk_alerts)
            or not isinstance(risk_alerts, list)
        ):
            risk_factors = getattr(trend_result, "risk_factors", None) or []
            intelligence["risk_alerts"] = list(risk_factors)

        if result.decision_type in ("buy", "hold"):
            battle = dashboard.get("battle_plan")
            if not isinstance(battle, dict):
                battle = {}
                dashboard["battle_plan"] = battle
            sniper_points = battle.get("sniper_points")
            if not isinstance(sniper_points, dict):
                sniper_points = {}
                battle["sniper_points"] = sniper_points
            if self._is_agent_field_missing(sniper_points.get("stop_loss"), scalar=True):
                sniper_points["stop_loss"] = self._stop_loss_fallback_from_trend(
                    trend_result,
                    report_language,
                )

    @staticmethod
    def _stop_loss_fallback_from_trend(
        trend_result: Optional[TrendAnalysisResult],
        report_language: str,
    ) -> Any:
        levels = getattr(trend_result, "support_levels", None) if trend_result else None
        if levels:
            return levels[0]
        return "To be completed" if report_language == "en" else "待補充"

    @staticmethod
    def _apply_trend_fallback(
        result: AnalysisResult,
        trend_result: Optional[TrendAnalysisResult],
        report_language: str,
    ) -> None:
        if trend_result is None:
            result.sentiment_score = 50
            result.operation_advice = localize_operation_advice("watch", report_language)
            return

        score = getattr(trend_result, "signal_score", None)
        try:
            numeric_score = int(score)
        except (TypeError, ValueError):
            numeric_score = 50
        result.sentiment_score = numeric_score if numeric_score > 0 else 50

        trend_label = StockAnalysisPipeline._trend_label_fallback(trend_result, report_language)
        if trend_label:
            result.trend_prediction = trend_label

        buy_signal = getattr(trend_result, "buy_signal", None)
        signal_label = StockAnalysisPipeline._trend_signal_fallback(
            trend_result,
            report_language,
        )
        if signal_label:
            result.operation_advice = signal_label
        else:
            result.operation_advice = localize_operation_advice("watch", report_language)

        from src.agent.protocols import normalize_decision_signal

        signal_name = getattr(buy_signal, "name", "").lower()
        signal_to_decision = {
            "strong_buy": "buy",
            "buy": "buy",
            "hold": "hold",
            "wait": "hold",
            "sell": "sell",
            "strong_sell": "sell",
        }
        result.decision_type = signal_to_decision.get(signal_name, result.decision_type or "hold")
        result.decision_type = normalize_decision_signal(result.decision_type)
        result.data_sources = f"{result.data_sources},trend:fallback" if result.data_sources else "trend:fallback"

    @staticmethod
    def _is_placeholder_stock_name(name: str, code: str) -> bool:
        """Return True when the stock name is missing or placeholder-like."""
        if not name:
            return True
        normalized = str(name).strip()
        if not normalized:
            return True
        if normalized == code:
            return True
        if normalized.startswith("股票"):
            return True
        if "Unknown" in normalized:
            return True
        return False

    @staticmethod
    def _safe_int(value: Any, default: int = 50) -> int:
        """安全地將值轉換為整數。"""
        if value is None:
            return default
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            import re
            match = re.search(r'-?\d+', value)
            if match:
                return int(match.group())
        return default
    
    def _describe_volume_ratio(self, volume_ratio: float) -> str:
        """
        量比描述
        
        量比 = 當前成交量 / 過去5日平均成交量
        """
        if volume_ratio < 0.5:
            return "極度萎縮"
        elif volume_ratio < 0.8:
            return "明顯萎縮"
        elif volume_ratio < 1.2:
            return "正常"
        elif volume_ratio < 2.0:
            return "溫和放量"
        elif volume_ratio < 3.0:
            return "明顯放量"
        else:
            return "巨量"

    @staticmethod
    def _compute_ma_status(close: float, ma5: float, ma10: float, ma20: float) -> str:
        """
        Compute MA alignment status from price and MA values.
        Logic mirrors storage._analyze_ma_status (Issue #234).
        """
        close = close or 0
        ma5 = ma5 or 0
        ma10 = ma10 or 0
        ma20 = ma20 or 0
        if close > ma5 > ma10 > ma20 > 0:
            return "多頭排列 📈"
        elif close < ma5 < ma10 < ma20 and ma20 > 0:
            return "空頭排列 📉"
        elif close > ma5 and ma5 > ma10:
            return "短期向好 🔼"
        elif close < ma5 and ma5 < ma10:
            return "短期走弱 🔽"
        else:
            return "震盪整理 ↔️"

    def _augment_historical_with_realtime(
        self, df: pd.DataFrame, realtime_quote: Any, code: str
    ) -> pd.DataFrame:
        """
        使用當日實時行情補齊歷史 OHLCV，用於盤中 MA 計算。
        Issue #234：技術指標使用實時價格，而不是沿用昨日收盤價。
        """
        if df is None or df.empty or 'close' not in df.columns:
            return df
        if realtime_quote is None:
            return df
        price = getattr(realtime_quote, 'price', None)
        if price is None or not (isinstance(price, (int, float)) and price > 0):
            return df

        # 非交易日可跳過實時補齊；異常情況下保持失敗開放。
        enable_realtime_tech = getattr(
            self.config, 'enable_realtime_technical_indicators', True
        )
        if not enable_realtime_tech:
            return df
        market = get_market_for_stock(code)
        market_today = get_market_now(market).date()
        if market and not is_market_open(market, market_today):
            return df

        last_val = df['date'].max()
        last_date = (
            last_val.date() if hasattr(last_val, 'date') else
            (last_val if isinstance(last_val, date) else pd.Timestamp(last_val).date())
        )
        yesterday_close = float(df.iloc[-1]['close']) if len(df) > 0 else price
        open_p = getattr(realtime_quote, 'open_price', None) or getattr(
            realtime_quote, 'pre_close', None
        ) or yesterday_close
        high_p = getattr(realtime_quote, 'high', None) or price
        low_p = getattr(realtime_quote, 'low', None) or price
        vol = getattr(realtime_quote, 'volume', None) or 0
        amt = getattr(realtime_quote, 'amount', None)
        pct = getattr(realtime_quote, 'change_pct', None)

        if last_date >= market_today:
            # 使用實時收盤價更新最後一行；先複製，避免修改呼叫方傳入的 df。
            df = df.copy()
            idx = df.index[-1]
            df.loc[idx, 'close'] = price
            if open_p is not None:
                df.loc[idx, 'open'] = open_p
            if high_p is not None:
                df.loc[idx, 'high'] = high_p
            if low_p is not None:
                df.loc[idx, 'low'] = low_p
            if vol:
                df.loc[idx, 'volume'] = vol
            if amt is not None:
                df.loc[idx, 'amount'] = amt
            if pct is not None:
                df.loc[idx, 'pct_chg'] = pct
        else:
            # 追加一行虛擬的當日實時 K 線。
            new_row = {
                'code': code,
                'date': market_today,
                'open': open_p,
                'high': high_p,
                'low': low_p,
                'close': price,
                'volume': vol,
                'amount': amt if amt is not None else 0,
                'pct_chg': pct if pct is not None else 0,
            }
            new_df = pd.DataFrame([new_row])
            df = pd.concat([df, new_df], ignore_index=True)
        return df

    def _build_context_snapshot(
        self,
        enhanced_context: Dict[str, Any],
        news_content: Optional[str],
        realtime_quote: Any,
        chip_data: Optional[ChipDistribution],
        news_result_count: Optional[int] = None,
        news_search_diagnostics: Optional[Dict[str, Any]] = None,
        analysis_context_pack_overview: Optional[Dict[str, Any]] = None,
        market_phase_summary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        構建分析上下文快照
        """
        realtime_quote_raw = self._safe_to_dict(realtime_quote)
        snapshot = {
            "enhanced_context": self._without_runtime_prompt_context(enhanced_context),
            "news_content": news_content,
            "realtime_quote_raw": realtime_quote_raw,
            "quote_availability": self._build_quote_availability_snapshot(
                enhanced_context,
                realtime_quote_raw,
            ),
            "chip_distribution_raw": self._safe_to_dict(chip_data),
        }
        if news_content is not None:
            snapshot["news_retrieval_content"] = news_content
        if news_result_count is not None:
            snapshot["news_result_count"] = news_result_count
        if isinstance(news_search_diagnostics, dict):
            snapshot["news_search"] = news_search_diagnostics
        if analysis_context_pack_overview is not None:
            snapshot["analysis_context_pack_overview"] = analysis_context_pack_overview
        if market_phase_summary is not None:
            snapshot[MARKET_PHASE_SUMMARY_KEY] = market_phase_summary
        diagnostic_snapshot = current_diagnostic_snapshot()
        if diagnostic_snapshot is not None:
            snapshot["diagnostics"] = diagnostic_snapshot
        if self.analysis_skills is not None:
            snapshot["skills"] = list(self.analysis_skills)
        return snapshot

    @staticmethod
    def _positive_float(value: Any) -> Optional[float]:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    @classmethod
    def _fallback_quote_from_context(
        cls,
        context: Dict[str, Any],
    ) -> Tuple[Optional[float], Optional[float]]:
        today = context.get("today") if isinstance(context.get("today"), dict) else {}
        yesterday = context.get("yesterday") if isinstance(context.get("yesterday"), dict) else {}
        price = cls._positive_float(today.get("close") or yesterday.get("close"))
        if price is None:
            return None, None

        pct_value = today.get("pct_chg") or today.get("pctChg")
        try:
            pct = float(pct_value) if pct_value is not None else None
        except (TypeError, ValueError):
            pct = None
        if pct is None:
            previous_close = cls._positive_float(yesterday.get("close"))
            if previous_close is not None:
                pct = round((price - previous_close) / previous_close * 100, 2)
        return price, pct

    @staticmethod
    def _quote_source_label(source: Any) -> Optional[str]:
        text = str(source or "").strip()
        if not text:
            return None
        labels = {
            "yfinance": "Yahoo Finance / yfinance",
            "YfinanceFetcher": "Yahoo Finance / yfinance",
            "fallback": "備援資料",
            "realtime_quote": "即時行情",
        }
        return labels.get(text, text)

    @classmethod
    def _build_quote_availability_snapshot(
        cls,
        enhanced_context: Dict[str, Any],
        realtime_quote_raw: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        enhanced = enhanced_context if isinstance(enhanced_context, dict) else {}
        realtime = enhanced.get("realtime") if isinstance(enhanced.get("realtime"), dict) else {}
        quote = realtime_quote_raw or {}
        price = cls._positive_float(quote.get("price") or realtime.get("price"))
        source = quote.get("source") or realtime.get("source")
        symbol = (
            quote.get("code")
            or quote.get("symbol")
            or enhanced.get("code")
            or enhanced.get("stock_code")
        )
        fallback_from = quote.get("fallback_from") or realtime.get("fallback_from")

        if price is not None and symbol:
            degraded = bool(fallback_from) or str(source or "").strip().lower() == "fallback"
            return {
                "status": "degraded" if degraded else "available",
                "usable": True,
                "source_label": cls._quote_source_label("fallback" if degraded else source),
                "primary_source": source,
                "fallback_used": degraded,
                "reason": "primary_quote_failed_fallback_used" if degraded else None,
                "user_message": (
                    "即時行情部分降級，但已取得可用替代資料"
                    if degraded else
                    "即時行情可用"
                ),
            }

        today = enhanced.get("today") if isinstance(enhanced.get("today"), dict) else {}
        yesterday = enhanced.get("yesterday") if isinstance(enhanced.get("yesterday"), dict) else {}
        fallback_close = cls._positive_float(today.get("close") or yesterday.get("close"))
        if fallback_close is not None and symbol:
            return {
                "status": "degraded",
                "usable": True,
                "source_label": "備援資料",
                "primary_source": source,
                "fallback_used": True,
                "reason": "primary_quote_failed_fallback_used",
                "user_message": "即時行情部分降級，但已取得可用替代資料",
            }

        return {
            "status": "missing",
            "usable": False,
            "source_label": None,
            "primary_source": source,
            "fallback_used": False,
            "reason": "empty_or_incomplete_quote",
            "user_message": "即時行情未取得可用資料",
        }

    @staticmethod
    def _build_notification_run_snapshot(
        *,
        channel: str,
        status: str,
        success: bool,
        attempts: int = 1,
        error_message: Optional[Any] = None,
    ) -> Dict[str, Any]:
        payload = {
            "channel": channel,
            "status": status,
            "success": success,
            "attempts": attempts,
            "created_at": datetime.now().isoformat(),
        }
        sanitized_error = sanitize_diagnostic_text(error_message)
        if sanitized_error:
            payload["error_message_sanitized"] = sanitized_error
        return payload

    def _refresh_saved_diagnostic_snapshot(
        self,
        *,
        result: Optional[AnalysisResult] = None,
        results: Optional[List[AnalysisResult]] = None,
        fallback_code: Optional[str] = None,
        notification_run: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Patch persisted history diagnostics with notification outcomes."""
        if not getattr(self, "save_context_snapshot", True):
            return

        db = getattr(self, "db", None)
        updater = getattr(db, "update_analysis_history_diagnostics", None)
        if not callable(updater):
            return

        diagnostic_snapshot = current_diagnostic_snapshot()
        if diagnostic_snapshot is not None:
            query_id = (
                diagnostic_snapshot.get("query_id")
                or getattr(result, "query_id", None)
                or getattr(self, "query_id", None)
            )
            code = (
                getattr(result, "code", None)
                or fallback_code
                or diagnostic_snapshot.get("stock_code")
            )
            if not query_id:
                return
            try:
                updater(query_id=query_id, code=code, diagnostics=diagnostic_snapshot)
            except Exception as exc:
                logger.warning("回寫執行診斷快照失敗（fail-open）: %s", exc)
            return

        if notification_run is None:
            return

        target_results = list(results or ([] if result is None else [result]))
        for item in target_results:
            query_id = getattr(item, "query_id", None) or getattr(self, "query_id", None)
            if not query_id:
                continue
            code = getattr(item, "code", None) or fallback_code
            try:
                updater(
                    query_id=query_id,
                    code=code,
                    notification_runs=[notification_run],
                )
            except Exception as exc:
                logger.warning("回寫通知診斷快照失敗（fail-open）: %s", exc)

    def _build_legacy_analysis_artifacts(
        self,
        *,
        code: str,
        stock_name: str,
        market: str,
        phase: Optional[Dict[str, Any]],
        context: Dict[str, Any],
        enhanced_context: Dict[str, Any],
        realtime_quote: Any,
        trend_result: Optional[TrendAnalysisResult],
        chip_data: Optional[ChipDistribution],
        fundamental_context: Optional[Dict[str, Any]],
        news_context: Optional[str],
        news_result_count: Optional[int],
        query_id: str,
    ) -> PipelineAnalysisArtifacts:
        return PipelineAnalysisArtifacts(
            code=code,
            stock_name=stock_name,
            market=market,
            phase=phase,
            base_context=context,
            enhanced_context=enhanced_context,
            realtime_quote=realtime_quote,
            trend_result=trend_result,
            chip_data=chip_data,
            fundamental_context=fundamental_context,
            news_context=news_context,
            news_result_count=news_result_count,
            metadata={
                "query_id": query_id,
                "trigger_source": self.query_source,
            },
        )

    def _build_agent_analysis_artifacts(
        self,
        *,
        code: str,
        stock_name: str,
        market: str,
        phase: Optional[Dict[str, Any]],
        initial_context: Dict[str, Any],
        fundamental_context: Optional[Dict[str, Any]],
        query_id: str,
        base_context: Optional[Dict[str, Any]] = None,
    ) -> PipelineAnalysisArtifacts:
        context_candidate = base_context
        if not isinstance(context_candidate, dict):
            context_candidate = initial_context.get("analysis_context")
        if isinstance(context_candidate, dict) and context_candidate:
            daily_context = dict(context_candidate)
            daily_context.setdefault("code", code)
            if stock_name:
                daily_context.setdefault("stock_name", stock_name)
        else:
            daily_context = {
                "code": code,
                "stock_name": stock_name,
                "data_missing": True,
                "today": {},
                "yesterday": {},
            }

        return PipelineAnalysisArtifacts(
            code=code,
            stock_name=stock_name,
            market=market,
            phase=phase,
            base_context=daily_context,
            enhanced_context={},
            realtime_quote=initial_context.get("realtime_quote"),
            trend_result=initial_context.get("trend_result"),
            chip_data=initial_context.get("chip_distribution"),
            fundamental_context=fundamental_context,
            news_context=initial_context.get("news_context"),
            news_result_count=None,
            metadata={
                "query_id": query_id,
                "trigger_source": self.query_source,
            },
        )

    def _build_analysis_context_pack_outputs(
        self,
        artifacts: PipelineAnalysisArtifacts,
        *,
        report_language: str,
        code: str,
        query_id: str,
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        try:
            pack = AnalysisContextBuilder.build(artifacts)
            summary = format_analysis_context_pack_prompt_section(
                pack,
                report_language=report_language,
            )
            overview = render_analysis_context_pack_overview(
                pack,
                report_language=report_language,
            )
            return summary, overview
        except Exception as exc:
            logger.warning(
                "AnalysisContextPack output generation failed for %s query_id=%s: %s",
                code,
                query_id,
                exc,
            )
            return "", None

    @staticmethod
    def _without_runtime_prompt_context(context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Return a shallow copy without runtime-only prompt context.

        Market phase and AnalysisContextPack summaries are prompt inputs only.
        P4 stores only the separately rendered public overview at snapshot top level.
        """
        sanitized = dict(context)
        sanitized.pop("market_phase_context", None)
        sanitized.pop("analysis_context_pack", None)
        sanitized.pop("analysis_context_pack_summary", None)
        return sanitized

    _without_market_phase_context = _without_runtime_prompt_context

    @staticmethod
    def _resolve_resume_target_date(
        code: str, current_time: Optional[datetime] = None
    ) -> date:
        """
        Resolve the trading date used by checkpoint/resume checks.
        """
        market = get_market_for_stock(normalize_stock_code(code))
        return get_effective_trading_date(market, current_time=current_time)

    @staticmethod
    def _safe_to_dict(value: Any) -> Optional[Dict[str, Any]]:
        """
        安全轉換為字典
        """
        if value is None:
            return None
        if hasattr(value, "to_dict"):
            try:
                return value.to_dict()
            except Exception:
                return None
        if hasattr(value, "__dict__"):
            try:
                return dict(value.__dict__)
            except Exception:
                return None
        return None

    def _resolve_query_source(self, query_source: Optional[str] = None) -> str:
        """
        解析請求來源。

        優先順序（從高到低）：
        1. 顯式傳入的 query_source：呼叫方明確指定時優先使用，便於覆蓋推斷結果或相容未來 source_message 來自非 bot 的場景
        2. 存在 source_message 時推斷為 "bot"：當前約定為機器人會話上下文
        3. 存在 query_id 時推斷為 "web"：Web 觸發的請求會帶上 query_id
        4. 預設 "system"：定時任務或 CLI 等無上述上下文時

        Args:
            query_source: 呼叫方顯式指定的來源，如 "bot" / "web" / "cli" / "system"

        Returns:
            歸一化後的來源標識字串，如 "bot" / "web" / "cli" / "system"
        """
        if query_source:
            return query_source
        if getattr(self, "source_message", None):
            return "bot"
        if getattr(self, "query_id", None):
            return "web"
        return "system"

    def _build_query_context(self, query_id: Optional[str] = None) -> Dict[str, str]:
        """
        生成使用者查詢關聯資訊
        """
        effective_query_id = query_id or self.query_id or ""

        context: Dict[str, str] = {
            "query_id": effective_query_id,
            "query_source": self.query_source or "",
        }

        if self.source_message:
            context.update({
                "requester_platform": self.source_message.platform or "",
                "requester_user_id": self.source_message.user_id or "",
                "requester_user_name": self.source_message.user_name or "",
                "requester_chat_id": self.source_message.chat_id or "",
                "requester_message_id": self.source_message.message_id or "",
                "requester_query": self.source_message.content or "",
            })

        return context
    
    def process_single_stock(
        self,
        code: str,
        skip_analysis: bool = False,
        single_stock_notify: bool = False,
        report_type: ReportType = ReportType.SIMPLE,
        analysis_query_id: Optional[str] = None,
        current_time: Optional[datetime] = None,
        data_context_mode: str = "fetch",
        analysis_mode: str = "full",
        pre_built_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[AnalysisResult]:
        """
        處理單隻股票的完整流程

        包括：
        1. 獲取資料
        2. 儲存資料
        3. AI 分析
        4. 單股推送（可選，#55）

        此方法會被執行緒池呼叫，需要處理好異常

        Args:
            analysis_query_id: 查詢鏈路關聯 id
            code: 股票程式碼
            skip_analysis: 是否跳過 AI 分析
            single_stock_notify: 是否啟用單股推送模式（每分析完一隻立即推送）
            report_type: 報告型別列舉（從配置讀取，Issue #119）
            current_time: 本輪執行凍結的參考時間，用於統一斷點續傳目標交易日判斷

        Returns:
            AnalysisResult 或 None
        """
        logger.info(f"========== 開始處理 {code} ==========")

        from src.services.history_loader import set_frozen_target_date, reset_frozen_target_date
        frozen_td = self._resolve_resume_target_date(code, current_time=current_time)
        token = set_frozen_target_date(frozen_td)
        effective_query_id = analysis_query_id or getattr(self, "query_id", None) or uuid.uuid4().hex
        effective_trace_id = getattr(self, "trace_id", None) or effective_query_id
        diag_token = None
        if get_current_diagnostic_context() is None:
            diag_token = activate_run_diagnostic_context(
                trace_id=effective_trace_id,
                query_id=effective_query_id,
                stock_code=code,
                trigger_source=getattr(self, "query_source", None),
            )
        try:
            self._emit_progress(12, f"{code}：正在準備分析任務")
            # Step 1: 獲取並儲存資料
            if data_context_mode == "prebuilt":
                logger.info(f"[{code}] prebuilt mode: skipping data fetch")
                success, error = True, None
            else:
                success, error = self.fetch_and_save_stock_data(
                    code, current_time=current_time
                )

            if not success:
                logger.warning(f"[{code}] 資料獲取失敗: {error}")
                # 即使獲取失敗，也嘗試用已有資料分析
            else:
                self._emit_progress(16, f"{code}：行情資料準備完成")
            
            # Step 2: AI 分析
            if skip_analysis or analysis_mode == "dry_run":
                logger.info(f"[{code}] 跳過 AI 分析（dry_run 模式）")
                return None

            if analysis_mode == "fixture":
                return self._load_llm_fixture(code, effective_query_id)

            analyze_kwargs = {"query_id": effective_query_id}
            if current_time is not None:
                analyze_kwargs["current_time"] = current_time
            if data_context_mode == "prebuilt" and pre_built_context is not None:
                result = self._analyze_with_prebuilt(
                    code, pre_built_context, report_type, effective_query_id, current_time
                )
            else:
                result = self.analyze_stock(code, report_type, **analyze_kwargs)
            
            if result and result.success:
                logger.info(
                    f"[{code}] 分析完成: {result.operation_advice}, "
                    f"評分 {result.sentiment_score}"
                )
                
                # 單股推送模式（#55）：每分析完一隻股票立即推送
                if single_stock_notify:
                    self._send_single_stock_notification(
                        result,
                        report_type=report_type,
                        fallback_code=code,
                    )
            elif result:
                logger.warning(
                    f"[{code}] 分析未成功: {result.error_message or '未知錯誤'}"
                )
            
            return result
            
        except Exception as e:
            # 捕獲所有異常，確保單股失敗不影響整體
            logger.exception(f"[{code}] 處理過程發生未知異常: {e}")
            return None
        finally:
            reset_run_diagnostic_context(diag_token)
            reset_frozen_target_date(token)
    
    def _load_llm_fixture(self, code: str, query_id: str = "") -> Optional[AnalysisResult]:
        """Return a canned AnalysisResult from tests/fixtures/llm/<code>.json.

        Fixture filenames use underscores instead of colons so they are safe
        across all filesystems (e.g. TW:2330 → TW_2330.json).
        """
        import json
        import os
        import re as _re
        safe_name = _re.sub(r"[^A-Za-z0-9_\-]", "_", code)
        fixture_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "tests", "fixtures", "llm",
        )
        fixture_path = os.path.join(fixture_dir, f"{safe_name}.json")
        _fixture_lang = normalize_report_language(getattr(self.config, "report_language", "zh"))
        if not os.path.abspath(fixture_path).startswith(os.path.abspath(fixture_dir) + os.sep):
            logger.warning(f"[{code}] LLM fixture path rejected: {fixture_path}")
            result = AnalysisResult(
                code=code,
                name=code,
                sentiment_score=50,
                trend_prediction=localize_trend_prediction("sideways", _fixture_lang),
                operation_advice=localize_operation_advice("watch", _fixture_lang),
                success=False,
                error_message=f"fixture_path_rejected: {safe_name}.json",
            )
            result.query_id = query_id
            return result
        if not os.path.exists(fixture_path):
            logger.warning(f"[{code}] LLM fixture not found: {fixture_path}")
            result = AnalysisResult(
                code=code,
                name=code,
                sentiment_score=50,
                trend_prediction=localize_trend_prediction("sideways", _fixture_lang),
                operation_advice=localize_operation_advice("watch", _fixture_lang),
                success=False,
                error_message=f"fixture_not_found: {safe_name}.json",
            )
            result.query_id = query_id
            return result
        try:
            with open(fixture_path, encoding="utf-8") as fh:
                data = json.load(fh)
            _data_lang = normalize_report_language(data.get("report_language", _fixture_lang))
            result = AnalysisResult(
                code=data.get("code", code),
                name=data.get("name", code),
                sentiment_score=int(data.get("sentiment_score", 50)),
                trend_prediction=localize_trend_prediction(data.get("trend_prediction", "sideways"), _data_lang),
                operation_advice=localize_operation_advice(data.get("operation_advice", "watch"), _data_lang),
                decision_type=data.get("decision_type", "hold"),
                confidence_level=data.get("confidence_level", "中"),
                report_language=_data_lang,
                analysis_summary=data.get("analysis_summary", ""),
                trend_analysis=data.get("trend_analysis", ""),
                short_term_outlook=data.get("short_term_outlook", ""),
                medium_term_outlook=data.get("medium_term_outlook", ""),
                technical_analysis=data.get("technical_analysis", ""),
                risk_warning=data.get("risk_warning", ""),
                success=bool(data.get("success", True)),
            )
            result.query_id = query_id
            return result
        except Exception as exc:
            logger.error(f"[{code}] Failed to load LLM fixture: {exc}")
            result = AnalysisResult(
                code=code,
                name=code,
                sentiment_score=50,
                trend_prediction=localize_trend_prediction("sideways", _fixture_lang),
                operation_advice=localize_operation_advice("watch", _fixture_lang),
                success=False,
                error_message=f"fixture_load_error: {exc}",
            )
            result.query_id = query_id
            return result

    def _analyze_with_prebuilt(
        self,
        code: str,
        pre_built_context: Dict[str, Any],
        report_type: ReportType,
        query_id: str,
        current_time: Optional[datetime] = None,
    ) -> Optional[AnalysisResult]:
        """Call GeminiAnalyzer.analyze() directly with a caller-supplied context dict.

        This path skips all data-fetch steps (realtime quote, chips, DB read,
        trend analysis, news search) while keeping the full LLM analysis path
        active.  The caller is responsible for building a well-formed context
        dict (see adapters/snapshot_schema.py: SnapshotContext).
        """
        news_context: Optional[str] = pre_built_context.get("news_context")  # type: ignore[assignment]
        news_context = cap_news_context(news_context)
        analyzer_context = dict(pre_built_context)
        if not analyzer_context.get("stock_name") and analyzer_context.get("name"):
            analyzer_context["stock_name"] = analyzer_context["name"]
        try:
            result = self.analyzer.analyze(
                analyzer_context,
                news_context=news_context,
                progress_callback=self._emit_progress,
            )
            if result:
                result.query_id = query_id
            return result
        except Exception as exc:
            logger.error(f"[{code}] prebuilt analysis failed: {exc}", exc_info=True)
            _pb_lang = normalize_report_language(getattr(self.config, "report_language", "zh"))
            result = AnalysisResult(
                code=code,
                name=pre_built_context.get("name", code),
                sentiment_score=50,
                trend_prediction=localize_trend_prediction("sideways", _pb_lang),
                operation_advice=localize_operation_advice("watch", _pb_lang),
                success=False,
                error_message=str(exc),
            )
            result.query_id = query_id
            return result

    def run(
        self,
        stock_codes: Optional[List[str]] = None,
        dry_run: bool = False,
        send_notification: bool = True,
        merge_notification: bool = False
    ) -> List[AnalysisResult]:
        """
        執行完整的分析流程

        流程：
        1. 獲取待分析的股票列表
        2. 使用執行緒池併發處理
        3. 收集分析結果
        4. 傳送通知

        Args:
            stock_codes: 股票程式碼列表（可選，預設使用配置中的自選股）
            dry_run: 是否僅獲取資料不分析
            send_notification: 是否傳送推送通知
            merge_notification: 是否合併推送（跳過本次推送，由 main 層合併個股+大盤後統一傳送，Issue #190）

        Returns:
            分析結果列表
        """
        start_time = time.time()
        
        # 使用配置中的股票列表
        if stock_codes is None:
            self.config.refresh_stock_list()
            stock_codes = self.config.stock_list
        
        if not stock_codes:
            logger.error("未配置自選股列表，請在 .env 檔案中設定 STOCK_LIST")
            return []
        
        logger.info(f"===== 開始分析 {len(stock_codes)} 只股票 =====")
        logger.info(f"股票列表: {', '.join(stock_codes)}")
        logger.info(f"併發數: {self.max_workers}, 模式: {'僅獲取資料' if dry_run else '完整分析'}")

        # 凍結本輪執行的統一參考時間，避免跨市場收盤邊界時同批股票使用不同目標交易日。
        resume_reference_time = datetime.now(timezone.utc)
        
        # === 批次預取實時行情（最佳化：避免每隻股票都觸發全量拉取）===
        # 只有股票數量 >= 5 時才進行預取，少量股票直接逐個查詢更高效
        if len(stock_codes) >= 5:
            prefetch_count = self.fetcher_manager.prefetch_realtime_quotes(stock_codes)
            if prefetch_count > 0:
                logger.info(f"已啟用批次預取架構：一次拉取全市場資料，{len(stock_codes)} 只股票共享快取")

        # Issue #455: 預取股票名稱，避免併發分析時顯示「股票xxxxx」
        # dry_run 僅做資料拉取，不需要名稱預取，避免額外網路開銷
        if not dry_run:
            self.fetcher_manager.prefetch_stock_names(stock_codes, use_bulk=False)

        # 單股推送模式（#55）：從配置讀取
        single_stock_notify = getattr(self.config, 'single_stock_notify', False)
        # Issue #119: 從配置讀取報告型別
        report_type_str = getattr(self.config, 'report_type', 'simple').lower()
        if report_type_str == 'brief':
            report_type = ReportType.BRIEF
        elif report_type_str == 'full':
            report_type = ReportType.FULL
        else:
            report_type = ReportType.SIMPLE
        # Issue #128: 從配置讀取分析間隔
        analysis_delay = getattr(self.config, 'analysis_delay', 0)

        if single_stock_notify:
            logger.info(
                "已啟用單股推送模式：分析仍併發執行，通知改為在結果收集側序列傳送（報告型別: %s）",
                report_type_str,
            )
        
        results: List[AnalysisResult] = []
        
        # 使用執行緒池併發處理
        # 注意：max_workers 設定較低（預設3）以避免觸發反爬
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交任務
            future_to_code = {
                executor.submit(
                    self.process_single_stock,
                    code,
                    skip_analysis=dry_run,
                    single_stock_notify=False,
                    report_type=report_type,  # Issue #119: 傳遞報告型別
                    analysis_query_id=uuid.uuid4().hex,
                    current_time=resume_reference_time,
                ): code
                for code in stock_codes
            }
            
            # 收集結果
            for idx, future in enumerate(as_completed(future_to_code)):
                code = future_to_code[future]
                try:
                    result = future.result()
                    if result and result.success:
                        results.append(result)
                        if single_stock_notify and send_notification and not dry_run:
                            self._send_single_stock_notification(
                                result,
                                report_type=report_type,
                                fallback_code=code,
                            )
                    elif result and not result.success:
                        logger.warning(
                            f"[{code}] 分析結果標記為失敗，不計入彙總: "
                            f"{result.error_message or '未知原因'}"
                        )

                    # Issue #128: 分析間隔 - 在個股分析和大盤分析之間新增延遲
                    if idx < len(stock_codes) - 1 and analysis_delay > 0:
                        # 注意：此 sleep 發生在“主執行緒收集 future 的迴圈”中，
                        # 並不會阻止執行緒池中的任務同時發起網路請求。
                        # 因此它對降低併發請求峰值的效果有限；真正的峰值主要由 max_workers 決定。
                        # 該行為目前保留（按需求不改邏輯）。
                        logger.debug(f"等待 {analysis_delay} 秒後繼續下一隻股票...")
                        time.sleep(analysis_delay)

                except Exception as e:
                    logger.error(f"[{code}] 任務執行失敗: {e}")
        
        # 統計
        elapsed_time = time.time() - start_time
        
        # dry-run 模式下，資料獲取成功即視為成功
        if dry_run:
            # 檢查哪些股票的最新可複用交易日資料已存在
            success_count = sum(
                1
                for code in stock_codes
                if self.db.has_today_data(
                    code,
                    self._resolve_resume_target_date(
                        code, current_time=resume_reference_time
                    ),
                )
            )
            fail_count = len(stock_codes) - success_count
        else:
            success_count = len(results)
            fail_count = len(stock_codes) - success_count
        
        logger.info("===== 分析完成 =====")
        logger.info(f"成功: {success_count}, 失敗: {fail_count}, 耗時: {elapsed_time:.2f} 秒")
        
        # 儲存報告到本地檔案（無論是否推送通知都儲存）
        if results and not dry_run:
            self._save_local_report(results, report_type)

        # 傳送通知（單股推送模式下跳過彙總推送，避免重複）
        if results and send_notification and not dry_run:
            if single_stock_notify:
                # 單股推送模式：只儲存彙總報告，不再重複推送
                logger.info("單股推送模式：跳過彙總推送，僅儲存報告到本地")
                self._send_notifications(results, report_type, skip_push=True)
            elif merge_notification:
                # 合併模式（Issue #190）：僅儲存，不推送，由 main 層合併個股+大盤後統一傳送
                logger.info("合併推送模式：跳過本次推送，將在個股+大盤覆盤後統一傳送")
                self._send_notifications(results, report_type, skip_push=True)
            else:
                self._send_notifications(results, report_type)
        
        return results

    def _send_single_stock_notification(
        self,
        result: AnalysisResult,
        report_type: ReportType = ReportType.SIMPLE,
        fallback_code: Optional[str] = None,
    ) -> None:
        """傳送單股通知，供直接單股入口和批次序列推送共用。"""
        if not self.notifier.is_available():
            notification_run = self._build_notification_run_snapshot(
                channel="report",
                status="not_configured",
                success=False,
                attempts=0,
            )
            record_notification_run(
                channel="report",
                status="not_configured",
                success=False,
                attempts=0,
            )
            self._refresh_saved_diagnostic_snapshot(
                result=result,
                fallback_code=fallback_code,
                notification_run=notification_run,
            )
            return

        stock_code = getattr(result, "code", None) or fallback_code or "unknown"
        notify_lock = getattr(self, "_single_stock_notify_lock", None)
        if notify_lock is None:
            with _SINGLE_STOCK_NOTIFY_LOCK_INIT_GUARD:
                notify_lock = getattr(self, "_single_stock_notify_lock", None)
                if notify_lock is None:
                    notify_lock = threading.Lock()
                    setattr(self, "_single_stock_notify_lock", notify_lock)

        with notify_lock:
            try:
                if report_type == ReportType.FULL:
                    report_content = self.notifier.generate_dashboard_report([result])
                    logger.info(f"[{stock_code}] 使用完整報告格式")
                elif report_type == ReportType.BRIEF:
                    report_content = self.notifier.generate_brief_report([result])
                    logger.info(f"[{stock_code}] 使用簡潔報告格式")
                else:
                    report_content = self.notifier.generate_single_stock_report(result)
                    logger.info(f"[{stock_code}] 使用精簡報告格式")

                sent = self.notifier.send(
                    report_content,
                    email_stock_codes=[stock_code],
                    route_type="report",
                    severity="info",
                    dedup_key=f"report:single:{stock_code}:{report_type.value}",
                    cooldown_key=f"report:single:{stock_code}:{report_type.value}",
                )
                notification_run = self._build_notification_run_snapshot(
                    channel="report",
                    status="success" if sent else "failed",
                    success=sent,
                )
                record_notification_run(
                    channel="report",
                    status="success" if sent else "failed",
                    success=sent,
                )
                self._refresh_saved_diagnostic_snapshot(
                    result=result,
                    fallback_code=fallback_code,
                    notification_run=notification_run,
                )
                if sent:
                    logger.info(f"[{stock_code}] 單股推送成功")
                else:
                    logger.warning(f"[{stock_code}] 單股推送失敗")
            except Exception as e:
                notification_run = self._build_notification_run_snapshot(
                    channel="report",
                    status="failed",
                    success=False,
                    error_message=e,
                )
                record_notification_run(
                    channel="report",
                    status="failed",
                    success=False,
                    error_message=e,
                )
                self._refresh_saved_diagnostic_snapshot(
                    result=result,
                    fallback_code=fallback_code,
                    notification_run=notification_run,
                )
                logger.error(f"[{stock_code}] 單股推送異常: {e}")

    def _save_local_report(
        self,
        results: List[AnalysisResult],
        report_type: ReportType = ReportType.SIMPLE,
    ) -> None:
        """儲存分析報告到本地檔案（與通知推送解耦）"""
        try:
            from src.core.zh_tw_localization import localize_if_route_b
            report = self._generate_aggregate_report(results, report_type)
            report = localize_if_route_b(report)
            filepath = self.notifier.save_report_to_file(report)
            logger.info(f"決策儀表盤日報已儲存: {filepath}")
        except Exception as e:
            logger.error(f"儲存本地報告失敗: {e}")

    def _send_notifications(
        self,
        results: List[AnalysisResult],
        report_type: ReportType = ReportType.SIMPLE,
        skip_push: bool = False,
    ) -> None:
        """
        傳送分析結果通知
        
        生成決策儀表盤格式的報告
        
        Args:
            results: 分析結果列表
            skip_push: 是否跳過推送（僅儲存到本地，用於單股推送模式）
        """
        noise_decision = None
        noise_finalized = False
        try:
            logger.info("生成決策儀表盤日報...")
            report = self._generate_aggregate_report(results, report_type)
            
            # 跳過推送（單股推送模式 / 合併模式：報告已由 _save_local_report 儲存）
            if skip_push:
                notification_run = self._build_notification_run_snapshot(
                    channel="report",
                    status="skipped",
                    success=False,
                    attempts=0,
                )
                record_notification_run(
                    channel="report",
                    status="skipped",
                    success=False,
                    attempts=0,
                )
                self._refresh_saved_diagnostic_snapshot(
                    results=results,
                    notification_run=notification_run,
                )
                return
            
            # 推送通知
            if self.notifier.is_available():
                channels = self.notifier.get_available_channels()
                channels = self.notifier.get_channels_for_route("report", channels=channels)

                def _send_channel_safely(
                    channel_label: str,
                    send_func: Callable[[], bool],
                ) -> tuple[bool, Optional[Exception]]:
                    try:
                        return bool(send_func()), None
                    except Exception as e:
                        logger.exception(
                            "通知通道 %s 推送異常，繼續嘗試其他通道: %s",
                            channel_label,
                            e,
                        )
                        return False, e

                def _record_channel_result(
                    channel_label: str,
                    success: bool,
                    error_message: Optional[Exception] = None,
                    target_results: Optional[List[AnalysisResult]] = None,
                ) -> None:
                    notification_run = self._build_notification_run_snapshot(
                        channel=channel_label,
                        status="success" if success else "failed",
                        success=success,
                        error_message=error_message,
                    )
                    record_notification_run(
                        channel=channel_label,
                        status="success" if success else "failed",
                        success=success,
                        error_message=error_message,
                    )
                    self._refresh_saved_diagnostic_snapshot(
                        results=results if target_results is None else target_results,
                        notification_run=notification_run,
                    )

                send_context = self.notifier.send_to_context(report)
                if send_context:
                    _record_channel_result("__context__", True)

                should_broadcast_static = True
                should_broadcast_static_func = getattr(
                    self.notifier,
                    "should_broadcast_static_channels",
                    None,
                )
                if callable(should_broadcast_static_func):
                    should_broadcast_static = bool(should_broadcast_static_func())
                if not should_broadcast_static:
                    if not send_context:
                        _record_channel_result("__context__", False)
                    if send_context:
                        logger.info("決策儀表盤推送成功")
                    else:
                        logger.warning("決策儀表盤推送失敗")
                    logger.info("互動式訊息上下文回覆模式：已跳過靜態通知通道")
                    return

                if channels and hasattr(self.notifier, "evaluate_noise_control"):
                    report_type_key = report_type.value if isinstance(report_type, ReportType) else str(report_type)
                    codes_key = ",".join(
                        sorted(str(getattr(result, "code", "") or "") for result in results)
                    )
                    noise_key = f"report:aggregate:{report_type_key}:{codes_key}"
                    noise_decision = self.notifier.evaluate_noise_control(
                        report,
                        route_type="report",
                        severity="info",
                        dedup_key=noise_key,
                        cooldown_key=noise_key,
                    )
                    if not noise_decision.should_send:
                        notification_run = self._build_notification_run_snapshot(
                            channel="report",
                            status="skipped",
                            success=False,
                            attempts=0,
                        )
                        record_notification_run(
                            channel="report",
                            status="skipped",
                            success=False,
                            attempts=0,
                        )
                        self._refresh_saved_diagnostic_snapshot(
                            results=results,
                            notification_run=notification_run,
                        )
                        logger.info(noise_decision.message)
                        return

                # Issue #455: Markdown 轉圖片（與 notification.send 邏輯一致）
                from src.md2img import markdown_to_image

                channels_needing_image = {
                    ch for ch in channels
                    if ch.value in self.notifier._markdown_to_image_channels
                    and ch not in {NotificationChannel.NTFY, NotificationChannel.GOTIFY}
                }
                non_wechat_channels_needing_image = {
                    ch for ch in channels_needing_image if ch != NotificationChannel.WECHAT
                }

                def _get_md2img_hint() -> str:
                    try:
                        engine = getattr(get_config(), "md2img_engine", "wkhtmltoimage")
                    except Exception:
                        engine = "wkhtmltoimage"
                    return (
                        "npm i -g markdown-to-file" if engine == "markdown-to-file"
                        else "wkhtmltopdf (apt install wkhtmltopdf / brew install wkhtmltopdf)"
                    )

                image_bytes = None
                if non_wechat_channels_needing_image:
                    image_bytes = markdown_to_image(
                        report, max_chars=self.notifier._markdown_to_image_max_chars
                    )
                    if image_bytes:
                        logger.info(
                            "Markdown 已轉換為圖片，將向 %s 傳送圖片",
                            [ch.value for ch in non_wechat_channels_needing_image],
                        )
                    else:
                        logger.warning(
                            "Markdown 轉圖片失敗，將回退為文字傳送。請檢查 MARKDOWN_TO_IMAGE_CHANNELS 配置並安裝 %s",
                            _get_md2img_hint(),
                        )

                # 企業微信：只發精簡版（平臺限制）
                wechat_success = False
                if NotificationChannel.WECHAT in channels:
                    def _send_wechat_report() -> bool:
                        if report_type == ReportType.BRIEF:
                            dashboard_content = self.notifier.generate_brief_report(results)
                        else:
                            dashboard_content = self.notifier.generate_wechat_dashboard(results)
                        logger.info(f"企業微信儀表盤長度: {len(dashboard_content)} 字元")
                        logger.debug(f"企業微信推送內容:\n{dashboard_content}")
                        wechat_image_bytes = None
                        if NotificationChannel.WECHAT in channels_needing_image:
                            wechat_image_bytes = markdown_to_image(
                                dashboard_content,
                                max_chars=self.notifier._markdown_to_image_max_chars,
                            )
                            if wechat_image_bytes is None:
                                logger.warning(
                                    "企業微信 Markdown 轉圖片失敗，將回退為文字傳送。請檢查 MARKDOWN_TO_IMAGE_CHANNELS 配置並安裝 %s",
                                    _get_md2img_hint(),
                                )
                        use_image = self.notifier._should_use_image_for_channel(
                            NotificationChannel.WECHAT, wechat_image_bytes
                        )
                        if use_image:
                            return self.notifier._send_wechat_image(wechat_image_bytes)
                        return self.notifier.send_to_wechat(dashboard_content)

                    wechat_success, wechat_error = _send_channel_safely(
                        NotificationChannel.WECHAT.value,
                        _send_wechat_report,
                    )
                    _record_channel_result(
                        NotificationChannel.WECHAT.value,
                        wechat_success,
                        wechat_error,
                    )

                # 其他通道：發完整報告（避免自定義 Webhook 被 wechat 截斷邏輯汙染）
                non_wechat_success = False
                stock_email_groups = getattr(self.config, 'stock_email_groups', []) or []
                for channel in channels:
                    if channel == NotificationChannel.WECHAT:
                        continue
                    if channel == NotificationChannel.FEISHU:
                        channel_success, channel_error = _send_channel_safely(
                            channel.value,
                            lambda: self.notifier.send_to_feishu(report),
                        )
                        non_wechat_success = channel_success or non_wechat_success
                        _record_channel_result(
                            channel.value,
                            channel_success,
                            channel_error,
                        )
                    elif channel == NotificationChannel.TELEGRAM:
                        def _send_telegram_report() -> bool:
                            use_image = self.notifier._should_use_image_for_channel(
                                channel, image_bytes
                            )
                            if use_image:
                                return self.notifier._send_telegram_photo(image_bytes)
                            return self.notifier.send_to_telegram(report)

                        channel_success, channel_error = _send_channel_safely(
                            channel.value,
                            _send_telegram_report,
                        )
                        non_wechat_success = channel_success or non_wechat_success
                        _record_channel_result(
                            channel.value,
                            channel_success,
                            channel_error,
                        )
                    elif channel == NotificationChannel.EMAIL:
                        if stock_email_groups:
                            code_to_emails: Dict[str, Optional[List[str]]] = {}
                            for r in results:
                                if r.code not in code_to_emails:
                                    canonical = normalize_stock_code(r.code)
                                    emails = []
                                    for stocks, emails_list in stock_email_groups:
                                        if canonical in stocks:
                                            emails.extend(emails_list)
                                    code_to_emails[r.code] = list(dict.fromkeys(emails)) if emails else None
                            emails_to_results: Dict[Optional[Tuple], List] = defaultdict(list)
                            for r in results:
                                recs = code_to_emails.get(r.code)
                                key = tuple(recs) if recs else None
                                emails_to_results[key].append(r)
                            for key, group_results in emails_to_results.items():
                                receivers = list(key) if key is not None else None

                                def _send_email_group(
                                    group_results=group_results,
                                    receivers=receivers,
                                ) -> bool:
                                    grp_report = self._generate_aggregate_report(group_results, report_type)
                                    grp_image_bytes = None
                                    if channel.value in self.notifier._markdown_to_image_channels:
                                        grp_image_bytes = markdown_to_image(
                                            grp_report,
                                            max_chars=self.notifier._markdown_to_image_max_chars,
                                        )
                                    use_image = self.notifier._should_use_image_for_channel(
                                        channel, grp_image_bytes
                                    )
                                    if use_image:
                                        return self.notifier._send_email_with_inline_image(
                                            grp_image_bytes, receivers=receivers
                                        )
                                    return self.notifier.send_to_email(
                                        grp_report, receivers=receivers
                                    )

                                email_label = (
                                    f"{channel.value}:{','.join(receivers)}"
                                    if receivers else f"{channel.value}:default"
                                )
                                channel_success, channel_error = _send_channel_safely(
                                    email_label,
                                    _send_email_group,
                                )
                                non_wechat_success = channel_success or non_wechat_success
                                _record_channel_result(
                                    email_label,
                                    channel_success,
                                    channel_error,
                                    target_results=group_results,
                                )
                        else:
                            def _send_email_report() -> bool:
                                use_image = self.notifier._should_use_image_for_channel(
                                    channel, image_bytes
                                )
                                if use_image:
                                    return self.notifier._send_email_with_inline_image(image_bytes)
                                return self.notifier.send_to_email(report)

                            channel_success, channel_error = _send_channel_safely(
                                channel.value,
                                _send_email_report,
                            )
                            non_wechat_success = channel_success or non_wechat_success
                            _record_channel_result(
                                channel.value,
                                channel_success,
                                channel_error,
                            )
                    elif channel == NotificationChannel.CUSTOM:
                        def _send_custom_report() -> bool:
                            use_image = self.notifier._should_use_image_for_channel(
                                channel, image_bytes
                            )
                            if use_image:
                                return self.notifier._send_custom_webhook_image(
                                    image_bytes, fallback_content=report
                                )
                            return self.notifier.send_to_custom(report)

                        channel_success, channel_error = _send_channel_safely(
                            channel.value,
                            _send_custom_report,
                        )
                        non_wechat_success = channel_success or non_wechat_success
                        _record_channel_result(
                            channel.value,
                            channel_success,
                            channel_error,
                        )
                    elif channel == NotificationChannel.PUSHPLUS:
                        channel_success, channel_error = _send_channel_safely(
                            channel.value,
                            lambda: self.notifier.send_to_pushplus(report),
                        )
                        non_wechat_success = channel_success or non_wechat_success
                        _record_channel_result(
                            channel.value,
                            channel_success,
                            channel_error,
                        )
                    elif channel == NotificationChannel.SERVERCHAN3:
                        channel_success, channel_error = _send_channel_safely(
                            channel.value,
                            lambda: self.notifier.send_to_serverchan3(report),
                        )
                        non_wechat_success = channel_success or non_wechat_success
                        _record_channel_result(
                            channel.value,
                            channel_success,
                            channel_error,
                        )
                    elif channel == NotificationChannel.DISCORD:
                        channel_success, channel_error = _send_channel_safely(
                            channel.value,
                            lambda: self.notifier.send_to_discord(report),
                        )
                        non_wechat_success = channel_success or non_wechat_success
                        _record_channel_result(
                            channel.value,
                            channel_success,
                            channel_error,
                        )
                    elif channel == NotificationChannel.PUSHOVER:
                        channel_success, channel_error = _send_channel_safely(
                            channel.value,
                            lambda: self.notifier.send_to_pushover(report),
                        )
                        non_wechat_success = channel_success or non_wechat_success
                        _record_channel_result(
                            channel.value,
                            channel_success,
                            channel_error,
                        )
                    elif channel == NotificationChannel.NTFY:
                        channel_success, channel_error = _send_channel_safely(
                            channel.value,
                            lambda: self.notifier.send_to_ntfy(report),
                        )
                        non_wechat_success = channel_success or non_wechat_success
                        _record_channel_result(
                            channel.value,
                            channel_success,
                            channel_error,
                        )
                    elif channel == NotificationChannel.GOTIFY:
                        channel_success, channel_error = _send_channel_safely(
                            channel.value,
                            lambda: self.notifier.send_to_gotify(report),
                        )
                        non_wechat_success = channel_success or non_wechat_success
                        _record_channel_result(
                            channel.value,
                            channel_success,
                            channel_error,
                        )
                    elif channel == NotificationChannel.ASTRBOT:
                        channel_success, channel_error = _send_channel_safely(
                            channel.value,
                            lambda: self.notifier.send_to_astrbot(report),
                        )
                        non_wechat_success = channel_success or non_wechat_success
                        _record_channel_result(
                            channel.value,
                            channel_success,
                            channel_error,
                        )
                    elif channel == NotificationChannel.SLACK:
                        def _send_slack_report() -> bool:
                            use_image = self.notifier._should_use_image_for_channel(
                                channel, image_bytes
                            )
                            if use_image and self.notifier._slack_bot_token and self.notifier._slack_channel_id:
                                return self.notifier._send_slack_image(
                                    image_bytes, fallback_content=report
                                )
                            return self.notifier.send_to_slack(report)

                        channel_success, channel_error = _send_channel_safely(
                            channel.value,
                            _send_slack_report,
                        )
                        non_wechat_success = channel_success or non_wechat_success
                        _record_channel_result(
                            channel.value,
                            channel_success,
                            channel_error,
                        )
                    else:
                        logger.warning(f"未知通知通道: {channel}")

                has_targeted_channels = bool(channels)
                success = wechat_success or non_wechat_success or send_context
                if (
                    (wechat_success or non_wechat_success)
                    and noise_decision is not None
                    and hasattr(self.notifier, "record_noise_control")
                ):
                    self.notifier.record_noise_control(noise_decision)
                    noise_finalized = True
                elif (
                    noise_decision is not None
                    and hasattr(self.notifier, "release_noise_control")
                ):
                    self.notifier.release_noise_control(noise_decision)
                    noise_finalized = True
                if success:
                    logger.info("決策儀表盤推送成功")
                else:
                    logger.warning("決策儀表盤推送失敗")
                if not has_targeted_channels and not send_context:
                    channel_label = ",".join(channel.value for channel in channels) or "report"
                    notification_run = self._build_notification_run_snapshot(
                        channel=channel_label,
                        status="success" if success else "failed",
                        success=success,
                    )
                    record_notification_run(
                        channel=channel_label,
                        status="success" if success else "failed",
                        success=success,
                    )
                    self._refresh_saved_diagnostic_snapshot(
                        results=results,
                        notification_run=notification_run,
                    )
            else:
                notification_run = self._build_notification_run_snapshot(
                    channel="report",
                    status="not_configured",
                    success=False,
                    attempts=0,
                )
                record_notification_run(
                    channel="report",
                    status="not_configured",
                    success=False,
                    attempts=0,
                )
                self._refresh_saved_diagnostic_snapshot(
                    results=results,
                    notification_run=notification_run,
                )
                logger.info("通知通道未配置，跳過推送")
                
        except Exception as e:
            notification_run = self._build_notification_run_snapshot(
                channel="report",
                status="failed",
                success=False,
                error_message=e,
            )
            record_notification_run(
                channel="report",
                status="failed",
                success=False,
                error_message=e,
            )
            self._refresh_saved_diagnostic_snapshot(
                results=results,
                notification_run=notification_run,
            )
            if (
                noise_decision is not None
                and not noise_finalized
                and hasattr(self.notifier, "release_noise_control")
            ):
                self.notifier.release_noise_control(noise_decision)
            import traceback
            logger.error(f"傳送通知失敗: {e}\n{traceback.format_exc()}")

    def _generate_aggregate_report(
        self,
        results: List[AnalysisResult],
        report_type: ReportType,
    ) -> str:
        """Generate aggregate report with backward-compatible notifier fallback."""
        generator = getattr(self.notifier, "generate_aggregate_report", None)
        if callable(generator):
            return generator(results, report_type)
        if report_type == ReportType.BRIEF and hasattr(self.notifier, "generate_brief_report"):
            return self.notifier.generate_brief_report(results)
        return self.notifier.generate_dashboard_report(results)
