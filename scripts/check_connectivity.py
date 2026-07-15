# -*- coding: utf-8 -*-
"""
===================================
Connectivity Check Script
===================================

Validates remote endpoints used by the analysis system:

1. LLM channels (LLM_CHANNELS / LITELLM_MODEL)
   -> Uses litellm with same params as runtime (model / api_key / api_base / extra_headers)
2. Search API keys (Tavily / Brave / SerpAPI / MiniMax / Bocha)
   -> Uses same endpoints and auth headers as src/search_service.py

Output: Console table + reports/connectivity_<date>.md + reports/connectivity_<date>.json

Usage:
    python scripts/check_connectivity.py
    python scripts/check_connectivity.py --llm-only
    python scripts/check_connectivity.py --search-only
    python scripts/check_connectivity.py --list-models
"""
import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

# Proxy config - controlled by USE_PROXY env var, off by default.
if os.getenv("GITHUB_ACTIONS") != "true" and os.getenv("USE_PROXY", "false").lower() == "true":
    proxy_host = os.getenv("PROXY_HOST", "127.0.0.1")
    proxy_port = os.getenv("PROXY_PORT", "10809")
    proxy_url = f"http://{proxy_host}:{proxy_port}"
    os.environ["http_proxy"] = proxy_url
    os.environ["https_proxy"] = proxy_url

os.environ.setdefault("LITELLM_LOG", "ERROR")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _reconfigure_output_stream(stream):
    """Avoid UnicodeEncodeError on legacy Windows console code pages."""
    reconfigure = getattr(stream, "reconfigure", None)
    if not callable(reconfigure):
        return
    for kwargs in ({"encoding": "utf-8", "errors": "replace"}, {"errors": "replace"}):
        try:
            reconfigure(**kwargs)
            return
        except Exception:
            continue


def configure_console_encoding():
    for stream in (sys.stdout, sys.stderr):
        _reconfigure_output_stream(stream)


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)

try:
    import litellm
    litellm.set_verbose = False
    logging.getLogger("litellm").setLevel(logging.ERROR)
except Exception:
    litellm = None


@dataclass
class CheckResult:
    category: str
    name: str
    target: str
    status: str  # PASS / FAIL / WARN / SKIP
    latency_s: Optional[float] = None
    detail: str = ""


TIMEOUT = int(os.getenv("CONNECTIVITY_TIMEOUT", "30"))


