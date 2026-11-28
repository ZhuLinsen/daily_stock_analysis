"""Native AU report context, quote identity, and macro routing regressions."""
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pandas as pd
import pytest
from data_provider.base import DataFetcherManager, normalize_stock_code
from data_provider.yfinance_fetcher import YfinanceFetcher
from data_provider.yfinance_fundamental_adapter import _convert_to_yf_symbol
from src.market_analyzer import MarketAnalyzer, MarketOverview
from src.core.market_profile import get_profile
from src.core.market_strategy import get_market_strategy_blueprint
from src.services.daily_market_context import _normalize_context_region
from src.utils.market_review_region import normalize_market_review_region_strict


def test_au_review_context_no_china_default():
    assert _normalize_context_region('au') == 'au'
    assert normalize_market_review_region_strict('au') == 'au'
    assert get_profile('au').region == 'au'
    assert get_profile('au').mood_index_code == 'AXJO'
    assert get_market_strategy_blueprint('au').region == 'au'
    analyzer = MarketAnalyzer(region='au', config=SimpleNamespace(report_language='en'))
    assert analyzer.region == 'au'
    assert 'ASX' in analyzer._get_market_scope_name('en')
    assert analyzer._get_turnover_unit_label() == 'AUD bn'
    assert 'ASX' in analyzer._get_index_hint()
    assert 'ASX' in analyzer._get_review_title('2026-11-24')


def test_au_indices_fail_closed():
    china=Mock(); china.name='EfinanceFetcher'; china.priority=0
    yf=YfinanceFetcher()
    m=DataFetcherManager(fetchers=[china,yf])
    with patch.object(yf,'get_main_indices',return_value=None):
        assert not m.get_main_indices('au')
    china.get_main_indices.assert_not_called()


def test_au_index_symbols():
    yf=YfinanceFetcher()
    seen=[]
    def fetch(_yf,symbol,name,code):
        seen.append(symbol)
        return {'code':code,'name':name,'current':100.0}
    with patch.object(yf,'_fetch_yf_ticker_data',side_effect=fetch):
        data=yf.get_main_indices('au')
    assert set(seen)=={'^AXJO','^AORD'}
    assert {x['market'] for x in data} == {'au'}


def test_au_quote_retains_aud_and_identity():
    ticker=Mock()
    ticker.fast_info=SimpleNamespace(last_price=6.3,previous_close=6.4,open=6.4,day_high=6.5,day_low=6.2,last_volume=1000,market_cap=1e9)
    ticker.info={'shortName':'The a2 Milk Company','currency':'AUD','symbol':'A2M.AX','quoteType':'EQUITY'}
    ticker.history.return_value=pd.DataFrame({'Open':[6.4,6.4],'High':[6.5,6.5],'Low':[6.2,6.2],'Close':[6.4,6.3],'Volume':[1000,1000]},index=pd.to_datetime(['2026-11-20','2026-11-23']))
    with patch('yfinance.Ticker',return_value=ticker) as constructor:
        quote=YfinanceFetcher().get_realtime_quote('A2M.AX')
    constructor.assert_called_once_with('A2M.AX')
    assert quote.code=='A2M.AX'
    assert quote.market=='au'
    assert quote.currency=='AUD'
    assert quote.quote_type=='EQUITY'
    assert quote.to_dict()['quote_type']=='EQUITY'
    assert quote.price==6.3
    assert quote.quote_date=='2026-11-23'
    assert _convert_to_yf_symbol('A2M.AX')=='A2M.AX'
    assert _convert_to_yf_symbol('HK2.AX')=='HK2.AX'


def test_au_currency_and_decision_service():
    from src.notification import NotificationService
    from src.services.decision_signal_service import DecisionSignalService
    from src.services.portfolio_service import PortfolioService
    assert '澳元' in NotificationService._format_amount_cn(1000,'AUD')
    assert '新西兰元' in NotificationService._format_amount_cn(1000,'NZD')
    assert DecisionSignalService._normalize_market('au')=='au'
    assert PortfolioService._default_currency_for_market('au')=='AUD'


@pytest.mark.parametrize('code',['A-1.AX','ABCDEFG.AX','中.AX'])
def test_malformed_asx_is_rejected_not_china(code):
    with pytest.raises(ValueError): normalize_stock_code(code)


def test_au_cross_asset_does_not_normalize_to_china():
    from src.services.cross_asset_context_service import normalize_cross_asset_market
    from data_provider.cross_asset_fetcher import _YF_INDEX_SYMBOLS
    assert normalize_cross_asset_market('au')=='au'
    assert 'AXJO' in _YF_INDEX_SYMBOLS['au']


@pytest.mark.parametrize('legacy', [True, False])
def test_actual_model_system_prompt_uses_au(legacy):
    from src.analyzer import GeminiAnalyzer
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    with patch.object(analyzer, '_get_skill_prompt_sections', return_value=('', '', legacy)):
        prompt = analyzer._get_analysis_system_prompt('en', 'A2M.AX')
    assert 'Australian ASX' in prompt
    assert 'Australia/Sydney' in prompt
    assert 'financialCurrency' in prompt and 'NZD' in prompt
    assert '{market_placeholder}' not in prompt


@pytest.mark.parametrize('fetch_ok, provider', [(False, 'YfinanceFetcher'), (True, 'EfinanceFetcher')])
def test_pipeline_refuses_rating_on_failed_or_contaminated_au_data(fetch_ok, provider):
    from datetime import date
    from src.core.pipeline import StockAnalysisPipeline
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.db = Mock()
    pipeline.db.get_latest_data.return_value = [SimpleNamespace(data_source=provider)]
    pipeline._emit_progress = Mock()
    pipeline.fetch_and_save_stock_data = Mock(return_value=(fetch_ok, 'test data missing'))
    pipeline.analyze_stock = Mock()
    pipeline._resolve_resume_target_date = Mock(return_value=date(2026, 11, 23))
    result = pipeline.process_single_stock('A2M.AX')
    assert result is None
    pipeline.analyze_stock.assert_not_called()
