from unittest.mock import Mock, patch

import pandas as pd
import pytest
import requests

from data_provider.base import BaseFetcher, DataFetchError, DataFetcherManager
from data_provider.realtime_types import RealtimeSource
from data_provider.tickplus_fetcher import TickPlusFetcher
from src.config import Config

ROW = dict(t='2026-11-12 15:00:00', code='600519', o=100, c=110, h=112, l=99, v=12.5, a=125000, pc=100)


def response(data):
    r = Mock()
    r.json.return_value = data
    return r


def test_daily_normalizes_units_dates_change_and_request_contract():
    f = TickPlusFetcher('private-test')
    rows = [dict(ROW, t='2026-11-13'), ROW, dict(ROW, t='2026-11-11', c=105)]
    with patch('data_provider.tickplus_fetcher.requests.get', return_value=response(rows)) as get:
        df = f.get_daily_data('600519', '2026-11-11', '2026-11-12')
    assert len(df) == 2
    assert list(df.volume) == [1250, 1250]
    assert df.iloc[-1].pct_chg == pytest.approx(10)
    assert df.iloc[-1]['close'] == 110
    params = get.call_args.kwargs['params']
    assert params['dividend'] == '1' and params['period'] == '1d'
    assert params['token'] == 'private-test'
    assert get.call_args.kwargs['timeout'] == 15


def test_quote_checks_identity_and_converts_units():
    f = TickPlusFetcher('private-test')
    with patch('data_provider.tickplus_fetcher.requests.get', return_value=response([ROW])):
        quote = f.get_realtime_quote('sh600519')
    assert quote.provider_timestamp.endswith("+08:00")
    assert quote.source == RealtimeSource.TICKPLUS
    assert quote.volume == 1250 and quote.change_pct == pytest.approx(10)
    f = TickPlusFetcher('private-test')
    with patch('data_provider.tickplus_fetcher.requests.get', return_value=response([dict(ROW, code='000001')])):
        with pytest.raises(DataFetchError, match='target'):
            f.get_realtime_quote('600519')


@pytest.mark.parametrize('value', [dict(error='no permission'), 'invalid'])
def test_permission_error_cools_down_and_does_not_expose_response(value):
    f = TickPlusFetcher('private-test')
    with patch('data_provider.tickplus_fetcher.requests.get', return_value=response(value)) as get:
        with pytest.raises(DataFetchError) as exc:
            f.get_realtime_quote('600519')
        assert 'private-test' not in str(exc.value)
        assert not f.is_available("realtime_quote")
        assert f.is_available("daily_data")
        with pytest.raises(DataFetchError):
            f.get_realtime_quote('600519')
        assert get.call_count == 2


def test_network_error_redacts_url_and_chain():
    f = TickPlusFetcher('private-test')
    with patch('data_provider.tickplus_fetcher.requests.get', side_effect=requests.Timeout('http://example?token=private-test')):
        with pytest.raises(DataFetchError) as exc:
            f.get_realtime_quote('600519')
    assert 'private-test' not in str(exc.value)
    assert exc.value.__context__ is None


@pytest.mark.parametrize('code', ['AAPL', 'HK00700', 'sh000001', '930606.CSI', '005930.KS', '2330.TW'])
def test_unsupported_symbols_do_not_make_requests(code):
    with patch('data_provider.tickplus_fetcher.requests.get') as get:
        with pytest.raises(DataFetchError):
            TickPlusFetcher('private-test').get_realtime_quote(code)
        get.assert_not_called()


def test_etf_and_names_use_correct_symbol_and_cache():
    f = TickPlusFetcher('private-test')
    with patch('data_provider.tickplus_fetcher.requests.get', return_value=response([dict(code='510300', name='ETF')])) as get:
        assert f.get_stock_name('510300') == 'ETF'
        assert f.get_stock_name('510300') == 'ETF'
        assert get.call_count == 1
        assert get.call_args.kwargs['params']['symbol'] == 'etf'


def test_priority_respects_explicit_and_injects_configured_provider(monkeypatch):
    monkeypatch.delenv('REALTIME_SOURCE_PRIORITY', raising=False)
    monkeypatch.setenv('TICKPLUS_API_KEY', 'private-test')
    monkeypatch.setenv('TUSHARE_TOKEN', 'other-test')
    assert Config._resolve_realtime_source_priority().startswith('tickplus,tushare,')
    monkeypatch.setenv('REALTIME_SOURCE_PRIORITY', 'tencent,tickplus')
    assert Config._resolve_realtime_source_priority() == 'tencent,tickplus'


def test_daily_manager_falls_back_after_tickplus_failure():
    class Backup(BaseFetcher):
        name = 'Backup'
        priority = 1

        def _fetch_raw_data(self, *args):
            return pd.DataFrame([dict(date='2026-11-12', open=10, high=12, low=9, close=11, volume=100, amount=1100, pct_chg=10)])

        def _normalize_data(self, frame, code):
            return frame

    f = TickPlusFetcher('private-test')
    manager = DataFetcherManager(fetchers=[f, Backup()])
    with patch('data_provider.tickplus_fetcher.requests.get', side_effect=requests.Timeout('secret')):
        frame, provider = manager.get_daily_data('600519', '2026-11-11', '2026-11-12')
    assert provider == 'Backup'
    assert frame.iloc[-1]['close'] == 11


