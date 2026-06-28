# -*- coding: utf-8 -*-
"""Notification channel rendering capability profiles.

This module intentionally uses plain channel strings instead of importing
``NotificationChannel`` from ``src.notification``.  The notification service may
import these profiles later without creating a circular dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple


@dataclass(frozen=True)
class ChannelProfile:
    """Static rendering capabilities for one notification channel."""

    channel: str
    markdown: str
    default_mode: str
    max_text_chars: Optional[int] = None
    max_text_bytes: Optional[int] = None
    supports_card: bool = False
    supports_image: bool = False
    supports_file: bool = False
    supports_link: bool = True
    notes: str = ""


@dataclass(frozen=True)
class PreparedMessage:
    """A channel-specific prepared notification message.

    The object describes how a message is ready to be sent for a channel without
    changing the original report semantics.  Senders can consume the fields they
    support and fall back to ``fallback_text`` or ``text`` when a richer payload
    is unavailable.
    """

    channel: str
    text: str
    formatted_text: Optional[str] = None
    card_payload: Optional[Mapping[str, Any]] = None
    fallback_text: Optional[str] = None
    attachments: Tuple[Any, ...] = ()
    diagnostics: Tuple[str, ...] = ()

    @property
    def content_for_text_send(self) -> str:
        """Return the best text payload for legacy text senders."""

        return self.formatted_text or self.fallback_text or self.text


@dataclass(frozen=True)
class RendererPreset:
    """Reserved renderer plan for one notification channel.

    Presets document the intended renderer shape without changing today's
    runtime send path.  A future opt-in implementation can use these names to
    wire platform-specific renderers while keeping the legacy text fallback.
    """

    channel: str
    text_renderer: str
    markdown: str
    enabled_by_default: bool = False
    rich_renderer: Optional[str] = None
    image_renderer: Optional[str] = None
    fallback_renderer: str = "legacy_text"
    notes: str = ""


CHANNEL_PROFILES: Dict[str, ChannelProfile] = {
    "wechat": ChannelProfile(
        channel="wechat",
        markdown="wechat_markdown",
        default_mode="full_report",
        max_text_bytes=4096,
        supports_image=True,
        supports_link=True,
        notes="Enterprise WeChat receives the full report by default and relies on safe chunking.",
    ),
    "feishu": ChannelProfile(
        channel="feishu",
        markdown="lark_md",
        default_mode="full_report",
        max_text_bytes=20000,
        supports_card=True,
        supports_file=True,
        supports_link=True,
        notes="Feishu uses lark_md/card payloads and needs table fallbacks.",
    ),
    "telegram": ChannelProfile(
        channel="telegram",
        markdown="markdown_v2",
        default_mode="full_report",
        max_text_chars=4096,
        supports_image=True,
        supports_link=True,
        notes="Telegram length limits are measured in UTF-16 code units.",
    ),
    "email": ChannelProfile(
        channel="email",
        markdown="html",
        default_mode="full_html",
        supports_image=True,
        supports_file=True,
        supports_link=True,
        notes="Email remains the high-fidelity full-report carrier.",
    ),
    "pushover": ChannelProfile(
        channel="pushover",
        markdown="plain_text",
        default_mode="plain_fallback",
        max_text_chars=1024,
        supports_link=True,
    ),
    "ntfy": ChannelProfile(
        channel="ntfy",
        markdown="plain_text",
        default_mode="plain_fallback",
        supports_link=True,
    ),
    "gotify": ChannelProfile(
        channel="gotify",
        markdown="markdown",
        default_mode="full_report",
        supports_link=True,
    ),
    "pushplus": ChannelProfile(
        channel="pushplus",
        markdown="markdown",
        default_mode="full_report",
        supports_link=True,
    ),
    "serverchan3": ChannelProfile(
        channel="serverchan3",
        markdown="markdown",
        default_mode="full_report",
        supports_link=True,
    ),
    "custom": ChannelProfile(
        channel="custom",
        markdown="channel_specific",
        default_mode="full_report",
        supports_image=True,
        supports_link=True,
        notes="Custom webhook payload shape can be configured by templates.",
    ),
    "discord": ChannelProfile(
        channel="discord",
        markdown="discord_markdown",
        default_mode="full_report",
        max_text_chars=2000,
        supports_link=True,
    ),
    "slack": ChannelProfile(
        channel="slack",
        markdown="mrkdwn",
        default_mode="full_report",
        max_text_chars=39000,
        supports_image=True,
        supports_file=True,
        supports_link=True,
        notes="Slack sections should avoid splitting markdown blocks.",
    ),
    "astrbot": ChannelProfile(
        channel="astrbot",
        markdown="plain_text",
        default_mode="plain_fallback",
        supports_link=True,
    ),
    "unknown": ChannelProfile(
        channel="unknown",
        markdown="plain_text",
        default_mode="plain_fallback",
        supports_link=False,
    ),
}


CHANNEL_RENDERER_PRESETS: Dict[str, RendererPreset] = {
    "wechat": RendererPreset(
        channel="wechat",
        text_renderer="wecom_markdown",
        markdown="wechat_markdown",
        rich_renderer="wecom_card",
        image_renderer="png_poster",
        notes="Preset only; current runtime keeps the legacy WeCom dashboard text.",
    ),
    "feishu": RendererPreset(
        channel="feishu",
        text_renderer="feishu_lark_md",
        markdown="lark_md",
        rich_renderer="feishu_interactive_card",
        image_renderer="png_poster",
        notes="Preset only; native card rendering is not enabled by default.",
    ),
    "telegram": RendererPreset(
        channel="telegram",
        text_renderer="telegram_markdown_v2",
        markdown="markdown_v2",
        rich_renderer="telegram_html",
        image_renderer="png_poster",
        notes="Preset only; future renderer must handle Telegram escaping and UTF-16 length limits.",
    ),
    "dingtalk": RendererPreset(
        channel="dingtalk",
        text_renderer="dingtalk_markdown",
        markdown="dingtalk_markdown",
        rich_renderer="dingtalk_action_card",
        image_renderer="png_poster",
        notes="Preset only; DingTalk is not an active NotificationChannel in this runtime yet.",
    ),
    "slack": RendererPreset(
        channel="slack",
        text_renderer="slack_mrkdwn",
        markdown="mrkdwn",
        rich_renderer="slack_blocks",
        image_renderer="png_poster",
        notes="Preset only; current runtime keeps the legacy report text fallback.",
    ),
}


def normalize_channel_name(channel: Any) -> str:
    """Normalize enum-like or string channel values into profile keys."""

    value = getattr(channel, "value", channel)
    return str(value or "").strip().lower() or "unknown"


def get_channel_profile(channel: Any) -> ChannelProfile:
    """Return the channel profile, falling back to ``unknown``."""

    name = normalize_channel_name(channel)
    return CHANNEL_PROFILES.get(name, CHANNEL_PROFILES["unknown"])


def all_channel_profiles() -> Tuple[ChannelProfile, ...]:
    """Return all profiles in deterministic declaration order."""

    return tuple(CHANNEL_PROFILES.values())


def get_renderer_preset(channel: Any) -> RendererPreset:
    """Return the reserved renderer preset for ``channel``.

    Unknown channels use a plain text fallback preset and stay disabled.
    """

    name = normalize_channel_name(channel)
    return CHANNEL_RENDERER_PRESETS.get(
        name,
        RendererPreset(
            channel=name,
            text_renderer="plain_text",
            markdown="plain_text",
            notes="Fallback preset for channels without a dedicated renderer plan.",
        ),
    )


def all_renderer_presets() -> Tuple[RendererPreset, ...]:
    """Return all reserved renderer presets in deterministic declaration order."""

    return tuple(CHANNEL_RENDERER_PRESETS.values())
