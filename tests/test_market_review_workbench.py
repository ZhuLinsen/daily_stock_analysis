# -*- coding: utf-8 -*-
"""复盘工作台（Issue #1584）单元测试。

覆盖：
1. 纯计算层：均线快照、技术状态标签、宽度分化诊断、市场状态、仓位档位、结构观察
2. 判读合并：确定性字段优先、新闻编号绑定、无效引用丢弃、无判读降级
3. MarketAnalyzer 集成：无 LLM 的确定性 payload、判读路径、fail-open、
   工作台 markdown 注入、旧 payload 兼容、均线富化熔断
"""

import sys
import os
from unittest.mock import MagicMock, patch

if 'fake_useragent' not in sys.modules:
    sys.modules['fake_useragent'] = MagicMock()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.market_review_workbench import (  # noqa: E402
    build_workbench_core,
    compute_divergence_diagnosis,
    compute_index_ma_snapshot,
    compute_structure_note,
    derive_market_state,
    derive_suggested_position,
    merge_workbench_judgment,
    render_catalysts_table,
    render_style_rotation_line,
    render_summary_block,
    technical_status_label,
)
from src.market_analyzer import MarketAnalyzer, MarketIndex, MarketOverview  # noqa: E402
from src.schemas.market_review import validate_market_review_judgment  # noqa: E402


def _rising_bars(count: int = 25):
    return [{'date': f'2026-06-{day:02d}', 'close': 3300.0 + day} for day in range(1, count + 1)]


def _make_overview(avg_changes, up_count, down_count, **kwargs):
    overview = MarketOverview(date=kwargs.pop('date', '2026-07-02'))
    overview.indices = [
        MarketIndex(code=f'idx{i}', name=f'指数{i}', current=1000.0, change_pct=change)
        for i, change in enumerate(avg_changes)
    ]
    overview.up_count = up_count
    overview.down_count = down_count
    overview.flat_count = kwargs.pop('flat_count', 100)
    overview.limit_up_count = kwargs.pop('limit_up_count', 20)
    overview.limit_down_count = kwargs.pop('limit_down_count', 5)
    overview.total_amount = kwargs.pop('total_amount', 15000.0)
    for key, value in kwargs.items():
        setattr(overview, key, value)
    return overview


# ---------------------------------------------------------------------------
# 均线快照
# ---------------------------------------------------------------------------

def test_ma_snapshot_full_history_ok():
    snapshot = compute_index_ma_snapshot(_rising_bars(25), latest_close=3330.0, latest_date='2026-06-26')
    assert snapshot['data_quality'] == 'ok'
    assert snapshot['ma5'] and snapshot['ma10'] and snapshot['ma20']
    assert snapshot['ma_status'] == {'ma5': 'above', 'ma10': 'above', 'ma20': 'above'}
    # 实时合成K线并入计算
    assert snapshot['bars_used'] == 26


def test_ma_snapshot_partial_and_insufficient():
    assert compute_index_ma_snapshot(_rising_bars(12))['data_quality'] == 'partial'
    assert compute_index_ma_snapshot(_rising_bars(3))['data_quality'] == 'insufficient'
    assert compute_index_ma_snapshot(None)['data_quality'] == 'insufficient'


def test_ma_snapshot_stale_history_refuses_to_compute():
    snapshot = compute_index_ma_snapshot(_rising_bars(25), latest_close=3330.0, latest_date='2026-07-20')
    assert snapshot['data_quality'] == 'stale'
    assert 'ma5' not in snapshot and 'ma_status' not in snapshot


def test_ma_snapshot_same_day_history_not_duplicated():
    snapshot = compute_index_ma_snapshot(_rising_bars(25), latest_close=9999.0, latest_date='2026-06-25')
    assert snapshot['bars_used'] == 25


