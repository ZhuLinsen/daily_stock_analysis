# -*- coding: utf-8 -*-
"""Zero-bloat minimal configuration generator and CLI setup wizard."""

from __future__ import annotations

import getpass
import os
from pathlib import Path
import shlex
import sys
import tempfile
from typing import Any, Callable, Dict, List, Optional


PROVIDER_SPECS: Dict[str, Dict[str, str]] = {
    "modelflare": {
        "env_key": "MODELFLARE_KEY",
        "label": "Modelflare (Single-key multi-model gateway)",
        "note": "Auto-configures gateway URL and default model with 1 key.",
    },
    "gemini": {
        "env_key": "GEMINI_API_KEY",
        "label": "Google Gemini (Free tier available)",
        "note": "Recommended starter with free quota at aistudio.google.com.",
    },
    "deepseek": {
        "env_key": "DEEPSEEK_API_KEY",
        "label": "DeepSeek API (Cost-effective Chinese/English reasoning)",
        "note": "Configure key from platform.deepseek.com.",
    },
    "aihubmix": {
        "env_key": "AIHUBMIX_KEY",
        "label": "AIHubMix (Unified aggregator key)",
        "note": "Single key access to multiple models.",
    },
    "openai": {
        "env_key": "OPENAI_API_KEY",
        "label": "OpenAI Official",
        "note": "Uses the official OpenAI endpoint by default.",
    },
    "openai-compatible": {
        "env_key": "OPENAI_API_KEY",
        "label": "OpenAI-compatible endpoint",
        "note": "Requires an explicit base URL and model.",
    },
    "anthropic": {
        "env_key": "ANTHROPIC_API_KEY",
        "label": "Anthropic Claude",
        "note": "Official Claude Messages API.",
    },
    "ollama": {
        "env_key": "OLLAMA_API_BASE",
        "label": "Ollama Local Model (Zero cloud API key)",
        "note": "Runs locally via http://127.0.0.1:11434 + OLLAMA_MODEL.",
    },
}

NOTIFY_SPECS: Dict[str, Dict[str, Any]] = {
    "none": {
        "label": "Skip for now (view reports in WebUI / reports/)",
        "keys": [],
    },
    "wechat": {
        "label": "WeChat Work Webhook",
        "keys": ["WECHAT_WEBHOOK_URL"],
    },
    "feishu": {
        "label": "Feishu / Lark Webhook",
        "keys": ["FEISHU_WEBHOOK_URL"],
    },
    "telegram": {
        "label": "Telegram Bot (Token + Chat ID)",
        "keys": ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"],
    },
    "discord": {
        "label": "Discord Webhook",
        "keys": ["DISCORD_WEBHOOK_URL"],
    },
}

PROVIDER_ORDER: List[str] = [
    "gemini",
    "deepseek",
    "modelflare",
    "aihubmix",
    "openai",
    "openai-compatible",
    "anthropic",
    "ollama",
]

NOTIFY_ORDER: List[str] = ["none", "wechat", "feishu", "telegram", "discord"]


_LINE_SEPARATORS = "\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029"


def _sanitize_single_line(value: Optional[str]) -> str:
    """Remove all Unicode line separators so input cannot inject env lines."""
    text = str(value or "")
    return text.translate({ord(separator): None for separator in _LINE_SEPARATORS}).strip()


def _normalize_stocks(value: Optional[str]) -> str:
    from src.services.stock_list_parser import serialize_stock_list

    # split_stock_list deliberately accepts copy/paste line-separated lists.
    # Normalize them to the canonical comma-separated representation before
    # embedding the value in a single dotenv assignment.
    raw = str(value or "").translate({ord(separator): "," for separator in _LINE_SEPARATORS})
    normalized = serialize_stock_list(raw)
    safe_tokens = [token for token in normalized.split(",") if "=" not in token]
    return ",".join(safe_tokens) or "600519,hk00700,AAPL"


def _set_private_permissions(fd: int, path: Path) -> None:
    """Restrict generated config files on both POSIX and Windows runtimes."""
    try:
        os.fchmod(fd, 0o600)
    except AttributeError:  # pragma: no cover - Windows Python builds
        os.chmod(path, 0o600)


def normalize_provider(provider: Optional[str]) -> str:
    norm = _sanitize_single_line(provider).lower() or "gemini"
    if norm not in PROVIDER_SPECS:
        supported = ", ".join(PROVIDER_ORDER)
        raise ValueError(f"Unsupported provider '{provider}'. Choose one of: {supported}")
    return norm