def test_registry_marks_key_sensitive_and_capabilities_are_scoped():
    from src.core.config_registry import _FIELD_DEFINITIONS
    from src.services.data_capability_service import _PROVIDER_DEFINITION_MAP
    assert _FIELD_DEFINITIONS['TICKPLUS_API_KEY']['is_sensitive']
    definition = _PROVIDER_DEFINITION_MAP['tickplus']
    assert definition.dataset_markets == {'quote.realtime': ('cn',), 'kline.daily': ('cn',)}



def test_realtime_manager_routes_tickplus_without_changing_index_chain():
    f = TickPlusFetcher('private-test')
    manager = DataFetcherManager(fetchers=[f])
    config = Config(realtime_source_priority='tickplus')
    with patch('src.config.get_config', return_value=config), patch(
        'data_provider.tickplus_fetcher.requests.get', return_value=response([ROW])
    ):
        quote = manager.get_realtime_quote('600519')
    assert quote is not None and quote.source == RealtimeSource.TICKPLUS
    assert quote.price == 110 and quote.volume == 1250
    assert 'TickPlusFetcher' not in manager._CN_INDEX_DAILY_SOURCE_ORDER


@pytest.mark.parametrize('code,expected', [
    ('000001', ('000001', 'stock')), ('sz000001', ('000001', 'stock')),
    ('000001.SZ', ('000001', 'stock')), ('000016', ('000016', 'stock')),
    ('600519.SH', ('600519', 'stock')), ('bj920002', ('920002', 'stock')),
    ('688981', ('688981', 'stock')), ('689009', ('689009', 'stock')),
    ('159915', ('159915', 'etf')), ('588000', ('588000', 'etf')),
    ('520880', ('520880', 'etf')), ('563300', ('563300', 'etf')),
])
def test_stock_identity_and_board_etf_routing(code, expected):
    assert TickPlusFetcher._symbol(code) == expected


def factor_row(code='600519', **kwargs):
    return dict(code=code, name='name', zxj=110, zrspj=100, cjl=12.5, cje=125000,
                tradeDate='2026-11-12 15:00:00', lb=1.5, hsl=2.5, zf=3,
                dtsyl=20, sjl=3, zsz=1000000, ltsz=900000, zdf60=10, **kwargs)


def test_factor_fields_and_percentage_units_without_extra_quote_request():
    f = TickPlusFetcher('private-test')
    with patch('data_provider.tickplus_fetcher.requests.get', return_value=response([factor_row()])) as get:
        quote = f.get_realtime_quote('600519')
        quote.volume_ratio = 99  # Mutating a returned quote must not pollute the cache.
        again = f.get_realtime_quote('600519.SH')
    assert get.call_count == 1
    assert get.call_args.args[0].endswith('/fullfactor')
    assert again.volume_ratio == 1.5 and again.turnover_rate == 2.5
    assert again.amplitude == 3 and again.change_60d == 10
    assert again.pe_ratio == 20 and again.pb_ratio == 3
    assert again.volume == 1250 and again.amount == 125000


def test_etf_factor_does_not_treat_stock_valuation_sentinels_as_fundamentals():
    with patch('data_provider.tickplus_fetcher.requests.get', return_value=response([factor_row('510300')])):
        quote = TickPlusFetcher('private-test').get_realtime_quote('510300')
    assert quote.pe_ratio is None and quote.pb_ratio is None
    assert quote.turnover_rate == 2.5


def test_indicator_permission_failure_keeps_basic_quotes_and_daily_available():
    f = TickPlusFetcher('private-test')
    def get(url, **kwargs):
        if url.endswith('/fullfactor'):
            return response({'error': 'permission denied'})
        return response([ROW])
    with patch('data_provider.tickplus_fetcher.requests.get', side_effect=get) as call:
        quote = f.get_realtime_quote('600519')
    assert quote.price == 110 and quote.volume_ratio is None
    assert len(call.call_args_list) == 2
    assert f.is_available('realtime_quote') and f.is_available('daily_data')
    assert not f._endpoint_ready('fullfactor')


def test_prefetch_groups_stock_etf_and_chunks_at_hard_limit():
    f = TickPlusFetcher('private-test')
    codes = [str(600000+i) for i in range(101)] + ['510300', '159915', 'sh000001', 'AAPL']
    def get(url, **kwargs):
        assert url.endswith('/fullfactor')
        return response([factor_row(code) for code in kwargs['params']['code'].split(',')])
    with patch('data_provider.tickplus_fetcher.requests.get', side_effect=get) as call:
        assert f.prefetch_realtime_quotes(codes, batch_size=500) == 103
        assert f.get_realtime_quote('600001').price == 110
    assert len(call.call_args_list) == 3
    assert [len(c.kwargs['params']['code'].split(',')) for c in call.call_args_list] == [100,1,2]
    assert [c.kwargs['params']['symbol'] for c in call.call_args_list] == ['stock','stock','etf']


