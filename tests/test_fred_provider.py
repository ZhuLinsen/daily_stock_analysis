from datetime import date

from src.providers.macro.fred import FREDProvider, US_FRED_SERIES


class Response:
    def __init__(self, payload): self.payload = payload
    def raise_for_status(self): pass
    def json(self): return self.payload


class Session:
    def get(self, url, params, timeout):
        if url.endswith('/fred/series'):
            return Response({'seriess': [{'title': 'Two Year', 'units': 'Percent', 'frequency': 'Daily'}]})
        return Response({'observations': [{'date': '2026-07-18', 'value': '.'}, {'date': '2026-07-17', 'value': '3.25'}]})


def test_fred_provider_skips_missing_observation():
    observation = FREDProvider('test', session=Session()).fetch_latest('treasury_2y', 'DGS2')
    assert observation and observation.value == 3.25
    assert observation.observation_date == date(2026, 7, 17)
    assert observation.unit == 'Percent'


def test_us_series_mapping_is_explicit():
    assert US_FRED_SERIES['policy_rate_upper'] == 'DFEDTARU'
