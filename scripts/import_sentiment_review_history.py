#!/usr/bin/env python
"""Import reviewed historical sentiment payloads without overwriting complete rows."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.repositories.sentiment_review_repo import SentimentReviewRepository


def import_file(path: Path, market: str = 'cn') -> int:
    records = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(records, list):
        raise ValueError('JSON root must be an array')
    repo = SentimentReviewRepository()
    saved = 0
    for item in records:
        trade_date = date.fromisoformat(str(item['trade_date']))
        payload = item.get('payload') or item.get('structured_payload')
        if not isinstance(payload, dict):
            raise ValueError(f'{trade_date}: payload must be an object')
        repo.upsert_daily(
            market=market,
            trade_date=trade_date,
            run_status='partial',
            data_quality='imported',
            structured_payload=payload,
            provider_trace={'source': item.get('source', 'controlled_import')},
            completeness=item.get('completeness') or {},
        )
        saved += 1
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description='Import historical sentiment review JSON')
    parser.add_argument('path', type=Path)
    parser.add_argument('--market', default='cn')
    args = parser.parse_args()
    print(f'imported={import_file(args.path, args.market)}')


if __name__ == '__main__':
    main()
