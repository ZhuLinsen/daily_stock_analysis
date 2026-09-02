# -*- coding: utf-8 -*-
"""
===================================
股票分析命令
===================================

分析指定股票或已登记指数，调用 AI 生成分析报告。
"""

import logging
import re
import unicodedata
from dataclasses import replace
from typing import List, Optional, Tuple, Union

from bot.commands.base import BotCommand
from bot.models import BotMessage, BotResponse
from src.services.stock_code_utils import is_code_like, resolve_index_stock_code_for_analysis
from src.services.stock_list_parser import (
    AnalysisTarget,
    ParseStatus,
    default_index_registry,
    parse_analysis_target,
)

logger = logging.getLogger(__name__)


class AnalyzeCommand(BotCommand):
    """
    股票分析命令
    
    分析指定股票代码或已登记指数，生成 AI 分析报告并推送。
    
    用法：
        /analyze 600519       - 分析贵州茅台（精简报告）
        /analyze 600519 full  - 分析并生成完整报告
        /analyze sh000016     - 分析上证50指数
        /analyze 930955.CSI   - 分析红利低波100指数（alias 收敛）
        /analyze 上证50       - 按注册名称分析上证50指数
    """
    
    @property
    def name(self) -> str:
        return "analyze"
    
    @property
    def aliases(self) -> List[str]:
        return ["a", "分析", "查"]
    
    @property
    def description(self) -> str:
        return "分析指定股票或指数"
    
    @property
    def usage(self) -> str:
        return "/analyze <股票代码/指数代码/指数名称> [full]"
    
    def validate_args(self, args: List[str]) -> Optional[str]:
        """验证参数（仅结构检查；语义校验在 execute 中完成）"""
        if not args:
            return "请输入股票代码或指数名称"
        return None
    
    def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
        """执行分析命令"""
        raw = (args[0] or "").strip()
        if not raw:
            return BotResponse.error_response("请输入股票代码或指数名称")

        # 检查是否需要完整报告（默认精简，传 full/完整/详细 切换）
        report_type = "simple"
        if len(args) > 1 and args[1].lower() in ["full", "完整", "详细"]:
            report_type = "full"

        try:
            code, analysis_target = self._resolve_analysis_input(raw)
            if code is None:
                error_msg = analysis_target
                if not isinstance(error_msg, str):
                    error_msg = "无法识别标的"
                return BotResponse.error_response(error_msg)
            if isinstance(analysis_target, str):
                return BotResponse.error_response(analysis_target)

            logger.info(f"[AnalyzeCommand] 分析标的: {code}, 报告类型: {report_type}")

            # 调用分析服务
            from src.services.task_service import get_task_service
            from src.enums import ReportType

            service = get_task_service()

            # 提交异步分析任务
            result = service.submit_analysis(
                code=code,
                report_type=ReportType.from_str(report_type),
                source_message=message,
                analysis_target=analysis_target,
            )

            if result.get("success"):
                task_id = result.get("task_id", "")
                # ``extra`` 仅供内部任务 identity 透传（transport-independent
                # 消费者，如 E2E smoke），文本保持既有契约不变，平台适配器可忽略。
                response = BotResponse.markdown_response(
                    f"✅ **分析任务已提交**\n\n"
                    f"• 标的: `{code}`\n"
                    f"• 报告类型: {ReportType.from_str(report_type).display_name}\n"
                    f"• 任务 ID: `{task_id[:20]}...`\n\n"
                    f"分析完成后将自动推送结果。"
                )
                response.extra = {
                    "task_id": task_id,
                    "stock_code": code,
                }
                return response
            error = result.get("error", "未知错误")
            return BotResponse.error_response(f"提交分析任务失败: {error}")

        except Exception as e:
            logger.error(f"[AnalyzeCommand] 执行失败: {e}")
            return BotResponse.error_response(f"分析失败: {str(e)[:100]}")

    def _resolve_analysis_input(
        self, raw: str
    ) -> Tuple[Optional[str], Union[AnalysisTarget, str, None]]:
        """Resolve one ``/analyze`` argument into ``(code, analysis_target)``.

        Registered index first, existing stock-name resolution as fallback.

        1. Explicit index identity/alias (``sh000016`` / ``930955.CSI`` /
           ``csi930955``) via
           :meth:`IndexRegistry.find_by_explicit_key`.
        2. Exact registered display name (``上证50``) via
           :meth:`IndexRegistry.find_by_display_name` — before any stock-name
           fallback; ambiguous names fail with an explicit error.
        3. Parser INDEX acceptance: when :func:`parse_analysis_target`
           classifies the raw input as INDEX (e.g. dotted-prefix aliases such
           as ``SH.000016`` the registry key lookup misses), submit the
           registry canonical with the matching structured target. Parser
           STOCK results are deliberately ignored here so the legacy stock
           gate stays authoritative for stock shapes.
        4. Explicit CSI forms (``csi`` + one or more digits, or one or more
           digits + ``.csi``) that no registry entry claimed — they surface
           the parser's ``unsupported`` details (never a stock-name fallback
           or a US-ticker guess).
        5. Legacy stock-code gate, preserved exactly as before this change
           (case-insensitive): A-share six digits, ``HK`` + five digits, and
           US 1-5 letters with optional ``.XX`` suffix. Matches keep the
           legacy code path (no structured target) so lowercase real tickers
           like ``usfd`` still resolve to ``USFD``.
        6. Any remaining parser-UNSUPPORTED input (e.g. ``us1``,
           ``600519.BJ``, ``1234567.SH``) is an explicit error — never sent
           into stock-name resolution.
        7. Anything code-like the legacy gate rejected (``12345``, bare
           ``00700``, ``600519.SH``, unregistered ``sh999999``) is an
           explicit error — never silently submitted.
        8. Non-code names through :func:`resolve_name_to_code` (stock only).

        Only INDEX targets are carried downstream; stock inputs keep the
        legacy code path so ``600519`` is never rewritten into a parser
        canonical. On failure returns ``(None, error_message)``.
        """
        from src.services.name_to_code_resolver import resolve_name_to_code

        registry = default_index_registry()

        # 1) Explicit index identity/alias — registered index wins over any
        #    stock-name fallback and is submitted with its lowercase
        #    canonical_id verbatim.
        if registry.find_by_explicit_key(raw) is not None:
            target = parse_analysis_target(raw, registry=registry)
            return target.canonical_id, target

        # 2) Exact registered display name — independent of identity aliases;
        #    a Chinese name must never become a parser identity alias.
        if registry.is_ambiguous_display_name(raw):
            return None, (
                f"指数名称 `{raw}` 存在歧义，请改用显式代码（如 `sh000016`）"
            )
        entry = registry.find_by_display_name(raw)
        if entry is not None:
            target = replace(
                parse_analysis_target(entry.canonical_id, registry=registry),
                raw_input=raw,
            )
            return target.canonical_id, target

        # 3) Parser INDEX acceptance — the shared parser recognizes forms the
        #    registry key lookup above misses (e.g. dotted-prefix aliases
        #    ``SH.000016`` / ``SZ.399001``). Only an INDEX result short-circuits
        #    here; STOCK and UNSUPPORTED results continue to the legacy gates
        #    below so the legacy stock contract stays authoritative.
        target = parse_analysis_target(raw, registry=registry)
        if target.asset_type == ParseStatus.INDEX:
            return target.canonical_id, target

        # 4) Explicit CSI forms — registered ones were claimed in step 1, so
        #    anything reaching here is unregistered and must surface the
        #    parser's UNSUPPORTED details. The full numeric explicit CSI
        #    family (``csi`` + one or more digits, or one or more digits +
        #    ``.csi``) is covered, not only six-digit forms.
        normalized = unicodedata.normalize("NFKC", raw).strip().casefold()
        if re.fullmatch(r"(?:csi\d+|\d+\.csi)", normalized):
            reason = target.unsupported_reason or f"无法识别标的: {raw}"
            return None, f"无法分析 `{raw}`：{reason}"

        # 5) Legacy stock-code gate — case-insensitive, exactly the shapes the
        #    old ``validate_args`` accepted. Matches keep the legacy code
        #    path (no structured target), including lowercase real tickers
        #    like ``usfd`` -> ``USFD``.
        upper = raw.upper()
        if (
            re.fullmatch(r"\d{6}", upper)
            or re.fullmatch(r"HK\d{5}", upper)
            or re.fullmatch(r"[A-Z]{1,5}(?:\.[A-Z]{1,2})?", upper)
        ):
            return resolve_index_stock_code_for_analysis(raw), None

        # 6) Any remaining parser-UNSUPPORTED input is an explicit error —
        #    never sent into stock-name resolution. This covers malformed
        #    code shapes the parser rejected (``us1``, ``600519.BJ``,
        #    ``1234567.SH``) that the legacy gate above did not claim.
        if target.asset_type == ParseStatus.UNSUPPORTED:
            reason = target.unsupported_reason or f"无法识别标的: {raw}"
            return None, f"无法分析 `{raw}`：{reason}"

        # 7) Code-like inputs the legacy gate rejected are explicit errors —
        #    never submitted, never routed into stock-name resolution. This
        #    includes ``sh``/``sz`` prefixed six-digit forms (``sh999999``)
        #    that ``is_code_like`` misses because the bare digits classify as
        #    a different exchange.
        if is_code_like(raw) or re.fullmatch(r"(?:sh|sz)\d{6}", normalized):
            return None, (
                f"无效的标的代码: `{raw}`"
                f"（A股6位数字 / HK+5位数字 / 美股1-5个字母 / 已登记指数代码或名称）"
            )

        # 8) Name input → stock-name fallback.
        code = resolve_name_to_code(raw)
        if not code:
            return None, f"无法识别标的: {raw}"
        return code, None
