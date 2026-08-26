# -*- coding: utf-8 -*-
"""Market strategy blueprints for CN/HK/US daily market recap."""

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class StrategyDimension:
    """Single strategy dimension used by market recap prompts."""

    name: str
    objective: str
    checkpoints: List[str]


@dataclass(frozen=True)
class MarketStrategyBlueprint:
    """Region specific market strategy blueprint."""

    region: str
    title: str
    positioning: str
    principles: List[str]
    dimensions: List[StrategyDimension]
    action_framework: List[str]

    def to_prompt_block(self) -> str:
        """Render blueprint as prompt instructions."""
        principles_text = "\n".join([f"- {item}" for item in self.principles])
        action_text = "\n".join([f"- {item}" for item in self.action_framework])

        dims = []
        for dim in self.dimensions:
            checkpoints = "\n".join([f"  - {cp}" for cp in dim.checkpoints])
            dims.append(f"- {dim.name}: {dim.objective}\n{checkpoints}")
        dimensions_text = "\n".join(dims)

        if self.region == "kr":
            return (
                f"## 전략 프레임워크: {self.title}\n"
                f"{self.positioning}\n\n"
                f"### 전략 원칙\n{principles_text}\n\n"
                f"### 분석 축\n{dimensions_text}\n\n"
                f"### 실행 기준\n{action_text}"
            )

        return (
            f"## Strategy Blueprint: {self.title}\n"
            f"{self.positioning}\n\n"
            f"### Strategy Principles\n{principles_text}\n\n"
            f"### Analysis Dimensions\n{dimensions_text}\n\n"
            f"### Action Framework\n{action_text}"
        )

    def to_markdown_block(self) -> str:
        """Render blueprint as markdown section for template fallback report."""
        dims = "\n".join([f"- **{dim.name}**: {dim.objective}" for dim in self.dimensions])
        if self.region == "kr":
            section_title = "### 6. 전략 프레임워크"
        else:
            section_title = "### VI. Strategy Framework" if self.region == "us" else "### 六、策略框架"
        return f"{section_title}\n{dims}\n"


CN_BLUEPRINT = MarketStrategyBlueprint(
    region="cn",
    title="A股市场三段式复盘策略",
    positioning="聚焦指数趋势、资金博弈与板块轮动，形成次日交易计划。",
    principles=[
        "先看指数方向，再看量能结构，最后看板块持续性。",
        "结论必须映射到仓位、节奏与风险控制动作。",
        "判断使用当日数据与近3日新闻，不臆测未验证信息。",
    ],
    dimensions=[
        StrategyDimension(
            name="趋势结构",
            objective="判断市场处于上升、震荡还是防守阶段。",
            checkpoints=["上证/深证/创业板是否同向", "放量上涨或缩量下跌是否成立", "关键支撑阻力是否被突破"],
        ),
        StrategyDimension(
            name="资金情绪",
            objective="识别短线风险偏好与情绪温度。",
            checkpoints=["涨跌家数与涨跌停结构", "成交额是否扩张", "高位股是否出现分歧"],
        ),
        StrategyDimension(
            name="主线板块",
            objective="提炼可交易主线与规避方向。",
            checkpoints=["领涨板块是否具备事件催化", "板块内部是否有龙头带动", "领跌板块是否扩散"],
        ),
    ],
    action_framework=[
        "进攻：指数共振上行 + 成交额放大 + 主线强化。",
        "均衡：指数分化或缩量震荡，控制仓位并等待确认。",
        "防守：指数转弱 + 领跌扩散，优先风控与减仓。",
    ],
)

US_BLUEPRINT = MarketStrategyBlueprint(
    region="us",
    title="US Market Regime Strategy",
    positioning="Focus on index trend, macro narrative, and sector rotation to define next-session risk posture.",
    principles=[
        "Read market regime from S&P 500, Nasdaq, and Dow alignment first.",
        "Separate beta move from theme-driven alpha rotation.",
        "Translate recap into actionable risk-on/risk-off stance with clear invalidation points.",
    ],
    dimensions=[
        StrategyDimension(
            name="Trend Regime",
            objective="Classify the market as momentum, range, or risk-off.",
            checkpoints=[
                "Are SPX/NDX/DJI directionally aligned",
                "Did volume confirm the move",
                "Are key index levels reclaimed or lost",
            ],
        ),
        StrategyDimension(
            name="Macro & Flows",
            objective="Map policy/rates narrative into equity risk appetite.",
            checkpoints=[
                "Treasury yield and USD implications",
                "Breadth and leadership concentration",
                "Defensive vs growth factor rotation",
            ],
        ),
        StrategyDimension(
            name="Sector Themes",
            objective="Identify persistent leaders and vulnerable laggards.",
            checkpoints=[
                "AI/semiconductor/software trend persistence",
                "Energy/financials sensitivity to macro data",
                "Volatility signals from VIX and large-cap earnings",
            ],
        ),
    ],
    action_framework=[
        "Risk-on: broad index breakout with expanding participation.",
        "Neutral: mixed index signals; focus on selective relative strength.",
        "Risk-off: failed breakouts and rising volatility; prioritize capital preservation.",
    ],
)