def test_ma_snapshot_closed_market_quote_not_double_counted():
    """休市/时差场景：实时价即最后收盘价时不得并入合成K线重复计入均线。

    典型场景：美股复盘在亚洲早间运行（latest_date 为服务器本地新日期，
    但美股没有新交易时段），或 A 股周末手动复盘。
    """
    bars = _rising_bars(25)  # last close 3325.0 @ 2026-06-25
    snapshot = compute_index_ma_snapshot(bars, latest_close=3325.0, latest_date='2026-06-26')
    assert snapshot['bars_used'] == 25  # no synthetic bar
    assert snapshot['ma5'] == round(sum(3300.0 + d for d in range(21, 26)) / 5, 2)
    # 真正的新交易时段（价格变化）仍应并入
    snapshot_new = compute_index_ma_snapshot(bars, latest_close=3330.0, latest_date='2026-06-26')
    assert snapshot_new['bars_used'] == 26


def test_technical_status_label_variants():
    assert technical_status_label({'ma5': 'above', 'ma10': 'above', 'ma20': 'above'}, 'zh') == '站上全部均线（MA5/MA10/MA20）'
    assert technical_status_label({'ma5': 'below', 'ma10': 'below', 'ma20': 'below'}, 'zh') == '跌破全部均线（MA5/MA10/MA20）'
    mixed = technical_status_label({'ma5': 'above', 'ma10': 'above', 'ma20': 'below'}, 'zh')
    assert '站上MA5/MA10' in mixed and 'MA20 之下' in mixed
    assert 'Above' in technical_status_label({'ma5': 'above', 'ma10': 'above', 'ma20': 'above'}, 'en')
    assert technical_status_label(None, 'zh') is None
    assert technical_status_label({}, 'zh') is None


# ---------------------------------------------------------------------------
# 分化诊断 / 市场状态 / 仓位 / 结构观察
# ---------------------------------------------------------------------------

def test_divergence_diagnosis_rules():
    narrow_up = _make_overview([0.5], up_count=1800, down_count=3200)
    assert '宽度不足' in compute_divergence_diagnosis(narrow_up, 'zh')

    broad_up = _make_overview([0.5], up_count=3500, down_count=1500)
    assert '同步走强' in compute_divergence_diagnosis(broad_up, 'zh')

    structural_down = _make_overview([-0.5], up_count=2000, down_count=3000)
    assert '结构性杀跌' in compute_divergence_diagnosis(structural_down, 'zh')

    broad_down = _make_overview([-1.0], up_count=800, down_count=4200)
    assert '普跌' in compute_divergence_diagnosis(broad_down, 'zh')

    # 温和下跌 + 宽度差：不得使用"普跌"措辞（与 derive_market_state 阈值对齐）
    soft_down = _make_overview([-0.5], up_count=1200, down_count=3800)
    soft_text = compute_divergence_diagnosis(soft_down, 'zh')
    assert '普跌' not in soft_text and '同步偏弱' in soft_text
    assert derive_market_state(soft_down, 'zh') == '弱势调整'


def test_divergence_diagnosis_none_without_breadth():
    no_breadth = _make_overview([0.5], up_count=0, down_count=0)
    assert compute_divergence_diagnosis(no_breadth, 'zh') is None
    no_indices = MarketOverview(date='2026-07-02')
    no_indices.up_count, no_indices.down_count = 1000, 2000
    assert compute_divergence_diagnosis(no_indices, 'zh') is None


def test_derive_market_state_vocabulary():
    assert derive_market_state(_make_overview([1.2], 3500, 1500), 'zh') == '强势扩散'
    assert derive_market_state(_make_overview([0.4], 3200, 1800), 'zh') == '普涨修复'
    assert derive_market_state(_make_overview([0.5], 1800, 3200), 'zh') == '指数强但个股弱'
    assert derive_market_state(_make_overview([-0.5], 3200, 1800), 'zh') == '指数弱但个股强'
    assert derive_market_state(_make_overview([-1.0], 800, 4200), 'zh') == '普跌'
    assert derive_market_state(_make_overview([-0.5], 2000, 3000), 'zh') == '弱势调整'
    assert derive_market_state(_make_overview([0.05], 2500, 2600), 'zh') == '震荡分化'
    assert derive_market_state(_make_overview([0.5], 0, 0), 'zh') is None


