# -*- coding: utf-8 -*-
"""
飞书 发送提醒服务

职责：
1. 通过 webhook 发送飞书消息
2. 通过飞书应用机器人（App Bot）发送消息（lark-oapi SDK）
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import tempfile
import threading
import time
import uuid as uuid_mod
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple, TypeVar
from urllib.parse import urlsplit

import requests

from src.config import Config
from src.formatters import (
    FENCED_CODE_BLOCK_RE,
    MIN_MAX_BYTES,
    PAGE_MARKER_SAFE_BYTES,
    chunk_content_by_max_bytes,
    format_feishu_markdown,
    strip_hidden_markdown_metadata,
)
from src.report_language import SUPPORTED_REPORT_LANGUAGES, get_report_labels

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# lark-oapi SDK availability
# ---------------------------------------------------------------------------

FEISHU_SDK_AVAILABLE = False
_lark: Any = None  # type: ignore[assignment]
FEISHU_DOMAIN = "feishu"
LARK_DOMAIN = "lark"
try:
    import lark_oapi as _lark
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest,
        CreateMessageRequestBody,
    )
    from lark_oapi.core.const import FEISHU_DOMAIN as _SDK_FEISHU_DOMAIN
    from lark_oapi.core.const import LARK_DOMAIN as _SDK_LARK_DOMAIN

    FEISHU_DOMAIN = _SDK_FEISHU_DOMAIN
    LARK_DOMAIN = _SDK_LARK_DOMAIN
    FEISHU_SDK_AVAILABLE = True
except ImportError:
    pass

# File-upload SDK classes (isolated from the core messaging SDK availability
# so that an older lark-oapi without file support doesn't break App Bot text).
FEISHU_FILE_SDK_AVAILABLE = False
_CreateFileRequest: Any = None
_CreateFileRequestBody: Any = None
try:
    from lark_oapi.api.im.v1 import (
        CreateFileRequest as _CreateFileRequest,
        CreateFileRequestBody as _CreateFileRequestBody,
    )
    FEISHU_FILE_SDK_AVAILABLE = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_APP_SEND_RETRIES = 3
_APP_SEND_BACKOFF_SECONDS = (1.0, 2.0, 4.0)
_APP_MAX_REQUEST_BYTES = 30_000
_WEBHOOK_SEND_TIMEOUT_SECONDS = 30
_WEBHOOK_MAX_REQUEST_BYTES = 20_000
_CardPayload = TypeVar("_CardPayload")
_CARD_HEADING = re.compile(r"^#{1,6}\s+(.+)")
_CARD_COUNTS = re.compile(r"([🟢🟡🔴])\s*(?:[^:：🟢🟡🔴]+[:：]\s*)?(\d+)(?=\s|$)")
_SIGNAL_MARKERS = {"🔴": "red", "🟢": "green", "💚": "green", "🟡": "orange", "⚪": "orange", "🟠": "orange"}
_RISK_HEADINGS = {"风险", "风险提示"} | {
    get_report_labels(language)["risk_alerts_label"].casefold()
    for language in SUPPORTED_REPORT_LANGUAGES
}
_LIST_ITEM = re.compile(r"^(?:[•*+-]\s|\d+\.\s)")

# Sentinel for "client not yet initialised".
_NO_CLIENT = object()


class FeishuSender:

    def __init__(self, config: Config):
        """
        Initialise Feishu sender.

        Two mutually exclusive routing modes are supported:
          1. **Webhook** – configured via ``feishu_webhook_url`` (legacy).
          2. **App Bot** – configured via ``feishu_app_id`` + ``feishu_app_secret``
             + ``feishu_chat_id``, sends through the ``lark-oapi`` SDK.

        Webhook mode takes precedence when both are configured.
        """
        # -- Webhook mode --
        self._feishu_url = getattr(config, "feishu_webhook_url", None)
        self._feishu_secret = (getattr(config, "feishu_webhook_secret", None) or "").strip()
        self._feishu_keyword = (getattr(config, "feishu_webhook_keyword", None) or "").strip()
        self._feishu_max_bytes = getattr(config, "feishu_max_bytes", 20000)
        self._feishu_send_as_file = getattr(config, "feishu_send_as_file", False)
        self._webhook_verify_ssl = getattr(config, "webhook_verify_ssl", True)

        # -- App Bot mode --
        self._feishu_app_id = (getattr(config, "feishu_app_id", None) or "").strip()
        self._feishu_app_secret = (getattr(config, "feishu_app_secret", None) or "").strip()
        self._feishu_chat_id = (getattr(config, "feishu_chat_id", None) or "").strip()
        self._feishu_receive_id_type = (
            getattr(config, "feishu_receive_id_type", None) or "chat_id"
        ).strip().lower()
        if self._feishu_receive_id_type not in ("chat_id", "open_id"):
            logger.warning(
                "Invalid FEISHU_RECEIVE_ID_TYPE=%s, falling back to chat_id",
                self._feishu_receive_id_type,
            )
            self._feishu_receive_id_type = "chat_id"
        # domain_name must be "feishu" or "lark"; anything else defaulted to feishu.
        raw_domain = (
            getattr(config, "feishu_domain", None) or os.getenv("FEISHU_DOMAIN", "feishu")
        ).strip().lower()
        if raw_domain not in ("feishu", "lark"):
            logger.warning(
                "Invalid FEISHU_DOMAIN=%s, falling back to feishu", raw_domain
            )
            raw_domain = "feishu"
        self._feishu_domain = FEISHU_DOMAIN if raw_domain == "feishu" else LARK_DOMAIN

        self._app_client: Any = _NO_CLIENT
        self._app_client_lock = threading.Lock()
        raw_web_url = (
            os.getenv("FEISHU_CARD_WEB_URL", "").strip()
            or os.getenv("DSA_WEB_URL", "").strip()
        )
        self._web_url = raw_web_url if self._is_web_url(raw_web_url) else ""

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_web_url(value: str) -> bool:
        try:
            url = urlsplit(value)
            return url.scheme in {"http", "https"} and bool(url.hostname) and not any(char.isspace() for char in value)
        except ValueError:
            return False

    @staticmethod
    def _is_risk_heading(line: str) -> bool:
        label = line.strip().lstrip("#").replace("**", "").strip().rstrip(":：").strip()
        label = label.lstrip("🚨⚠\ufe0f ")
        return label.casefold() in _RISK_HEADINGS

    @staticmethod
    def _card_metadata_lines(content: str) -> list[str]:
        # Keep offsets aligned with the visible body while ignoring code samples.
        return FENCED_CODE_BLOCK_RE.sub(lambda match: "\n" * match[0].count("\n"), content).split("\n")

    @classmethod
    def _infer_card_header(cls, content: str) -> tuple[str, str]:
        """Infer Feishu card title and header template color from report markdown."""
        title = "股票智能分析报告"
        lines = [line.strip() for line in cls._card_metadata_lines(content)]
        for line in lines:
            heading = _CARD_HEADING.match(line)
            if heading:
                title = heading[1].replace("**", "").replace(r"\*", "*")[:60]
                break

        if any(cls._is_risk_heading(line) for line in lines) or "异动告警" in title:
            return title, "red"

        counts = [
            (marker, int(count))
            for line in lines if line.startswith((">", "💬"))
            for marker, count in _CARD_COUNTS.findall(line)
        ]
        if counts:
            markers = {marker for marker, count in counts if count > 0}
        elif title[:1] in _SIGNAL_MARKERS:
            return title, _SIGNAL_MARKERS[title[0]]
        else:
            markers = {
                line.lstrip("# *")[:1]
                for line in lines
                if _CARD_HEADING.match(line) or re.match(r"^\S\s+\*\*", line)
            }
        if "🔴" in markers or (not counts and any(word in title for word in ("卖出", "清仓"))):
            template = "red"
        elif markers & {"🟢", "💚"} or (not counts and any(word in title for word in ("买入", "加仓"))):
            template = "green"
        elif markers & {"🟡", "⚪", "🟠"} or (not counts and any(word in title for word in ("观望", "持有", "减仓"))):
            template = "orange"
        else:
            template = "blue"
        return title, template

    @classmethod
    def _split_risk_sections(cls, content: str) -> list[str]:
        """Keep each risk panel in its original position within the report."""
        lines = content.split("\n")
        metadata_lines = cls._card_metadata_lines(content)
        sections = []
        start = index = 0
        while index < len(lines):
            if not cls._is_risk_heading(metadata_lines[index]):
                index += 1
                continue

            sections.append("\n".join(lines[start:index]).strip())
            start = index
            index += 1
            while index < len(lines) and not lines[index].strip():
                index += 1
            has_list = False
            while index < len(lines):
                line = lines[index]
                stripped = line.strip()
                if _LIST_ITEM.match(stripped):
                    has_list = True
                elif (
                    not stripped
                    or not metadata_lines[index].strip()
                    or cls._is_risk_heading(stripped)
                    or stripped.startswith(("#", "---", "────────"))
                    or (has_list and not line.startswith((" ", "\t")))
                    or re.match(r"^(?:[^\w\s]+\s+)?\*\*", stripped)
                ):
                    break
                index += 1
            sections.append("\n".join(lines[start:index]).strip())
            start = index

        sections.append("\n".join(lines[start:]).strip())
        return [section for section in sections if section] or [""]

    def _build_card_body(
        self,
        content: str,
        web_url: Optional[str] = None,
        *,
        header: Optional[Tuple[str, str]] = None,
    ) -> dict:
        """Build a Feishu interactive-card body (without the ``msg_type`` wrapper)."""
        title, template = header or self._infer_card_header(content)
        elements: list[dict] = []
        for section in self._split_risk_sections(content):
            if elements:
                elements.append({"tag": "hr"})
            elements.append(
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": section},
                }
            )

        target_url = (web_url if web_url is not None else getattr(self, "_web_url", "")) or ""
        if self._is_web_url(target_url):
            elements.append({"tag": "hr"})
            elements.append(
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "打开 Web 工作台追问"},
                            "type": "primary",
                            "url": target_url,
                        }
                    ],
                }
            )

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": template,
            },
            "elements": elements,
        }

    # ------------------------------------------------------------------
    # Webhook helpers (unchanged legacy path)
    # ------------------------------------------------------------------

    def _get_keyword_prefix(self) -> str:
        if not self._feishu_keyword:
            return ""
        return f"{self._feishu_keyword}\n"

    def _apply_keyword_prefix(self, content: str) -> str:
        prefix = self._get_keyword_prefix()
        if not prefix:
            return content
        return f"{prefix}{content}" if content else self._feishu_keyword

    def _build_security_fields(self) -> Dict[str, str]:
        if not self._feishu_secret:
            return {}
        timestamp = str(int(time.time()))
        string_to_sign = f"{timestamp}\n{self._feishu_secret}"
        sign = base64.b64encode(
            hmac.new(
                string_to_sign.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).digest()
        ).decode("utf-8")
        return {"timestamp": timestamp, "sign": sign}

    # ------------------------------------------------------------------
    # App Bot client (lazy, thread-safe)
    # ------------------------------------------------------------------

    def _ensure_app_client(self) -> Any:
        """Lazily initialise the ``lark-oapi`` client for App Bot mode."""
        if self._app_client is not _NO_CLIENT:
            return self._app_client
        with self._app_client_lock:
            if self._app_client is not _NO_CLIENT:
                return self._app_client
            if not FEISHU_SDK_AVAILABLE:
                logger.warning(
                    "Feishu App Bot requires lark-oapi; install with: pip install -r requirements.txt"
                )
                self._app_client = None
                return None
            if not self._feishu_app_id or not self._feishu_app_secret:
                missing = []
                if not self._feishu_app_id:
                    missing.append("FEISHU_APP_ID")
                if not self._feishu_app_secret:
                    missing.append("FEISHU_APP_SECRET")
                logger.warning("Feishu App Bot credentials incomplete, missing: %s", ", ".join(missing))
                self._app_client = None
                return None
            try:
                self._app_client = (
                    _lark.Client.builder()
                    .app_id(self._feishu_app_id)
                    .app_secret(self._feishu_app_secret)
                    .domain(self._feishu_domain)
                    .log_level(_lark.LogLevel.WARNING)
                    .build()
                )
                logger.info("Feishu App Bot client initialized (domain=%s)", self._feishu_domain)
            except Exception as e:
                logger.error("Feishu App Bot client initialization failed: %s", e)
                self._app_client = None
            return self._app_client

    # ------------------------------------------------------------------
    # App Bot send helpers
    # ------------------------------------------------------------------

    def _send_via_app_bot(self, content: str) -> bool:
        """Send message through the Feishu App Bot, chunking if necessary."""
        if not self._feishu_chat_id:
            logger.warning("FEISHU_CHAT_ID not configured, skipping App Bot send")
            return False

        client = self._ensure_app_client()
        if client is None:
            return False

        header = self._infer_card_header(content)
        formatted = format_feishu_markdown(content)
        web_url = self._web_url

        def build_card(chunk: str) -> str:
            return json.dumps(self._build_card_body(chunk, web_url=web_url, header=header), ensure_ascii=False)

        def build_pages() -> list[tuple[str, str]]:
            return self._build_card_pages(
                formatted, build_card, self._feishu_max_bytes, self._app_card_request_bytes, _APP_MAX_REQUEST_BYTES,
            )

        try:
            try:
                pages = build_pages()
            except ValueError:
                if not web_url:
                    raise
                logger.warning("App Bot card pagination budget insufficient, retrying without workbench button")
                web_url = ""
                pages = build_pages()
        except ValueError as e:
            logger.error("App Bot chunking failed: %s", e)
            return False

        success = True
        for i, (chunk, card_payload) in enumerate(pages):
            ok = self._app_send_once(client, chunk, card_payload=card_payload)
            if not ok:
                logger.error("App Bot chunk %d/%d send failed", i + 1, len(pages))
                success = False
            if i < len(pages) - 1:
                time.sleep(1)
        return success

    def _app_send_once(
        self, client: Any, content: str, *, card_payload: str
    ) -> bool:
        """Single-shot send via App Bot with card-first / text-fallback.

        Content received here has already been through ``format_feishu_markdown``
        which converts all Markdown constructs to ``lark_md``-compatible format.
        The interactive card uses ``tag: lark_md`` for rendering.
        """
        if self._app_send_raw(client, "interactive", card_payload):
            return True

        # Fallback to plain text.
        text_payload = json.dumps({"text": content}, ensure_ascii=False)
        return self._app_send_raw(client, "text", text_payload)

    def _build_app_message_body(self, msg_type: str, content_json: str, send_uuid: str) -> "CreateMessageRequestBody":
        return (
            CreateMessageRequestBody.builder()
            .receive_id(self._feishu_chat_id)
            .content(content_json)
            .msg_type(msg_type)
            .uuid(send_uuid)
            .build()
        )

    def _app_card_request_bytes(self, card_payload: str) -> int:
        # The SDK escapes the card JSON again as the request body's content string.
        body = self._build_app_message_body("interactive", card_payload, "0" * 36)
        return len(_lark.JSON.marshal(body).encode("utf-8"))

    def _app_send_raw(self, client: Any, msg_type: str, content_json: str) -> bool:
        """Low-level send via lark-oapi SDK with retry and idempotency UUID.

        Request construction is done once outside the retry loop; it is
        deterministic and a construction error is a programming error, not
        a transient failure.
        """
        if client is None:
            return False

        send_uuid = str(uuid_mod.uuid4())
        try:
            req = (
                CreateMessageRequest.builder()
                .receive_id_type(self._feishu_receive_id_type)
                .request_body(self._build_app_message_body(msg_type, content_json, send_uuid))
                .build()
            )
        except Exception as e:
            logger.error("App Bot request build failed: %s: %s", type(e).__name__, e)
            return False

        last_status: Optional[str] = None

        for attempt in range(_APP_SEND_RETRIES):
            try:
                resp = client.im.v1.message.create(req)
            except Exception as e:
                logger.warning(
                    "App Bot send exception (attempt=%d/%d): %s: %s",
                    attempt + 1, _APP_SEND_RETRIES, type(e).__name__, e,
                )
                if attempt < _APP_SEND_RETRIES - 1:
                    time.sleep(
                        _APP_SEND_BACKOFF_SECONDS[
                            min(attempt, len(_APP_SEND_BACKOFF_SECONDS) - 1)
                        ]
                    )
                continue

            if resp.success():
                logger.info("App Bot message sent successfully (type=%s)", msg_type)
                return True

            try:
                log_id = resp.get_log_id()
            except (AttributeError, Exception):
                log_id = "N/A"
            status = "code=%s, msg=%s, log_id=%s" % (
                resp.code, resp.msg, log_id,
            )
            last_status = status
            logger.warning(
                "App Bot send failed (attempt=%d/%d): %s",
                attempt + 1, _APP_SEND_RETRIES, status,
            )

            if attempt < _APP_SEND_RETRIES - 1:
                time.sleep(
                    _APP_SEND_BACKOFF_SECONDS[
                        min(attempt, len(_APP_SEND_BACKOFF_SECONDS) - 1)
                    ]
                )

        if last_status:
            logger.error("App Bot send permanently failed: %s", last_status)
        return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_to_feishu(self, content: str, *, timeout_seconds: Optional[float] = None) -> bool:
        """
        Push a message to Feishu.

        Routing priority:
          1. **Webhook** – when ``feishu_webhook_url`` is configured.
          2. **App Bot** – when ``feishu_app_id`` + ``feishu_app_secret``
             + ``feishu_chat_id`` are all configured and webhook is absent.

        Returns:
            Whether the send succeeded.
        """
        if content is None:
            logger.error("send_to_feishu: content must not be None")
            return False
        sanitized_content = strip_hidden_markdown_metadata(content).strip()
        if self._feishu_url:
            return self._send_via_webhook(sanitized_content, timeout_seconds=timeout_seconds)
        return self._send_via_app_bot(sanitized_content)

    def send_feishu_file(self, file_path: str) -> bool:
        """
        Upload and send a file to the Feishu chat.

        .. note::

           * **App Bot mode** – uploads the file via the lark-oapi SDK and
             sends it as a file message.  This is the recommended path.
           * **Webhook mode** – reads the file content and sends it as a
             regular text/card message (webhooks do not support file upload).

        Args:
            file_path: Absolute or relative path to the local file.

        Returns:
            Whether the send succeeded.
        """
        path = Path(file_path)
        if not path.is_file():
            logger.error("send_feishu_file: file does not exist: %s", file_path)
            return False

        upload_path, display_name = self._prepare_sanitized_file(path)
        try:
            if self._feishu_url:
                # Webhook mode: send file content as a message (best-effort).
                return self._send_file_via_webhook(upload_path, display_name=display_name)

            # App Bot mode: upload file via SDK.
            return self._send_file_via_app_bot(upload_path, display_name=display_name)
        finally:
            if upload_path != path:
                try:
                    upload_path.unlink()
                except OSError:
                    logger.warning("Failed to clean up Feishu temp file: %s", upload_path)

    @staticmethod
    def _prepare_sanitized_file(path: Path) -> Tuple[Path, str]:
        display_name = path.name
        if path.suffix.lower() not in {".md", ".markdown", ".txt"}:
            return path, display_name

        try:
            raw_text = path.read_text("utf-8")
        except (OSError, UnicodeDecodeError):
            return path, display_name
        if not isinstance(raw_text, str):
            return path, display_name

        sanitized_text = strip_hidden_markdown_metadata(raw_text).strip()
        if sanitized_text == raw_text:
            return path, display_name

        temp_file = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=path.suffix,
            prefix="feishu_sanitized_",
            delete=False,
        )
        with temp_file:
            temp_file.write(sanitized_text)
        return Path(temp_file.name), display_name

    def _send_file_via_app_bot(self, path: Path, *, display_name: Optional[str] = None) -> bool:
        """Upload *path* to Feishu via App Bot SDK and send as file message."""
        if not FEISHU_FILE_SDK_AVAILABLE:
            logger.warning("lark-oapi SDK does not support file upload; upgrade lark-oapi")
            return False

        if not self._feishu_chat_id:
            logger.warning("FEISHU_CHAT_ID not configured, skipping App Bot file send")
            return False

        client = self._ensure_app_client()
        if client is None:
            return False

        file_name = display_name or path.name
        # Determine file_type from extension; fall back to "stream" for unknown types.
        feishu_file_types = {
            ".opus": "opus", ".aac": "aac", ".amr": "amr", ".mp3": "mp3",
            ".wma": "wma", ".pcm": "pcm", ".wav": "wav",
            ".mp4": "mp4", ".gif": "gif",
            ".pdf": "pdf",
            ".doc": "doc", ".docx": "docx",
            ".xls": "xls", ".xlsx": "xlsx",
            ".ppt": "ppt", ".pptx": "pptx",
        }
        file_type = feishu_file_types.get(path.suffix.lower(), "stream")

        try:
            with path.open("rb") as f:
                body = (
                    _CreateFileRequestBody.builder()
                    .file_type(file_type)
                    .file_name(file_name)
                    .file(f)  # type: ignore[arg-type]
                    .build()
                )
                req = (
                    _CreateFileRequest.builder()
                    .request_body(body)
                    .build()
                )
                resp = client.im.v1.file.create(req)
        except Exception as e:
            logger.error("App Bot file upload exception: %s: %s", type(e).__name__, e)
            return False

        if not resp.success():
            try:
                log_id = resp.get_log_id()
            except (AttributeError, Exception):
                log_id = "N/A"
            logger.error(
                "App Bot file upload failed: code=%s, msg=%s, log_id=%s",
                resp.code, resp.msg, log_id,
            )
            return False

        file_key = resp.data.file_key if resp.data else None
        if not file_key:
            logger.error("App Bot file upload succeeded but no file_key returned")
            return False

        logger.info("App Bot file upload succeeded: file_key=%s, file_name=%s", file_key, file_name)

        # Send a file message with the uploaded file_key.
        content_json = json.dumps({"file_key": file_key})
        return self._app_send_raw(client, "file", content_json)

    @staticmethod
    def _guess_mime_for_webhook(path: Path) -> str:
        """Determine a human-readable label for webhook fallback."""
        suffix = path.suffix.lower()
        labels = {".md": "Markdown", ".txt": "文本", ".pdf": "PDF", ".csv": "CSV"}
        return labels.get(suffix, suffix.lstrip(".").upper() or "文件")

    def _send_file_via_webhook(self, path: Path, *, display_name: Optional[str] = None) -> bool:
        """Send file *content* as a Feishu message (webhook fallback)."""
        try:
            text = path.read_text("utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.error("Failed to read file content (webhook fallback): %s: %s", type(e).__name__, e)
            return False

        file_label = self._guess_mime_for_webhook(path)
        header = f"**📄 {file_label} 文件内容: {display_name or path.name}**\n\n"
        content = header + strip_hidden_markdown_metadata(text).strip()
        # Delegate to the existing webhook send path.
        return self._send_via_webhook(content)

    # ------------------------------------------------------------------
    # Webhook path
    # ------------------------------------------------------------------

    def _send_via_webhook(self, content: str, *, timeout_seconds: Optional[float] = None) -> bool:
        """Budget the report using the same JSON encoding as requests.post."""
        header = self._infer_card_header(content)
        formatted_content = format_feishu_markdown(content)
        content_budget = self._feishu_max_bytes - len(self._get_keyword_prefix().encode("utf-8"))
        if content_budget <= 0:
            logger.error("Feishu keyword exceeds max bytes allowed per message, cannot send")
            return False
        sample_security_fields = self._build_security_fields()
        web_url = self._web_url

        def build_payload(chunk: str) -> Dict[str, Any]:
            return {
                "msg_type": "interactive",
                "card": self._build_card_body(self._apply_keyword_prefix(chunk), web_url=web_url, header=header),
                **sample_security_fields,
            }

        try:
            try:
                pages = self._build_card_pages(
                    formatted_content, build_payload, content_budget, self._webhook_payload_bytes, _WEBHOOK_MAX_REQUEST_BYTES,
                )
            except ValueError:
                if not web_url:
                    raise
                logger.warning(
                    "Feishu Webhook card pagination budget insufficient, retrying without workbench button"
                )
                web_url = ""
                pages = self._build_card_pages(
                    formatted_content, build_payload, content_budget, self._webhook_payload_bytes, _WEBHOOK_MAX_REQUEST_BYTES,
                )
        except ValueError as e:
            # A long keyword can fit in a text request but leave no room for a card.
            text_payload = self._build_webhook_text_payload(formatted_content, sample_security_fields)
            if (
                len(formatted_content.encode("utf-8")) > content_budget
                or self._webhook_payload_bytes(text_payload) > _WEBHOOK_MAX_REQUEST_BYTES
            ):
                logger.error("Feishu Webhook card build or chunking failed: %s", e)
                return False
            pages = [(formatted_content, None)]

        total_chunks = len(pages)
        success_count = 0
        if total_chunks > 1:
            logger.info("Feishu chunked send: %d chunks total", total_chunks)
        for i, (chunk, card_payload) in enumerate(pages):
            try:
                if self._send_feishu_message(chunk, card_payload, timeout_seconds):
                    success_count += 1
                else:
                    logger.error("Feishu chunk %d/%d send failed", i + 1, total_chunks)
            except Exception as e:
                logger.error("Feishu chunk %d/%d send exception: %s", i + 1, total_chunks, e)
            if i < total_chunks - 1:
                time.sleep(1)
        return success_count == total_chunks

    @staticmethod
    def _webhook_payload_bytes(payload: Dict[str, Any]) -> int:
        return len(requests.models.complexjson.dumps(payload, allow_nan=False).encode("utf-8"))

    def _build_webhook_text_payload(self, content: str, security_fields: Dict[str, str]) -> Dict[str, Any]:
        return {
            "msg_type": "text",
            "content": {"text": self._apply_keyword_prefix(content)},
            **security_fields,
        }

    @staticmethod
    def _build_card_pages(
        content: str,
        build_card: Callable[[str], _CardPayload],
        content_budget: int,
        request_bytes: Callable[[_CardPayload], int],
        request_limit: int,
    ) -> list[Tuple[str, _CardPayload]]:
        card = build_card(content)
        if len(content.encode("utf-8")) <= content_budget and request_bytes(card) <= request_limit:
            return [(content, card)]

        fixed_bytes = request_bytes(build_card(""))
        wire_budget = request_limit - fixed_bytes
        budget = min(content_budget, wire_budget)
        min_budget = MIN_MAX_BYTES + PAGE_MARKER_SAFE_BYTES
        while budget >= min_budget:
            chunks = chunk_content_by_max_bytes(content, budget, add_page_marker=True)
            pages = [(chunk, build_card(chunk)) for chunk in chunks]
            largest_chunk, largest = max(
                ((chunk, request_bytes(card)) for chunk, card in pages),
                key=lambda page: page[1],
            )
            if largest <= request_limit:
                return pages
            if budget == min_budget:
                break
            # JSON escaping and risk panels can vary by page.
            chunk_bytes = min(budget, len(largest_chunk.encode("utf-8")))
            budget = max(min_budget, chunk_bytes * wire_budget // (largest - fixed_bytes))
        raise ValueError("单条请求的可用字节数不足以分页发送卡片")

    def _send_feishu_message(
        self,
        content: str,
        card_payload: Optional[Dict[str, Any]],
        timeout_seconds: Optional[float],
    ) -> bool:
        """Send a single Feishu webhook message (interactive card, fallback text)."""
        security_fields = self._build_security_fields()

        def _post_payload(payload: Dict[str, Any]) -> bool:
            try:
                response = requests.post(
                    self._feishu_url,
                    json=payload,
                    timeout=timeout_seconds or _WEBHOOK_SEND_TIMEOUT_SECONDS,
                    verify=self._webhook_verify_ssl,
                )
            except (requests.exceptions.ConnectionError,
                     requests.exceptions.Timeout,
                     requests.exceptions.RequestException) as e:
                logger.error("Feishu Webhook network request exception: %s", e)
                return False
            if response.status_code == 200:
                try:
                    result = response.json()
                except (ValueError, AttributeError):
                    logger.error("Feishu Webhook returned non-JSON response: %s", response.text[:200])
                    return False
                if not isinstance(result, dict):
                    logger.error("Feishu Webhook returned unexpected format: %s", type(result).__name__)
                    return False
                code = result.get("code") if "code" in result else result.get("StatusCode")
                if code == 0:
                    logger.info("Feishu Webhook message sent successfully")
                    return True
                logger.error(
                    "Feishu Webhook returned error [code=%s]: %s",
                    code,
                    result.get("msg") or result.get("StatusMessage", "Unknown error"),
                )
                return False
            logger.error("Feishu Webhook request failed: HTTP %d", response.status_code)
            return False

        if card_payload is not None:
            card_payload.update(security_fields)
            if self._webhook_payload_bytes(card_payload) <= _WEBHOOK_MAX_REQUEST_BYTES and _post_payload(card_payload):
                return True

        text_payload = self._build_webhook_text_payload(content, security_fields)
        if self._webhook_payload_bytes(text_payload) > _WEBHOOK_MAX_REQUEST_BYTES:
            logger.error("Feishu Webhook plain-text request body too large, cannot send")
            return False
        return _post_payload(text_payload)
