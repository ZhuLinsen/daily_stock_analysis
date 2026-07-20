from data_provider.yfinance_fetcher import YfinanceFetcher


def test_yahoo_special_symbols_are_not_treated_as_a_share_codes():
    fetcher = YfinanceFetcher()
    assert fetcher._convert_stock_code("^GSPC") == "^GSPC"
    assert fetcher._convert_stock_code("GC=F") == "GC=F"
    assert fetcher._convert_stock_code("DX-Y.NYB") == "DX-Y.NYB"