def test_derive_suggested_position_bands():
    assert derive_suggested_position(29) == '0-2成'
    assert derive_suggested_position(30) == '1-3成'
    assert derive_suggested_position(40) == '3-5成'
    assert derive_suggested_position(59) == '3-5成'
    assert derive_suggested_position(60) == '5-7成'
    assert derive_suggested_position(75) == '6-8成'
    assert derive_suggested_position(75, 'en') == '60-80%'
    assert derive_suggested_position(None) is None
    assert derive_suggested_position('abc') is None


def test_compute_structure_note_pairs_and_threshold():
    overview = MarketOverview(date='2026-07-02')
    overview.indices = [
        MarketIndex(code='sh000016', name='上证50', current=2700.0, change_pct=0.4),
        MarketIndex(code='sz399006', name='创业板指', current=2100.0, change_pct=-1.8),
    ]
    note = compute_structure_note(overview, 'cn', 'zh')
    assert '上证50' in note and '强于' in note

    # 分化不足 1 个百分点时不输出
    overview.indices[1].change_pct = 0.0
    assert compute_structure_note(overview, 'cn', 'zh') is None
    # 对照指数缺失时不输出
    overview.indices = overview.indices[:1]
    assert compute_structure_note(overview, 'cn', 'zh') is None
    # 未配置的市场不输出
    assert compute_structure_note(overview, 'jp', 'zh') is None


# ---------------------------------------------------------------------------
# 核心组装与判读合并
# ---------------------------------------------------------------------------

_LIGHT = {'score': 45, 'temperature_label': '震荡', 'guidance': '信号分化，控制仓位并等待量价确认。'}
_NEWS = [
    {'title': '关税政策调整影响出口', 'snippet': '', 'source': 't', 'published_date': '', 'url': ''},
    {'title': 'AI服务器成本上升', 'snippet': '', 'source': 't', 'published_date': '', 'url': ''},
]


def _core(overview):
    return build_workbench_core(overview, _LIGHT, 'cn', 'zh', ma_notes=['指数历史K线缺失（sh000688）'])


def test_build_workbench_core_deterministic_fields():
    overview = _make_overview([0.5], 1800, 3200)
    core = _core(overview)
    assert core['summary']['temperature_score'] == 45
    assert core['summary']['suggested_position'] == '3-5成'
    assert core['summary']['market_state'] == '指数强但个股弱'
    assert core['summary']['market_state_source'] == 'deterministic'
    assert '宽度不足' in core['divergence_diagnosis']
    assert core['data_quality']['notes'] == ['指数历史K线缺失（sh000688）']


def test_build_workbench_core_without_market_light_adds_note():
    overview = _make_overview([0.5], 0, 0)
    core = build_workbench_core(overview, None, 'jp', 'zh')
    assert 'temperature_score' not in (core.get('summary') or {})
    assert any('市场温度' in note for note in core['data_quality']['notes'])


def test_merge_judgment_deterministic_wins_and_invalid_refs_dropped():
    overview = _make_overview([0.5], 1800, 3200)
    core = _core(overview)
    judgment = validate_market_review_judgment({
        'market_state': '应被忽略',
        'core_conclusion': '权重护盘、成长杀跌的结构性调整日。',
        'style_rotation': {'strong': '资源', 'weak': ['半导体']},
        'indices': [
            {'code': 'idx0', 'comment': '权重护盘明显'},
            {'code': 'unknown', 'comment': '应被丢弃'},
        ],
        'sectors': [
            {'name': '煤炭', 'persistence': '强', 'comment': '连续三日居前'},
            {'name': '未知板块', 'persistence': '强'},
        ],
        'catalysts': [
            {'news_index': 0, 'nature': '利空', 'scope': '出口链', 'duration': '中期', 'digestion': '部分消化'},
            {'news_index': 99, 'nature': '利好'},
            {'nature': '利好'},
        ],
        'next_session_plan': {'position_advice': '维持3-5成', 'focus_sectors': '资源'},
    })
    merged = merge_workbench_judgment(
        core, judgment, _NEWS, 'zh',
        index_codes=['idx0'], sector_names=['煤炭'],
        fallback_guidance=_LIGHT['guidance'],
    )
    # 确定性优先
    assert merged['summary']['market_state'] == '指数强但个股弱'
    assert merged['summary']['market_state_source'] == 'deterministic'
    # 判读补空位
    assert merged['summary']['core_conclusion'].startswith('权重护盘')
    assert merged['style_rotation']['strong'] == ['资源']
    # 无效引用丢弃；标题从新闻复制
    assert len(merged['catalysts']) == 1
    assert merged['catalysts'][0]['title'] == '关税政策调整影响出口'
    assert merged['index_comments'] == {'idx0': '权重护盘明显'}
    assert list(merged['sector_extras'].keys()) == ['煤炭']
    assert merged['next_session_plan']['focus_sectors'] == ['资源']