def normalize_notify(notify: Optional[str]) -> str:
    norm = _sanitize_single_line(notify).lower() or "none"
    if norm not in NOTIFY_SPECS:
        supported = ", ".join(NOTIFY_ORDER)
        raise ValueError(f"Unsupported notify channel '{notify}'. Choose one of: {supported}")
    return norm


def generate_minimal_env_content(
    *,
    provider: str = "gemini",
    api_key: str = "",
    stocks: str = "600519,hk00700,AAPL",
    notify: str = "none",
    notify_target: str = "",
    extra_notify_id: str = "",
    base_url: str = "",
    model: str = "",
) -> str:
    """Render a minimal, clean .env file with only core variables."""
    norm_provider = normalize_provider(provider)
    norm_notify = normalize_notify(notify)
    clean_stocks = _normalize_stocks(stocks)
    clean_key = _sanitize_single_line(api_key)
    clean_notify_target = _sanitize_single_line(notify_target)
    clean_extra_id = _sanitize_single_line(extra_notify_id)
    clean_base_url = _sanitize_single_line(base_url)
    clean_model = _sanitize_single_line(model)

    if norm_provider == "openai-compatible" and (not clean_base_url or not clean_model):
        raise ValueError("OpenAI-compatible provider requires OPENAI_BASE_URL and OPENAI_MODEL")
    if norm_notify == "telegram" and (not clean_notify_target or not clean_extra_id):
        raise ValueError("Telegram requires both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")

    provider_spec = PROVIDER_SPECS[norm_provider]
    lines: List[str] = [
        "# ==========================================================",
        "# Daily Stock Analysis (DSA) - Minimal Configuration (.env)",
        "# Generated by: python main.py --init",
        "# Docs: docs/INDEX.md | Full options: .env.example",
        "# ==========================================================",
        "",
        "# 1) Watchlist (comma-separated: A-share, HK, US, JP, KR, TW)",
        f"STOCK_LIST={clean_stocks}",
        "",
        f"# 2) AI Model ({provider_spec['label']})",
    ]

    if norm_provider == "ollama":
        base_val = clean_key or "http://127.0.0.1:11434"
        lines.append(f"OLLAMA_API_BASE={base_val}")
        lines.append("OLLAMA_MODEL=qwen2.5:14b")
        lines.append("LITELLM_MODEL=ollama/qwen2.5:14b")
    elif norm_provider == "deepseek":
        lines.append(f"{provider_spec['env_key']}={clean_key}")
        lines.append("LITELLM_MODEL=deepseek/deepseek-v4-flash")
    elif norm_provider == "openai-compatible":
        lines.append(f"{provider_spec['env_key']}={clean_key}")
        lines.append(f"OPENAI_BASE_URL={clean_base_url}")
        lines.append(f"OPENAI_MODEL={clean_model}")
    else:
        lines.append(f"{provider_spec['env_key']}={clean_key}")

    lines.extend(["", "# 3) Notification Channel (Optional)"])
    notify_keys = NOTIFY_SPECS[norm_notify]["keys"]
    if not notify_keys:
        lines.append("# WECHAT_WEBHOOK_URL=")
    elif norm_notify == "telegram":
        lines.append(f"TELEGRAM_BOT_TOKEN={clean_notify_target}")
        lines.append(f"TELEGRAM_CHAT_ID={clean_extra_id}")
    else:
        lines.append(f"{notify_keys[0]}={clean_notify_target}")

    lines.extend([
        "",
        "# Next commands:",
        "#   python main.py --serve-only   # Start WebUI at http://127.0.0.1:8000",
        "#   python main.py --stocks 600519 --dry-run --no-market-review",
        "",
    ])
    return "\n".join(lines)


def write_minimal_env(
    output_path: str | Path,
    content: str,
    *,
    force: bool = False,
) -> Dict[str, Any]:
    """Write minimal .env safely without overwriting existing config unless forced."""
    target = Path(output_path)
    existed = target.exists()
    if existed and target.is_dir():
        raise IsADirectoryError(f"Target path is a directory, cannot write config: {target}")
    if existed and not force:
        raise FileExistsError(
            f"Config file already exists: {target}. Use --init-force to overwrite, or pick --init-output <path>."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    if not force:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            fd = os.open(target, flags, 0o600)
        except FileExistsError:
            raise FileExistsError(
                f"Config file already exists: {target}. Use --init-force to overwrite, or pick --init-output <path>."
            ) from None
        try:
            _set_private_permissions(fd, target)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            try:
                target.unlink()
            except FileNotFoundError:
                pass
            raise
    else:
        fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            _set_private_permissions(fd, Path(temp_name))
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, target)
        finally:
            try:
                Path(temp_name).unlink()
            except FileNotFoundError:
                pass
    return {
        "ok": True,
        "path": str(target),
        "overwritten": existed,
        "bytes": len(content.encode("utf-8")),
        "next_steps": [
            "Edit the AI API key in the generated file if left blank",
            "python main.py --serve-only",
        ],
    }


