# -*- coding: utf-8 -*-
"""Master persona debate service (大师视角多空辩论).

让多位投资大师（巴菲特/索罗斯/利弗莫尔/彼得林奇/欧奈尔/缠论）对同一标的各自
给出立场与论据，再聚合成多空分歧度。核心聚合逻辑为纯函数，可离线测试。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy import desc, select

from src.repositories.master_debate_repo import MasterDebateRepository
from src.services.portfolio_service import VALID_MARKETS
from src.storage import AnalysisHistory, DatabaseManager

logger = logging.getLogger(__name__)

VALID_STANCES = frozenset({"bull", "bear", "neutral"})
_FENCE = chr(96) * 3  # 反引号代码块标记


@dataclass(frozen=True)
class MasterPersona:
    """一位大师的分析人格与视角。"""

    id: str
    name: str
    english_name: str
    philosophy: str
    lens: str
    key_questions: List[str] = field(default_factory=list)


PERSONAS: List[MasterPersona] = [
    MasterPersona(
        id="warren_buffett",
        name="巴菲特",
        english_name="Warren Buffett",
        philosophy="价值投资：只买看得懂、有护城河、估值有安全边际的好生意，长期持有。",
        lens="关注护城河、自由现金流、ROE 与估值安全边际；对高估值成长股天然警惕。",
        key_questions=["商业模式是否清晰且可持续？", "当前估值相对内在价值是否有安全边际？", "管理层与资本配置是否可信？"],
    ),
    MasterPersona(
        id="george_soros",
        name="索罗斯",
        english_name="George Soros",
        philosophy="反身性：市场预期会反作用于基本面，拐点往往出现在认知与现实的背离处。",
        lens="关注市场叙事、预期差与趋势拐点；重视风险收益的不对称性。",
        key_questions=["当前叙事是否已过度透支？", "预期与基本面的背离是否正在收敛？", "拐点信号是否已出现？"],
    ),
    MasterPersona(
        id="jesse_livermore",
        name="利弗莫尔",
        english_name="Jesse Livermore",
        philosophy="趋势与关键点位：只在趋势明确时重仓，跌破关键价位立即止损，不与市场争辩。",
        lens="关注趋势方向、关键支撑/压力位与量价配合；纪律性止损优先。",
        key_questions=["趋势是否明确向上/向下？", "关键价位在哪里，突破或跌破意味着什么？", "当前盈亏比是否值得入场？"],
    ),
    MasterPersona(
        id="peter_lynch",
        name="彼得林奇",
        english_name="Peter Lynch",
        philosophy="成长与常识：投资你了解的、成长性好的公司，警惕过度复杂的故事。",
        lens="关注成长性、行业空间与身边常识；用 PEG 衡量成长股估值。",
        key_questions=["业务是否简单易懂？", "成长空间与持续性如何？", "估值相对增速是否合理？"],
    ),
    MasterPersona(
        id="william_oneil",
        name="欧奈尔",
        english_name="William O'Neil",
        philosophy="CANSLIM：当季盈利、年度增长、新高、机构认同、市场方向与龙头地位缺一不可。",
        lens="关注盈利加速度、相对强度、突破新高与机构资金动向。",
        key_questions=["当季与年度盈利是否加速？", "是否创出阶段新高并伴随放量？", "所在板块与市场方向是否配合？"],
    ),
    MasterPersona(
        id="chan_theory",
        name="缠论",
        english_name="Chan Theory",
        philosophy="结构买卖点：以中枢、级别与走势类型定位买卖点，不预测只跟随。",
        lens="关注走势结构、中枢位置、级别与背驰信号；买卖点分级。",
        key_questions=["当前处于哪一级别的什么走势类型？", "是否出现背驰或三类买卖点信号？", "中枢的支撑与压力如何界定？"],
    ),
]

_PERSONA_BY_ID = {p.id: p for p in PERSONAS}


class MasterDebateError(RuntimeError):
    """Raised when the master debate cannot be produced."""


def normalize_stance(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in VALID_STANCES:
        return text
    if text in {"long", "看多", "多头"}:
        return "bull"
    if text in {"short", "看空", "空头"}:
        return "bear"
    if text in {"hold", "观望", "中性"}:
        return "neutral"
    return "neutral"


def build_debate_prompt(code: str, name: Optional[str], market: str, context: str) -> str:
    persona_blocks = []
    for p in PERSONAS:
        questions = "\n".join("   - " + q for q in p.key_questions)
        persona_blocks.append(
            "- " + p.name + "（" + p.english_name + "）：" + p.philosophy
            + "\n  视角：" + p.lens + "\n" + questions
        )
    personas_text = "\n".join(persona_blocks)
    stock_label = (str(name or "") + "（" + code + "）").strip()
    return (
        "你是一位投资大师圆桌会议的主持人。请让以下六位大师各自独立地对标的 "
        + stock_label + "（市场 " + market + "）发表多空立场。\n\n"
        + "## 参考分析上下文\n" + (context or "（未提供额外上下文，请仅基于标的与市场常识给出谨慎立场）") + "\n\n"
        + "## 与会大师\n" + personas_text + "\n\n"
        + "## 输出要求\n"
        + "只输出一个 JSON 对象，不要输出任何其他文字或 Markdown 代码块标记。结构如下：\n"
        + '{"personas": [{"persona_id": "warren_buffett", "stance": "bull", "confidence": 0.0, '
        + '"thesis": "一句话核心结论", "key_points": ["论点1", "论点2"], '
        + '"key_levels": {"support": 0.0, "resistance": 0.0}, "risk": "该立场下的主要风险"}]}\n'
        + "必须包含全部六位大师（persona_id 依次为 warren_buffett / george_soros / jesse_livermore / "
        + "peter_lynch / william_oneil / chan_theory）。confidence 取值范围 0 到 1。"
    )


def extract_json(text: str) -> Dict[str, Any]:
    """Extract a JSON object from LLM output, tolerating code fences and prose."""
    cleaned = (text or "").strip()
    lines = cleaned.splitlines()
    if lines and lines[0].strip().startswith(_FENCE):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith(_FENCE):
        lines = lines[:-1]
    cleaned = "\n".join(lines).strip()

    try:
        value = json.loads(cleaned)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            value = json.loads(cleaned[start:end + 1])
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
    raise MasterDebateError("master debate output did not contain a valid JSON object")


def parse_persona_outputs(text: str) -> List[Dict[str, Any]]:
    """Parse raw LLM text into a validated list of persona stance dicts."""
    payload = extract_json(text)
    raw_items = payload.get("personas")
    if not isinstance(raw_items, list) or not raw_items:
        raise MasterDebateError("master debate output missing personas array")
    outputs: List[Dict[str, Any]] = []
    seen: set = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        persona_id = str(item.get("persona_id") or "").strip()
        if persona_id not in _PERSONA_BY_ID:
            continue
        if persona_id in seen:
            continue
        seen.add(persona_id)
        stance = normalize_stance(item.get("stance"))
        try:
            confidence = float(item.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        key_points = item.get("key_points")
        if not isinstance(key_points, list):
            key_points = []
        key_points = [str(p) for p in key_points if str(p).strip()][:5]
        key_levels = item.get("key_levels") if isinstance(item.get("key_levels"), dict) else {}
        outputs.append({
            "persona_id": persona_id,
            "name": _PERSONA_BY_ID[persona_id].name,
            "english_name": _PERSONA_BY_ID[persona_id].english_name,
            "philosophy": _PERSONA_BY_ID[persona_id].philosophy,
            "stance": stance,
            "confidence": round(confidence, 2),
            "thesis": str(item.get("thesis") or "").strip(),
            "key_points": key_points,
            "key_levels": key_levels,
            "risk": str(item.get("risk") or "").strip(),
        })
    if not outputs:
        raise MasterDebateError("master debate output contained no recognised personas")
    return outputs


def aggregate_debate(outputs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pure aggregation of persona stances into a consensus + divergence score."""
    if not outputs:
        return {
            "consensus": "neutral",
            "divergence": 0,
            "conviction": 0,
            "bull_count": 0,
            "bear_count": 0,
            "neutral_count": 0,
            "bull_arguments": [],
            "bear_arguments": [],
            "summary": "无有效大师意见。",
        }

    bull = [o for o in outputs if o.get("stance") == "bull"]
    bear = [o for o in outputs if o.get("stance") == "bear"]
    neutral = [o for o in outputs if o.get("stance") == "neutral"]
    counts = {"bull": len(bull), "bear": len(bear), "neutral": len(neutral)}
    total = len(outputs)
    majority = max(counts.values())
    tied = [k for k, v in counts.items() if v == majority]
    consensus = tied[0] if len(tied) == 1 else "neutral"
    divergence = round(100 * (1 - majority / total))
    conviction = round(100 * majority / total)

    def _top_arguments(group: List[Dict[str, Any]]) -> List[str]:
        ordered = sorted(group, key=lambda o: -(float(o.get("confidence") or 0.0)))
        args: List[str] = []
        for o in ordered:
            for point in (o.get("key_points") or []):
                if point not in args:
                    args.append(point)
            if len(args) >= 3:
                break
        return args[:3]

    bull_args = _top_arguments(bull)
    bear_args = _top_arguments(bear)
    summary = _build_summary(outputs, counts, consensus, divergence)

    return {
        "consensus": consensus,
        "divergence": divergence,
        "conviction": conviction,
        "bull_count": counts["bull"],
        "bear_count": counts["bear"],
        "neutral_count": counts["neutral"],
        "bull_arguments": bull_args,
        "bear_arguments": bear_args,
        "summary": summary,
    }