HK_BLUEPRINT = MarketStrategyBlueprint(
    region="hk",
    title="港股市场三段式复盘策略",
    positioning="聚焦恒生指数趋势、南向资金博弈与板块轮动，形成次日交易计划。",
    principles=[
        "先看恒指/恒科/国企指数方向，再看南向资金情绪，最后看板块持续性。",
        "结论必须映射到仓位、节奏与风险控制动作。",
        "判断使用当日数据与近3日新闻，不臆测未验证信息。",
    ],
    dimensions=[
        StrategyDimension(
            name="趋势结构",
            objective="判断市场处于上升、震荡还是防守阶段。",
            checkpoints=["恒指/恒科/国企指数是否同向", "放量上涨或缩量下跌是否成立", "关键支撑阻力是否被突破"],
        ),
        StrategyDimension(
            name="资金情绪",
            objective="识别南向资金风险偏好与情绪温度。",
            checkpoints=["南向资金净流入方向与规模", "港元汇率与内地政策含义", "市场广度与龙头集中度"],
        ),
        StrategyDimension(
            name="主线板块",
            objective="提炼可交易主线与规避方向。",
            checkpoints=["科技/互联网平台趋势持续性", "金融/地产对政策转向的敏感度", "防御与成长因子轮动"],
        ),
    ],
    action_framework=[
        "进攻：恒指共振上行 + 南向资金持续流入 + 主线强化。",
        "均衡：指数分化或缩量震荡，控制仓位并等待确认。",
        "防守：指数转弱 + 波动率上升，优先风控与减仓。",
    ],
)


JP_BLUEPRINT = MarketStrategyBlueprint(
    region="jp",
    title="日本市场三段式复盘策略",
    positioning="聚焦日经225、东证指数、汇率与全球风险偏好，形成次日交易计划。",
    principles=[
        "先看日经225与TOPIX是否同向，再看日元、半导体/出口链与金融股表现。",
        "把指数结论映射到仓位、节奏与风险控制动作。",
        "只基于可得指数、新闻和价格行为判断，不臆造市场广度或板块统计。",
    ],
    dimensions=[
        StrategyDimension(
            name="趋势结构",
            objective="判断日本市场处于上攻、震荡还是防守阶段。",
            checkpoints=["日经225/TOPIX是否同向", "指数是否突破或跌破关键区间", "大盘权重与成长链是否共振"],
        ),
        StrategyDimension(
            name="宏观与汇率",
            objective="识别日元、利率和全球风险偏好对权益市场的影响。",
            checkpoints=["日元方向对出口链的影响", "日本央行和美债利率叙事", "海外科技股与半导体链映射"],
        ),
        StrategyDimension(
            name="主题线索",
            objective="提炼可延续主线与需要规避的拥挤方向。",
            checkpoints=["半导体/自动化/汽车链持续性", "金融与内需股是否轮动", "新闻催化是否支撑价格行为"],
        ),
    ],
    action_framework=[
        "进攻：主要指数共振上行 + 外部风险偏好改善 + 主线强化。",
        "均衡：指数分化或汇率扰动，降低追涨并等待确认。",
        "防守：主要指数转弱或外部风险升温，优先控制仓位。",
    ],
)

KR_BLUEPRINT = MarketStrategyBlueprint(
    region="kr",
    title="한국 증시 3단계 시장 복기 전략",
    positioning="KOSPI·KOSDAQ, 반도체 대형주, 글로벌 기술주 위험선호를 중심으로 다음 거래일 계획을 수립합니다.",
    principles=[
        "KOSPI와 KOSDAQ의 동행 여부를 먼저 확인하고 삼성전자·SK하이닉스 등 대형주의 신호를 봅니다.",
        "지수 베타, 반도체 사이클, 성장주 위험선호의 기여도를 구분합니다.",
        "제공된 지수·뉴스·가격 행동만으로 판단하며, 시장 폭이나 업종 통계를 임의로 만들지 않습니다.",
    ],
    dimensions=[
        StrategyDimension(
            name="추세 구조",
            objective="한국 시장이 상승, 횡보, 방어 중 어느 국면인지 판단합니다.",
            checkpoints=["KOSPI/KOSDAQ의 방향 일치 여부", "대형주가 지수를 지지하는지", "핵심 지지·저항선 돌파 여부"],
        ),
        StrategyDimension(
            name="기술 사이클",
            objective="반도체, AI 하드웨어, 글로벌 기술주가 한국 시장에 미치는 영향을 파악합니다.",
            checkpoints=["메모리·반도체 공급망 뉴스 촉매", "미국 기술주와의 연동", "외국인 위험선호 변화"],
        ),
        StrategyDimension(
            name="주도 테마",
            objective="지속 가능한 주도주와 피해야 할 과열 구간을 추립니다.",
            checkpoints=["2차전지·자동차·인터넷 업종 순환", "KOSDAQ 성장주 위험선호", "뉴스 촉매가 가격 행동을 뒷받침하는지"],
        ),
    ],
    action_framework=[
        "공격: KOSPI/KOSDAQ 동반 상승, 기술 대형주 확인, 대외 위험선호 개선.",
        "균형: 지수 또는 대형주가 엇갈리면 비중을 관리하며 확인을 기다림.",
        "방어: 기술 대형주 약세 또는 대외 위험 확대 시 낙폭 관리 우선.",
    ],
)

def get_market_strategy_blueprint(region: str) -> MarketStrategyBlueprint:
    """Return strategy blueprint by market region."""
    if region == "us":
        return US_BLUEPRINT
    if region == "hk":
        return HK_BLUEPRINT
    if region == "jp":
        return JP_BLUEPRINT
    if region == "kr":
        return KR_BLUEPRINT
    return CN_BLUEPRINT
