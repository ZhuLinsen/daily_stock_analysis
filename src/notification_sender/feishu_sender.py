# -*- coding: utf-8 -*-
"""
飞书 发送提醒服务

职责：
1. 通过 webhook 发送飞书消息
"""
import logging
from typing import Dict, Any
import requests
import time

from src.config import Config
from src.formatters import format_feishu_markdown, chunk_content_by_max_bytes


logger = logging.getLogger(__name__)


class FeishuSender:
    
    def __init__(self, config: Config):
        """
        初始化飞书配置

        Args:
            config: 配置对象
        """
        self._feishu_url = getattr(config, 'feishu_webhook_url', None)
        self._feishu_max_bytes = getattr(config, 'feishu_max_bytes', 20000)
        self._webhook_verify_ssl = getattr(config, 'webhook_verify_ssl', True)
    
          
    def send_to_feishu(self, content: str) -> bool:
        """
        推送消息到飞书机器人
        
        飞书自定义机器人 Webhook 消息格式：
        {
            "msg_type": "text",
            "content": {
                "text": "文本内容"
            }
        }
        
        说明：飞书文本消息不会渲染 Markdown，需使用交互卡片（lark_md）格式
        
        注意：飞书文本消息限制约 20KB，超长内容会自动分批发送
        可通过环境变量 FEISHU_MAX_BYTES 调整限制值
        
        Args:
            content: 消息内容（Markdown 会转为纯文本）
            
        Returns:
            是否发送成功
        """
        if not self._feishu_url:
            logger.warning("飞书 Webhook 未配置，跳过推送")
            return False
        
        # 飞书 lark_md 支持有限，先做格式转换
        formatted_content = format_feishu_markdown(content)

        max_bytes = self._feishu_max_bytes  # 从配置读取，默认 20000 字节
        
        # 检查字节长度，超长则分批发送
        content_bytes = len(formatted_content.encode('utf-8'))
        if content_bytes > max_bytes:
            logger.info(f"飞书消息内容超长({content_bytes}字节/{len(content)}字符)，将分批发送")
            return self._send_feishu_chunked(formatted_content, max_bytes)
        
        try:
            return self._send_feishu_message(formatted_content)
        except Exception as e:
            logger.error(f"发送飞书消息失败: {e}")
            return False
   
    def _send_feishu_chunked(self, content: str, max_bytes: int) -> bool:
        """
        分批发送长消息到飞书
        
        按股票分析块（以 --- 或 ### 分隔）智能分割，确保每批不超过限制
        
        Args:
            content: 完整消息内容
            max_bytes: 单条消息最大字节数
            
        Returns:
            是否全部发送成功
        """
        chunks = chunk_content_by_max_bytes(content, max_bytes, add_page_marker=True)
        
        # 分批发送
        total_chunks = len(chunks)
        success_count = 0
        
        logger.info(f"飞书分批发送：共 {total_chunks} 批")
        
        for i, chunk in enumerate(chunks):
            try:
                if self._send_feishu_message(chunk):
                    success_count += 1
                    logger.info(f"飞书第 {i+1}/{total_chunks} 批发送成功")
                else:
                    logger.error(f"飞书第 {i+1}/{total_chunks} 批发送失败")
            except Exception as e:
                logger.error(f"飞书第 {i+1}/{total_chunks} 批发送异常: {e}")
            
            # 批次间隔，避免触发频率限制
            if i < total_chunks - 1:
                time.sleep(1)
        
        return success_count == total_chunks
    
    def _send_feishu_message(self, content: str) -> bool:
        """发送单条飞书消息（优先使用 Markdown 卡片）"""
        def _post_payload(payload: Dict[str, Any]) -> bool:
            logger.debug(f"飞书请求 URL: {self._feishu_url}")
            logger.debug(f"飞书请求 payload 长度: {len(content)} 字符")

            response = requests.post(
                self._feishu_url,
                json=payload,
                timeout=30,
                verify=self._webhook_verify_ssl
            )

            logger.debug(f"飞书响应状态码: {response.status_code}")
            logger.debug(f"飞书响应内容: {response.text}")

            if response.status_code == 200:
                result = response.json()
                code = result.get('code') if 'code' in result else result.get('StatusCode')
                if code == 0:
                    logger.info("飞书消息发送成功")
                    return True
                else:
                    error_msg = result.get('msg') or result.get('StatusMessage', '未知错误')
                    error_code = result.get('code') or result.get('StatusCode', 'N/A')
                    logger.error(f"飞书返回错误 [code={error_code}]: {error_msg}")
                    logger.error(f"完整响应: {result}")
                    return False
            else:
                logger.error(f"飞书请求失败: HTTP {response.status_code}")
                logger.error(f"响应内容: {response.text}")
                return False

        # 1) 优先使用交互卡片（支持 Markdown 渲染）
        card_payload = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": "A股智能分析报告"
                    }
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": content
                        }
                    }
                ]
            }
        }

        if _post_payload(card_payload):
            return True

        # 2) 回退为普通文本消息
        text_payload = {
            "msg_type": "text",
            "content": {
                "text": content
            }
        }

        return _post_payload(text_payload)
