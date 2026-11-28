# -*- coding: utf-8 -*-
"""
Wechat 发送提醒服务

职责：
1. 通过企业微信 Webhook 发送文本消息
2. 通过企业微信 Webhook 发送图片消息
"""
import logging
import base64
import hashlib
import requests
import time
from typing import Any, Optional

from src.config import Config
from src.formatters import chunk_content_by_max_bytes, strip_hidden_markdown_metadata
from src.services.channel_renderers import render_wechat_digest_chunks


logger = logging.getLogger(__name__)


# WeChat Work image msgtype limit ~2MB (base64 payload)
WECHAT_IMAGE_MAX_BYTES = 2 * 1024 * 1024

class WechatSender:
    
    def __init__(self, config: Config):
        """
        初始化企业微信配置

        Args:
            config: 配置对象
        """
        self._wechat_url = config.wechat_webhook_url
        self._wechat_max_bytes = getattr(config, 'wechat_max_bytes', 4000)
        self._wechat_msg_type = getattr(config, 'wechat_msg_type', 'markdown')
        self._webhook_verify_ssl = getattr(config, 'webhook_verify_ssl', True)
        
    def send_to_wechat(
        self,
        content: str,
        *,
        report_payload: Optional[Any] = None,
        timeout_seconds: Optional[float] = None,
    ) -> bool:
        """
        推送消息到企业微信机器人

        Args:
            content: Markdown 格式的消息内容
            report_payload: 可选结构化报告载荷，存在时输出高信噪比原生摘要

        Returns:
            是否发送成功
        """
        if not self._wechat_url:
            logger.warning("WeChat Work Webhook not configured, skipping notification")
            return False

        if report_payload is not None:
            effective_max_bytes = (
                min(self._wechat_max_bytes, 1950)
                if self._wechat_msg_type == 'text'
                else min(self._wechat_max_bytes, 3950)
            )
            chunks = []
            try:
                chunks = render_wechat_digest_chunks(
                    report_payload,
                    msg_type=self._wechat_msg_type,
                    max_bytes=effective_max_bytes,
                )
            except Exception as e:
                logger.warning("WeChat structured digest rendering failed, falling back to text mode: %s", e)

            if chunks:
                success_count = 0
                for i, chunk in enumerate(chunks):
                    try:
                        ok = self._send_wechat_message(chunk, timeout_seconds=timeout_seconds)
                    except Exception as e:
                        logger.error("WeChat chunk %d/%d send error: %s", i + 1, len(chunks), e)
                        ok = False
                    if ok:
                        success_count += 1
                    else:
                        logger.error("WeChat chunk %d/%d send failed", i + 1, len(chunks))
                    if i < len(chunks) - 1:
                        time.sleep(1)
                return success_count == len(chunks)

        sanitized_content = strip_hidden_markdown_metadata(content).strip()
        if not sanitized_content:
            logger.warning("WeChat Work message content is empty, skipping notification")
            return False

        # 根据消息类型动态限制上限，避免 text 类型超过企业微信 2048 字节限制
        if self._wechat_msg_type == 'text':
            max_bytes = min(self._wechat_max_bytes, 2000)  # 预留一定字节给系统/分页标记
        else:
            max_bytes = self._wechat_max_bytes  # markdown 默认 4000 字节

        # 检查字节长度，超长则分批发送
        content_bytes = len(sanitized_content.encode('utf-8'))
        if content_bytes > max_bytes:
            logger.info(f"Message exceeds limit ({content_bytes} bytes/{len(content)} chars), sending in chunks")
            return self._send_wechat_chunked(sanitized_content, max_bytes)

        try:
            return self._send_wechat_message(sanitized_content, timeout_seconds=timeout_seconds)
        except Exception as e:
            logger.error(f"Failed to send WeChat Work message: {e}")
            return False

    def _send_wechat_image(self, image_bytes: bytes) -> bool:
        """Send image via WeChat Work webhook msgtype image (Issue #289)."""
        if not self._wechat_url:
            return False
        if len(image_bytes) > WECHAT_IMAGE_MAX_BYTES:
            logger.warning(
                "WeChat Work image exceeds limit (%d > %d bytes); refusing to send, caller should fall back to text",
                len(image_bytes), WECHAT_IMAGE_MAX_BYTES,
            )
            return False
        try:
            b64 = base64.b64encode(image_bytes).decode("ascii")
            md5_hash = hashlib.md5(image_bytes).hexdigest()
            payload = {
                "msgtype": "image",
                "image": {"base64": b64, "md5": md5_hash},
            }
            response = requests.post(
                self._wechat_url, json=payload, timeout=30, verify=self._webhook_verify_ssl
            )
            if response.status_code == 200:
                result = response.json()
                if result.get("errcode") == 0:
                    logger.info("WeChat Work image sent successfully")
                    return True
                logger.error("WeChat Work image send failed: %s", result.get("errmsg", ""))
            else:
                logger.error("WeChat Work request failed: HTTP %s", response.status_code)
            return False
        except Exception as e:
            logger.error("WeChat Work image send error: %s", e)
            return False
    
    def _send_wechat_message(self, content: str, *, timeout_seconds: Optional[float] = None) -> bool:
        """发送企业微信消息"""
        payload = self._gen_wechat_payload(content)
        
        response = requests.post(
            self._wechat_url,
            json=payload,
            timeout=timeout_seconds or 10,
            verify=self._webhook_verify_ssl
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('errcode') == 0:
                logger.info("WeChat Work message sent successfully")
                return True
            else:
                logger.error(f"WeChat Work returned error: {result}")
                return False
        else:
            logger.error(f"WeChat Work request failed: {response.status_code}")
            return False
        
    def _send_wechat_chunked(self, content: str, max_bytes: int) -> bool:
        """
        分批发送长消息到企业微信
        
        按股票分析块（以 --- 或 ### 分隔）智能分割，确保每批不超过限制
        
        Args:
            content: 完整消息内容
            max_bytes: 单条消息最大字节数
            
        Returns:
            是否全部发送成功
        """
        chunks = chunk_content_by_max_bytes(content, max_bytes, add_page_marker=True)
        total_chunks = len(chunks)
        success_count = 0
        for i, chunk in enumerate(chunks):
            if self._send_wechat_message(chunk):
                success_count += 1
            else:
                logger.error(f"WeChat Work chunk {i+1}/{total_chunks} send failed")
            if i < total_chunks - 1:
                time.sleep(1)
        return success_count == len(chunks)

    def _gen_wechat_payload(self, content: str) -> dict:
        """生成企业微信消息 payload"""
        sanitized_content = strip_hidden_markdown_metadata(content).strip()
        if self._wechat_msg_type == 'text':
            return {
                "msgtype": "text",
                "text": {
                    "content": sanitized_content
                }
            }
        else:
            return {
                "msgtype": "markdown",
                "markdown": {
                    "content": sanitized_content
                }
            }
