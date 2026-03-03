# -*- coding: utf-8 -*-
"""
===================================
Markdown 转图片工具模块
===================================

将 Markdown 转为 PNG 图片（用于不支持 Markdown 的通知渠道）。
基于 wkhtmltoimage (imgkit)，复用 formatters.markdown_to_html_document。

Security note: imgkit passes HTML to wkhtmltoimage via stdin, not argv, so
command injection from content is not applicable. Output is rasterized to PNG
(no script execution). Input is from system-generated reports, not raw user
input. Risk is considered low for the current use case.
"""

import logging
from typing import Optional

from src.formatters import markdown_to_html_document

logger = logging.getLogger(__name__)


def markdown_to_image(markdown_text: str, max_chars: int = 15000) -> Optional[bytes]:
    """
    Convert Markdown to PNG image bytes via HTML and wkhtmltoimage.

    When imgkit or wkhtmltopdf is unavailable, returns None so caller can
    fall back to text sending.

    Args:
        markdown_text: Raw Markdown content.
        max_chars: Skip conversion and return None if content exceeds this length
            (avoids huge images). Default 15000.

    Returns:
        PNG bytes, or None if conversion fails or dependencies unavailable.
    """
    if len(markdown_text) > max_chars:
        logger.warning(
            "Markdown content (%d chars) exceeds max_chars (%d), skipping image conversion",
            len(markdown_text),
            max_chars,
        )
        return None

    try:
        import imgkit
    except ImportError:
        logger.debug("imgkit not installed, markdown_to_image unavailable")
        return None

    html = markdown_to_html_document(markdown_text)

    try:
        # imgkit.from_string(html, False) returns PNG bytes via wkhtmltoimage stdout
        options = {
            "format": "png",
            "encoding": "UTF-8",
            "quiet": "",  # Suppress wkhtmltoimage stderr to console
        }
        out = imgkit.from_string(html, False, options=options)
        if out and isinstance(out, bytes) and len(out) > 0:
            return out
        logger.warning("imgkit.from_string returned empty or invalid result")
        return None
    except OSError as e:
        if "wkhtmltoimage" in str(e).lower() or "wkhtmltopdf" in str(e).lower():
            logger.debug("wkhtmltopdf/wkhtmltoimage not found: %s", e)
        else:
            logger.warning("imgkit/wkhtmltoimage error: %s", e)
        return None
    except Exception as e:
        logger.warning("markdown_to_image conversion failed: %s", e)
        return None