def _mask_secret(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return "（空）"
    if len(value) <= 8:
        return value[:1] + "***"
    return value[:4] + "…" + value[-2:]


def _netloc(url: Optional[str]) -> str:
    if not url:
        return "（默认端点）"
    try:
        return urlparse(url).netloc or url
    except Exception:
        return url


def _split_keys(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    return [k.strip() for k in raw.split(",") if k.strip()]


def _short_error(exc: Exception, secret: Optional[str] = None) -> str:
    msg = str(exc)
    if secret:
        msg = msg.replace(secret, "***KEY***")
    msg = msg.replace("\n", " ").strip()
    if len(msg) > 300:
        msg = msg[:300] + "…"
    etype = type(exc).__name__
    return f"{etype}: {msg}"


# ---------------------------------------------------------------------------
# 1) LLM Channel Connectivity
# ---------------------------------------------------------------------------
def check_llm_channels(config) -> List[CheckResult]:
    results: List[CheckResult] = []
    model_list = getattr(config, "llm_model_list", None) or []
    if not model_list:
        results.append(CheckResult(
            "LLM Channels", "No config", "-", "WARN",
            detail="No LLM model_list parsed (configure LLM_CHANNELS or LITELLM_MODEL).",
        ))
        return results

    seen = set()
    for entry in model_list:
        lp = entry.get("litellm_params") or {}
        model_name = entry.get("model_name") or lp.get("model") or "?"
        api_base = lp.get("api_base") or lp.get("base_url")
        dedup_key = (model_name, api_base or "")
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        api_key = lp.get("api_key")
        wire_model = lp.get("model")
        extra_headers = lp.get("extra_headers")

        host = urlparse(api_base).hostname if api_base else None
        if host in ("127.0.0.1", "localhost", "0.0.0.0"):
            results.append(CheckResult(
                "LLM Channels", model_name, _netloc(api_base), "SKIP",
                detail="Local loopback endpoint, skipped.",
            ))
            continue

        if not api_key:
            results.append(CheckResult(
                "LLM Channels", model_name, _netloc(api_base), "WARN",
                detail="No API key configured, skipped connectivity test.",
            ))
            continue

        if litellm is None:
            results.append(CheckResult(
                "LLM Channels", model_name, _netloc(api_base), "FAIL",
                detail="litellm not installed, cannot send test request.",
            ))
            continue

        start = time.time()
        try:
            resp = litellm.completion(
                model=wire_model,
                messages=[{"role": "user", "content": "ping"}],
                api_key=api_key,
                api_base=api_base,
                extra_headers=extra_headers,
                max_tokens=5,
                temperature=0,
                timeout=TIMEOUT,
                stream=False,
            )
            latency = time.time() - start
            used = None
            try:
                used = getattr(resp, "model", None)
            except Exception:
                pass
            results.append(CheckResult(
                "LLM Channels", model_name, _netloc(api_base), "PASS",
                latency_s=latency,
                detail=f"Response model: {used or wire_model}",
            ))
        except Exception as exc:
            latency = time.time() - start
            results.append(CheckResult(
                "LLM Channels", model_name, _netloc(api_base), "FAIL",
                latency_s=latency,
                detail=_short_error(exc, api_key),
            ))
    return results


# ---------------------------------------------------------------------------
# 2) Search API Key Connectivity
# ---------------------------------------------------------------------------
def _http_probe(name: str, method: str, url: str, *, headers=None, params=None, json_body=None,
                 secret: Optional[str] = None) -> CheckResult:
    import requests

    start = time.time()
    try:
        resp = requests.request(
            method, url, headers=headers or {}, params=params, json=json_body, timeout=TIMEOUT,
        )
        latency = time.time() - start
        if resp.status_code == 200:
            return CheckResult(
                "Search API", name, _netloc(url), "PASS",
                latency_s=latency, detail=f"HTTP {resp.status_code}",
            )
        detail = f"HTTP {resp.status_code}: {resp.text[:120]}"
        if secret:
            detail = detail.replace(secret, "***KEY***")
        return CheckResult(
            "Search API", name, _netloc(url), "FAIL",
            latency_s=latency, detail=detail,
        )
    except Exception as exc:
        latency = time.time() - start
        detail = _short_error(exc, secret)
        return CheckResult(
            "Search API", name, _netloc(url), "FAIL",
            latency_s=latency, detail=detail,
        )


def check_search_keys() -> List[CheckResult]:
    results: List[CheckResult] = []

    # Tavily
    tavily = _split_keys(os.getenv("TAVILY_API_KEYS"))
    if tavily:
        results.append(_http_probe(
            "Tavily", "POST", "https://api.tavily.com/search",
            json_body={"api_key": tavily[0], "query": "test", "max_results": 1, "topic": "general"},
            secret=tavily[0],
        ))
    else:
        results.append(CheckResult("Search API", "Tavily", "api.tavily.com", "SKIP", detail="TAVILY_API_KEYS not configured"))

    # Brave
    brave = _split_keys(os.getenv("BRAVE_API_KEYS"))
    brave_enabled_raw = (os.getenv("BRAVE_ENABLED") or "").strip().lower()
    brave_enabled = brave_enabled_raw not in ("false", "0", "no")
    if not brave_enabled:
        results.append(CheckResult("Search API", "Brave", "api.search.brave.com", "SKIP", detail="BRAVE_ENABLED=false"))
    elif brave:
        results.append(_http_probe(
            "Brave", "GET", "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": brave[0], "Accept": "application/json"},
            params={"q": "test", "count": 1},
            secret=brave[0],
        ))
    else:
        results.append(CheckResult("Search API", "Brave", "api.search.brave.com", "SKIP", detail="BRAVE_API_KEYS not configured"))

    # SerpAPI
    serpapi = _split_keys(os.getenv("SERPAPI_API_KEYS"))
    if serpapi:
        results.append(_http_probe(
            "SerpAPI", "GET", "https://serpapi.com/search.json",
            params={"q": "test", "num": 1, "api_key": serpapi[0]},
            secret=serpapi[0],
        ))
    else:
        results.append(CheckResult("Search API", "SerpAPI", "serpapi.com", "SKIP", detail="SERPAPI_API_KEYS not configured"))

    # MiniMax
    minimax = _split_keys(os.getenv("MINIMAX_API_KEYS"))
    if minimax:
        results.append(_http_probe(
            "MiniMax", "POST", "https://api.minimaxi.com/v1/coding_plan/search",
            headers={"Authorization": f"Bearer {minimax[0]}", "Content-Type": "application/json", "MM-API-Source": "Minimax-MCP"},
            json_body={"q": "test"},
            secret=minimax[0],
        ))
    else:
        results.append(CheckResult("Search API", "MiniMax", "api.minimaxi.com", "SKIP", detail="MINIMAX_API_KEYS not configured"))

    # Bocha
    bocha = _split_keys(os.getenv("BOCHA_API_KEYS"))
    if bocha:
        results.append(_http_probe(
            "Bocha", "POST", "https://api.bocha.cn/v1/web-search",
            headers={"Authorization": f"Bearer {bocha[0]}", "Content-Type": "application/json"},
            json_body={"query": "test", "freshness": "oneWeek", "summary": True, "count": 1},
            secret=bocha[0],
        ))
    else:
        results.append(CheckResult("Search API", "Bocha", "api.bocha.cn", "SKIP", detail="BOCHA_API_KEYS not configured"))

    return results


# ---------------------------------------------------------------------------
# 3) Model Catalog Fetch from base_url/models
# ---------------------------------------------------------------------------
def _fetch_openai_models(base_url: Optional[str], api_key: Optional[str], timeout: int):
    """Fetch model catalog from OpenAI-compatible endpoint {base_url}/models.

    Returns (ids, error): success when error=None with ids list; failure when ids=None.
    """
    if not base_url:
        return None, "No base_url (default endpoint, skipped)"
    base = str(base_url).rstrip("/")
    url = base + "/models"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        import requests
        resp = requests.get(url, headers=headers, timeout=timeout)
    except Exception as exc:
        return None, "Request error: " + _short_error(exc, api_key)
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code}: " + _short_error(Exception(resp.text[:300]), api_key)
    try:
        data = resp.json()
    except Exception as exc:
        return None, "Non-JSON response: " + _short_error(exc, api_key)
    ids: List[str] = []
    items = None
    if isinstance(data, dict):
        candidate = data.get("data") if isinstance(data.get("data"), list) else data.get("models")
        items = candidate
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and item.get("id"):
                ids.append(str(item["id"]))
    if not ids:
        return [], "Empty model list or unknown structure: " + _short_error(Exception(resp.text[:300]), api_key)
    return ids, None


