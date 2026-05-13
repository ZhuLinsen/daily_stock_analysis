# -*- coding: utf-8 -*-
"""
自定义 Webhook 发送提醒服务

职责：
1. 发送自定义 Webhook 消息
"""
import logging
import json
import time
from string import Template
from typing import Any, Dict, List, Optional, Tuple

import requests

from src.config import Config
from src.formatters import chunk_content_by_max_bytes, slice_at_max_bytes


logger = logging.getLogger(__name__)


class CustomWebhookSender:

    def __init__(self, config: Config):
        """
        初始化自定义 Webhook 配置

        Args:
            config: 配置对象
        """
        self._custom_webhook_urls = getattr(config, 'custom_webhook_urls', []) or []
        self._custom_webhook_bearer_token = getattr(config, 'custom_webhook_bearer_token', None)
        self._custom_webhook_body_template = getattr(config, 'custom_webhook_body_template', None)
        self._webhook_verify_ssl = getattr(config, 'webhook_verify_ssl', True)
 
    def send_to_custom(self, content: str) -> bool:
        """
        推送消息到自定义 Webhook
        
        支持任意接受 POST JSON 的 Webhook 端点
        默认发送格式：{"text": "消息内容", "content": "消息内容"}
        
        适用于：
        - 钉钉机器人
        - Discord Webhook
        - Slack Incoming Webhook
        - 自建通知服务
        - 其他支持 POST JSON 的服务
        
        Args:
            content: 消息内容（Markdown 格式）
            
        Returns:
            是否至少有一个 Webhook 发送成功
        """
        if not self._custom_webhook_urls:
            logger.warning("未配置自定义 Webhook，跳过推送")
            return False
        
        success_count = 0
        
        for i, url in enumerate(self._custom_webhook_urls):
            try:
                # 通用 JSON 格式，兼容大多数 Webhook
                # 钉钉格式: {"msgtype": "text", "text": {"content": "xxx"}}
                # Slack 格式: {"text": "xxx"}
                # Discord 格式: {"content": "xxx"}
                
                # 钉钉机器人对 body 有字节上限（约 20000 bytes），超长需要分批发送
                if self._is_dingtalk_webhook(url):
                    templated_payload = self._build_custom_webhook_template_payload(content)
                    if templated_payload is not None:
                        if self._post_custom_webhook(url, templated_payload, timeout=30):
                            logger.info(f"自定义 Webhook {i+1}（钉钉模板）推送成功")
                            success_count += 1
                        elif self._send_dingtalk_chunked(url, content, max_bytes=20000):
                            logger.info(f"自定义 Webhook {i+1}（钉钉模板失败，回退分批）推送成功")
                            success_count += 1
                        else:
                            logger.error(f"自定义 Webhook {i+1}（钉钉模板）推送失败")
                    elif self._send_dingtalk_chunked(url, content, max_bytes=20000):
                        logger.info(f"自定义 Webhook {i+1}（钉钉）推送成功")
                        success_count += 1
                    else:
                        logger.error(f"自定义 Webhook {i+1}（钉钉）推送失败")
                    continue

                # 其他 Webhook：单次发送
                payload = self._build_custom_webhook_payload(url, content)
                if self._post_custom_webhook(url, payload, timeout=30):
                    logger.info(f"自定义 Webhook {i+1} 推送成功")
                    success_count += 1
                else:
                    logger.error(f"自定义 Webhook {i+1} 推送失败")
                    
            except Exception as e:
                logger.error(f"自定义 Webhook {i+1} 推送异常: {e}")
        
        logger.info(f"自定义 Webhook 推送完成：成功 {success_count}/{len(self._custom_webhook_urls)}")
        return success_count > 0

    
    def _send_custom_webhook_image(
        self, image_bytes: bytes, fallback_content: str = ""
    ) -> bool:
        """Send image to Custom Webhooks; Discord supports file attachment (Issue #289)."""
        if not self._custom_webhook_urls:
            return False
        success_count = 0
        for i, url in enumerate(self._custom_webhook_urls):
            try:
                if self._is_discord_webhook(url):
                    files = {"file": ("report.png", image_bytes, "image/png")}
                    data = {"content": "📈 股票智能分析报告"}
                    headers = {"User-Agent": "StockAnalysis/1.0"}
                    if self._custom_webhook_bearer_token:
                        headers["Authorization"] = (
                            f"Bearer {self._custom_webhook_bearer_token}"
                        )
                    response = requests.post(
                        url, data=data, files=files, headers=headers, timeout=30,
                        verify=self._webhook_verify_ssl
                    )
                    if response.status_code in (200, 204):
                        logger.info("自定义 Webhook %d（Discord 图片）推送成功", i + 1)
                        success_count += 1
                    else:
                        logger.error(
                            "自定义 Webhook %d（Discord 图片）推送失败: HTTP %s",
                            i + 1, response.status_code,
                        )
                else:
                    if fallback_content:
                        payload = self._build_custom_webhook_payload(url, fallback_content)
                        if self._post_custom_webhook(url, payload, timeout=30):
                            logger.info(
                                "自定义 Webhook %d（图片不支持，回退文本）推送成功", i + 1
                            )
                            success_count += 1
                    else:
                        logger.warning(
                            "自定义 Webhook %d 不支持图片，且无回退内容，跳过", i + 1
                        )
            except Exception as e:
                logger.error("自定义 Webhook %d 图片推送异常: %s", i + 1, e)
        return success_count > 0

    def _post_custom_webhook(self, url: str, payload: dict, timeout: int = 30) -> bool:
        headers = {
            'Content-Type': 'application/json; charset=utf-8',
            'User-Agent': 'StockAnalysis/1.0',
        }
        # 支持 Bearer Token 认证（#51）
        if self._custom_webhook_bearer_token:
            headers['Authorization'] = f'Bearer {self._custom_webhook_bearer_token}'
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        response = requests.post(url, data=body, headers=headers, timeout=timeout, verify=self._webhook_verify_ssl)
        if response.status_code == 200:
            return True
        logger.error(f"自定义 Webhook 推送失败: HTTP {response.status_code}")
        logger.debug(f"响应内容: {response.text[:200]}")
        return False

    def test_custom_webhooks(self, content: str, *, timeout_seconds: float = 20.0) -> List[Dict[str, Any]]:
        """Send a test message to each custom webhook and return raw per-URL attempts."""
        attempts: List[Dict[str, Any]] = []
        for index, url in enumerate(self._custom_webhook_urls):
            try:
                payload = self._build_custom_webhook_payload(url, content)
                attempts.append(
                    self._post_custom_webhook_attempt(
                        url=url,
                        payload=payload,
                        timeout_seconds=timeout_seconds,
                        index=index,
                    )
                )
            except Exception as exc:
                attempts.append({
                    "channel": "custom",
                    "success": False,
                    "message": f"自定义 Webhook {index + 1} 测试异常: {exc}",
                    "target": url,
                    "error_code": self._classify_custom_webhook_exception(exc)[0],
                    "stage": "notification_send",
                    "retryable": self._classify_custom_webhook_exception(exc)[1],
                    "latency_ms": None,
                    "http_status": None,
                })
        return attempts

    def _post_custom_webhook_attempt(
        self,
        *,
        url: str,
        payload: dict,
        timeout_seconds: float,
        index: int,
    ) -> Dict[str, Any]:
        headers = {
            'Content-Type': 'application/json; charset=utf-8',
            'User-Agent': 'StockAnalysis/1.0',
        }
        if self._custom_webhook_bearer_token:
            headers['Authorization'] = f'Bearer {self._custom_webhook_bearer_token}'

        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        started_at = time.perf_counter()
        try:
            response = requests.post(
                url,
                data=body,
                headers=headers,
                timeout=timeout_seconds,
                verify=self._webhook_verify_ssl,
            )
        except Exception as exc:
            error_code, retryable = self._classify_custom_webhook_exception(exc)
            return {
                "channel": "custom",
                "success": False,
                "message": f"自定义 Webhook {index + 1} 测试失败: {exc}",
                "target": url,
                "error_code": error_code,
                "stage": "notification_send",
                "retryable": retryable,
                "latency_ms": int((time.perf_counter() - started_at) * 1000),
                "http_status": None,
            }

        latency_ms = int((time.perf_counter() - started_at) * 1000)
        if response.status_code == 200:
            return {
                "channel": "custom",
                "success": True,
                "message": f"自定义 Webhook {index + 1} 测试发送成功",
                "target": url,
                "error_code": None,
                "stage": "notification_send",
                "retryable": False,
                "latency_ms": latency_ms,
                "http_status": response.status_code,
            }

        retryable = response.status_code == 429 or response.status_code >= 500
        return {
            "channel": "custom",
            "success": False,
            "message": f"自定义 Webhook {index + 1} 测试失败: HTTP {response.status_code}",
            "target": url,
            "error_code": "http_error",
            "stage": "notification_send",
            "retryable": retryable,
            "latency_ms": latency_ms,
            "http_status": response.status_code,
        }

    @staticmethod
    def _classify_custom_webhook_exception(exc: Exception) -> Tuple[str, bool]:
        if isinstance(exc, requests.exceptions.Timeout):
            return "timeout", True
        if isinstance(exc, requests.exceptions.ConnectionError):
            return "network_error", True
        if isinstance(exc, requests.exceptions.RequestException):
            return "network_error", True
        return "unexpected_error", False
    
    def _build_custom_webhook_payload(self, url: str, content: str) -> dict:
        """
        根据 URL 构建对应的 Webhook payload
        
        自动识别常见服务并使用对应格式
        """
        templated_payload = self._build_custom_webhook_template_payload(content)
        if templated_payload is not None:
            return templated_payload

        url_lower = url.lower()
        
        # 钉钉机器人
        if 'dingtalk' in url_lower or 'oapi.dingtalk.com' in url_lower:
            return {
                "msgtype": "markdown",
                "markdown": {
                    "title": "股票分析报告",
                    "text": content
                }
            }
        
        # Discord Webhook
        if 'discord.com/api/webhooks' in url_lower or 'discordapp.com/api/webhooks' in url_lower:
            # Discord 限制 2000 字符
            truncated = content[:1900] + "..." if len(content) > 1900 else content
            return {
                "content": truncated
            }
        
        # Slack Incoming Webhook
        if 'hooks.slack.com' in url_lower:
            return {
                "text": content,
                "mrkdwn": True
            }
        
        # Bark (iOS 推送)
        if 'api.day.app' in url_lower:
            return {
                "title": "股票分析报告",
                "body": content[:4000],  # Bark 限制
                "group": "stock"
            }
        
        # 通用格式（兼容大多数服务）
        return {
            "text": content,
            "content": content,
            "message": content,
            "body": content
        }

    def _build_custom_webhook_template_payload(self, content: str) -> Optional[dict]:
        """Build payload from CUSTOM_WEBHOOK_BODY_TEMPLATE when configured."""
        template = (self._custom_webhook_body_template or "").strip()
        if not template:
            return None

        title = "股票分析报告"
        variables = {
            "title": title,
            "title_json": json.dumps(title, ensure_ascii=False),
            "content": content,
            "content_json": json.dumps(content, ensure_ascii=False),
        }
        rendered = Template(template).safe_substitute(variables)
        try:
            payload: Any = json.loads(rendered)
        except json.JSONDecodeError as exc:
            logger.error(
                "CUSTOM_WEBHOOK_BODY_TEMPLATE 不是有效 JSON，已回退为默认 Webhook payload: %s",
                exc,
            )
            return None
        if not isinstance(payload, dict):
            logger.error(
                "CUSTOM_WEBHOOK_BODY_TEMPLATE 必须渲染为 JSON object，已回退为默认 Webhook payload"
            )
            return None
        return payload
    
    def _send_dingtalk_chunked(self, url: str, content: str, max_bytes: int = 20000) -> bool:
        import time as _time

        # 为 payload 开销预留空间，避免 body 超限
        budget = max(1000, max_bytes - 1500)
        chunks = chunk_content_by_max_bytes(content, budget)
        if not chunks:
            return False

        total = len(chunks)
        ok = 0

        for idx, chunk in enumerate(chunks):
            marker = f"\n\n📄 *({idx+1}/{total})*" if total > 1 else ""
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": "股票分析报告",
                    "text": chunk + marker,
                },
            }

            # 如果仍超限（极端情况下），再按字节硬截断一次
            body_bytes = len(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
            if body_bytes > max_bytes:
                hard_budget = max(200, budget - (body_bytes - max_bytes) - 200)
                payload["markdown"]["text"], _ = slice_at_max_bytes(payload["markdown"]["text"], hard_budget)

            if self._post_custom_webhook(url, payload, timeout=30):
                ok += 1
            else:
                logger.error(f"钉钉分批发送失败: 第 {idx+1}/{total} 批")

            if idx < total - 1:
                _time.sleep(1)

        return ok == total

    
    @staticmethod
    def _is_dingtalk_webhook(url: str) -> bool:
        url_lower = (url or "").lower()
        return 'dingtalk' in url_lower or 'oapi.dingtalk.com' in url_lower

    @staticmethod
    def _is_discord_webhook(url: str) -> bool:
        url_lower = (url or "").lower()
        return (
            'discord.com/api/webhooks' in url_lower
            or 'discordapp.com/api/webhooks' in url_lower
        )
