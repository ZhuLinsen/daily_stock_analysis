from src.services.us_macro_rules import assess_us_macro


def test_rules_return_neutral_low_when_data_is_insufficient():
    result = assess_us_macro([], [])
    assert result['horizons']['未来1周']['direction'] == '中性'
    assert result['horizons']['未来1周']['confidence'] == '低'


def test_rules_classify_risk_on_with_supporting_signals():
    result = assess_us_macro([
        {'indicator': 'vix', 'change_5d': -12},
        {'indicator': 'sp500', 'above_ma_20': True, 'above_ma_50': True},
    ], [{'indicator': 'treasury_2y', 'value': 4.0}, {'indicator': 'treasury_10y', 'value': 4.2}])
    assert result['regime'] == 'risk_on'
    assert result['horizons']['当日或下一交易日']['direction'] in ('偏多', '明显偏多')