def test_merge_judgment_absent_degrades_with_note_and_skeleton_plan():
    overview = _make_overview([0.5], 1800, 3200)
    merged = merge_workbench_judgment(
        _core(overview), None, _NEWS, 'zh', fallback_guidance=_LIGHT['guidance'],
    )
    assert any('LLM' in note for note in merged['data_quality']['notes'])
    assert '3-5成' in merged['next_session_plan']['position_advice']
    assert 'catalysts' not in merged and 'style_rotation' not in merged


def test_merge_judgment_llm_market_state_used_when_deterministic_missing():
    overview = _make_overview([0.5], 0, 0)
    core = build_workbench_core(overview, _LIGHT, 'cn', 'zh')
    judgment = {'market_state': '外围回暖带动修复'}
    merged = merge_workbench_judgment(core, judgment, [], 'zh')
    assert merged['summary']['market_state'] == '外围回暖带动修复'
    assert merged['summary']['market_state_source'] == 'llm'


# ---------------------------------------------------------------------------
# markdown 块渲染
# ---------------------------------------------------------------------------

def test_render_summary_block_full():
    overview = _make_overview([0.5], 1800, 3200)
    judgment = {'core_conclusion': '结构性调整日。'}
    merged = merge_workbench_judgment(_core(overview), judgment, _NEWS, 'zh')
    block = render_summary_block(merged, 'zh')
    assert block.startswith('### 一句话结论')
    assert '市场温度：45/100' in block
    assert '**核心结论**：结构性调整日。' in block
    assert '> 数据说明' in block
    # 结论块只承载判断，不携带任何数据表
    assert '|' not in block


def test_render_summary_block_empty_returns_empty():
    assert render_summary_block(None, 'zh') == ''
    assert render_summary_block({}, 'zh') == ''
    # 只有数据说明、无任何结论内容时不注入（说明由其他模块携带无意义）
    assert render_summary_block({'data_quality': {'notes': ['x']}}, 'zh') == ''


def test_render_summary_block_en_heading():
    overview = _make_overview([0.5], 1800, 3200)
    core = build_workbench_core(overview, _LIGHT, 'cn', 'en')
    merged = merge_workbench_judgment(core, None, [], 'en')
    block = render_summary_block(merged, 'en')
    assert block.startswith('### One-Line Conclusion')


def test_render_catalysts_table_and_rotation_line():
    catalysts = [
        {'title': '关税政策调整影响出口', 'nature': '利空', 'scope': '出口链',
         'duration': '中期', 'digestion': '部分消化', 'comment': '已部分定价'},
        {'nature': '利好'},  # 无标题行被跳过
    ]
    table = render_catalysts_table(catalysts, 'zh')
    assert '| 消息 | 性质 | 影响范围 | 持续性 | 消化状态 | 点评 |' in table
    assert '关税政策调整影响出口 | 利空 | 出口链 | 中期 | 部分消化 | 已部分定价' in table
    assert render_catalysts_table([], 'zh') == ''
    assert render_catalysts_table(None, 'en') == ''

    line = render_style_rotation_line({'strong': ['资源'], 'weak': ['半导体'], 'comment': '切向防御。'}, 'zh')
    assert line.startswith('**判断（风格切换）**')
    assert '走强 资源' in line and '承压 半导体' in line
    assert render_style_rotation_line(None, 'zh') == ''
    assert render_style_rotation_line({}, 'en') == ''