def run_init_wizard(
    *,
    default_provider: str = "gemini",
    default_stocks: str = "600519,hk00700,AAPL",
    output_path: str | Path | None = None,
    force: bool = False,
    non_interactive: bool = False,
    base_url: str = "",
    model: str = "",
    input_fn: Callable[[str], str] = input,
) -> Dict[str, Any]:
    """Run minimal .env initialization wizard (interactive when TTY + allowed)."""
    provider = normalize_provider(default_provider)
    stocks = _normalize_stocks(default_stocks)
    api_key = ""
    notify = "none"
    notify_target = ""
    extra_notify_id = ""
    base_url = _sanitize_single_line(base_url)
    model = _sanitize_single_line(model)

    def read_prompt(prompt: str, *, secret: bool = False) -> str:
        if input_fn is input:
            if secret:
                return getpass.getpass(prompt, stream=sys.stderr)
            print(prompt, end="", file=sys.stderr, flush=True)
            return input()
        return input_fn(prompt)

    interactive = not non_interactive and (input_fn is not input or sys.stdin.isatty())
    if interactive:
        provider_choices = ", ".join(PROVIDER_ORDER)
        chosen_provider = _sanitize_single_line(read_prompt(
            f"1/3 Choose AI provider [{provider_choices}] (default: {provider}): "
        ))
        if chosen_provider:
            provider = normalize_provider(chosen_provider)

        env_key = PROVIDER_SPECS[provider]["env_key"]
        prompt_label = (
            f"    Enter {env_key} (press Enter to leave blank and fill later): "
            if provider != "ollama"
            else "    Enter OLLAMA_API_BASE (default http://127.0.0.1:11434): "
        )
        api_key = _sanitize_single_line(read_prompt(prompt_label, secret=provider != "ollama"))
        if provider == "openai-compatible":
            base_url = _sanitize_single_line(read_prompt("    OPENAI_BASE_URL (required): "))
            model = _sanitize_single_line(read_prompt("    OPENAI_MODEL (required): "))
            if not base_url or not model:
                raise ValueError("OpenAI-compatible provider requires OPENAI_BASE_URL and OPENAI_MODEL")

        chosen_stocks = read_prompt(f"2/3 Watchlist STOCK_LIST (default: {stocks}): ")
        if chosen_stocks:
            stocks = _normalize_stocks(chosen_stocks)

        notify_choices = ", ".join(NOTIFY_ORDER)
        chosen_notify = _sanitize_single_line(read_prompt(
            f"3/3 Optional notification [{notify_choices}] (default: none): "
        ))
        if chosen_notify:
            notify = normalize_notify(chosen_notify)
        if notify == "telegram":
            prompt = "    TELEGRAM_BOT_TOKEN (required): "
            notify_target = _sanitize_single_line(read_prompt(prompt, secret=True))
            extra_notify_id = _sanitize_single_line(read_prompt("    TELEGRAM_CHAT_ID (required): "))
            if not notify_target or not extra_notify_id:
                raise ValueError("Telegram requires both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        elif notify != "none":
            target_key = NOTIFY_SPECS[notify]["keys"][0]
            notify_target = _sanitize_single_line(read_prompt(f"    {target_key} (optional): ", secret=True))

    if provider == "openai-compatible" and (not base_url or not model):
        raise ValueError("OpenAI-compatible provider requires --init-base-url and --init-model")
    if notify == "telegram" and (not notify_target or not extra_notify_id):
        raise ValueError("Telegram requires both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")

    if output_path is None:
        output_path = os.getenv("ENV_FILE") or Path(__file__).resolve().parents[2] / ".env"
    content = generate_minimal_env_content(
        provider=provider,
        api_key=api_key,
        stocks=stocks,
        notify=notify,
        notify_target=notify_target,
        extra_notify_id=extra_notify_id,
        base_url=base_url,
        model=model,
    )
    result = write_minimal_env(output_path, content, force=force)
    active_path = Path(os.getenv("ENV_FILE") or Path(__file__).resolve().parents[2] / ".env").resolve()
    written_path = Path(result["path"]).resolve()
    if written_path != active_path:
        result["next_steps"].insert(
            0,
            f"ENV_FILE={shlex.quote(str(written_path))} python main.py --serve-only",
        )
    result["provider"] = provider
    result["env_key"] = PROVIDER_SPECS[provider]["env_key"]
    result["stocks"] = stocks
    result["notify"] = notify
    result["interactive"] = interactive
    return result