# ---------------------------------------------------------------------------
# 4) List and Validate Models (config-only, no network)
# ---------------------------------------------------------------------------
def list_and_validate_models(config) -> List[CheckResult]:
    results: List[CheckResult] = []
    channels = getattr(config, "llm_channels", None) or []
    model_list = getattr(config, "llm_model_list", None) or []
    raw_channels_str = (os.getenv("LLM_CHANNELS") or "").strip()
    raw_names = [c.strip() for c in raw_channels_str.split(",") if c.strip()]

    resolved_names = {str(ch.get("name") or "").lower() for ch in channels}

    if raw_names:
        for name in raw_names:
            if name.lower() in resolved_names:
                continue
            up = name.upper()
            has_models = bool((os.getenv(f"LLM_{up}_MODELS") or "").strip())
            has_key = bool(
                (os.getenv(f"LLM_{up}_API_KEYS") or os.getenv(f"LLM_{up}_API_KEY") or "").strip()
            )
            enabled_raw = os.getenv(f"LLM_{up}_ENABLED")
            disabled = enabled_raw is not None and enabled_raw.strip().lower() in (
                "false", "0", "no", "off",
            )
            if disabled:
                results.append(CheckResult(
                    "LLM Config", name, "-", "SKIP",
                    detail=f"Disabled (LLM_{up}_ENABLED=false), channel discarded",
                ))
            elif not has_models:
                results.append(CheckResult(
                    "LLM Config", name, "-", "FAIL",
                    detail=f"No model_name set (LLM_{up}_MODELS empty), channel discarded",
                ))
            elif not has_key:
                results.append(CheckResult(
                    "LLM Config", name, "-", "WARN",
                    detail=f"No API key (LLM_{up}_API_KEY(S) empty), channel discarded",
                ))
            else:
                results.append(CheckResult(
                    "LLM Config", name, "-", "WARN",
                    detail="Not parsed (unsupported protocol or invalid config), channel discarded",
                ))
    elif model_list:
        results.append(CheckResult(
            "LLM Config", "legacy (LITELLM_MODEL)", "-", "PASS",
            detail="No LLM_CHANNELS declared, using legacy LITELLM_MODEL path",
        ))
    else:
        results.append(CheckResult(
            "LLM Config", "No config", "-", "WARN",
            detail="No LLM channels parsed (configure LLM_CHANNELS or LITELLM_MODEL).",
        ))

    for ch in channels:
        name = ch.get("name") or "?"
        models = ch.get("models") or []
        base_url = ch.get("base_url")
        if not models:
            results.append(CheckResult(
                "LLM Config", name, _netloc(base_url), "FAIL",
                detail="Model list is empty",
            ))
        else:
            results.append(CheckResult(
                "LLM Config", name, _netloc(base_url), "PASS",
                detail="models: " + ", ".join(models),
            ))

    for e in model_list:
        if not e.get("model_name"):
            wire = (e.get("litellm_params") or {}).get("model") or "?"
            results.append(CheckResult(
                "Expanded Model", wire, "-", "WARN", detail="model_name is empty",
            ))
    return results


