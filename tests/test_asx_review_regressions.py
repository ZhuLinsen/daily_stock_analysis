"""Regressions for AU routing and the real pipeline-to-model handoff."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from data_provider.base import DataFetcherManager
from src.services.stock_profile_service import StockProfileService


@pytest.mark.parametrize('code', ['A2M.AX', 'BHP.AX', 'A200.AX'])
def test_asx_chip_data_is_unsupported_without_provider_calls(code):
    provider = Mock()
    provider.name = 'AkshareFetcher'
    provider.priority = 0
    manager = DataFetcherManager(fetchers=[provider])
    with patch('src.config.get_config', return_value=SimpleNamespace(enable_chip_distribution=True)):
        assert manager.get_chip_distribution(code) is None
    provider.get_chip_distribution.assert_not_called()


@pytest.mark.parametrize('code,market', [('HKS.AX', 'au'), ('HK2.AX', 'au'), ('HK00700', 'hk')])
def test_explicit_suffix_precedes_hk_prefix_in_stock_profile(code, market):
    assert StockProfileService.market_for_code(code) == market


@pytest.mark.parametrize('language', ['zh', 'en'])
@pytest.mark.parametrize('quote_type', ['EQUITY', 'ETF'])
def test_pipeline_metadata_reaches_model_prompt(language, quote_type):
    from src.analyzer import GeminiAnalyzer
    from src.core.pipeline import StockAnalysisPipeline

    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = SimpleNamespace(report_language=language)
    pipeline.search_service = SimpleNamespace(news_window_days=3)
    quote = SimpleNamespace(name='Synthetic ASX fixture', price=6.3,
                            currency='AUD', quote_type=quote_type)
    fundamentals = {'earnings': {'data': {
        'financial_report': {'currency': 'NZD', 'revenue': 1234},
        'dividend': {'currency': 'AUD', 'ttm_cash_dividend_per_share': 0.1},
    }}}
    context = pipeline._enhance_context(
        {'code': 'A2M.AX', 'today': {'close': 6.3}},
        quote, None, None, fundamental_context=fundamentals,
    )
    assert context['realtime']['currency'] == 'AUD'
    assert context['realtime']['quote_type'] == quote_type
    assert context['is_index_etf'] is (quote_type == 'ETF')
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    with patch.object(analyzer, '_get_skill_prompt_sections', return_value=('', '', True)):
        prompt = analyzer._format_prompt(context, quote.name, report_language=language)
    currency_label = 'Financial Statement Currency' if language == 'en' else '财报币种'
    type_label = 'Instrument Type' if language == 'en' else '证券类型'
    assert f'| {currency_label} | NZD |' in prompt
    assert f'| {type_label} | {quote_type} |' in prompt
    assert '6.3 AUD' in prompt
    assert '6.3 元' not in prompt


@pytest.mark.parametrize('language', ['zh', 'en', 'ko'])
@pytest.mark.parametrize('risk_appetite', ['risk_off', 'unknown'])
@pytest.mark.parametrize('use_safe_dict', [False, True], ids=['typed', 'safe-dict'])
def test_cross_asset_prompt_uses_au_market_label(language, risk_appetite, use_safe_dict):
    """OR-COR-7f0389ac: accepting au must not silently label it as A-share."""
    from src.cross_asset_context_prompt import format_cross_asset_context_prompt_section
    from src.schemas.cross_asset_context import CrossAssetContext

    context = CrossAssetContext(
        market='au', trade_date='2026-11-25', risk_appetite=risk_appetite,
        impact_summary='Synthetic cross-asset fixture',
    )
    payload = context.to_safe_dict() if use_safe_dict else context
    section = format_cross_asset_context_prompt_section(payload, report_language=language)
    assert section.count('BEGIN_UNTRUSTED_CROSS_ASSET_SUMMARY') == 1
    assert section.count('END_UNTRUSTED_CROSS_ASSET_SUMMARY') == 1
    preamble = section.split('BEGIN_UNTRUSTED_CROSS_ASSET_SUMMARY', 1)[0]
    prefix = '- 外围风险偏好：' if language == 'zh' else '- Risk appetite: '
    appetite_line = next(line for line in preamble.splitlines() if line.startswith(prefix))
    assert appetite_line.endswith('（澳股）' if language == 'zh' else '(Australia ASX)')
    assert 'A股' not in preamble
    assert 'A-share' not in preamble
    assert '2026-11-25' in preamble


@pytest.mark.parametrize('language', ['zh', 'en', 'ko'])
@pytest.mark.parametrize('use_summary', [True, False], ids=['summary', 'dict-fallback'])
def test_pipeline_cross_asset_au_label_reaches_model_prompt(language, use_summary):
    from src.analyzer import GeminiAnalyzer
    from src.core.pipeline import StockAnalysisPipeline
    from src.schemas.cross_asset_context import CrossAssetContext

    context = {'code': 'BHP.AX', 'today': {'close': 1.0}}
    cross_asset = CrossAssetContext(
        market='au', trade_date='2026-11-25', risk_appetite='risk_off',
        impact_summary='Synthetic cross-asset fixture',
    )
    StockAnalysisPipeline._attach_cross_asset_context(
        context, cross_asset, report_language=language,
    )
    assert context['cross_asset_context']['market'] == 'au'
    if not use_summary:
        del context['cross_asset_context_summary']
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    with patch.object(analyzer, '_get_skill_prompt_sections', return_value=('', '', True)):
        prompt = analyzer._format_prompt(context, 'BHP', report_language=language)
    expected_line = (
        '- 外围风险偏好：risk-off（外围偏拖累）（澳股）' if language == 'zh'
        else '- Risk appetite: risk-off (headwind) (Australia ASX)'
    )
    assert expected_line in prompt
    assert prompt.count('BEGIN_UNTRUSTED_CROSS_ASSET_SUMMARY') == 1
    assert prompt.count('END_UNTRUSTED_CROSS_ASSET_SUMMARY') == 1



@pytest.mark.parametrize('language,titles', [
    ('zh', ['日股市场复盘', '澳股市场复盘']),
    ('en', ['Japan Market Recap', 'Australian ASX Market Recap']),
])
def test_multi_market_share_image_renders_the_asx_section(tmp_path, language, titles):
    import re

    from src.config import Config
    from src.core.market_review import run_market_review
    from src.market_analyzer import MarketIndex
    from src.share_image import build_share_image_html
    from src.storage import DatabaseManager

    config = Config(database_path=str(tmp_path / 'recap.db'), market_review_region='jp', report_language=language)
    indices = {
        'jp': MarketIndex(code='N225', name='Nikkei 225', current=39000),
        'au': MarketIndex(code='^AXJO', name='S&P/ASX 200', current=8000),
    }
    notifier = Mock()
    notifier.is_available.return_value = notifier.send.return_value = True
    DatabaseManager.reset_instance()
    try:
        with patch('src.storage.get_config', return_value=config), \
                patch('src.market_analyzer.DataFetcherManager') as manager:
            manager.return_value.get_main_indices.side_effect = lambda region: [
                {**indices[region].to_dict(), 'prev_close': indices[region].current}
            ]
            result = run_market_review(
                notifier, analyzer=None, config=config, override_region='jp,au', query_id='asx-share',
                return_structured=True, save_report_file=False,
            )
    finally:
        DatabaseManager.reset_instance()

    for payload in (None, result.market_review_payload):
        html = build_share_image_html(result.report, structured_payload=payload)
        assert re.findall(r'market-region-title"><h2><b>◎</b>(.*?)</h2>', html) == titles
        assert 'S&amp;P/ASX 200' in html or 'S&P/ASX 200' in html
