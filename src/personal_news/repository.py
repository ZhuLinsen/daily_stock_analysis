"""Persistence and restart-safe deduplication for the personal news radar."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import and_, desc, select
from sqlalchemy.exc import IntegrityError

from src.personal_news.schemas import NewsAnalysis, NewsCandidate, NewsRadarSettings
from src.storage import (
    DatabaseManager,
    PersonalNewsAnalysis,
    PersonalNewsArticle,
    PersonalNewsHash,
    PersonalNewsProviderStatus,
    PersonalNewsPushRecord,
    PersonalNewsSetting,
    to_utc_naive_datetime,
    utc_naive_now,
)


_TRACKING_QUERY_KEYS = {
    "from",
    "ref",
    "spm",
    "source",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}
_PUNCTUATION_RE = re.compile(r"[^\w\u3400-\u9fff]+", re.UNICODE)


def normalize_title(title: str) -> str:
    normalized = unicodedata.normalize("NFKC", title or "").casefold()
    return "".join(_PUNCTUATION_RE.sub(" ", normalized).split())


def canonicalize_url(url: str) -> str:
    parts = urlsplit((url or "").strip())
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key.casefold() not in _TRACKING_QUERY_KEYS and not key.casefold().startswith("utm_")
        )
    )
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), parts.path.rstrip("/") or "/", query, ""))


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def article_hashes(candidate: NewsCandidate) -> Dict[str, str]:
    normalized_title = normalize_title(candidate.title)
    published = candidate.published_at or utc_naive_now()
    if published.tzinfo is not None:
        published = to_utc_naive_datetime(published)
    six_hour_bucket = int(published.timestamp()) // (6 * 60 * 60)
    symbols = ",".join(sorted(candidate.symbols))
    return {
        "url": stable_hash(canonicalize_url(candidate.url)),
        "title": stable_hash(normalized_title),
        "event": stable_hash(f"{symbols}|{normalized_title}|{six_hour_bucket}"),
    }


class PersonalNewsRepository:
    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def ingest(self, candidate: NewsCandidate) -> Tuple[int, bool]:
        hashes = article_hashes(candidate)
        canonical_url = canonicalize_url(candidate.url)
        normalized_title = normalize_title(candidate.title)
        published_at = candidate.published_at
        if published_at is not None:
            published_at = to_utc_naive_datetime(published_at)

        with self.db.get_session() as session:
            existing_hash = session.execute(
                select(PersonalNewsHash).where(
                    PersonalNewsHash.hash_value.in_(list(hashes.values()))
                ).limit(1)
            ).scalar_one_or_none()
            if existing_hash is not None:
                article = session.get(PersonalNewsArticle, existing_hash.article_id)
                if article is not None:
                    article.source_count = max(article.source_count or 1, candidate.source_count)
                    article.fetched_at = utc_naive_now()
                    session.commit()
                return int(existing_hash.article_id), False

            article = PersonalNewsArticle(
                title=candidate.title.strip(),
                normalized_title=normalized_title,
                title_hash=hashes["title"],
                url=canonical_url,
                source=(candidate.source or "unknown").strip(),
                summary=candidate.summary.strip(),
                symbols_json=json.dumps(candidate.symbols, ensure_ascii=False),
                published_at=published_at,
                fetched_at=utc_naive_now(),
                source_count=candidate.source_count,
                price_change_percent=candidate.price_change_percent,
                volume_change_percent=candidate.volume_change_percent,
                is_announcement=bool(candidate.is_announcement or candidate.is_regulatory),
                raw_payload_json=json.dumps(candidate.raw_payload, ensure_ascii=False, default=str),
            )
            session.add(article)
            session.flush()
            for hash_type, hash_value in hashes.items():
                session.add(PersonalNewsHash(hash_type=hash_type, hash_value=hash_value, article_id=article.id))
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                winner = session.execute(
                    select(PersonalNewsHash).where(
                        PersonalNewsHash.hash_value.in_(list(hashes.values()))
                    ).limit(1)
                ).scalar_one()
                return int(winner.article_id), False
            article_id = int(article.id)
            session.commit()
            return article_id, True

    def set_score(self, article_id: int, score: int, reasons: Iterable[str]) -> None:
        with self.db.get_session() as session:
            article = session.get(PersonalNewsArticle, article_id)
            if article is None:
                raise KeyError(article_id)
            article.importance_score = max(0, min(int(score), 100))
            article.score_reasons_json = json.dumps(list(reasons), ensure_ascii=False)
            session.commit()

    def save_analysis(
        self,
        article_id: int,
        analysis: NewsAnalysis,
        *,
        provider: str = "openai-compatible",
        model: str = "",
    ) -> None:
        payload = analysis.model_dump_json()
        with self.db.get_session() as session:
            row = session.execute(
                select(PersonalNewsAnalysis).where(PersonalNewsAnalysis.article_id == article_id)
            ).scalar_one_or_none()
            if row is None:
                row = PersonalNewsAnalysis(article_id=article_id, payload_json=payload)
                session.add(row)
            row.payload_json = payload
            row.provider = provider
            row.model = model
            row.status = "completed"
            row.error = None
            session.commit()

    def save_analysis_error(self, article_id: int, error: str) -> None:
        with self.db.get_session() as session:
            row = session.execute(
                select(PersonalNewsAnalysis).where(PersonalNewsAnalysis.article_id == article_id)
            ).scalar_one_or_none()
            if row is None:
                row = PersonalNewsAnalysis(article_id=article_id, payload_json="{}")
                session.add(row)
            row.status = "failed"
            row.error = (error or "analysis failed")[:2000]
            session.commit()

    def get_article(self, article_id: int) -> Optional[Dict[str, Any]]:
        with self.db.get_session() as session:
            article = session.get(PersonalNewsArticle, article_id)
            if article is None:
                return None
            analysis = session.execute(
                select(PersonalNewsAnalysis).where(PersonalNewsAnalysis.article_id == article_id)
            ).scalar_one_or_none()
            return self._serialize_article(article, analysis)

    def list_articles(self, *, limit: int = 50, important_only: bool = False) -> List[Dict[str, Any]]:
        statement = select(PersonalNewsArticle).order_by(
            desc(PersonalNewsArticle.published_at), desc(PersonalNewsArticle.fetched_at)
        ).limit(max(1, min(limit, 200)))
        if important_only:
            statement = statement.where(PersonalNewsArticle.importance_score > 0)
        with self.db.get_session() as session:
            articles = list(session.execute(statement).scalars().all())
            ids = [article.id for article in articles]
            analyses = {}
            if ids:
                analyses = {
                    row.article_id: row
                    for row in session.execute(
                        select(PersonalNewsAnalysis).where(PersonalNewsAnalysis.article_id.in_(ids))
                    ).scalars().all()
                }
            return [self._serialize_article(article, analyses.get(article.id)) for article in articles]

    def push_succeeded(self, article_id: int, channel: str) -> bool:
        with self.db.get_session() as session:
            row = session.execute(
                select(PersonalNewsPushRecord).where(
                    and_(
                        PersonalNewsPushRecord.article_id == article_id,
                        PersonalNewsPushRecord.channel == channel,
                        PersonalNewsPushRecord.status == "sent",
                    )
                )
            ).scalar_one_or_none()
            return row is not None

    def record_push(self, article_id: int, channel: str, *, success: bool, error: str = "") -> None:
        with self.db.get_session() as session:
            row = session.execute(
                select(PersonalNewsPushRecord).where(
                    and_(
                        PersonalNewsPushRecord.article_id == article_id,
                        PersonalNewsPushRecord.channel == channel,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = PersonalNewsPushRecord(article_id=article_id, channel=channel)
                session.add(row)
            row.attempts = int(row.attempts or 0) + 1
            row.status = "sent" if success else "failed"
            row.last_error = None if success else (error or "push failed")[:2000]
            row.pushed_at = utc_naive_now() if success else None
            row.updated_at = utc_naive_now()
            session.commit()

    def sync_settings(self, settings: NewsRadarSettings) -> None:
        values = {
            "watchlist": ",".join(settings.watchlist),
            "macro_keywords": ",".join(settings.macro_keywords),
            "poll_interval_minutes": str(settings.poll_interval_minutes),
            "min_analysis_score": str(settings.min_analysis_score),
            "min_push_score": str(settings.min_push_score),
            "public_base_url": settings.public_base_url,
        }
        with self.db.get_session() as session:
            for key, value in values.items():
                row = session.get(PersonalNewsSetting, key)
                if row is None:
                    session.add(PersonalNewsSetting(key=key, value=value))
                else:
                    row.value = value
                    row.updated_at = utc_naive_now()
            session.commit()

    def set_provider_status(self, provider: str, provider_type: str, status: str, message: str = "") -> None:
        with self.db.get_session() as session:
            row = session.get(PersonalNewsProviderStatus, provider)
            if row is None:
                row = PersonalNewsProviderStatus(provider=provider, provider_type=provider_type)
                session.add(row)
            row.status = status
            row.message = (message or "")[:2000]
            row.checked_at = utc_naive_now()
            session.commit()

    def list_provider_status(self) -> List[Dict[str, Any]]:
        with self.db.get_session() as session:
            rows = session.execute(
                select(PersonalNewsProviderStatus).order_by(PersonalNewsProviderStatus.provider_type, PersonalNewsProviderStatus.provider)
            ).scalars().all()
            return [
                {
                    "provider": row.provider,
                    "provider_type": row.provider_type,
                    "status": row.status,
                    "message": row.message or "",
                    "checked_at": row.checked_at,
                }
                for row in rows
            ]

    @staticmethod
    def _serialize_article(article: PersonalNewsArticle, analysis: Optional[PersonalNewsAnalysis]) -> Dict[str, Any]:
        analysis_payload = None
        if analysis is not None and analysis.status == "completed":
            try:
                analysis_payload = json.loads(analysis.payload_json)
            except json.JSONDecodeError:
                analysis_payload = None
        return {
            "id": article.id,
            "title": article.title,
            "url": article.url,
            "source": article.source,
            "summary": article.summary or "",
            "symbols": json.loads(article.symbols_json or "[]"),
            "published_at": article.published_at,
            "fetched_at": article.fetched_at,
            "importance_score": article.importance_score,
            "score_reasons": json.loads(article.score_reasons_json or "[]"),
            "source_count": article.source_count,
            "price_change_percent": article.price_change_percent,
            "volume_change_percent": article.volume_change_percent,
            "is_announcement": article.is_announcement,
            "analysis": analysis_payload,
            "analysis_status": analysis.status if analysis else "pending",
            "analysis_error": analysis.error if analysis else None,
        }