# ---------------------------------------------------------------------------
# Report Rendering
# ---------------------------------------------------------------------------
_STATUS_ICON = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️", "SKIP": "⏭️"}


def render_markdown(results: List[CheckResult], env_label: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    counts = {s: 0 for s in _STATUS_ICON}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1

    lines: List[str] = []
    lines.append(f"# 🔌 Connectivity Check Report")
    lines.append("")
    lines.append(f"- Time: {now}")
    lines.append(f"- Environment: {env_label}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(
        f"- ✅ Pass: **{counts.get('PASS', 0)}**  "
        f"- ❌ Fail: **{counts.get('FAIL', 0)}**  "
        f"- ⚠️ Warn: **{counts.get('WARN', 0)}**  "
        f"- ⏭️ Skip: **{counts.get('SKIP', 0)}**"
    )
    lines.append("")

    by_cat: Dict[str, List[CheckResult]] = {}
    for r in results:
        by_cat.setdefault(r.category, []).append(r)

    for cat, items in by_cat.items():
        lines.append(f"## {cat}")
        lines.append("")
        lines.append("| Name | Endpoint | Latency | Status | Detail |")
        lines.append("| --- | --- | --- | --- | --- |")
        for r in items:
            lat = f"{r.latency_s:.2f}s" if r.latency_s is not None else "-"
            lines.append(
                f"| {r.name} | {r.target} | {lat} | {_STATUS_ICON.get(r.status, r.status)} {r.status} | {r.detail} |"
            )
        lines.append("")

    fails = [r for r in results if r.status == "FAIL"]
    if fails:
        lines.append("## Failure Details")
        lines.append("")
        for r in fails:
            lines.append(f"- **{r.category} / {r.name}** ({r.target}): {r.detail}")
        lines.append("")
    return "\n".join(lines)


def write_reports(markdown: str, results: List[CheckResult]) -> Path:
    reports_dir = REPO_ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    md_path = reports_dir / f"connectivity_{date_str}.md"
    json_path = reports_dir / f"connectivity_{date_str}.json"
    md_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(json.dumps(
        [r.__dict__ for r in results], ensure_ascii=False, indent=2
    ), encoding="utf-8")
    return md_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    configure_console_encoding()

    parser = argparse.ArgumentParser(description="DSA - Connectivity Check")
    parser.add_argument("--llm-only", action="store_true", help="Check LLM channels only")
    parser.add_argument("--search-only", action="store_true", help="Check search API keys only")
    parser.add_argument("--list-models", action="store_true",
                        help="List LLM models and fetch catalog from base_url/models")
    args = parser.parse_args()

    env_label = "GitHub Actions (CI)" if os.getenv("GITHUB_ACTIONS") == "true" else "Local"

    print("\n" + "=" * 60)
    print("  🔌 Connectivity Check")
    print("=" * 60)
    print(f"  Environment: {env_label}")
    print(f"  Timeout: {TIMEOUT}s")
    print("=" * 60 + "\n")

    if args.list_models:
        try:
            from src.config import get_config
            config = get_config()
        except Exception as exc:
            logger.warning(f"Failed to load LLM config: {exc}")
            print("\n❌ Cannot load config, exit code 1.")
            return 1

        expanded = []
        try:
            from src.config import get_configured_llm_models
            expanded = get_configured_llm_models(config.llm_model_list)
        except Exception:
            pass

        print("📋 LLM_CHANNELS parsed models:")
        for m in expanded:
            print(f"   - {m}")
        print("")

        print("🔎 Channel endpoint model catalogs (GET base_url/models):")
        channels = getattr(config, "llm_channels", None) or []
        for ch in channels:
            name = ch.get("name") or "?"
            up = str(name).upper()
            base_url = ch.get("base_url")
            models = ch.get("models") or []
            key = (os.getenv(f"LLM_{up}_API_KEYS") or os.getenv(f"LLM_{up}_API_KEY") or "").strip()
            print(f"\n   • Channel: {name}")
            print(f"     base_url: {base_url or '(default endpoint)'}")
            ids, err = _fetch_openai_models(base_url, key, TIMEOUT)
            if err:
                print(f"     Fetch failed: {err}")
            elif ids:
                print(f"     Available models ({len(ids)}):")
                for mid in ids:
                    print(f"       - {mid}")
            else:
                print("     No models returned (endpoint may not support /models)")
            print(f"     Configured models: {', '.join(models) if models else '(empty)'}")
        print("")

        results = list_and_validate_models(config)
        markdown = render_markdown(results, env_label)
        print(markdown)
        try:
            md_path = write_reports(markdown, results)
            print(f"\n📄 Report written to: {md_path}")
        except Exception as exc:
            logger.warning(f"Failed to write report: {exc}")

        missing = [r for r in results if r.status == "FAIL"]
        if missing:
            print(f"\n❌ {len(missing)} channels missing model_name, exit code 1.")
            return 1
        print("\n✅ All channels have model_name configured.")
        return 0

    results: List[CheckResult] = []

    if not args.search_only:
        try:
            from src.config import get_config
            config = get_config()
            results += check_llm_channels(config)
        except Exception as exc:
            logger.warning(f"Failed to load LLM config, skipping LLM check: {exc}")

    if not args.llm_only:
        results += check_search_keys()

    markdown = render_markdown(results, env_label)
    print(markdown)

    try:
        md_path = write_reports(markdown, results)
        print(f"\n📄 Report written to: {md_path}")
    except Exception as exc:
        logger.warning(f"Failed to write report: {exc}")

    failed = sum(1 for r in results if r.status == "FAIL")
    if failed:
        print(f"\n❌ {failed} connectivity failures, exit code 1.")
        return 1
    print("\n✅ No connectivity failures.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
