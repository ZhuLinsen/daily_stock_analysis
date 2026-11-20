# -*- coding: utf-8 -*-
"""Zero-bloat minimal configuration generator and CLI setup wizard."""

from __future__ import annotations

import getpass
import os
from pathlib import Path
import shlex
import stat
import sys
import tempfile
import warnings
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlsplit
from uuid import uuid4


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
        "env_key": "LLM_DEEPSEEK_API_KEY",
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
        "env_key": "LLM_COMPATIBLE_API_KEY",
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


_OLLAMA_DEFAULT_BASE = "http://127.0.0.1:11434"
_OLLAMA_DEFAULT_MODEL = "qwen2.5:14b"
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


def _open_private_windows_file(path: Path) -> int:
    """Create a new file with a protected DACL for the current Windows user."""
    import ctypes as c
    from ctypes import wintypes as w
    import msvcrt

    kernel = c.WinDLL("kernel32", use_last_error=True)
    security = c.WinDLL("advapi32", use_last_error=True)

    class SecurityAttributes(c.Structure):
        _fields_ = [("length", w.DWORD), ("descriptor", w.LPVOID), ("inherit_handle", w.BOOL)]

    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.LocalFree.argtypes = [w.HLOCAL]
    kernel.LocalFree.restype = w.HLOCAL
    security.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)]
    security.GetTokenInformation.argtypes = [w.HANDLE, c.c_int, w.LPVOID, w.DWORD, c.POINTER(w.DWORD)]
    security.ConvertSidToStringSidW.argtypes = [w.LPVOID, c.POINTER(w.LPWSTR)]
    security.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        w.LPCWSTR, w.DWORD, c.POINTER(w.LPVOID), c.POINTER(w.DWORD),
    ]
    kernel.CreateFileW.argtypes = [
        w.LPCWSTR, w.DWORD, w.DWORD, c.POINTER(SecurityAttributes), w.DWORD, w.DWORD, w.HANDLE,
    ]
    kernel.CreateFileW.restype = w.HANDLE
    kernel.GetVolumeInformationByHandleW.argtypes = [
        w.HANDLE, w.LPWSTR, w.DWORD, c.POINTER(w.DWORD), c.POINTER(w.DWORD),
        c.POINTER(w.DWORD), w.LPWSTR, w.DWORD,
    ]

    token = w.HANDLE()
    if not security.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, c.byref(token)):  # TOKEN_QUERY
        raise c.WinError(c.get_last_error())
    try:
        size = w.DWORD()
        token_user = 1  # TokenUser
        security.GetTokenInformation(token, token_user, None, 0, c.byref(size))
        user = c.create_string_buffer(size.value)
        if not security.GetTokenInformation(token, token_user, user, size, c.byref(size)):
            raise c.WinError(c.get_last_error())
        # TOKEN_USER starts with the SID pointer of its SID_AND_ATTRIBUTES member.
        user_sid = c.cast(user, c.POINTER(w.LPVOID))[0]
        sid_string = w.LPWSTR()
        if not security.ConvertSidToStringSidW(user_sid, c.byref(sid_string)):
            raise c.WinError(c.get_last_error())
        try:
            sid = sid_string.value
        finally:
            kernel.LocalFree(c.cast(sid_string, w.LPVOID))
    finally:
        kernel.CloseHandle(token)

    # Set the owner explicitly because an elevated token may default to a group.
    # D:P prevents inheritance. FA grants full file access only to this SID.
    descriptor = w.LPVOID()
    sddl = f"O:{sid}D:P(A;;FA;;;{sid})"
    if not security.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, c.byref(descriptor), None):
        raise c.WinError(c.get_last_error())
    try:
        attrs = SecurityAttributes(c.sizeof(SecurityAttributes), descriptor, False)
        generic_read_write = 0x80000000 | 0x40000000  # GENERIC_READ | GENERIC_WRITE
        create_new, normal_attributes = 1, 0x80
        handle = kernel.CreateFileW(str(path), generic_read_write, 0, c.byref(attrs), create_new, normal_attributes, None)
        if handle == w.HANDLE(-1).value:  # INVALID_HANDLE_VALUE
            raise c.WinError(c.get_last_error())
    finally:
        kernel.LocalFree(descriptor)

    try:
        flags = w.DWORD()
        if not kernel.GetVolumeInformationByHandleW(handle, None, 0, None, None, c.byref(flags), None, 0):
            raise c.WinError(c.get_last_error())
        if not flags.value & 0x00000008:  # FILE_PERSISTENT_ACLS
            raise OSError(f"The output filesystem does not support Windows file ACLs: {path.parent}")
        return msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(handle)
        path.unlink(missing_ok=True)
        raise


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

    if norm_provider == "openai-compatible":
        if not clean_model or "," in clean_model:
            raise ValueError("OpenAI-compatible provider requires one model ID")
        try:
            url = urlsplit(clean_base_url)
            valid_url = (
                url.scheme in {"http", "https"} and url.hostname and url.username is None
                and not url.fragment and not any(ch.isspace() for ch in clean_base_url)
                and url.port != 0
            )
        except ValueError:
            valid_url = False
        if not valid_url:
            raise ValueError("OpenAI-compatible provider requires a valid HTTP(S) base URL without embedded credentials or a fragment")
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
        lines.append(f"OLLAMA_API_BASE={clean_key or _OLLAMA_DEFAULT_BASE}")
        lines.append(f"OLLAMA_MODEL={_OLLAMA_DEFAULT_MODEL}")
        lines.append(f"LITELLM_MODEL=ollama/{_OLLAMA_DEFAULT_MODEL}")
    elif norm_provider == "deepseek":
        lines.extend([
            "LLM_CHANNELS=deepseek",
            "LLM_DEEPSEEK_PROTOCOL=deepseek",
            "LLM_DEEPSEEK_BASE_URL=https://api.deepseek.com",
            f"{provider_spec['env_key']}={clean_key}",
            "LLM_DEEPSEEK_MODELS=deepseek-flash",
        ])
    elif norm_provider == "openai-compatible":
        # Bind the gateway key, endpoint and model in one channel. The first
        # prefix is LiteLLM's protocol and the remainder is the raw gateway ID.
        lines.extend([
            "LLM_CHANNELS=compatible",
            "LLM_COMPATIBLE_PROTOCOL=openai",
            f"LLM_COMPATIBLE_BASE_URL={clean_base_url}",
            f"{provider_spec['env_key']}={clean_key}",
            f"LLM_COMPATIBLE_MODELS=openai/{clean_model}",
        ])
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
        "# Start with the command printed by the initialization wizard.",
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
    temp_prefix = ".env.dsa-init-"  # Covered by the repository's .env.* ignore rule.
    if os.name == "nt":
        if force and existed:
            # Directory delete rights can allow replacement of a file the
            # current user could not read. Keep that ACL boundary in place.
            with target.open("rb"):
                pass
        temp_path = target.parent / f"{temp_prefix}{uuid4().hex}.tmp"
        fd = _open_private_windows_file(temp_path)
    else:
        fd, temp_name = tempfile.mkstemp(prefix=temp_prefix, dir=target.parent)
        temp_path = Path(temp_name)
    try:
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n", closefd=False) as stream:
                if os.name != "nt":
                    os.fchmod(fd, 0o600)
                    if stat.S_IMODE(os.fstat(fd).st_mode) != 0o600:
                        raise OSError(f"The output filesystem did not apply private file permissions: {target.parent}")
                stream.write(content)
                stream.flush()
                os.fsync(fd)
        finally:
            os.close(fd)
        try:
            if force:
                os.replace(temp_path, target)
            elif os.name == "nt":
                os.rename(temp_path, target)  # Windows rename fails if the destination exists.
            else:
                os.link(temp_path, target)  # POSIX rename would overwrite a racing writer.
        except FileExistsError:
            if force:
                raise
            raise FileExistsError(
                f"Config file already exists: {target}. Use --init-force to overwrite, or pick --init-output <path>."
            ) from None
    finally:
        temp_path.unlink(missing_ok=True)
    return {
        "ok": True,
        "path": str(target),
        "overwritten": existed,
        "bytes": len(content.encode("utf-8")),
    }


