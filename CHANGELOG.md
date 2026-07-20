# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]
### Fixed
- Fix US/HK ticker news relevance scoring for English articles (issue #2026)
  - When STOCK_NAME_MAP maps a US/HK ticker to a Chinese display name (e.g., AAPL -> "苹果"),
    English news articles about the company were incorrectly downgraded to macro_market_news
    because the Chinese name didn't match English text.
  - Added a search-layer alias map (_FOREIGN_TICKER_ENGLISH_ALIASES) that provides English
    display names for affected tickers (e.g., AAPL -> "Apple Inc.").
  - The alias is used in:
      1. Constructing English search queries for foreign tickers (search_stock_news,
         search_comprehensive_intel)
      2. Extending the company identity term set for relevance scoring (_company_identity_terms)
  - Ensures English articles about AAPL, TSLA, etc. are correctly recognized as
    direct_company_news when the pipeline supplies a Chinese name.
  - A-share code path remains unchanged (no alias map applied).