# -*- coding: utf-8 -*-
"""Periodic review report sender.

Follows the same pattern as ``SectorAnalysisReportSender``: uses
``FeishuSender`` to send Markdown reports to the configured chat ID,
falling back to the default notification channel.
"""

from __future__ import annotations

import logging
from typing import Optional

from src.config import Config, get_config
from src.notification_sender.feishu_sender import FeishuSender

logger = logging.getLogger(__name__)


class PeriodicReviewReportSender:
    """Send periodic review reports via the project notification system."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()
        self.feishu_sender = FeishuSender(self.config)

    def send_report(self, report_content: str) -> bool:
        if not report_content:
            logger.error("periodic_review: report content is empty")
            return False

        logger.info("periodic_review: sending report")
        try:
            return self.feishu_sender.send_to_feishu(report_content)
        except Exception as exc:
            logger.error("periodic_review: send failed: %s", exc)
            return False

    def send_notification(self, notification_content: str) -> bool:
        return self.send_report(notification_content)


def create_periodic_review_report_sender() -> PeriodicReviewReportSender:
    return PeriodicReviewReportSender(get_config())