def _init_launch_command(alternate_path: Optional[Path], *, windows: bool) -> str:
    command = "python main.py --serve-only"
    if alternate_path is None:
        return command
    if windows:
        single_quotes = "'\u2018\u2019\u201a\u201b"
        value = str(alternate_path).translate({ord(quote): quote * 2 for quote in single_quotes})
        return f"$env:ENV_FILE = '{value}'; {command}"
    return f"ENV_FILE={shlex.quote(str(alternate_path))} {command}"


def run_init_wizard(
    *,
    default_provider: str = "gemini",
    default_stocks: str = "600519,hk00700,AAPL",
    output_path: str | Path | None = None,
    force: bool = False,
    non_interactive: bool = False,
    base_url: str = "",
    model: str = "",
    input_fn: Optional[Callable[[str], str]] = None,
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
        if input_fn is not None:
            return input_fn(prompt)
        if not secret:
            print(prompt, end="", file=sys.stderr, flush=True)
            return input()
        # Windows getpass uses the console for its prompt, ignoring stream.
        if os.name == "nt":
            print(prompt, end="", file=sys.stderr, flush=True)
            prompt = ""
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            try:
                return getpass.getpass(prompt, stream=sys.stderr)
            except getpass.GetPassWarning as exc:
                raise ValueError("Cannot hide credential input. Use --non-interactive and edit the file.") from exc

    interactive = not non_interactive and (input_fn is not None or sys.stdin.isatty())
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
            else f"    Enter OLLAMA_API_BASE (default {_OLLAMA_DEFAULT_BASE}): "
        )
        api_key = _sanitize_single_line(read_prompt(prompt_label, secret=provider != "ollama"))
        if provider == "openai-compatible":
            url_hint = "Enter keeps --init-base-url" if base_url else "required"
            model_hint = "Enter keeps --init-model" if model else "required"
            base_url = _sanitize_single_line(read_prompt(f"    Gateway base URL ({url_hint}): ")) or base_url
            model = _sanitize_single_line(read_prompt(f"    Gateway model ID ({model_hint}): ")) or model

        stock_lines = []
        line = read_prompt(f"2/3 Watchlist STOCK_LIST (blank line to finish, default: {stocks}): ")
        while line.strip():
            stock_lines.append(line)
            line = read_prompt("")
        if stock_lines:
            stocks = _normalize_stocks("\n".join(stock_lines))

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
    active_path = Path(os.getenv("ENV_FILE") or Path(__file__).resolve().parents[2] / ".env")
    if output_path is None:
        output_path = active_path
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
    written_path = Path(result["path"]).resolve()
    alternate_path = written_path if written_path != active_path.resolve() else None
    result["provider"] = provider
    result["env_key"] = PROVIDER_SPECS[provider]["env_key"]
    result["next_steps"] = [
        f"Run ollama pull {_OLLAMA_DEFAULT_MODEL} if the default model is missing"
        if provider == "ollama" else f"Fill {result['env_key']} in the generated file if left blank",
        _init_launch_command(alternate_path, windows=os.name == "nt"),
    ]
    result["stocks"] = stocks
    result["notify"] = notify
    result["interactive"] = interactive
    return result
