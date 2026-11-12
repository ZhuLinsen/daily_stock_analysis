"""Daily Actions env and runtime routing must agree on optional data sources."""
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import yaml

from data_provider.base import DataFetcherManager
from data_provider.tickplus_fetcher import TickPlusFetcher
from src.config import Config


WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/00-daily-analysis.yml'


def _apply_actions_env(monkeypatch, *, tickplus='', tushare='', explicit=''):
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding='utf-8'))
    step = next(s for s in workflow['jobs']['analyze']['steps'] if s.get('name') == '执行股票分析')
    env = step['env']
    assert env['TICKPLUS_API_KEY'] == '${{ secrets.TICKPLUS_API_KEY }}'
    # An unset Actions variable expands to ''. A literal nonempty fallback here
    # bypasses Config's automatic source selection and must fail this regression.
    assert env['REALTIME_SOURCE_PRIORITY'] == '${{ vars.REALTIME_SOURCE_PRIORITY }}'
    monkeypatch.setenv('TICKPLUS_API_KEY', tickplus)
    monkeypatch.setenv('TUSHARE_TOKEN', tushare)
    monkeypatch.setenv('REALTIME_SOURCE_PRIORITY', explicit)
    return Config._resolve_realtime_source_priority()


@pytest.mark.parametrize('tickplus,tushare,explicit,prefix', [
    ('test-key', '', '', 'tickplus,tencent,'),
    ('test-key', 'other-key', '', 'tickplus,tushare,tencent,'),
    ('', 'other-key', '', 'tushare,tencent,'),
    ('', '', '', 'tencent,akshare_sina,'),
    ('test-key', '', 'tencent,akshare_sina', 'tencent,akshare_sina'),
    ('test-key', '', 'tickflow,tickplus,tencent', 'tickflow,tickplus,tencent'),
])
def test_daily_actions_respects_key_selection_and_explicit_priority(monkeypatch, tickplus, tushare, explicit, prefix):
    resolved = _apply_actions_env(monkeypatch, tickplus=tickplus, tushare=tushare, explicit=explicit)
    assert resolved.startswith(prefix)
    if explicit:
        assert resolved == explicit


def test_actions_key_only_reaches_tickplus_realtime_and_batch_prefetch(monkeypatch):
    priority = _apply_actions_env(monkeypatch, tickplus='test-key')
    config = Config(tickplus_api_key='test-key', realtime_source_priority=priority)
    fetcher = TickPlusFetcher('test-key')
    manager = DataFetcherManager(fetchers=[fetcher])
    codes = ['000001', '600519', '300750', '510300', '159915']

    def response(url, **kwargs):
        assert url.endswith('/fullfactor')
        result = Mock()
        result.json.return_value = [dict(
            code=code, name='fixture', zxj=10, zrspj=9, cjl=100, cje=100000,
            tradeDate='2026-11-12 15:00:00', lb=1.2, hsl=2,
        ) for code in kwargs['params']['code'].split(',')]
        return result

    with patch('src.config.get_config', return_value=config), patch(
        'data_provider.tickplus_fetcher.requests.get', side_effect=response
    ) as get:
        assert manager.prefetch_realtime_quotes(codes) == 5
        quote = manager.get_realtime_quote('000001')
        assert quote.source.value == 'tickplus'
        assert quote.price == 10 and quote.volume_ratio == 1.2
        assert get.call_count == 2  # One stock group and one ETF group; quote hits cache.
