from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel


class SentimentReviewRunRequest(BaseModel):
    trade_date: Optional[date] = None
    market: str = 'cn'
    force: bool = False
