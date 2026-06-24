# -*- coding: utf-8 -*-
"""Configurable compliant news / intelligence source service."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import re
import socket
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from xml.etree import ElementTree as ET

import requests
from sqlalchemy.exc import IntegrityError

from src.config import get_config
from src.repositories.intelligence_repo import IntelligenceRepository
from src.storage import IntelligenceSource, INTELLIGENCE_ITEM_NULL_SCOPE_VALUE
from src.services.run_diagnostics import sanitize_diagnostic_text

logger = logging.getLogger(__name__)
_ALLOWED_SOURCE_TYPES = {"rss", "atom", "newsnow"}
_ALLOWED_SCOPE_TYPES = {"symbol", "market", "sector"}
_ALLOWED_MARKETS = {"cn", "hk", "us", "jp", "kr", "global"}
_PRIVATE_HOSTNAMES = {"localhost", "localhost.localdomain"}
_MAX_FEED_BYTES = 2 * 1024 * 1024
_MAX_FEED_REDIRECTS = 5
_UPSTREAM_FETCH_FAILURE_MESSAGE = "fetch failed: upstream request failed"
_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
_DISABLE_REQUEST_PROXIES = {"http": None, "https": None}
_DNS_GUARD_LOCK = threading.Lock()
_BUILTIN_SOURCE_TEMPLATES = [
    {
        "template_id": "sec-company-news",
        "name": "SEC Latest Filings",
        "source_type": "rss",
        "url": "https://www.sec.gov/news/pressreleases.rss",
        "scope_type": "market",
        "market": "us",
        "description": "SEC official press release RSS feed for US market evidence.",
    },
    {
        "template_id": "hkex-news",
        "name": "HKEX Market News",
        "source_type": "rss",
        "url": "https://www.hkex.com.hk/Services/RSS-Feeds/News-Releases?sc_lang=en",
        "scope_type": "market",
        "market": "hk",
        "description": "HKEX public news entry for Hong Kong market evidence. Test before enabling.",
    },
    {
        "template_id": "global-marketwatch",
        "name": "MarketWatch Top Stories",
        "source_type": "rss",
        "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
        "scope_type": "market",
        "market": "global",
        "description": "Public market news RSS for global market context. Test before enabling.",
    },
]
_NEWSNOW_DEFAULT_SOURCE_DEFS = [
    {
        "template_id": "newsnow-cls-hot",
        "name": "NewsNow 财联社热门",
        "source_id": "cls-hot",
        "market": "cn",
        "description": "NewsNow 财联社热门财经资讯，适合 A 股大盘和题材热点。",
    },
    {
        "template_id": "newsnow-xueqiu-hotstock",
        "name": "NewsNow 雪球热门股票",
        "source_id": "xueqiu-hotstock",
        "market": "cn",
        "description": "NewsNow 雪球热门股票，适合捕捉 A 股和港美股散户关注度。",
    },
    {
        "template_id": "newsnow-wallstreetcn-quick",
        "name": "NewsNow 华尔街见闻快讯",
        "source_id": "wallstreetcn-quick",
        "market": "cn",
        "description": "NewsNow 华尔街见闻快讯，适合宏观、商品和市场事件上下文。",
    },
    {
        "template_id": "newsnow-jin10",
        "name": "NewsNow 金十数据",
        "source_id": "jin10",
        "market": "global",
        "description": "NewsNow 金十数据实时财经消息，适合全球宏观和外盘事件。",
    },
    {
        "template_id": "newsnow-gelonghui",
        "name": "NewsNow 格隆汇事件",
        "source_id": "gelonghui",
        "market": "hk",
        "description": "NewsNow 格隆汇事件资讯，适合港股和中概股市场上下文。",
    },
]


class IntelligenceServiceError(ValueError):
    """User-facing validation error for intelligence operations."""


@dataclass(frozen=True)
class FeedEntry:
    title: str
    summary: str
    url: str
    source: str
    published_at: Optional[datetime]
    raw_payload: Dict[str, Any]


class IntelligenceService:
    """Fetch, validate, persist and query configurable intelligence sources."""

    def __init__(self, repository: Optional[IntelligenceRepository] = None):
        self.repo = repository or IntelligenceRepository()
        self.config = get_config()

    def create_source(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        fields = self._normalize_source_fields(payload)
        self._validate_url(fields["url"])
        try:
            return self._source_to_dict(self.repo.create_source(fields))
        except IntegrityError as exc:
            raise IntelligenceServiceError(f"intelligence source name already exists: {fields['name']}") from exc

    def list_sources(self, **filters: Any) -> Dict[str, Any]:
        rows, total = self.repo.list_sources(**filters)
        return {
            "items": [self._source_to_dict(row) for row in rows],
            "total": total,
            "page": max(1, int(filters.get("page") or 1)),
            "page_size": max(1, min(int(filters.get("page_size") or 50), 100)),
        }

    def list_source_templates(self, **filters: Any) -> Dict[str, Any]:
        market = str(filters.get("market") or "").strip().lower()
        source_type = str(filters.get("source_type") or "").strip().lower()
        templates = []
        for template in self._builtin_source_templates():
            if market and template["market"] != market:
                continue
            if source_type and template["source_type"] != source_type:
                continue
            templates.append(dict(template))
        return {"items": templates, "total": len(templates)}

    def create_source_from_template(self, template_id: str, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        selected = next(
            (dict(template) for template in self._builtin_source_templates() if template["template_id"] == template_id),
            None,
        )
        if selected is None:
            raise IntelligenceServiceError(f"Intelligence source template not found: {template_id}")
        payload = {key: value for key, value in selected.items() if key != "template_id"}
        payload.update({key: value for key, value in (overrides or {}).items() if value is not None})
        return self.create_source(payload)

    def create_default_sources(self, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        request_fields = dict(overrides or {})
        request_fields.setdefault("enabled", False)
        created_count = 0
        items = []
        for template in self._builtin_source_templates():
            payload = {key: value for key, value in template.items() if key != "template_id"}
            payload.update({key: value for key, value in request_fields.items() if value is not None})
            existing = self.repo.get_source_by_name(str(payload["name"]))
            if existing is not None:
                items.append({"created": False, "source": self._source_to_dict(existing)})
                continue
            source = self.create_source(payload)
            created_count += 1
            items.append({"created": True, "source": source})
        return {"items": items, "created_count": created_count, "total": len(items)}

    def list_items(self, **filters: Any) -> Dict[str, Any]:
        rows, total = self.repo.list_items(**filters)
        return {
            "items": [self._item_to_dict(row) for row in rows],
            "total": total,
            "page": max(1, int(filters.get("page") or 1)),
            "page_size": max(1, min(int(filters.get("page_size") or 50), 100)),
        }

    def test_source(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        fields = self._normalize_source_fields(payload)
        entries = self._fetch_feed_entries(fields, limit=min(5, self.config.news_intel_max_items_per_source))
        return {
            "ok": True,
            "source": self._redact_source_fields(fields),
            "fetched_count": len(entries),
            "sample_items": [self._feed_entry_to_dict(entry) for entry in entries[:5]],
        }

    def fetch_source(self, source_id: int, *, dry_run: bool = False) -> Dict[str, Any]:
        source = self.repo.get_source(source_id)
        if source is None:
            raise IntelligenceServiceError(f"Intelligence source not found: {source_id}")
        if not source.enabled:
            raise IntelligenceServiceError(f"Intelligence source is disabled: {source_id}")
        now = datetime.now()
        try:
            entries = self._fetch_feed_entries(self._source_to_fields(source), limit=self.config.news_intel_max_items_per_source)
            item_fields = [self._entry_to_item_fields(entry, source, now) for entry in entries]
            saved = 0 if dry_run else self.repo.upsert_items(item_fields)
            deleted = 0 if dry_run else self.repo.apply_retention(self.config.news_intel_retention_days)
            if not dry_run:
                self.repo.update_source_status(source.id, status="success", error=None, fetched_at=now)
            return {
                "ok": True,
                "source_id": source.id,
                "fetched_count": len(entries),
                "saved_count": saved,
                "retention_deleted": deleted,
                "dry_run": dry_run,
                "sample_items": [self._feed_entry_to_dict(entry) for entry in entries[:5]],
            }
        except Exception as exc:
            error = self._sanitize_error(exc)
            if not dry_run:
                self.repo.update_source_status(source.id, status="failed", error=error)
            logger.warning("Intelligence source fetch failed id=%s name=%s: %s", source.id, source.name, error)
            raise

    def fetch_enabled_sources(self) -> Dict[str, Any]:
        rows, total = self.repo.list_sources(enabled=True, page=1, page_size=100)
        results = []
        page = 1
        source_count = 0
        while True:
            for row in rows:
                source_count += 1
                try:
                    results.append(self.fetch_source(row.id))
                except Exception as exc:
                    results.append({"ok": False, "source_id": row.id, "error": self._sanitize_error(exc)})
            if source_count >= total:
                break
            page += 1
            rows, _ = self.repo.list_sources(enabled=True, page=page, page_size=100)
            if not rows:
                break
        return {
            "ok": True,
            "source_count": source_count,
            "results": results,
            "saved_count": sum(int(item.get("saved_count") or 0) for item in results),
        }

    def _normalize_source_fields(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        url = str(payload.get("url") or "").strip()
        source_type = str(payload.get("source_type") or "rss").strip().lower()
        scope_type = str(payload.get("scope_type") or "market").strip().lower()
        scope_value = str(payload.get("scope_value") or "").strip() or None
        market = str(payload.get("market") or "cn").strip().lower()
        enabled = bool(payload.get("enabled", True))
        description = str(payload.get("description") or "").strip() or None
        if not name:
            raise IntelligenceServiceError("source name is required")
        if not url:
            raise IntelligenceServiceError("source url is required")
        if source_type not in _ALLOWED_SOURCE_TYPES:
            raise IntelligenceServiceError(f"unsupported source_type: {source_type}")
        if scope_type not in _ALLOWED_SCOPE_TYPES:
            raise IntelligenceServiceError(f"unsupported scope_type: {scope_type}")
        if scope_type in {"symbol", "sector"} and not scope_value:
            raise IntelligenceServiceError(f"scope_value is required when scope_type={scope_type}")
        if market not in _ALLOWED_MARKETS:
            raise IntelligenceServiceError(f"unsupported market: {market}")
        return {
            "name": name[:100],
            "source_type": source_type,
            "url": url,
            "enabled": enabled,
            "scope_type": scope_type,
            "scope_value": scope_value[:64] if scope_value else None,
            "market": market,
            "description": description,
        }

    def _validate_url(self, raw_url: str, *, allow_no_url: bool = False) -> None:
        if allow_no_url and raw_url.startswith("no-url:intel:"):
            return
        parsed = urlparse(raw_url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            raise IntelligenceServiceError("source url must be an absolute http(s) URL")
        if parsed.username or parsed.password:
            raise IntelligenceServiceError("source url must not contain credentials")
        hostname = (parsed.hostname or "").strip().lower().rstrip(".")
        if not hostname:
            raise IntelligenceServiceError("source url host is required")
        if hostname in _PRIVATE_HOSTNAMES or hostname.endswith(".local"):
            raise IntelligenceServiceError("source url host is not allowed")
        has_public_address = False
        try:
            ip = ipaddress.ip_address(hostname)
        except ValueError:
            ip = None
        if ip is not None:
            if self._is_blocked_ip(ip):
                raise IntelligenceServiceError("source url must not target private or local network addresses")
            return
        try:
            addr_infos = socket.getaddrinfo(hostname, None)
        except OSError as exc:
            raise IntelligenceServiceError(f"source url host DNS resolution failed: {hostname}") from exc
        if not addr_infos:
            raise IntelligenceServiceError(f"source url host DNS resolution failed: {hostname}")
        for info in addr_infos:
            try:
                ip = ipaddress.ip_address(info[4][0])
            except (IndexError, ValueError):
                continue
            if self._is_blocked_ip(ip):
                raise IntelligenceServiceError("source url must not target private or local network addresses")
            has_public_address = True
        if not has_public_address:
            raise IntelligenceServiceError(f"source url host DNS resolution failed: {hostname}")

    @staticmethod
    def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
        return (
            not ip.is_global
            or ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        )

    def _fetch_feed_entries(self, fields: Dict[str, Any], *, limit: int) -> List[FeedEntry]:
        if fields["source_type"] == "newsnow":
            return self._fetch_newsnow_entries(fields, limit=limit)

        timeout = max(1, min(float(self.config.news_intel_fetch_timeout_sec), 30.0))
        headers = {"User-Agent": "daily-stock-analysis-intel/1.0"}
        self._validate_url(fields["url"])
        request_url = fields["url"]
        response = None
        try:
            for _ in range(_MAX_FEED_REDIRECTS + 1):
                response = self._get_with_validated_dns(
                    request_url,
                    timeout=timeout,
                    headers=headers,
                    allow_redirects=False,
                    stream=True,
                )
                status_code = int(getattr(response, "status_code", 200))
                if status_code in _REDIRECT_STATUS_CODES:
                    location = getattr(response, "headers", {}).get("Location")
                    if not location:
                        raise IntelligenceServiceError("feed redirect missing Location header")
                    response.close()
                    request_url = urljoin(request_url, location)
                    self._validate_url(request_url)
                    continue
                response.raise_for_status()
                break
            else:
                raise IntelligenceServiceError(f"feed redirect chain exceeds {_MAX_FEED_REDIRECTS}")

            self._validate_url(response.url or request_url)

            if hasattr(response, "iter_content") and callable(response.iter_content):
                chunks = []
                total = 0
                for chunk in response.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > _MAX_FEED_BYTES:
                        raise IntelligenceServiceError("feed response is too large")
                    chunks.append(chunk)
                content = b"".join(chunks)
            else:
                content = response.content[: _MAX_FEED_BYTES + 1]
                if len(content) > _MAX_FEED_BYTES:
                    raise IntelligenceServiceError("feed response is too large")
            return self._parse_feed(content, source_name=fields["name"], limit=limit)
        except IntelligenceServiceError:
            raise
        except Exception as exc:
            raise IntelligenceServiceError(_UPSTREAM_FETCH_FAILURE_MESSAGE) from exc
        finally:
            if response is not None:
                response.close()

    def _fetch_newsnow_entries(self, fields: Dict[str, Any], *, limit: int) -> List[FeedEntry]:
        timeout = max(1, min(float(self.config.news_intel_fetch_timeout_sec), 30.0))
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 daily-stock-analysis-intel/1.0"
            ),
            "Accept": "application/json",
        }
        self._validate_url(fields["url"])
        response = None
        try:
            response = self._get_with_validated_dns(
                fields["url"],
                timeout=timeout,
                headers=headers,
                allow_redirects=False,
                stream=True,
            )
            status_code = int(getattr(response, "status_code", 200))
            if status_code in _REDIRECT_STATUS_CODES:
                raise IntelligenceServiceError("NewsNow API redirects are not followed")
            response.raise_for_status()
            self._validate_url(response.url or fields["url"])

            content = self._read_limited_response(response)
            try:
                payload = json.loads(content.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise IntelligenceServiceError(f"invalid NewsNow JSON response: {exc}") from exc
            return self._parse_newsnow_payload(payload, source_name=fields["name"], limit=limit)
        except IntelligenceServiceError:
            raise
        except Exception as exc:
            raise IntelligenceServiceError(_UPSTREAM_FETCH_FAILURE_MESSAGE) from exc
        finally:
            if response is not None:
                response.close()

    def _read_limited_response(self, response: requests.Response) -> bytes:
        if hasattr(response, "iter_content") and callable(response.iter_content):
            chunks = []
            total = 0
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                total += len(chunk)
                if total > _MAX_FEED_BYTES:
                    raise IntelligenceServiceError("feed response is too large")
                chunks.append(chunk)
            return b"".join(chunks)
        content = response.content[: _MAX_FEED_BYTES + 1]
        if len(content) > _MAX_FEED_BYTES:
            raise IntelligenceServiceError("feed response is too large")
        return content

    def _get_with_validated_dns(self, raw_url: str, **kwargs: Any) -> requests.Response:
        parsed = urlparse(raw_url)
        target_hostname = self._normalize_hostname(parsed.hostname)
        original_getaddrinfo = socket.getaddrinfo

        def guarded_getaddrinfo(host: Any, port: Any, *args: Any, **inner_kwargs: Any) -> Any:
            addrinfos = original_getaddrinfo(host, port, *args, **inner_kwargs)
            if self._normalize_hostname(host) == target_hostname:
                self._validate_addrinfos(addrinfos)
            return addrinfos

        with _DNS_GUARD_LOCK:
            socket.getaddrinfo = guarded_getaddrinfo
            try:
                request_kwargs = dict(kwargs)
                request_kwargs.setdefault("proxies", _DISABLE_REQUEST_PROXIES)
                return requests.get(raw_url, **request_kwargs)
            finally:
                socket.getaddrinfo = original_getaddrinfo

    @staticmethod
    def _normalize_hostname(hostname: Any) -> str:
        if isinstance(hostname, bytes):
            hostname = hostname.decode("ascii", errors="ignore")
        normalized = str(hostname or "").strip().lower().rstrip(".")
        try:
            return normalized.encode("idna").decode("ascii")
        except UnicodeError:
            return normalized

    @staticmethod
    def _validate_addrinfos(addr_infos: Any) -> None:
        for info in addr_infos or []:
            try:
                ip = ipaddress.ip_address(info[4][0])
            except (IndexError, TypeError, ValueError):
                continue
            if IntelligenceService._is_blocked_ip(ip):
                raise IntelligenceServiceError("source url must not target private or local network addresses")

    def _parse_feed(self, content: bytes, *, source_name: str, limit: int) -> List[FeedEntry]:
        try:
            root = ET.fromstring(content)
        except ET.ParseError as exc:
            raise IntelligenceServiceError(f"invalid RSS/Atom feed: {exc}") from exc
        tag = self._strip_ns(root.tag).lower()
        if tag == "rss":
            nodes = root.findall("./channel/item")
            return [entry for entry in (self._parse_rss_item(node, source_name) for node in nodes[:limit]) if entry]
        if tag == "feed":
            nodes = root.findall("./{*}entry") or root.findall("./entry")
            return [entry for entry in (self._parse_atom_entry(node, source_name) for node in nodes[:limit]) if entry]
        raise IntelligenceServiceError("unsupported feed format; expected RSS or Atom")

    def _parse_newsnow_payload(self, payload: Any, *, source_name: str, limit: int) -> List[FeedEntry]:
        if not isinstance(payload, dict):
            raise IntelligenceServiceError("invalid NewsNow response: expected object")
        items = payload.get("items")
        if not isinstance(items, list):
            raise IntelligenceServiceError("invalid NewsNow response: missing items")
        entries = []
        for item in items[:limit]:
            if not isinstance(item, dict):
                continue
            extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
            published_raw = item.get("pubDate") or extra.get("date")
            entries.append(self._build_entry(
                str(item.get("title") or ""),
                str(extra.get("info") or extra.get("hover") or ""),
                str(item.get("url") or item.get("mobileUrl") or ""),
                source_name,
                self._parse_datetime_or_timestamp(published_raw),
            ))
        return [entry for entry in entries if entry]

    def _parse_rss_item(self, node: ET.Element, source_name: str) -> Optional[FeedEntry]:
        return self._build_entry(
            self._text(node, "title"),
            self._text(node, "description") or self._text(node, "summary"),
            self._text(node, "link"),
            source_name,
            self._parse_datetime(self._text(node, "pubDate") or self._text(node, "published")),
        )

    def _parse_atom_entry(self, node: ET.Element, source_name: str) -> Optional[FeedEntry]:
        url = ""
        for link in node.findall("./{*}link") or node.findall("./link"):
            if (link.attrib.get("rel") or "alternate").lower() == "alternate" and link.attrib.get("href"):
                url = link.attrib["href"].strip()
                break
        return self._build_entry(
            self._text(node, "title"),
            self._text(node, "summary") or self._text(node, "content"),
            url,
            source_name,
            self._parse_datetime(self._text(node, "published") or self._text(node, "updated")),
        )

    def _build_entry(self, title: str, summary: str, url: str, source_name: str, published_at: Optional[datetime]) -> Optional[FeedEntry]:
        title = self._clean_text(title)[:300]
        summary = self._clean_text(summary)[:2000]
        url = url.strip()
        if not title and not url:
            return None
        if url:
            try:
                self._validate_url(url, allow_no_url=True)
            except IntelligenceServiceError:
                return None
            url_key = url
        else:
            digest = hashlib.sha256(f"{source_name}|{title}|{published_at}".encode("utf-8")).hexdigest()[:24]
            url_key = f"no-url:intel:{digest}"
        return FeedEntry(title or url_key, summary, url_key, source_name, published_at, {"source": source_name})

    def _entry_to_item_fields(self, entry: FeedEntry, source: IntelligenceSource, now: datetime) -> Dict[str, Any]:
        return {
            "source_id": source.id,
            "source_name": source.name,
            "source_type": source.source_type,
            "title": entry.title,
            "summary": entry.summary,
            "url": entry.url,
            "source": entry.source,
            "published_at": entry.published_at,
            "fetched_at": now,
            "scope_type": source.scope_type,
            "scope_value": source.scope_value,
            "market": source.market,
            "raw_payload": json.dumps(entry.raw_payload, ensure_ascii=False),
        }

    @staticmethod
    def _source_to_fields(source: IntelligenceSource) -> Dict[str, Any]:
        return {
            "name": source.name,
            "source_type": source.source_type,
            "url": source.url,
            "enabled": source.enabled,
            "scope_type": source.scope_type,
            "scope_value": source.scope_value,
            "market": source.market,
            "description": source.description,
        }

    @staticmethod
    def _source_to_dict(source: IntelligenceSource) -> Dict[str, Any]:
        return {
            "id": source.id,
            "name": source.name,
            "source_type": source.source_type,
            "url": source.url,
            "enabled": bool(source.enabled),
            "scope_type": source.scope_type,
            "scope_value": source.scope_value,
            "market": source.market,
            "description": source.description,
            "last_status": source.last_status,
            "last_error": source.last_error,
            "last_fetched_at": IntelligenceService._iso(source.last_fetched_at),
            "created_at": IntelligenceService._iso(source.created_at),
            "updated_at": IntelligenceService._iso(source.updated_at),
        }

    @staticmethod
    def _item_to_dict(item: Any) -> Dict[str, Any]:
        return {
            "id": item.id,
            "source_id": item.source_id,
            "source_name": item.source_name,
            "source_type": item.source_type,
            "title": item.title,
            "summary": item.summary,
            "url": item.url,
            "source": item.source,
            "published_at": IntelligenceService._iso(item.published_at),
            "fetched_at": IntelligenceService._iso(item.fetched_at),
            "scope_type": item.scope_type,
            "scope_value": None if (
                item.scope_type == "market" and item.scope_value == INTELLIGENCE_ITEM_NULL_SCOPE_VALUE
            ) else item.scope_value,
            "market": item.market,
        }

    @staticmethod
    def _feed_entry_to_dict(entry: FeedEntry) -> Dict[str, Any]:
        return {
            "title": entry.title,
            "summary": entry.summary,
            "url": entry.url,
            "source": entry.source,
            "published_at": IntelligenceService._iso(entry.published_at),
        }

    @staticmethod
    def _redact_source_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in fields.items() if k not in {"headers", "token", "api_key"}}

    @staticmethod
    def _sanitize_error(exc: Exception) -> str:
        return sanitize_diagnostic_text(str(exc), max_length=500) or "internal intelligence service error"

    @staticmethod
    def _strip_ns(tag: str) -> str:
        return tag.rsplit("}", 1)[-1] if "}" in tag else tag

    @classmethod
    def _text(cls, node: ET.Element, name: str) -> str:
        found = node.find(f"./{{*}}{name}")
        if found is None:
            found = node.find(f"./{name}")
        return "" if found is None or found.text is None else found.text.strip()

    @staticmethod
    def _clean_text(value: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or "")).strip()

    @staticmethod
    def _parse_datetime(value: str) -> Optional[datetime]:
        raw = (value or "").strip()
        if not raw:
            return None
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                return None
        if parsed.tzinfo is not None and parsed.utcoffset() is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed

    @classmethod
    def _parse_datetime_or_timestamp(cls, value: Any) -> Optional[datetime]:
        if isinstance(value, (int, float)):
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp = timestamp / 1000
            try:
                return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(tzinfo=None)
            except (OSError, OverflowError, ValueError):
                return None
        raw = str(value or "").strip()
        if raw.isdigit():
            return cls._parse_datetime_or_timestamp(float(raw))
        return cls._parse_datetime(raw)

    def _builtin_source_templates(self) -> List[Dict[str, Any]]:
        templates = [dict(template) for template in _BUILTIN_SOURCE_TEMPLATES]
        for item in _NEWSNOW_DEFAULT_SOURCE_DEFS:
            templates.append({
                "template_id": item["template_id"],
                "name": item["name"],
                "source_type": "newsnow",
                "url": self._build_newsnow_url(item["source_id"]),
                "scope_type": "market",
                "market": item["market"],
                "description": item["description"],
            })
        return templates

    def _build_newsnow_url(self, source_id: str) -> str:
        base_url = (self.config.newsnow_base_url or "https://newsnow.busiyi.world").strip().rstrip("/")
        parsed = urlparse(f"{base_url}/api/s")
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["id"] = source_id
        return urlunparse(parsed._replace(query=urlencode(query)))


    @staticmethod
    def _iso(value: Optional[datetime]) -> Optional[str]:
        return value.isoformat() if value else None
