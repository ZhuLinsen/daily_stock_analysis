#!/usr/bin/env python3
"""Select liquid A-share intraday candidates for downstream AI analysis."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Sequence
from zoneinfo import ZoneInfo

import pandas as pd


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class Candidate:
    code: str
    name: str
    price: float
    pct_change: float
    amount: float
    turnover: float
    volume_ratio: float
    speed: float
    score: float


COLUMN_ALIASES = {
    "code": ("代码", "股票代码", "code", "symbol"),
    "name": ("名称", "股票名称", "name"),
    "price": ("最新价", "现价", "price", "trade"),
    "pct_change": ("涨跌幅", "change_percent", "pct_change", "changepercent"),
    "amount": ("成交额", "amount"),
    "turnover": ("换手率", "turnover", "turnover_rate", "turnoverratio"),
    "volume_ratio": ("量比", "volume_ratio"),
    "speed": ("涨速", "speed"),
}


def _column(frame: pd.DataFrame, key: str) -> pd.Series:
    for alias in COLUMN_ALIASES[key]:
        if alias in frame.columns:
            return frame[alias]
    if key in {"speed", "turnover", "volume_ratio"}:
        neutral = 0.0 if key == "speed" else 1.0
        return pd.Series(neutral, index=frame.index)
    raise ValueError(f"行情数据缺少必要字段: {key}")


def _number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _percentile(series: pd.Series) -> pd.Series:
    return series.rank(method="average", pct=True).fillna(0.0)


def _quality_filter(frame: pd.DataFrame, relaxed: bool = False) -> pd.DataFrame:
    min_amount = float(os.getenv("AUTO_SELECT_MIN_AMOUNT", "100000000"))
    min_price = float(os.getenv("AUTO_SELECT_MIN_PRICE", "2"))
    max_price = float(os.getenv("AUTO_SELECT_MAX_PRICE", "200"))

    pct_low, pct_high = (-4.0, 9.3) if relaxed else (-2.0, 7.5)
    amount_floor = min_amount * (0.5 if relaxed else 1.0)
    volume_low, volume_high = (0.5, 8.0) if relaxed else (0.8, 5.0)
    turnover_low, turnover_high = (0.2, 20.0) if relaxed else (0.5, 15.0)

    names = frame["name"].astype(str).str.upper()
    excluded_names = names.str.contains(r"ST|退", regex=True) | names.str.startswith(("N", "C"))
    valid_codes = frame["code"].astype(str).str.fullmatch(r"\d{6}")

    return frame[
        valid_codes
        & ~excluded_names
        & frame["price"].between(min_price, max_price)
        & frame["pct_change"].between(pct_low, pct_high)
        & frame["amount"].ge(amount_floor)
        & frame["turnover"].between(turnover_low, turnover_high)
        & frame["volume_ratio"].between(volume_low, volume_high)
    ].copy()


def select_candidates(raw: pd.DataFrame, count: int = 10) -> list[Candidate]:
    frame = pd.DataFrame(
        {
            "code": _column(raw, "code").astype(str).str.extract(r"(\d{6})", expand=False),
            "name": _column(raw, "name").astype(str).str.strip(),
            "price": _number(_column(raw, "price")),
            "pct_change": _number(_column(raw, "pct_change")),
            "amount": _number(_column(raw, "amount")),
            "turnover": _number(_column(raw, "turnover")),
            "volume_ratio": _number(_column(raw, "volume_ratio")),
            "speed": _number(_column(raw, "speed")).fillna(0.0),
        }
    ).dropna(subset=["code", "price", "pct_change", "amount", "turnover", "volume_ratio"])

    filtered = _quality_filter(frame)
    if len(filtered) < count:
        filtered = _quality_filter(frame, relaxed=True)
    if len(filtered) < count:
        raise RuntimeError(f"符合风控和流动性条件的股票不足 {count} 支（当前 {len(filtered)} 支）")

    # Prefer active, liquid leaders while penalizing names already close to limit-up.
    momentum_quality = 1.0 - ((filtered["pct_change"] - 3.0).abs() / 7.0).clip(upper=1.0)
    volume_quality = 1.0 - ((filtered["volume_ratio"] - 2.0).abs() / 6.0).clip(upper=1.0)
    filtered["score"] = (
        _percentile(filtered["amount"]) * 30.0
        + momentum_quality * 25.0
        + volume_quality * 20.0
        + _percentile(filtered["turnover"]) * 15.0
        + _percentile(filtered["speed"]) * 10.0
    )

    selected = filtered.sort_values(
        ["score", "amount", "pct_change"], ascending=False
    ).head(count)
    return [
        Candidate(
            code=row.code,
            name=row.name,
            price=round(float(row.price), 3),
            pct_change=round(float(row.pct_change), 2),
            amount=round(float(row.amount), 2),
            turnover=round(float(row.turnover), 2),
            volume_ratio=round(float(row.volume_ratio), 2),
            speed=round(float(row.speed), 2),
            score=round(float(row.score), 2),
        )
        for row in selected.itertuples(index=False)
    ]


def is_trading_day(now: datetime | None = None) -> bool:
    now = now or datetime.now(SHANGHAI_TZ)
    try:
        import exchange_calendars as xcals

        calendar = xcals.get_calendar("XSHG")
        return bool(calendar.is_session(pd.Timestamp(now.date())))
    except Exception as exc:
        print(f"交易日历不可用，按工作日降级判断: {exc}", file=sys.stderr)
        return now.weekday() < 5


def _market_sources() -> Sequence[tuple[str, Callable[[], pd.DataFrame]]]:
    """Build full-market sources lazily so one broken package does not block fallbacks."""

    sources: list[tuple[str, Callable[[], pd.DataFrame]]] = []
    try:
        import akshare as ak

        sources.append(("akshare_eastmoney", ak.stock_zh_a_spot_em))
    except Exception as exc:
        print(f"[行情源] AkShare 东财不可用: {exc}", file=sys.stderr)

    try:
        import efinance as ef

        sources.append(("efinance", ef.stock.get_realtime_quotes))
    except Exception as exc:
        print(f"[行情源] efinance 不可用: {exc}", file=sys.stderr)

    try:
        import akshare as ak

        sources.append(("akshare_sina", ak.stock_zh_a_spot))
    except Exception as exc:
        print(f"[行情源] AkShare 新浪不可用: {exc}", file=sys.stderr)
    return sources


def fetch_market_snapshot(
    sources: Sequence[tuple[str, Callable[[], pd.DataFrame]]] | None = None,
    attempts: int = 2,
) -> pd.DataFrame:
    """Fetch a non-empty full-market snapshot with retries and source failover."""

    errors: list[str] = []
    configured_sources = sources if sources is not None else _market_sources()
    if not configured_sources:
        raise RuntimeError("没有可用的全市场行情源")

    for source_name, loader in configured_sources:
        for attempt in range(1, max(attempts, 1) + 1):
            try:
                print(
                    f"[行情源] 尝试 {source_name} ({attempt}/{max(attempts, 1)})",
                    file=sys.stderr,
                )
                frame = loader()
                if frame is None or frame.empty:
                    raise RuntimeError("返回空数据")
                # Validate the minimum fields before accepting this source.
                for required in ("code", "name", "price", "pct_change", "amount"):
                    _column(frame, required)
                print(
                    f"[行情源] {source_name} 成功，返回 {len(frame)} 条",
                    file=sys.stderr,
                )
                return frame
            except Exception as exc:
                error = f"{source_name} 第 {attempt} 次失败: {exc}"
                errors.append(error)
                print(f"[行情源] {error}", file=sys.stderr)
                if attempt < max(attempts, 1):
                    time.sleep(min(2 ** (attempt - 1), 3))

    raise RuntimeError("所有行情源均失败：" + "；".join(errors))


def write_reports(candidates: Iterable[Candidate], json_path: Path, md_path: Path) -> None:
    rows = list(candidates)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps([asdict(item) for item in rows], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# A股盘中候选池",
        "",
        f"生成时间：{datetime.now(SHANGHAI_TZ):%Y-%m-%d %H:%M:%S}（北京时间）",
        "",
        "| 排名 | 代码 | 名称 | 最新价 | 涨跌幅 | 成交额(亿) | 换手率 | 量比 | 评分 |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for rank, item in enumerate(rows, 1):
        lines.append(
            f"| {rank} | {item.code} | {item.name} | {item.price:.2f} | "
            f"{item.pct_change:.2f}% | {item.amount / 100000000:.2f} | "
            f"{item.turnover:.2f}% | {item.volume_ratio:.2f} | {item.score:.2f} |"
        )
    lines.extend(
        [
            "",
            "> 候选池仅用于后续 AI 分析，不等于无条件买入；最终以买入观察条件、止损/放弃条件和仓位上限为准。",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def configured_fallback_codes(value: str, count: int) -> list[str]:
    """Return unique configured A-share codes without inventing market data."""

    codes: list[str] = []
    for code in re.findall(r"(?<!\d)\d{6}(?!\d)", value or ""):
        if code not in codes:
            codes.append(code)
        if len(codes) >= count:
            break
    return codes


def write_fallback_reports(
    codes: Sequence[str], reason: str, json_path: Path, md_path: Path
) -> None:
    """Record that configured stocks were used because live screening was unavailable."""

    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(
            [
                {
                    "code": code,
                    "source": "configured_stock_list",
                    "degraded": True,
                }
                for code in codes
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    lines = [
        "# A股盘中候选池（降级模式）",
        "",
        f"生成时间：{datetime.now(SHANGHAI_TZ):%Y-%m-%d %H:%M:%S}（北京时间）",
        "",
        "> 实时全市场行情源暂时不可用，本次改用已配置自选股继续分析。",
        "> 未生成实时排名和行情指标，不应据此追涨；请以正文中的观察条件和风险控制为准。",
        "",
        "| 排名 | 代码 | 来源 |",
        "|---:|---|---|",
    ]
    lines.extend(
        f"| {rank} | {code} | 已配置自选股 |" for rank, code in enumerate(codes, 1)
    )
    lines.extend(["", f"降级原因：{reason}"])
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="筛选 A 股盘中候选股票")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--force-run", action="store_true")
    parser.add_argument("--json", type=Path, default=Path("reports/intraday_candidates.json"))
    parser.add_argument("--markdown", type=Path, default=Path("reports/intraday_candidates.md"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.count < 1:
        raise ValueError("count 必须大于 0")
    if not args.force_run and not is_trading_day():
        print("SKIP_NON_TRADING_DAY")
        return 0

    try:
        candidates = select_candidates(fetch_market_snapshot(), count=args.count)
    except RuntimeError as exc:
        fallback_codes = configured_fallback_codes(
            os.getenv("STOCK_LIST", ""), count=args.count
        )
        if not fallback_codes:
            raise RuntimeError(
                f"实时选股失败且未配置可用的 STOCK_LIST：{exc}"
            ) from exc
        reason = str(exc)
        print(
            "[行情源] 实时选股不可用，改用已配置自选股继续分析："
            f"{reason}",
            file=sys.stderr,
        )
        write_fallback_reports(fallback_codes, reason, args.json, args.markdown)
        print(",".join(fallback_codes))
        return 0

    write_reports(candidates, args.json, args.markdown)
    print(",".join(item.code for item in candidates))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