# ---------------------------------------------------------------------------
# MarketAnalyzer 集成
# ---------------------------------------------------------------------------

def _integration_overview():
    overview = MarketOverview(date='2026-07-02')
    overview.indices = [
        MarketIndex(code='sh000001', name='上证指数', current=3400.0, change_pct=0.5),
        MarketIndex(code='sh000016', name='上证50', current=2700.0, change_pct=0.6),
        MarketIndex(code='sz399006', name='创业板指', current=2100.0, change_pct=-1.9),
    ]
    overview.up_count, overview.down_count, overview.flat_count = 1800, 3200, 200
    overview.limit_up_count, overview.limit_down_count = 30, 8
    overview.total_amount = 15000.0
    overview.top_sectors = [{'name': '煤炭', 'change_pct': 3.2, 'leader': '中国神华', 'leader_change_pct': 5.6}]
    overview.bottom_sectors = [{'name': '半导体', 'change_pct': -2.8}]
    return overview


def _run_review(analyzer, overview, news_items):
    with patch.object(MarketAnalyzer, 'search_market_news', return_value=[]), \
         patch.object(MarketAnalyzer, '_merge_persisted_market_intelligence', side_effect=lambda n: list(news_items)), \
         patch.object(MarketAnalyzer, 'get_market_overview', return_value=overview):
        return analyzer.run_daily_review_with_snapshot()


def test_pipeline_deterministic_only_without_llm():
    analyzer = MarketAnalyzer(search_service=None, analyzer=None, region='cn')
    result = _run_review(analyzer, _integration_overview(), _NEWS)
    payload = result.structured_payload

    # 旧契约完整保留
    assert payload['version'] == 1
    for key in ('kind', 'region', 'language', 'title', 'generated_at', 'date', 'market_scope',
                'indices', 'sectors', 'concepts', 'news', 'sections', 'markdown_report',
                'market_light', 'breadth'):
        assert key in payload, key

    # 确定性工作台字段
    assert payload['summary']['temperature_score'] == payload['market_light']['score']
    assert payload['summary']['suggested_position']
    assert 'divergence_diagnosis' in payload['breadth']
    assert payload['sectors']['top'][0]['leader'] == '中国神华'
    # 无 LLM：判读字段缺失 + 数据质量说明
    assert 'catalysts' not in payload and 'style_rotation' not in payload
    assert any('LLM' in note for note in payload['data_quality']['notes'])
    # 模板兜底自包含：不注入结论块之外的表格；结论块含确定性内容时注入
    # （模板路径 summary 无 core_conclusion，但温度/状态/结构观察存在 → 注入）
    assert '### 一句话结论' in result.report
    assert '市场温度：' in result.report
    # sections = 纯叙事：不含结论段（后者只存在于 markdown_report）
    assert all(section['title'] != '一句话结论' for section in payload['sections'])
    assert payload['markdown_report'] == result.report


