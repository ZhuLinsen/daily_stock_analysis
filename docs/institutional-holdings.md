# Institutional 13F holdings (PoC)

This module treats H&H International Investment's public SEC Form 13F filings
as a proxy for publicly disclosed US long holdings. It must not be presented as
a complete or real-time personal portfolio.

## Configuration

SEC fair-access guidance requires an identifying user agent with a contact
email. Set it before importing:

```bash
export SEC_USER_AGENT="daily-stock-analysis your-team@example.com"
```

The importer uses the application's existing `DatabaseManager` and creates two
tables when needed:

- `filing_snapshots`: one immutable source snapshot per SEC accession;
- `filing_holdings`: aggregated security rows for that accession.

Quarter-over-quarter `holding_deltas` are derived from these facts rather than
stored. This keeps the output reproducible and prevents stale derived rows.

## API

Import the latest eight distinct H&H report periods (CIK `0001759760` is the
request default):

```bash
curl -X POST http://localhost:8000/api/v1/institutional-holdings/import \
  -H 'Content-Type: application/json' \
  -d '{"cik":"0001759760","max_filings":8}'
```

Read the latest imported quarter and compare it with the preceding effective
quarter:

```bash
curl http://localhost:8000/api/v1/institutional-holdings/0001759760/latest
```

The response reports:

- current and prior SEC source URLs and acceptance timestamps;
- current market-value weights and top-four/top-six concentration;
- `new`, `increased`, `decreased`, `unchanged`, and `exited` status based on
  **reported share-count changes**;
- both current and prior reported values, without treating value changes as
  purchases or sales.

When multiple accessions exist for the same report period, the newest accepted
accession (for example, an amendment) is the effective snapshot.

SEC filings submitted before January 3, 2023 reported values rounded to the
nearest thousand dollars. The importer normalizes those historical values to
US dollars; filings submitted on or after that date are already reported in
dollars.

## Disclosure and backtest boundary

Form 13F can be filed up to 45 days after quarter end. It does not disclose
cash, short positions, non-reportable securities, non-US-exchange holdings, or
intra-quarter trades. A future follower backtest must therefore start no earlier
than the first tradable bar after the filing's SEC `accepted_at` timestamp. It
must never start at `report_period`, which would introduce look-ahead bias.
