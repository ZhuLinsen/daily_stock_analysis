# -*- coding: utf-8 -*-
import time
import hmac
import hashlib
import base64
import urllib.parse
import requests
import logging
from typing import Optional

from src.config import Config

logger = logging.getLogger(__name__)

class DingtalkSender:
    def __init__(self, config: Config):
        self.webhook_url = config.dingtalk_webhook_url
        self.secret = config.dingtalk_secret

    def send_to_dingtalk(self, content: str, title: str = "", timeout_seconds: int = 10) -> bool:
        """发送 Markdown 消息到钉钉群"""
        if not self.webhook_url:
            return False

        # 1. 签名逻辑 (Security Signature)
        if self.secret:
            timestamp = str(round(time.time() * 1000))
            secret_enc = self.secret.encode('utf-8')
            string_to_sign = f'{timestamp}\n{self.secret}'
            string_to_sign_enc = string_to_sign.encode('utf-8')
            hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
            sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
            
            if "?" in self.webhook_url:
                url = f"{self.webhook_url}&timestamp={timestamp}&sign={sign}"
            else:
                url = f"{self.webhook_url}?timestamp={timestamp}&sign={sign}"
        else:
            url = self.webhook_url

        # 2. 组装 Payload
        # DingTalk requires the title in the markdown text body for it to display nicely
        text = f"### {title}\n\n{content}" if title else content
        
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title or "通知 (Notification)",
                "text": text
            }
        }
        headers = {'Content-Type': 'application/json'}

        # 3. 发送请求
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=timeout_seconds)
            response.raise_for_status()
            
            result = response.json()
            if result.get("errcode") == 0:
                logger.info("钉钉消息发送成功 (DingTalk message sent successfully)")
                return True
            else:
                logger.error(f"钉钉消息发送失败 (DingTalk API error): {result}")
                return False
        except Exception as e:
            logger.error(f"发送钉钉消息异常 (Failed to send DingTalk notification): {e}")
            return False