def _build_summary(outputs: List[Dict[str, Any]], counts: Dict[str, int], consensus: str, divergence: int) -> str:
    stance_label = {"bull": "看多", "bear": "看空", "neutral": "中性"}
    parts = []
    for o in outputs:
        name = o.get("name") or o.get("persona_id") or "大师"
        parts.append(str(name) + "：" + stance_label[o.get("stance", "neutral")] + "（" + (o.get("thesis") or "未陈述") + "）")
    consensus_label = {"bull": "偏多", "bear": "偏空", "neutral": "分歧"}[consensus]
    header = (
        "共 " + str(len(outputs)) + " 位大师表态：" + str(counts["bull"]) + " 看多、"
        + str(counts["bear"]) + " 看空、" + str(counts["neutral"]) + " 中性；综合共识「"
        + consensus_label + "」，分歧度 " + str(divergence) + "。"
    )
    return header + "\n" + "\n".join(parts)


class MasterDebateService:
    """Business logic for master persona debates."""

    def __init__(
        self,
        repo: Optional[MasterDebateRepository] = None,
        db_manager: Optional[DatabaseManager] = None,
    ):
        self.repo = repo or MasterDebateRepository(db_manager)
        self.db = db_manager or getattr(self.repo, "db", None) or DatabaseManager.get_instance()

    def normalize_market(self, market: str) -> str:
        value = str(market or "").strip().lower()
        if value not in VALID_MARKETS:
            raise ValueError("market must be one of " + str(sorted(VALID_MARKETS)) + ": " + str(market))
        return value

    def run_debate(
        self,
        *,
        code: str,
        name: Optional[str],
        market: str,
        context: Optional[str] = None,
        analysis_history_id: Optional[int] = None,
        generate_text: Optional[Callable[[str], Optional[str]]] = None,
        persist: bool = True,
    ) -> Dict[str, Any]:
        market = self.normalize_market(market)
        if not str(code or "").strip():
            raise ValueError("code must not be empty")

        if context is None:
            context = self._load_context(code, analysis_history_id)

        generator = generate_text or self._default_generate_text
        # 先带完整分析上下文请求；部分 LLM 渠道对长 prompt 会返回空内容或坏 JSON，
        # 失败时自动降级为无上下文重试（仅基于股票代码/名称生成辩论）。
        outputs: Optional[List[Dict[str, Any]]] = None
        last_error: Optional[Exception] = None
        for attempt_context in (context, ""):
            if outputs is not None:
                break
            prompt = build_debate_prompt(code, name, market, attempt_context)
            try:
                raw = self._generate_with_retry(generator, prompt)
                outputs = parse_persona_outputs(raw)
            except MasterDebateError as exc:
                last_error = exc
                logger.warning(
                    "master debate attempt failed (context_len=%s): %s", len(attempt_context), exc
                )
        if outputs is None:
            assert last_error is not None
            raise last_error
        aggregate = aggregate_debate(outputs)

        record_id = None
        if persist:
            row = self.repo.create({
                "code": code,
                "name": name,
                "market": market,
                "consensus": aggregate["consensus"],
                "divergence": aggregate["divergence"],
                "bull_count": aggregate["bull_count"],
                "bear_count": aggregate["bear_count"],
                "neutral_count": aggregate["neutral_count"],
                "personas_json": json.dumps(outputs, ensure_ascii=False),
                "summary": aggregate["summary"],
            })
            record_id = row.id

        return {
            "id": record_id,
            "code": code,
            "name": name,
            "market": market,
            "personas": outputs,
            **aggregate,
        }

    def get_record(self, record_id: int) -> Dict[str, Any]:
        row = self.repo.get(record_id)
        if row is None:
            raise ValueError("master debate record " + str(record_id) + " not found")
        return self._record_to_dict(row)

    def list_records(
        self, *, market: Optional[str] = None, code: Optional[str] = None, page: int = 1, page_size: int = 20
    ) -> Tuple[List[Dict[str, Any]], int]:
        rows, total = self.repo.list(market=market, code=code, page=page, page_size=page_size)
        return [self._record_to_dict(row) for row in rows], total

    # 部分 LLM 渠道对长 JSON prompt 偶发返回空内容，重试一次可显著提高成功率
    LLM_ATTEMPTS = 2

    def _generate_with_retry(self, generator: Callable[[str], Optional[str]], prompt: str) -> str:
        last_error: Optional[Exception] = None
        for attempt in range(1, self.LLM_ATTEMPTS + 1):
            try:
                raw = generator(prompt)
            except Exception as exc:  # generate_text 会把“全部模型失败”直接抛出
                last_error = exc
                logger.warning("master debate LLM call failed (attempt %s/%s): %s", attempt, self.LLM_ATTEMPTS, exc)
                continue
            if raw:
                return raw
            logger.warning("master debate LLM returned empty content (attempt %s/%s)", attempt, self.LLM_ATTEMPTS)
        if last_error is not None:
            raise MasterDebateError("LLM 调用失败：" + str(last_error))
        raise MasterDebateError(
            "LLM 返回了空内容（已自动重试一次）。请稍后重试；若持续失败，"
            "请在设置中检查模型渠道，或更换为非推理类/输出更稳定的模型。"
        )

    def _default_generate_text(self, prompt: str) -> Optional[str]:
        from src.analyzer import GeminiAnalyzer

        return GeminiAnalyzer().generate_text(prompt, max_tokens=4096, temperature=0.6)

    def _load_context(self, code: str, analysis_history_id: Optional[int]) -> str:
        with self.db.get_session() as session:
            query = select(AnalysisHistory).where(AnalysisHistory.code == code)
            if analysis_history_id is not None:
                query = query.where(AnalysisHistory.id == analysis_history_id)
            row = session.execute(
                query.order_by(desc(AnalysisHistory.created_at), desc(AnalysisHistory.id)).limit(1)
            ).scalar_one_or_none()
        if row is None:
            return ""
        parts = []
        if getattr(row, "analysis_summary", None):
            parts.append("分析摘要：\n" + str(row.analysis_summary))
        if getattr(row, "raw_result", None):
            parts.append("结构化结果：\n" + _truncate(str(row.raw_result), 4000))
        if getattr(row, "trend_prediction", None):
            parts.append("趋势判断：\n" + str(row.trend_prediction))
        return "\n\n".join(parts)

    def _record_to_dict(self, row: Any) -> Dict[str, Any]:
        personas = _load_json(row.personas_json, [])
        return {
            "id": row.id,
            "code": row.code,
            "name": row.name,
            "market": row.market,
            "consensus": row.consensus,
            "divergence": row.divergence,
            "bull_count": row.bull_count,
            "bear_count": row.bear_count,
            "neutral_count": row.neutral_count,
            "personas": personas,
            "summary": row.summary,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }


def _truncate(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "…"


def _load_json(raw: Optional[str], default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return default