def test_pipeline_with_llm_judgment():
    import json

    review_md = (
        "## 2026-07-02 大盘复盘\n\n> 总览。\n\n"
        "### 一、盘面总览\n正文A\n\n### 二、指数结构\n正文B\n"
    )
    judgment = {
        'core_conclusion': '权重护盘、成长杀跌。',
        'indices': [{'code': 'sh000016', 'comment': '权重护盘明显'}],
        'sectors': [{'name': '煤炭', 'persistence': '强'}],
        'catalysts': [{'news_index': 0, 'nature': '利空', 'duration': '中期', 'digestion': '部分消化'}],
        'next_session_plan': {'position_advice': '维持3-5成', 'key_levels': ['上证3400']},
    }
    mock_llm = MagicMock()
    mock_llm.is_available.return_value = True
    mock_llm.get_generation_backend_config_error = lambda: None
    mock_llm.generate_text.side_effect = [review_md, json.dumps(judgment, ensure_ascii=False)]

    analyzer = MarketAnalyzer(search_service=None, analyzer=mock_llm, region='cn')
    result = _run_review(analyzer, _integration_overview(), _NEWS)
    payload = result.structured_payload

    assert payload['summary']['core_conclusion'] == '权重护盘、成长杀跌。'
    assert payload['catalysts'][0]['title'] == '关税政策调整影响出口'
    assert payload['sectors']['top'][0]['persistence'] == '强'
    assert payload['next_session_plan']['key_levels'] == ['上证3400']
    idx50 = next(row for row in payload['indices'] if row['code'] == 'sh000016')
    assert idx50['comment'] == '权重护盘明显'
    # 一句话结论块注入在首个原有 ### 段之前
    assert result.report.index('### 一句话结论') < result.report.index('### 一、盘面总览')
    # 指数表升级为参考图 6 列并落在指数结构 section（含判读点评）
    indices_segment = result.report.split('### 二、指数结构')[1]
    assert '| 指数 | 收盘 | 涨跌幅 | 成交额(亿) | 均线状态 | 点评 |' in indices_segment
    assert '权重护盘明显' in indices_segment
    # 催化表注入（无对应 section 时按兜底段追加）
    assert '| 消息 | 性质 | 影响范围 | 持续性 | 消化状态 | 点评 |' in result.report
    # 温度全文只出现一次（结论块）；数据全文唯一
    assert result.report.count('/100') == 1
    assert result.report.count('关税政策调整影响出口') == 1
    # sections = 纯叙事（无表格行）
    assert all('|' not in section['markdown'] for section in payload['sections'])
    assert any(section['markdown'] == '正文A' for section in payload['sections'])
    # 判读 prompt 使用与 payload.news 对齐的编号
    judgment_prompt = mock_llm.generate_text.call_args_list[1][0][0]
    assert '0. 关税政策调整影响出口' in judgment_prompt


def test_pipeline_fail_open_on_invalid_judgment_response():
    review_md = "## 2026-07-02 大盘复盘\n\n### 一、盘面总览\n正文\n"
    mock_llm = MagicMock()
    mock_llm.is_available.return_value = True
    mock_llm.get_generation_backend_config_error = lambda: None
    mock_llm.generate_text.side_effect = [review_md, '抱歉，我无法输出 JSON。']

    analyzer = MarketAnalyzer(search_service=None, analyzer=mock_llm, region='cn')
    result = _run_review(analyzer, _integration_overview(), _NEWS)
    payload = result.structured_payload

    assert 'catalysts' not in payload
    assert any('LLM' in note for note in payload['data_quality']['notes'])
    assert '### 一句话结论' in result.report
    assert payload['summary']['temperature_score'] is not None


def test_payload_without_workbench_matches_legacy_shape():
    analyzer = MarketAnalyzer(search_service=None, analyzer=None, region='cn')
    overview = _integration_overview()
    report = "## 标题\n\n### 一、盘面总览\n正文\n"
    legacy = analyzer.build_market_review_payload(overview, _NEWS, report, None)
    assert 'summary' not in legacy
    assert 'data_quality' not in legacy
    assert 'divergence_diagnosis' not in legacy.get('breadth', {})
    # MarketIndex.to_dict 未计算均线时形状与旧版一致
    index_keys = set(legacy['indices'][0].keys())
    assert index_keys == {
        'code', 'name', 'current', 'change', 'change_pct', 'open', 'high', 'low',
        'volume', 'amount', 'amplitude',
    }


def test_enrich_indices_with_ma_success_and_circuit_breaker():
    analyzer = MarketAnalyzer(search_service=None, analyzer=None, region='cn')
    overview = _integration_overview()
    analyzer.data_manager = MagicMock()
    analyzer.data_manager.get_index_daily_history.return_value = _rising_bars(25)
    analyzer._enrich_indices_with_ma(overview)
    assert overview.indices[0].ma5 is not None
    assert overview.indices[0].technical_status
    assert overview.data_quality_notes == []

    # 连续失败熔断：全部返回空 -> 恰好尝试 2 只后跳过剩余（第 3 只不再抓取），并追加说明
    overview2 = _integration_overview()
    analyzer.data_manager.get_index_daily_history.reset_mock()
    analyzer.data_manager.get_index_daily_history.return_value = []
    analyzer._enrich_indices_with_ma(overview2)
    assert analyzer.data_manager.get_index_daily_history.call_count == 2
    assert overview2.indices[0].ma5 is None
    assert any('均线状态省略' in note for note in overview2.data_quality_notes)
    assert any('跳过剩余指数' in note for note in overview2.data_quality_notes)


