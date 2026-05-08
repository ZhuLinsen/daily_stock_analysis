# -*- coding: utf-8 -*-
"""Read-only notification configuration diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal, Optional, Sequence, Tuple

from src.config import Config
from src.notification import ChannelDetector, NotificationChannel, NotificationService

KeyTier = Literal["minimal", "advanced"]
IssueSeverity = Literal["error", "warning", "info"]
ChannelKind = Literal["configured", "fallback", "context"]


@dataclass(frozen=True)
class NotificationKeySpec:
    """Metadata for a notification-related configuration key."""

    key: str
    tier: KeyTier
    description: str
    channel: str


@dataclass(frozen=True)
class NotificationChannelSpec:
    """Baseline metadata for one notification channel."""

    channel: str
    display_name: str
    kind: ChannelKind
    minimal_keys: Tuple[str, ...]
    alternative_minimal_keys: Tuple[Tuple[str, ...], ...] = ()
    advanced_keys: Tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class NotificationDiagnosticIssue:
    """One diagnostic message."""

    severity: IssueSeverity
    code: str
    message: str
    key: Optional[str] = None


@dataclass(frozen=True)
class NotificationDiagnosticResult:
    """Structured notification diagnostic result."""

    configured_channels: Tuple[str, ...]
    errors: Tuple[NotificationDiagnosticIssue, ...]
    warnings: Tuple[NotificationDiagnosticIssue, ...]
    info: Tuple[NotificationDiagnosticIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


CHANNEL_SPECS: Tuple[NotificationChannelSpec, ...] = (
    NotificationChannelSpec(
        channel=NotificationChannel.WECHAT.value,
        display_name=ChannelDetector.get_channel_name(NotificationChannel.WECHAT),
        kind="configured",
        minimal_keys=("WECHAT_WEBHOOK_URL",),
        advanced_keys=("WECHAT_MSG_TYPE",),
    ),
    NotificationChannelSpec(
        channel=NotificationChannel.FEISHU.value,
        display_name=ChannelDetector.get_channel_name(NotificationChannel.FEISHU),
        kind="configured",
        minimal_keys=("FEISHU_WEBHOOK_URL",),
        advanced_keys=("FEISHU_WEBHOOK_SECRET", "FEISHU_WEBHOOK_KEYWORD"),
    ),
    NotificationChannelSpec(
        channel=NotificationChannel.TELEGRAM.value,
        display_name=ChannelDetector.get_channel_name(NotificationChannel.TELEGRAM),
        kind="configured",
        minimal_keys=("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"),
        advanced_keys=("TELEGRAM_MESSAGE_THREAD_ID",),
    ),
    NotificationChannelSpec(
        channel=NotificationChannel.EMAIL.value,
        display_name=ChannelDetector.get_channel_name(NotificationChannel.EMAIL),
        kind="configured",
        minimal_keys=("EMAIL_SENDER", "EMAIL_PASSWORD"),
        advanced_keys=("EMAIL_RECEIVERS", "EMAIL_SENDER_NAME"),
    ),
    NotificationChannelSpec(
        channel=NotificationChannel.PUSHOVER.value,
        display_name=ChannelDetector.get_channel_name(NotificationChannel.PUSHOVER),
        kind="configured",
        minimal_keys=("PUSHOVER_USER_KEY", "PUSHOVER_API_TOKEN"),
    ),
    NotificationChannelSpec(
        channel=NotificationChannel.PUSHPLUS.value,
        display_name=ChannelDetector.get_channel_name(NotificationChannel.PUSHPLUS),
        kind="configured",
        minimal_keys=("PUSHPLUS_TOKEN",),
        advanced_keys=("PUSHPLUS_TOPIC",),
    ),
    NotificationChannelSpec(
        channel=NotificationChannel.SERVERCHAN3.value,
        display_name=ChannelDetector.get_channel_name(NotificationChannel.SERVERCHAN3),
        kind="configured",
        minimal_keys=("SERVERCHAN3_SENDKEY",),
    ),
    NotificationChannelSpec(
        channel=NotificationChannel.CUSTOM.value,
        display_name=ChannelDetector.get_channel_name(NotificationChannel.CUSTOM),
        kind="configured",
        minimal_keys=("CUSTOM_WEBHOOK_URLS",),
        advanced_keys=("CUSTOM_WEBHOOK_BEARER_TOKEN", "CUSTOM_WEBHOOK_BODY_TEMPLATE", "WEBHOOK_VERIFY_SSL"),
    ),
    NotificationChannelSpec(
        channel=NotificationChannel.DISCORD.value,
        display_name=ChannelDetector.get_channel_name(NotificationChannel.DISCORD),
        kind="configured",
        minimal_keys=("DISCORD_WEBHOOK_URL",),
        alternative_minimal_keys=(("DISCORD_BOT_TOKEN", "DISCORD_MAIN_CHANNEL_ID"),),
        advanced_keys=("DISCORD_INTERACTIONS_PUBLIC_KEY",),
        note="Webhook URL or bot token + channel ID can enable Discord.",
    ),
    NotificationChannelSpec(
        channel=NotificationChannel.SLACK.value,
        display_name=ChannelDetector.get_channel_name(NotificationChannel.SLACK),
        kind="configured",
        minimal_keys=("SLACK_WEBHOOK_URL",),
        alternative_minimal_keys=(("SLACK_BOT_TOKEN", "SLACK_CHANNEL_ID"),),
        note="Webhook URL or bot token + channel ID can enable Slack.",
    ),
    NotificationChannelSpec(
        channel=NotificationChannel.ASTRBOT.value,
        display_name=ChannelDetector.get_channel_name(NotificationChannel.ASTRBOT),
        kind="configured",
        minimal_keys=("ASTRBOT_URL",),
        advanced_keys=("ASTRBOT_TOKEN", "WEBHOOK_VERIFY_SSL"),
    ),
    NotificationChannelSpec(
        channel=NotificationChannel.UNKNOWN.value,
        display_name=ChannelDetector.get_channel_name(NotificationChannel.UNKNOWN),
        kind="fallback",
        minimal_keys=(),
        note="Fallback enum value only; it is not configured from static environment keys.",
    ),
    NotificationChannelSpec(
        channel="dingtalk_context",
        display_name="钉钉会话",
        kind="context",
        minimal_keys=(),
        note="Runtime-only reply channel extracted from source message context.",
    ),
    NotificationChannelSpec(
        channel="feishu_context",
        display_name="飞书会话",
        kind="context",
        minimal_keys=(),
        note="Runtime-only reply channel extracted from source message context.",
    ),
)

KEY_SPECS: Tuple[NotificationKeySpec, ...] = tuple(
    NotificationKeySpec(key=key, tier="minimal", description="Required to enable the channel.", channel=spec.channel)
    for spec in CHANNEL_SPECS
    for key in (
        spec.minimal_keys
        + tuple(key for key_group in spec.alternative_minimal_keys for key in key_group)
    )
) + tuple(
    NotificationKeySpec(key=key, tier="advanced", description="Optional channel behavior or security setting.", channel=spec.channel)
    for spec in CHANNEL_SPECS
    for key in spec.advanced_keys
)

P0_ACTIONS_ENV_KEYS: Tuple[str, ...] = (
    "CUSTOM_WEBHOOK_BODY_TEMPLATE",
    "WEBHOOK_VERIFY_SSL",
    "FEISHU_WEBHOOK_SECRET",
    "FEISHU_WEBHOOK_KEYWORD",
    "PUSHPLUS_TOPIC",
)


def _value(config: Config, attr: str):
    return getattr(config, attr, None)


def _has(config: Config, attr: str) -> bool:
    value = _value(config, attr)
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return value is not None and str(value).strip() != ""


def _issue(
    severity: IssueSeverity,
    code: str,
    message: str,
    key: Optional[str] = None,
) -> NotificationDiagnosticIssue:
    return NotificationDiagnosticIssue(severity=severity, code=code, message=message, key=key)


def _require_pair(
    config: Config,
    *,
    left_attr: str,
    right_attr: str,
    left_key: str,
    right_key: str,
    channel_name: str,
    errors: List[NotificationDiagnosticIssue],
    warnings: Optional[List[NotificationDiagnosticIssue]] = None,
    severity: IssueSeverity = "error",
) -> None:
    left = _has(config, left_attr)
    right = _has(config, right_attr)
    target = errors if severity == "error" else warnings
    if target is None:
        target = errors
    if left and not right:
        target.append(
            _issue(
                severity,
                "partial_channel_config",
                f"{channel_name} 已配置 {left_key}，但缺少 {right_key}，该渠道不会启用。",
                key=right_key,
            )
        )
    if right and not left:
        target.append(
            _issue(
                severity,
                "partial_channel_config",
                f"{channel_name} 已配置 {right_key}，但缺少 {left_key}，该渠道不会启用。",
                key=left_key,
            )
        )


def run_notification_diagnostics(config: Config) -> NotificationDiagnosticResult:
    """Run read-only diagnostics for notification configuration."""

    configured = tuple(channel.value for channel in NotificationService.detect_configured_channels(config))
    errors: List[NotificationDiagnosticIssue] = []
    warnings: List[NotificationDiagnosticIssue] = []
    info: List[NotificationDiagnosticIssue] = [
        _issue(
            "info",
            "context_channels_runtime_only",
            "钉钉会话和飞书会话属于运行时消息上下文渠道，无法仅靠静态 .env 完整判断。",
        ),
        _issue(
            "info",
            "phase_scope",
            "P0 只做配置基线和只读诊断；路由、降噪和 Web 一键测试留给后续 Phase。",
        ),
    ]

    if not configured:
        errors.append(
            _issue(
                "error",
                "no_channels_configured",
                "0 个通知渠道已配置；如需发送通知，请至少配置一个渠道的 minimal key。",
            )
        )

    _require_pair(
        config,
        left_attr="telegram_bot_token",
        right_attr="telegram_chat_id",
        left_key="TELEGRAM_BOT_TOKEN",
        right_key="TELEGRAM_CHAT_ID",
        channel_name="Telegram",
        errors=errors,
    )
    _require_pair(
        config,
        left_attr="email_sender",
        right_attr="email_password",
        left_key="EMAIL_SENDER",
        right_key="EMAIL_PASSWORD",
        channel_name="邮件",
        errors=errors,
    )
    _require_pair(
        config,
        left_attr="pushover_user_key",
        right_attr="pushover_api_token",
        left_key="PUSHOVER_USER_KEY",
        right_key="PUSHOVER_API_TOKEN",
        channel_name="Pushover",
        errors=errors,
    )
    _require_pair(
        config,
        left_attr="discord_bot_token",
        right_attr="discord_main_channel_id",
        left_key="DISCORD_BOT_TOKEN",
        right_key="DISCORD_MAIN_CHANNEL_ID",
        channel_name="Discord Bot",
        errors=errors,
        warnings=warnings,
        severity="warning" if _has(config, "discord_webhook_url") else "error",
    )
    _require_pair(
        config,
        left_attr="slack_bot_token",
        right_attr="slack_channel_id",
        left_key="SLACK_BOT_TOKEN",
        right_key="SLACK_CHANNEL_ID",
        channel_name="Slack Bot",
        errors=errors,
        warnings=warnings,
        severity="warning" if _has(config, "slack_webhook_url") else "error",
    )

    if (_has(config, "feishu_webhook_secret") or _has(config, "feishu_webhook_keyword")) and not _has(config, "feishu_webhook_url"):
        warnings.append(
            _issue(
                "warning",
                "advanced_without_minimal",
                "已配置飞书 Webhook 高级安全项，但缺少 FEISHU_WEBHOOK_URL，飞书 Webhook 渠道不会启用。",
                key="FEISHU_WEBHOOK_URL",
            )
        )
    if _has(config, "pushplus_topic") and not _has(config, "pushplus_token"):
        warnings.append(
            _issue(
                "warning",
                "advanced_without_minimal",
                "已配置 PUSHPLUS_TOPIC，但缺少 PUSHPLUS_TOKEN，PushPlus 渠道不会启用。",
                key="PUSHPLUS_TOKEN",
            )
        )
    if (
        _has(config, "custom_webhook_bearer_token")
        or _has(config, "custom_webhook_body_template")
    ) and not _has(config, "custom_webhook_urls"):
        warnings.append(
            _issue(
                "warning",
                "advanced_without_minimal",
                "已配置自定义 Webhook 高级项，但缺少 CUSTOM_WEBHOOK_URLS，自定义 Webhook 渠道不会启用。",
                key="CUSTOM_WEBHOOK_URLS",
            )
        )
    if _has(config, "astrbot_token") and not _has(config, "astrbot_url"):
        warnings.append(
            _issue(
                "warning",
                "advanced_without_minimal",
                "已配置 ASTRBOT_TOKEN，但缺少 ASTRBOT_URL，AstrBot 渠道不会启用。",
                key="ASTRBOT_URL",
            )
        )

    return NotificationDiagnosticResult(
        configured_channels=configured,
        errors=tuple(errors),
        warnings=tuple(warnings),
        info=tuple(info),
    )


def _format_issues(title: str, issues: Sequence[NotificationDiagnosticIssue]) -> List[str]:
    if not issues:
        return [f"{title}: 无"]
    lines = [f"{title}:"]
    for item in issues:
        key_suffix = f" [{item.key}]" if item.key else ""
        lines.append(f"- {item.code}{key_suffix}: {item.message}")
    return lines


def format_notification_diagnostics(result: NotificationDiagnosticResult) -> str:
    """Format diagnostics for CLI output without exposing secret values."""

    lines = [
        "通知配置诊断",
        f"已配置渠道: {len(result.configured_channels)} 个",
    ]
    if result.configured_channels:
        channel_names = [
            ChannelDetector.get_channel_name(NotificationChannel(channel))
            for channel in result.configured_channels
        ]
        lines.append("渠道列表: " + ", ".join(channel_names))
    else:
        lines.append("渠道列表: (无)")

    lines.append("")
    lines.extend(_format_issues("Errors", result.errors))
    lines.append("")
    lines.extend(_format_issues("Warnings", result.warnings))
    lines.append("")
    lines.extend(_format_issues("Info", result.info))
    return "\n".join(lines)