def test_manager_prefetch_uses_tickplus_and_preserves_index_identity():
    f = TickPlusFetcher('private-test')
    manager = DataFetcherManager(fetchers=[f])
    config = Config(realtime_source_priority='tickplus,tencent')
    with patch('src.config.get_config', return_value=config), patch.object(f, 'prefetch_realtime_quotes', return_value=4) as prefetch:
        assert manager.prefetch_realtime_quotes(['600519','000001','300750','510300','sh000001']) == 4
    assert 'sh000001' in prefetch.call_args.args[0]
    assert prefetch.call_args.kwargs['batch_size'] == 100


def test_daily_cooldown_does_not_disable_quotes_or_names():
    f = TickPlusFetcher('private-test')
    with patch('data_provider.tickplus_fetcher.requests.get', side_effect=requests.Timeout('secret')):
        with pytest.raises(DataFetchError):
            f.get_daily_data('600519', '2026-11-01', '2026-11-12')
    assert not f.is_available('daily_data')
    assert f.is_available('realtime_quote')


def test_empty_name_response_does_not_poison_list_cache():
    f = TickPlusFetcher('private-test')
    with patch('data_provider.tickplus_fetcher.requests.get', side_effect=[response([]),response([dict(code='000001', name='bank')])]):
        assert f.get_stock_name('000001') is None
        assert f.get_stock_name('000001') == 'bank'


def test_rotation_uses_request_local_forward_adjustment(monkeypatch):
    from datetime import date
    from src.services.etf_rotation_service import load_closes
    f = TickPlusFetcher('private-test')
    manager = DataFetcherManager(fetchers=[f])
    monkeypatch.setattr('src.core.trading_calendar.get_trading_dates', lambda *args: pd.DatetimeIndex(['2026-11-12']))
    with patch('data_provider.tickplus_fetcher.requests.get', return_value=response([dict(ROW,code='510300')])) as get:
        loaded = load_closes(manager, ['510300'], years=1, end=date(2026,11,12))
    assert not loaded.failed
    assert loaded.sources == {'510300':'TickPlusFetcher'}
    assert get.call_args.kwargs['params']['dividend'] == '2'
    assert f.kline_adjust == 'none' and manager._get_fetchers_snapshot()[0] is f


@pytest.mark.parametrize('bad', [float('inf'),float('nan'),0,-1])
def test_invalid_factor_prices_do_not_become_valid_quotes(bad):
    row = factor_row()
    row['zxj'] = bad
    with patch('data_provider.tickplus_fetcher.requests.get', return_value=response([row])):
        with pytest.raises(DataFetchError):
            TickPlusFetcher('private-test').get_realtime_quote('600519')



def test_capability_overview_keeps_unvalidated_key_unknown_and_never_leaks_secret():
    import json
    from src.services.data_capability_service import DataCapabilityService
    f = TickPlusFetcher('private-test')
    service = DataCapabilityService(config=Config(tickplus_api_key='private-test', realtime_source_priority='tickplus'),
                                    fetcher_manager=DataFetcherManager(fetchers=[f]))
    with patch('data_provider.tickplus_fetcher.requests.get') as get:
        overview = service.get_overview()
        get.assert_not_called()
    provider = next(p for p in overview['providers'] if p['name']=='tickplus')
    assert provider['configured'] and provider['status']=='unknown'
    assert 'private-test' not in json.dumps(overview)
    with patch('data_provider.tickplus_fetcher.requests.get',return_value=response([factor_row()])):
        f.get_realtime_quote('600519')
    assert f.runtime_status == 'ok'


def test_recommendation_metadata_links_the_project_registration_and_masks_key():
    from src.core.config_registry import get_field_definition
    field = get_field_definition('TICKPLUS_API_KEY')
    assert field['is_sensitive'] and field['ui_control']=='password'
    assert 'Recommended' in field['title']
    assert any(doc['href']=='http://www.tickplus.org/register?reg=5433cf922395' for doc in field['docs'])



@pytest.mark.parametrize('api_key,priority', [(None, 0), ('', 0), ('   ', 0), ('private-test', 0), ('private-test', 3)])
def test_default_manager_registers_tickplus_only_for_configured_key(api_key, priority):
    config = Config(tickplus_api_key=api_key, tickplus_priority=priority)
    with patch('src.config.get_config', return_value=config), patch(
        'data_provider.tickplus_fetcher.requests.get'
    ) as get:
        manager = DataFetcherManager()
        get.assert_not_called()
    fetchers = manager._get_fetchers_snapshot()
    registered = [f for f in fetchers if f.name == 'TickPlusFetcher']
    assert len(registered) == int(bool(api_key and api_key.strip()))
    if registered:
        assert registered[0].api_key == api_key
        assert registered[0].priority == priority
        if priority == 0:
            assert fetchers[0] is registered[0]