def test_enrich_indices_with_ma_partial_quality_note_not_contradictory():
    """MA20 不足时：MA5/MA10 正常展示，说明用"MA20 缺失"措辞而非"均线状态省略"。"""
    analyzer = MarketAnalyzer(search_service=None, analyzer=None, region='cn')
    overview = _integration_overview()
    analyzer.data_manager = MagicMock()
    # 12 根且贴近 overview.date（2026-07-02），避免触发过期防护
    analyzer.data_manager.get_index_daily_history.return_value = [
        {'date': f'2026-06-{day:02d}', 'close': 3300.0 + day} for day in range(19, 31)
    ]
    analyzer._enrich_indices_with_ma(overview)
    assert overview.indices[0].ma5 is not None and overview.indices[0].ma20 is None
    assert overview.indices[0].technical_status
    assert any('MA20 缺失' in note for note in overview.data_quality_notes)
    assert not any('均线状态省略' in note for note in overview.data_quality_notes)


def test_get_market_overview_wires_ma_enrichment():
    """覆盖 get_market_overview 步骤 1.5 的真实接线（不 patch get_market_overview）。"""
    from datetime import datetime, timedelta

    analyzer = MarketAnalyzer(search_service=None, analyzer=None, region='cn')
    analyzer.data_manager = MagicMock()
    analyzer.data_manager.get_main_indices.return_value = [{
        'code': 'sh000001', 'name': '上证指数', 'current': 3400.0, 'change': 10.0,
        'change_pct': 0.3, 'open': 3390.0, 'high': 3410.0, 'low': 3380.0,
        'prev_close': 3390.0, 'volume': 1.0, 'amount': 1.0, 'amplitude': 0.9,
    }]
    # 真实 get_market_overview 用 datetime.now() 作日期，历史需贴近当日以避开过期防护
    today = datetime.now()
    analyzer.data_manager.get_index_daily_history.return_value = [
        {'date': (today - timedelta(days=offset)).strftime('%Y-%m-%d'), 'close': 3300.0 + offset}
        for offset in range(25, 0, -1)
    ]
    analyzer.data_manager.get_market_stats.return_value = {}
    analyzer.data_manager.get_sector_rankings.return_value = ([], [])
    analyzer.data_manager.get_concept_rankings.return_value = ([], [])
    overview = analyzer.get_market_overview()
    assert overview.indices[0].ma5 is not None
    assert overview.indices[0].technical_status


def test_jp_region_omits_temperature_with_note():
    analyzer = MarketAnalyzer(search_service=None, analyzer=None, region='jp')
    overview = MarketOverview(date='2026-07-02')
    overview.indices = [MarketIndex(code='N225', name='日经225', current=40000.0, change_pct=0.3)]
    result = _run_review(analyzer, overview, [])
    payload = result.structured_payload
    assert 'market_light' not in payload
    summary = payload.get('summary') or {}
    assert 'temperature_score' not in summary
    assert 'suggested_position' not in summary
    assert any('市场温度' in note or 'temperature' in note.lower()
               for note in payload['data_quality']['notes'])


def test_cross_market_block_in_review_prompt():
    analyzer = MarketAnalyzer(search_service=None, analyzer=None, region='cn')
    overview = _integration_overview()
    prompt = analyzer._build_review_prompt(
        overview,
        [],
        cross_market_snapshot={'us': [{'name': '标普500', 'change_pct': 0.52}]},
    )
    assert '跨市场参考' in prompt
    assert '标普500 +0.52%' in prompt
    # 不传快照时不出现该块
    prompt_plain = analyzer._build_review_prompt(overview, [])
    assert '跨市场参考' not in prompt_plain
