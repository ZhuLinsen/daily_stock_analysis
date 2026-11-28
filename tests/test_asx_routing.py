"""ASX market identity must survive daily/quote routing and provider failure."""
from unittest.mock import Mock, patch
import pytest
from data_provider.base import DataFetcherManager, DataFetchError, _market_tag
from data_provider.us_index_mapping import is_us_stock_code, get_us_stock_yf_symbol
from data_provider.yfinance_fetcher import YfinanceFetcher
from src.services.market_symbol_utils import get_suffix_market, normalize_suffix_market_symbol
from src.services.stock_code_utils import resolve_daily_stock_identity

ASX = ['A2M.AX','NXT.AX','GAME.AX','XMET.AX','BHP.AX','A200.AX','CSL.AX','CBA.AX','WBC.AX','WES.AX','TLS.AX','VAS.AX','NDQ.AX','FMG.AX','RIO.AX','WDS.AX','STO.AX','CAR.AX','SGH.AX']

@pytest.mark.parametrize('code', ASX)
def test_asx_is_separate_market(code):
    assert get_suffix_market(code) == 'au'
    assert _market_tag(code) == 'au'
    assert not is_us_stock_code(code)
    assert get_us_stock_yf_symbol(code) is None
    assert YfinanceFetcher()._convert_stock_code(code) == code
    from src.services.stock_code_utils import is_code_like, normalize_code
    assert is_code_like(code)
    assert normalize_code(code) == code
    identity = resolve_daily_stock_identity(code)
    assert identity is not None
    assert identity.market == 'au'
    assert identity.normalized_code == code
    assert code[:-3] not in identity.code_candidates

@pytest.mark.parametrize('code', ['A2M.AX','a200.ax','ABCDEF.AX'])
def test_alphanumeric_and_six_character_symbols(code):
    assert normalize_suffix_market_symbol(code) == code.upper()

@pytest.mark.parametrize('code', ['A2M','NXT','GAME','XMET','ABCDEFG.AX','A-1.AX','ABC..AX','中.AX'])
def test_no_implicit_australian_identity(code):
    assert get_suffix_market(code) is None

@pytest.mark.parametrize('code', ['AAPL','QQQ','BRK.B'])
def test_us_regression(code):
    assert is_us_stock_code(code)
    assert _market_tag(code) == 'us'

def test_daily_failure_never_calls_chinese_or_us_provider():
    bad = Mock(name='cn'); bad.name='EfinanceFetcher'; bad.priority=0
    us = Mock(name='us'); us.name='FinnhubFetcher'; us.priority=1
    yf = YfinanceFetcher()
    manager = DataFetcherManager(fetchers=[bad, us, yf])
    with patch.object(yf, 'get_daily_data', side_effect=DataFetchError('test missing Yahoo data')), patch.object(manager, '_filter_fetchers_by_capability', side_effect=lambda fs, **kw: fs):
        with pytest.raises(DataFetchError):
            manager.get_daily_data('A2M.AX')
    bad.get_daily_data.assert_not_called()
    us.get_daily_data.assert_not_called()

def test_realtime_failure_only_tries_yahoo():
    manager = DataFetcherManager(fetchers=[YfinanceFetcher()])
    with patch.object(manager, '_try_fetcher_quote', return_value=None) as fetch:
        assert manager.get_realtime_quote('A2M.AX') is None
    assert [c.args[1] for c in fetch.call_args_list] == ['YfinanceFetcher']
