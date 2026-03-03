# -*- coding: utf-8 -*-
"""
===================================
A股自选股智能分析系统 - 通知层
===================================

职责：
1. 汇总分析结果生成日报
2. 支持 Markdown 格式输出
3. 多渠道推送（自动识别）：
   - 企业微信 Webhook
   - 飞书 Webhook
   - Telegram Bot
   - 邮件 SMTP
   - Pushover（手机/桌面推送）
"""
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from enum import Enum

from src.config import get_config
from src.analyzer import AnalysisResult
from bot.models import BotMessage
from src.notification_sender import (
    AstrbotSender,
    CustomWebhookSender,
    DiscordSender,
    EmailSender,
    FeishuSender,
    PushoverSender,
    PushplusSender,
    Serverchan3Sender,
    TelegramSender,
    WechatSender,
    WECHAT_IMAGE_MAX_BYTES
)

logger = logging.getLogger(__name__)


class NotificationChannel(Enum):
    """通知渠道类型"""
    WECHAT = "wechat"      # 企业微信
    FEISHU = "feishu"      # 飞书
    TELEGRAM = "telegram"  # Telegram
    EMAIL = "email"        # 邮件
    PUSHOVER = "pushover"  # Pushover（手机/桌面推送）
    PUSHPLUS = "pushplus"  # PushPlus（国内推送服务）
    SERVERCHAN3 = "serverchan3"  # Server酱3（手机APP推送服务）
    CUSTOM = "custom"      # 自定义 Webhook
    DISCORD = "discord"    # Discord 机器人 (Bot)
    ASTRBOT = "astrbot"
    UNKNOWN = "unknown"    # 未知


class ChannelDetector:
    """
    渠道检测器 - 简化版
    
    根据配置直接判断渠道类型（不再需要 URL 解析）
    """
    
    @staticmethod
    def get_channel_name(channel: NotificationChannel) -> str:
        """获取渠道中文名称"""
        names = {
            NotificationChannel.WECHAT: "企业微信",
            NotificationChannel.FEISHU: "飞书",
            NotificationChannel.TELEGRAM: "Telegram",
            NotificationChannel.EMAIL: "邮件",
            NotificationChannel.PUSHOVER: "Pushover",
            NotificationChannel.PUSHPLUS: "PushPlus",
            NotificationChannel.SERVERCHAN3: "Server酱3",
            NotificationChannel.CUSTOM: "自定义Webhook",
            NotificationChannel.DISCORD: "Discord机器人",
            NotificationChannel.ASTRBOT: "ASTRBOT机器人",
            NotificationChannel.UNKNOWN: "未知渠道",
        }
        return names.get(channel, "未知渠道")


class NotificationService(
    AstrbotSender,
    CustomWebhookSender,
    DiscordSender,
    EmailSender,
    FeishuSender,
    PushoverSender,
    PushplusSender,
    Serverchan3Sender,
    TelegramSender,
    WechatSender
):
    """
    通知服务
    
    职责：
    1. 生成 Markdown 格式的分析日报
    2. 向所有已配置的渠道推送消息（多渠道并发）
    3. 支持本地保存日报
    
    支持的渠道：
    - 企业微信 Webhook
    - 飞书 Webhook
    - Telegram Bot
    - 邮件 SMTP
    - Pushover（手机/桌面推送）
    
    注意：所有已配置的渠道都会收到推送
    """
    
    def __init__(self, source_message: Optional[BotMessage] = None):
        """
        初始化通知服务
        
        检测所有已配置的渠道，推送时会向所有渠道发送
        """
        config = get_config()
        self._source_message = source_message
        self._context_channels: List[str] = []

        # Markdown 转图片（Issue #289）
        self._markdown_to_image_channels = set(
            getattr(config, 'markdown_to_image_channels', []) or []
        )
        self._markdown_to_image_max_chars = getattr(
            config, 'markdown_to_image_max_chars', 15000
        )

        # 仅分析结果摘要（Issue #262）：true 时只推送汇总，不含个股详情
        self._report_summary_only = getattr(config, 'report_summary_only', False)

        # 初始化各渠道
        AstrbotSender.__init__(self, config)
        CustomWebhookSender.__init__(self, config)
        DiscordSender.__init__(self, config)
        EmailSender.__init__(self, config)
        FeishuSender.__init__(self, config)
        PushoverSender.__init__(self, config)
        PushplusSender.__init__(self, config)
        Serverchan3Sender.__init__(self, config)
        TelegramSender.__init__(self, config)
        WechatSender.__init__(self, config)
        
        # 检测所有已配置的渠道
        self._available_channels = self._detect_all_channels()
        if self._has_context_channel():
            self._context_channels.append("钉钉会话")
        
        if not self._available_channels and not self._context_channels:
            logger.warning("未配置有效的通知渠道，将不发送推送通知")
        else:
            channel_names = [ChannelDetector.get_channel_name(ch) for ch in self._available_channels]
            channel_names.extend(self._context_channels)
            logger.info(f"已配置 {len(channel_names)} 个通知渠道：{', '.join(channel_names)}")
    
    def _detect_all_channels(self) -> List[NotificationChannel]:
        """
        检测所有已配置的渠道
        
        Returns:
            已配置的渠道列表
        """
        channels = []
        
        # 企业微信
        if self._wechat_url:
            channels.append(NotificationChannel.WECHAT)
        
        # 飞书
        if self._feishu_url:
            channels.append(NotificationChannel.FEISHU)
        
        # Telegram
        if self._is_telegram_configured():
            channels.append(NotificationChannel.TELEGRAM)
        
        # 邮件
        if self._is_email_configured():
            channels.append(NotificationChannel.EMAIL)
        
        # Pushover
        if self._is_pushover_configured():
            channels.append(NotificationChannel.PUSHOVER)

        # PushPlus
        if self._pushplus_token:
            channels.append(NotificationChannel.PUSHPLUS)

       # Server酱3
        if self._serverchan3_sendkey:
            channels.append(NotificationChannel.SERVERCHAN3)
       
        # 自定义 Webhook
        if self._custom_webhook_urls:
            channels.append(NotificationChannel.CUSTOM)
        
        # Discord
        if self._is_discord_configured():
            channels.append(NotificationChannel.DISCORD)
        # AstrBot
        if self._is_astrbot_configured():
            channels.append(NotificationChannel.ASTRBOT)
        return channels

    def is_available(self) -> bool:
        """检查通知服务是否可用（至少有一个渠道或上下文渠道）"""
        return len(self._available_channels) > 0 or self._has_context_channel()
    
    def get_available_channels(self) -> List[NotificationChannel]:
        """获取所有已配置的渠道"""
        return self._available_channels
    
    def get_channel_names(self) -> str:
        """获取所有已配置渠道的名称"""
        names = [ChannelDetector.get_channel_name(ch) for ch in self._available_channels]
        if self._has_context_channel():
            names.append("钉钉会话")
        return ', '.join(names)

    # ===== Context channel =====
    def _has_context_channel(self) -> bool:
        """判断是否存在基于消息上下文的临时渠道（如钉钉会话、飞书会话）"""
        return (
            self._extract_dingtalk_session_webhook() is not None
            or self._extract_feishu_reply_info() is not None
        )

    def _extract_dingtalk_session_webhook(self) -> Optional[str]:
        """从来源消息中提取钉钉会话 Webhook（用于 Stream 模式回复）"""
        if not isinstance(self._source_message, BotMessage):
            return None
        raw_data = getattr(self._source_message, "raw_data", {}) or {}
        if not isinstance(raw_data, dict):
            return None
        session_webhook = (
            raw_data.get("_session_webhook")
            or raw_data.get("sessionWebhook")
            or raw_data.get("session_webhook")
            or raw_data.get("session_webhook_url")
        )
        if not session_webhook and isinstance(raw_data.get("headers"), dict):
            session_webhook = raw_data["headers"].get("sessionWebhook")
        return session_webhook

    def _extract_feishu_reply_info(self) -> Optional[Dict[str, str]]:
        """
        从来源消息中提取飞书回复信息（用于 Stream 模式回复）
        
        Returns:
            包含 chat_id 的字典，或 None
        """
        if not isinstance(self._source_message, BotMessage):
            return None
        if getattr(self._source_message, "platform", "") != "feishu":
            return None
        chat_id = getattr(self._source_message, "chat_id", "")
        if not chat_id:
            return None
        return {"chat_id": chat_id}

    def send_to_context(self, content: str) -> bool:
        """
        向基于消息上下文的渠道发送消息（例如钉钉 Stream 会话）
        
        Args:
            content: Markdown 格式内容
        """
        return self._send_via_source_context(content)
    
    def _send_via_source_context(self, content: str) -> bool:
        """
        使用消息上下文（如钉钉/飞书会话）发送一份报告
        
        主要用于从机器人 Stream 模式触发的任务，确保结果能回到触发的会话。
        """
        success = False
        
        # 尝试钉钉会话
        session_webhook = self._extract_dingtalk_session_webhook()
        if session_webhook:
            try:
                if self._send_dingtalk_chunked(session_webhook, content, max_bytes=20000):
                    logger.info("已通过钉钉会话（Stream）推送报告")
                    success = True
                else:
                    logger.error("钉钉会话（Stream）推送失败")
            except Exception as e:
                logger.error(f"钉钉会话（Stream）推送异常: {e}")

        # 尝试飞书会话
        feishu_info = self._extract_feishu_reply_info()
        if feishu_info:
            try:
                if self._send_feishu_stream_reply(feishu_info["chat_id"], content):
                    logger.info("已通过飞书会话（Stream）推送报告")
                    success = True
                else:
                    logger.error("飞书会话（Stream）推送失败")
            except Exception as e:
                logger.error(f"飞书会话（Stream）推送异常: {e}")

        return success

    def _send_feishu_stream_reply(self, chat_id: str, content: str) -> bool:
        """
        通过飞书 Stream 模式发送消息到指定会话
        
        Args:
            chat_id: 飞书会话 ID
            content: 消息内容
            
        Returns:
            是否发送成功
        """
        try:
            from bot.platforms.feishu_stream import FeishuReplyClient, FEISHU_SDK_AVAILABLE
            if not FEISHU_SDK_AVAILABLE:
                logger.warning("飞书 SDK 不可用，无法发送 Stream 回复")
                return False
            
            from src.config import get_config
            config = get_config()
            
            app_id = getattr(config, 'feishu_app_id', None)
            app_secret = getattr(config, 'feishu_app_secret', None)
            
            if not app_id or not app_secret:
                logger.warning("飞书 APP_ID 或 APP_SECRET 未配置")
                return False
            
            # 创建回复客户端
            reply_client = FeishuReplyClient(app_id, app_secret)
            
            # 飞书文本消息有长度限制，需要分批发送
            max_bytes = getattr(config, 'feishu_max_bytes', 20000)
            content_bytes = len(content.encode('utf-8'))
            
            if content_bytes > max_bytes:
                return self._send_feishu_stream_chunked(reply_client, chat_id, content, max_bytes)
            
            return reply_client.send_to_chat(chat_id, content)
            
        except ImportError as e:
            logger.error(f"导入飞书 Stream 模块失败: {e}")
            return False
        except Exception as e:
            logger.error(f"飞书 Stream 回复异常: {e}")
            return False

    def _send_feishu_stream_chunked(
        self, 
        reply_client, 
        chat_id: str, 
        content: str, 
        max_bytes: int
    ) -> bool:
        """
        分批发送长消息到飞书（Stream 模式）
        
        Args:
            reply_client: FeishuReplyClient 实例
            chat_id: 飞书会话 ID
            content: 完整消息内容
            max_bytes: 单条消息最大字节数
            
        Returns:
            是否全部发送成功
        """
        import time
        
        def get_bytes(s: str) -> int:
            return len(s.encode('utf-8'))
        
        # 按段落或分隔线分割
        if "\n---\n" in content:
            sections = content.split("\n---\n")
            separator = "\n---\n"
        elif "\n### " in content:
            parts = content.split("\n### ")
            sections = [parts[0]] + [f"### {p}" for p in parts[1:]]
            separator = "\n"
        else:
            # 按行分割
            sections = content.split("\n")
            separator = "\n"
        
        chunks = []
        current_chunk = []
        current_bytes = 0
        separator_bytes = get_bytes(separator)
        
        for section in sections:
            section_bytes = get_bytes(section) + separator_bytes
            
            if current_bytes + section_bytes > max_bytes:
                if current_chunk:
                    chunks.append(separator.join(current_chunk))
                current_chunk = [section]
                current_bytes = section_bytes
            else:
                current_chunk.append(section)
                current_bytes += section_bytes
        
        if current_chunk:
            chunks.append(separator.join(current_chunk))
        
        # 发送每个分块
        success = True
        for i, chunk in enumerate(chunks):
            if i > 0:
                time.sleep(0.5)  # 避免请求过快
            
            if not reply_client.send_to_chat(chat_id, chunk):
                success = False
                logger.error(f"飞书 Stream 分块 {i+1}/{len(chunks)} 发送失败")
        
        return success
        
    def generate_daily_report(
        self,
        results: List[AnalysisResult],
        report_date: Optional[str] = None
    ) -> str:
        """
        生成 Markdown 格式的日报（详细版）

        Args:
            results: 分析结果列表
            report_date: 报告日期（默认今天）

        Returns:
            Markdown 格式的日报内容
        """
        if report_date is None:
            report_date = datetime.now().strftime('%Y-%m-%d')

        # 标题
        report_lines = [
            f"# 📅 {report_date} 股票智能分析报告",
            "",
            f"> 共分析 **{len(results)}** 只股票 | 报告生成时间：{datetime.now().strftime('%H:%M:%S')}",
            "",
            "---",
            "",
        ]
        
        # 按评分排序（高分在前）
        sorted_results = sorted(
            results, 
            key=lambda x: x.sentiment_score, 
            reverse=True
        )
        
        # 统计信息 - 使用 decision_type 字段准确统计
        buy_count = sum(1 for r in results if getattr(r, 'decision_type', '') == 'buy')
        sell_count = sum(1 for r in results if getattr(r, 'decision_type', '') == 'sell')
        hold_count = sum(1 for r in results if getattr(r, 'decision_type', '') in ('hold', ''))
        avg_score = sum(r.sentiment_score for r in results) / len(results) if results else 0
        
        report_lines.extend([
            "## 📊 操作建议汇总",
            "",
            "| 指标 | 数值 |",
            "|------|------|",
            f"| 🟢 建议买入/加仓 | **{buy_count}** 只 |",
            f"| 🟡 建议持有/观望 | **{hold_count}** 只 |",
            f"| 🔴 建议减仓/卖出 | **{sell_count}** 只 |",
            f"| 📈 平均看多评分 | **{avg_score:.1f}** 分 |",
            "",
            "---",
            "",
        ])
        
        # Issue #262: summary_only 时仅输出摘要，跳过个股详情
        if self._report_summary_only:
            report_lines.extend(["## 📊 分析结果摘要", ""])
            for r in sorted_results:
                emoji = r.get_emoji()
                report_lines.append(
                    f"{emoji} **{r.name}({r.code})**: {r.operation_advice} | "
                    f"评分 {r.sentiment_score} | {r.trend_prediction}"
                )
        else:
            report_lines.extend(["## 📈 个股详细分析", ""])
            # 逐个股票的详细分析
            for result in sorted_results:
                emoji = result.get_emoji()
                confidence_stars = result.get_confidence_stars() if hasattr(result, 'get_confidence_stars') else '⭐⭐'
                
                report_lines.extend([
                    f"### {emoji} {result.name} ({result.code})",
                    "",
                    f"**操作建议：{result.operation_advice}** | **综合评分：{result.sentiment_score}分** | **趋势预测：{result.trend_prediction}** | **置信度：{confidence_stars}**",
                    "",
                ])

                self._append_market_snapshot(report_lines, result)
                
                # 核心看点
                if hasattr(result, 'key_points') and result.key_points:
                    report_lines.extend([
                        f"**🎯 核心看点**：{result.key_points}",
                        "",
                    ])
                
                # 买入/卖出理由
                if hasattr(result, 'buy_reason') and result.buy_reason:
                    report_lines.extend([
                        f"**💡 操作理由**：{result.buy_reason}",
                        "",
                    ])
                
                # 走势分析
                if hasattr(result, 'trend_analysis') and result.trend_analysis:
                    report_lines.extend([
                        "#### 📉 走势分析",
                        f"{result.trend_analysis}",
                        "",
                    ])
                
                # 短期/中期展望
                outlook_lines = []
                if hasattr(result, 'short_term_outlook') and result.short_term_outlook:
                    outlook_lines.append(f"- **短期（1-3日）**：{result.short_term_outlook}")
                if hasattr(result, 'medium_term_outlook') and result.medium_term_outlook:
                    outlook_lines.append(f"- **中期（1-2周）**：{result.medium_term_outlook}")
                if outlook_lines:
                    report_lines.extend([
                        "#### 🔮 市场展望",
                        *outlook_lines,
                        "",
                    ])
                
                # 技术面分析
                tech_lines = []
                if result.technical_analysis:
                    tech_lines.append(f"**综合**：{result.technical_analysis}")
                if hasattr(result, 'ma_analysis') and result.ma_analysis:
                    tech_lines.append(f"**均线**：{result.ma_analysis}")
                if hasattr(result, 'volume_analysis') and result.volume_analysis:
                    tech_lines.append(f"**量能**：{result.volume_analysis}")
                if hasattr(result, 'pattern_analysis') and result.pattern_analysis:
                    tech_lines.append(f"**形态**：{result.pattern_analysis}")
                if tech_lines:
                    report_lines.extend([
                        "#### 📊 技术面分析",
                        *tech_lines,
                        "",
                    ])
                
                # 基本面分析
                fund_lines = []
                if hasattr(result, 'fundamental_analysis') and result.fundamental_analysis:
                    fund_lines.append(result.fundamental_analysis)
                if hasattr(result, 'sector_position') and result.sector_position:
                    fund_lines.append(f"**板块地位**：{result.sector_position}")
                if hasattr(result, 'company_highlights') and result.company_highlights:
                    fund_lines.append(f"**公司亮点**：{result.company_highlights}")
                if fund_lines:
                    report_lines.extend([
                        "#### 🏢 基本面分析",
                        *fund_lines,
                        "",
                    ])
                
                # 消息面/情绪面
                news_lines = []
                if result.news_summary:
                    news_lines.append(f"**新闻摘要**：{result.news_summary}")
                if hasattr(result, 'market_sentiment') and result.market_sentiment:
                    news_lines.append(f"**市场情绪**：{result.market_sentiment}")
                if hasattr(result, 'hot_topics') and result.hot_topics:
                    news_lines.append(f"**相关热点**：{result.hot_topics}")
                if news_lines:
                    report_lines.extend([
                        "#### 📰 消息面/情绪面",
                        *news_lines,
                        "",
                    ])
                
                # 综合分析
                if result.analysis_summary:
                    report_lines.extend([
                        "#### 📝 综合分析",
                        result.analysis_summary,
                        "",
                    ])
                
                # 风险提示
                if hasattr(result, 'risk_warning') and result.risk_warning:
                    report_lines.extend([
                        f"⚠️ **风险提示**：{result.risk_warning}",
                        "",
                    ])
                
                # 数据来源说明
                if hasattr(result, 'search_performed') and result.search_performed:
                    report_lines.append("*🔍 已执行联网搜索*")
                if hasattr(result, 'data_sources') and result.data_sources:
                    report_lines.append(f"*📋 数据来源：{result.data_sources}*")
                
                # 错误信息（如果有）
                if not result.success and result.error_message:
                    report_lines.extend([
                        "",
                        f"❌ **分析异常**：{result.error_message[:100]}",
                    ])
                
                report_lines.extend([
                    "",
                    "---",
                    "",
                ])
        
        # 底部信息（去除免责声明）
        report_lines.extend([
            "",
            f"*报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        ])
        
        return "\n".join(report_lines)
    
    @staticmethod
    def _escape_md(name: str) -> str:
        """Escape markdown special characters in stock names (e.g. *ST → \\*ST)."""
        return name.replace('*', r'\*') if name else name

    @staticmethod
    def _clean_sniper_value(value: Any) -> str:
        """Normalize sniper point values and remove redundant label prefixes."""
        if value is None:
            return 'N/A'
        if isinstance(value, (int, float)):
            return str(value)
        if not isinstance(value, str):
            return str(value)
        if not value or value == 'N/A':
            return value
        prefixes = ['理想买入点：', '次优买入点：', '止损位：', '目标位：',
                     '理想买入点:', '次优买入点:', '止损位:', '目标位:']
        for prefix in prefixes:
            if value.startswith(prefix):
                return value[len(prefix):]
        return value

    def _get_signal_level(self, result: AnalysisResult) -> tuple:
        """
        Get signal level and color based on operation advice.

        Priority: advice string takes precedence over score.
        Score-based fallback is used only when advice doesn't match
        any known value.

        Returns:
            (signal_text, emoji, color_tag)
        """
        advice = result.operation_advice
        score = result.sentiment_score

        # Advice-first lookup (exact match takes priority)
        advice_map = {
            '强烈买入': ('强烈买入', '💚', '强买'),
            '买入': ('买入', '🟢', '买入'),
            '加仓': ('买入', '🟢', '买入'),
            '持有': ('持有', '🟡', '持有'),
            '观望': ('观望', '⚪', '观望'),
            '减仓': ('减仓', '🟠', '减仓'),
            '卖出': ('卖出', '🔴', '卖出'),
            '强烈卖出': ('卖出', '🔴', '卖出'),
        }
        if advice in advice_map:
            return advice_map[advice]

        # Score-based fallback when advice is unrecognized
        if score >= 80:
            return ('强烈买入', '💚', '强买')
        elif score >= 65:
            return ('买入', '🟢', '买入')
        elif score >= 55:
            return ('持有', '🟡', '持有')
        elif score >= 45:
            return ('观望', '⚪', '观望')
        elif score >= 35:
            return ('减仓', '🟠', '减仓')
        elif score < 35:
            return ('卖出', '🔴', '卖出')
        else:
            return ('观望', '⚪', '观望')
    
    def generate_dashboard_report(
        self,
        results: List[AnalysisResult],
        report_date: Optional[str] = None
    ) -> str:
        """
        生成决策仪表盘格式的日报（详细版）

        格式：市场概览 + 重要信息 + 核心结论 + 数据透视 + 作战计划

        Args:
            results: 分析结果列表
            report_date: 报告日期（默认今天）

        Returns:
            Markdown 格式的决策仪表盘日报
        """
        if report_date is None:
            report_date = datetime.now().strftime('%Y-%m-%d')

        # 按评分排序（高分在前）
        sorted_results = sorted(results, key=lambda x: x.sentiment_score, reverse=True)

        # 统计信息 - 使用 decision_type 字段准确统计
        buy_count = sum(1 for r in results if getattr(r, 'decision_type', '') == 'buy')
        sell_count = sum(1 for r in results if getattr(r, 'decision_type', '') == 'sell')
        hold_count = sum(1 for r in results if getattr(r, 'decision_type', '') in ('hold', ''))

        report_lines = [
            f"# 🎯 {report_date} 决策仪表盘",
            "",
            f"> 共分析 **{len(results)}** 只股票 | 🟢买入:{buy_count} 🟡观望:{hold_count} 🔴卖出:{sell_count}",
            "",
        ]

        # === 新增：分析结果摘要 (Issue #112) ===
        if results:
            report_lines.extend([
                "## 📊 分析结果摘要",
                "",
            ])
            for r in sorted_results:
                _, signal_emoji, _ = self._get_signal_level(r)
                display_name = self._escape_md(r.name)
                report_lines.append(
                    f"{signal_emoji} **{display_name}({r.code})**: {r.operation_advice} | "
                    f"评分 {r.sentiment_score} | {r.trend_prediction}"
                )
            report_lines.extend([
                "",
                "---",
                "",
            ])

        # 逐个股票的决策仪表盘（Issue #262: summary_only 时跳过详情）
        if not self._report_summary_only:
            for result in sorted_results:
                signal_text, signal_emoji, signal_tag = self._get_signal_level(result)
                dashboard = result.dashboard if hasattr(result, 'dashboard') and result.dashboard else {}
                
                # 股票名称（优先使用 dashboard 或 result 中的名称，转义 *ST 等特殊字符）
                raw_name = result.name if result.name and not result.name.startswith('股票') else f'股票{result.code}'
                stock_name = self._escape_md(raw_name)
                
                report_lines.extend([
                    f"## {signal_emoji} {stock_name} ({result.code})",
                    "",
                ])
                
                # ========== 舆情与基本面概览（放在最前面）==========
                intel = dashboard.get('intelligence', {}) if dashboard else {}
                if intel:
                    report_lines.extend([
                        "### 📰 重要信息速览",
                        "",
                    ])
                    # 舆情情绪总结
                    if intel.get('sentiment_summary'):
                        report_lines.append(f"**💭 舆情情绪**: {intel['sentiment_summary']}")
                    # 业绩预期
                    if intel.get('earnings_outlook'):
                        report_lines.append(f"**📊 业绩预期**: {intel['earnings_outlook']}")
                    # 风险警报（醒目显示）
                    risk_alerts = intel.get('risk_alerts', [])
                    if risk_alerts:
                        report_lines.append("")
                        report_lines.append("**🚨 风险警报**:")
                        for alert in risk_alerts:
                            report_lines.append(f"- {alert}")
                    # 利好催化
                    catalysts = intel.get('positive_catalysts', [])
                    if catalysts:
                        report_lines.append("")
                        report_lines.append("**✨ 利好催化**:")
                        for cat in catalysts:
                            report_lines.append(f"- {cat}")
                    # 最新消息
                    if intel.get('latest_news'):
                        report_lines.append("")
                        report_lines.append(f"**📢 最新动态**: {intel['latest_news']}")
                    report_lines.append("")
                
                # ========== 核心结论 ==========
                core = dashboard.get('core_conclusion', {}) if dashboard else {}
                one_sentence = core.get('one_sentence', result.analysis_summary)
                time_sense = core.get('time_sensitivity', '本周内')
                pos_advice = core.get('position_advice', {})
                
                report_lines.extend([
                    "### 📌 核心结论",
                    "",
                    f"**{signal_emoji} {signal_text}** | {result.trend_prediction}",
                    "",
                    f"> **一句话决策**: {one_sentence}",
                    "",
                    f"⏰ **时效性**: {time_sense}",
                    "",
                ])
                # 持仓分类建议
                if pos_advice:
                    report_lines.extend([
                        "| 持仓情况 | 操作建议 |",
                        "|---------|---------|",
                        f"| 🆕 **空仓者** | {pos_advice.get('no_position', result.operation_advice)} |",
                        f"| 💼 **持仓者** | {pos_advice.get('has_position', '继续持有')} |",
                        "",
                    ])

                self._append_market_snapshot(report_lines, result)
                
                # ========== 数据透视 ==========
                data_persp = dashboard.get('data_perspective', {}) if dashboard else {}
                if data_persp:
                    trend_data = data_persp.get('trend_status', {})
                    price_data = data_persp.get('price_position', {})
                    vol_data = data_persp.get('volume_analysis', {})
                    chip_data = data_persp.get('chip_structure', {})
                    
                    report_lines.extend([
                        "### 📊 数据透视",
                        "",
                    ])
                    # 趋势状态
                    if trend_data:
                        is_bullish = "✅ 是" if trend_data.get('is_bullish', False) else "❌ 否"
                        report_lines.extend([
                            f"**均线排列**: {trend_data.get('ma_alignment', 'N/A')} | 多头排列: {is_bullish} | 趋势强度: {trend_data.get('trend_score', 'N/A')}/100",
                            "",
                        ])
                    # 价格位置
                    if price_data:
                        bias_status = price_data.get('bias_status', 'N/A')
                        bias_emoji = "✅" if bias_status == "安全" else ("⚠️" if bias_status == "警戒" else "🚨")
                        report_lines.extend([
                            "| 价格指标 | 数值 |",
                            "|---------|------|",
                            f"| 当前价 | {price_data.get('current_price', 'N/A')} |",
                            f"| MA5 | {price_data.get('ma5', 'N/A')} |",
                            f"| MA10 | {price_data.get('ma10', 'N/A')} |",
                            f"| MA20 | {price_data.get('ma20', 'N/A')} |",
                            f"| 乖离率(MA5) | {price_data.get('bias_ma5', 'N/A')}% {bias_emoji}{bias_status} |",
                            f"| 支撑位 | {price_data.get('support_level', 'N/A')} |",
                            f"| 压力位 | {price_data.get('resistance_level', 'N/A')} |",
                            "",
                        ])
                    # 量能分析
                    if vol_data:
                        report_lines.extend([
                            f"**量能**: 量比 {vol_data.get('volume_ratio', 'N/A')} ({vol_data.get('volume_status', '')}) | 换手率 {vol_data.get('turnover_rate', 'N/A')}%",
                            f"💡 *{vol_data.get('volume_meaning', '')}*",
                            "",
                        ])
                    # 筹码结构
                    if chip_data:
                        chip_health = chip_data.get('chip_health', 'N/A')
                        chip_emoji = "✅" if chip_health == "健康" else ("⚠️" if chip_health == "一般" else "🚨")
                        report_lines.extend([
                            f"**筹码**: 获利比例 {chip_data.get('profit_ratio', 'N/A')} | 平均成本 {chip_data.get('avg_cost', 'N/A')} | 集中度 {chip_data.get('concentration', 'N/A')} {chip_emoji}{chip_health}",
                            "",
                        ])
                
                # ========== 作战计划 ==========
                battle = dashboard.get('battle_plan', {}) if dashboard else {}
                if battle:
                    report_lines.extend([
                        "### 🎯 作战计划",
                        "",
                    ])
                    # 狙击点位
                    sniper = battle.get('sniper_points', {})
                    if sniper:
                        report_lines.extend([
                            "**📍 狙击点位**",
                            "",
                            "| 点位类型 | 价格 |",
                            "|---------|------|",
                            f"| 🎯 理想买入点 | {self._clean_sniper_value(sniper.get('ideal_buy', 'N/A'))} |",
                            f"| 🔵 次优买入点 | {self._clean_sniper_value(sniper.get('secondary_buy', 'N/A'))} |",
                            f"| 🛑 止损位 | {self._clean_sniper_value(sniper.get('stop_loss', 'N/A'))} |",
                            f"| 🎊 目标位 | {self._clean_sniper_value(sniper.get('take_profit', 'N/A'))} |",
                            "",
                        ])
                    # 仓位策略
                    position = battle.get('position_strategy', {})
                    if position:
                        report_lines.extend([
                            f"**💰 仓位建议**: {position.get('suggested_position', 'N/A')}",
                            f"- 建仓策略: {position.get('entry_plan', 'N/A')}",
                            f"- 风控策略: {position.get('risk_control', 'N/A')}",
                            "",
                        ])
                    # 检查清单
                    checklist = battle.get('action_checklist', []) if battle else []
                    if checklist:
                        report_lines.extend([
                            "**✅ 检查清单**",
                            "",
                        ])
                        for item in checklist:
                            report_lines.append(f"- {item}")
                        report_lines.append("")
                
                # 如果没有 dashboard，显示传统格式
                if not dashboard:
                    # 操作理由
                    if result.buy_reason:
                        report_lines.extend([
                            f"**💡 操作理由**: {result.buy_reason}",
                            "",
                        ])
                    # 风险提示
                    if result.risk_warning:
                        report_lines.extend([
                            f"**⚠️ 风险提示**: {result.risk_warning}",
                            "",
                        ])
                    # 技术面分析
                    if result.ma_analysis or result.volume_analysis:
                        report_lines.extend([
                            "### 📊 技术面",
                            "",
                        ])
                        if result.ma_analysis:
                            report_lines.append(f"**均线**: {result.ma_analysis}")
                        if result.volume_analysis:
                            report_lines.append(f"**量能**: {result.volume_analysis}")
                        report_lines.append("")
                    # 消息面
                    if result.news_summary:
                        report_lines.extend([
                            "### 📰 消息面",
                            f"{result.news_summary}",
                            "",
                        ])
                
                report_lines.extend([
                    "---",
                    "",
                ])
        
        # 底部（去除免责声明）
        report_lines.extend([
            "",
            f"*报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        ])
        
        return "\n".join(report_lines)
    
    def generate_wechat_dashboard(self, results: List[AnalysisResult]) -> str:
        """
        生成企业微信决策仪表盘精简版（控制在4000字符内）
        
        只保留核心结论和狙击点位
        
        Args:
            results: 分析结果列表
            
        Returns:
            精简版决策仪表盘
        """
        report_date = datetime.now().strftime('%Y-%m-%d')
        
        # 按评分排序
        sorted_results = sorted(results, key=lambda x: x.sentiment_score, reverse=True)
        
        # 统计 - 使用 decision_type 字段准确统计
        buy_count = sum(1 for r in results if getattr(r, 'decision_type', '') == 'buy')
        sell_count = sum(1 for r in results if getattr(r, 'decision_type', '') == 'sell')
        hold_count = sum(1 for r in results if getattr(r, 'decision_type', '') in ('hold', ''))
        
        lines = [
            f"## 🎯 {report_date} 决策仪表盘",
            "",
            f"> {len(results)}只股票 | 🟢买入:{buy_count} 🟡观望:{hold_count} 🔴卖出:{sell_count}",
            "",
        ]
        
        # Issue #262: summary_only 时仅输出摘要列表
        if self._report_summary_only:
            lines.append("**📊 分析结果摘要**")
            lines.append("")
            for r in sorted_results:
                _, signal_emoji, _ = self._get_signal_level(r)
                stock_name = self._escape_md(r.name if r.name and not r.name.startswith('股票') else f'股票{r.code}')
                lines.append(
                    f"{signal_emoji} **{stock_name}({r.code})**: {r.operation_advice} | "
                    f"评分 {r.sentiment_score} | {r.trend_prediction}"
                )
        else:
            for result in sorted_results:
                signal_text, signal_emoji, _ = self._get_signal_level(result)
                dashboard = result.dashboard if hasattr(result, 'dashboard') and result.dashboard else {}
                core = dashboard.get('core_conclusion', {}) if dashboard else {}
                battle = dashboard.get('battle_plan', {}) if dashboard else {}
                intel = dashboard.get('intelligence', {}) if dashboard else {}
                
                # 股票名称
                stock_name = result.name if result.name and not result.name.startswith('股票') else f'股票{result.code}'
                stock_name = self._escape_md(stock_name)
                
                # 标题行：信号等级 + 股票名称
                lines.append(f"### {signal_emoji} **{signal_text}** | {stock_name}({result.code})")
                lines.append("")
                
                # 核心决策（一句话）
                one_sentence = core.get('one_sentence', result.analysis_summary) if core else result.analysis_summary
                if one_sentence:
                    lines.append(f"📌 **{one_sentence[:80]}**")
                    lines.append("")
                
                # 重要信息区（舆情+基本面）
                info_lines = []
                
                # 业绩预期
                if intel.get('earnings_outlook'):
                    outlook = intel['earnings_outlook'][:60]
                    info_lines.append(f"📊 业绩: {outlook}")
                if intel.get('sentiment_summary'):
                    sentiment = intel['sentiment_summary'][:50]
                    info_lines.append(f"💭 舆情: {sentiment}")
                if info_lines:
                    lines.extend(info_lines)
                    lines.append("")
                
                # 风险警报（最重要，醒目显示）
                risks = intel.get('risk_alerts', []) if intel else []
                if risks:
                    lines.append("🚨 **风险**:")
                    for risk in risks[:2]:  # 最多显示2条
                        risk_text = risk[:50] + "..." if len(risk) > 50 else risk
                        lines.append(f"   • {risk_text}")
                    lines.append("")
                
                # 利好催化
                catalysts = intel.get('positive_catalysts', []) if intel else []
                if catalysts:
                    lines.append("✨ **利好**:")
                    for cat in catalysts[:2]:  # 最多显示2条
                        cat_text = cat[:50] + "..." if len(cat) > 50 else cat
                        lines.append(f"   • {cat_text}")
                    lines.append("")
                
                # 狙击点位
                sniper = battle.get('sniper_points', {}) if battle else {}
                if sniper:
                    ideal_buy = sniper.get('ideal_buy', '')
                    stop_loss = sniper.get('stop_loss', '')
                    take_profit = sniper.get('take_profit', '')
                    points = []
                    if ideal_buy:
                        points.append(f"🎯买点:{ideal_buy[:15]}")
                    if stop_loss:
                        points.append(f"🛑止损:{stop_loss[:15]}")
                    if take_profit:
                        points.append(f"🎊目标:{take_profit[:15]}")
                    if points:
                        lines.append(" | ".join(points))
                        lines.append("")
                
                # 持仓建议
                pos_advice = core.get('position_advice', {}) if core else {}
                if pos_advice:
                    no_pos = pos_advice.get('no_position', '')
                    has_pos = pos_advice.get('has_position', '')
                    if no_pos:
                        lines.append(f"🆕 空仓者: {no_pos[:50]}")
                    if has_pos:
                        lines.append(f"💼 持仓者: {has_pos[:50]}")
                    lines.append("")
                
                # 检查清单简化版
                checklist = battle.get('action_checklist', []) if battle else []
                if checklist:
                    # 只显示不通过的项目
                    failed_checks = [c for c in checklist if c.startswith('❌') or c.startswith('⚠️')]
                    if failed_checks:
                        lines.append("**检查未通过项**:")
                        for check in failed_checks[:3]:
                            lines.append(f"   {check[:40]}")
                        lines.append("")
                
                lines.append("---")
                lines.append("")
        
        # 底部
        lines.append(f"*生成时间: {datetime.now().strftime('%H:%M')}*")
        
        content = "\n".join(lines)
        
        return content
    
    def generate_wechat_summary(self, results: List[AnalysisResult]) -> str:
        """
        生成企业微信精简版日报（控制在4000字符内）

        Args:
            results: 分析结果列表

        Returns:
            精简版 Markdown 内容
        """
        report_date = datetime.now().strftime('%Y-%m-%d')

        # 按评分排序
        sorted_results = sorted(results, key=lambda x: x.sentiment_score, reverse=True)

        # 统计 - 使用 decision_type 字段准确统计
        buy_count = sum(1 for r in results if getattr(r, 'decision_type', '') == 'buy')
        sell_count = sum(1 for r in results if getattr(r, 'decision_type', '') == 'sell')
        hold_count = sum(1 for r in results if getattr(r, 'decision_type', '') in ('hold', ''))
        avg_score = sum(r.sentiment_score for r in results) / len(results) if results else 0

        lines = [
            f"## 📅 {report_date} 股票分析报告",
            "",
            f"> 共 **{len(results)}** 只 | 🟢买入:{buy_count} 🟡持有:{hold_count} 🔴卖出:{sell_count} | 均分:{avg_score:.0f}",
            "",
        ]
        
        # 每只股票精简信息（控制长度）
        for result in sorted_results:
            emoji = result.get_emoji()
            
            # 核心信息行
            lines.append(f"### {emoji} {result.name}({result.code})")
            lines.append(f"**{result.operation_advice}** | 评分:{result.sentiment_score} | {result.trend_prediction}")
            
            # 操作理由（截断）
            if hasattr(result, 'buy_reason') and result.buy_reason:
                reason = result.buy_reason[:80] + "..." if len(result.buy_reason) > 80 else result.buy_reason
                lines.append(f"💡 {reason}")
            
            # 核心看点
            if hasattr(result, 'key_points') and result.key_points:
                points = result.key_points[:60] + "..." if len(result.key_points) > 60 else result.key_points
                lines.append(f"🎯 {points}")
            
            # 风险提示（截断）
            if hasattr(result, 'risk_warning') and result.risk_warning:
                risk = result.risk_warning[:50] + "..." if len(result.risk_warning) > 50 else result.risk_warning
                lines.append(f"⚠️ {risk}")
            
            lines.append("")
        
        # 底部
        lines.extend([
            "---",
            "*AI生成，仅供参考，不构成投资建议*",
            f"*详细报告见 reports/report_{report_date.replace('-', '')}.md*"
        ])
        
        content = "\n".join(lines)
        
        return content
    
    def generate_single_stock_report(self, result: AnalysisResult) -> str:
        """
        生成单只股票的分析报告（用于单股推送模式 #55）
        
        格式精简但信息完整，适合每分析完一只股票立即推送
        
        Args:
            result: 单只股票的分析结果
            
        Returns:
            Markdown 格式的单股报告
        """
        report_date = datetime.now().strftime('%Y-%m-%d %H:%M')
        signal_text, signal_emoji, _ = self._get_signal_level(result)
        dashboard = result.dashboard if hasattr(result, 'dashboard') and result.dashboard else {}
        core = dashboard.get('core_conclusion', {}) if dashboard else {}
        battle = dashboard.get('battle_plan', {}) if dashboard else {}
        intel = dashboard.get('intelligence', {}) if dashboard else {}
        
        # 股票名称（转义 *ST 等特殊字符）
        raw_name = result.name if result.name and not result.name.startswith('股票') else f'股票{result.code}'
        stock_name = self._escape_md(raw_name)
        
        lines = [
            f"## {signal_emoji} {stock_name} ({result.code})",
            "",
            f"> {report_date} | 评分: **{result.sentiment_score}** | {result.trend_prediction}",
            "",
        ]

        self._append_market_snapshot(lines, result)
        
        # 核心决策（一句话）
        one_sentence = core.get('one_sentence', result.analysis_summary) if core else result.analysis_summary
        if one_sentence:
            lines.extend([
                "### 📌 核心结论",
                "",
                f"**{signal_text}**: {one_sentence}",
                "",
            ])
        
        # 重要信息（舆情+基本面）
        info_added = False
        if intel:
            if intel.get('earnings_outlook'):
                if not info_added:
                    lines.append("### 📰 重要信息")
                    lines.append("")
                    info_added = True
                lines.append(f"📊 **业绩预期**: {intel['earnings_outlook'][:100]}")
            
            if intel.get('sentiment_summary'):
                if not info_added:
                    lines.append("### 📰 重要信息")
                    lines.append("")
                    info_added = True
                lines.append(f"💭 **舆情情绪**: {intel['sentiment_summary'][:80]}")
            
            # 风险警报
            risks = intel.get('risk_alerts', [])
            if risks:
                if not info_added:
                    lines.append("### 📰 重要信息")
                    lines.append("")
                    info_added = True
                lines.append("")
                lines.append("🚨 **风险警报**:")
                for risk in risks[:3]:
                    lines.append(f"- {risk[:60]}")
            
            # 利好催化
            catalysts = intel.get('positive_catalysts', [])
            if catalysts:
                lines.append("")
                lines.append("✨ **利好催化**:")
                for cat in catalysts[:3]:
                    lines.append(f"- {cat[:60]}")
        
        if info_added:
            lines.append("")
        
        # 狙击点位
        sniper = battle.get('sniper_points', {}) if battle else {}
        if sniper:
            lines.extend([
                "### 🎯 操作点位",
                "",
                "| 买点 | 止损 | 目标 |",
                "|------|------|------|",
            ])
            ideal_buy = sniper.get('ideal_buy', '-')
            stop_loss = sniper.get('stop_loss', '-')
            take_profit = sniper.get('take_profit', '-')
            lines.append(f"| {ideal_buy} | {stop_loss} | {take_profit} |")
            lines.append("")
        
        # 持仓建议
        pos_advice = core.get('position_advice', {}) if core else {}
        if pos_advice:
            lines.extend([
                "### 💼 持仓建议",
                "",
                f"- 🆕 **空仓者**: {pos_advice.get('no_position', result.operation_advice)}",
                f"- 💼 **持仓者**: {pos_advice.get('has_position', '继续持有')}",
                "",
            ])
        
        lines.extend([
            "---",
            "*AI生成，仅供参考，不构成投资建议*",
        ])
        
        return "\n".join(lines)

    # Display name mapping for realtime data sources
    _SOURCE_DISPLAY_NAMES = {
        "tencent": "腾讯财经",
        "akshare_em": "东方财富",
        "akshare_sina": "新浪财经",
        "akshare_qq": "腾讯财经",
        "efinance": "东方财富(efinance)",
        "tushare": "Tushare Pro",
        "sina": "新浪财经",
        "fallback": "降级兜底",
    }

    def _append_market_snapshot(self, lines: List[str], result: AnalysisResult) -> None:
        snapshot = getattr(result, 'market_snapshot', None)
        if not snapshot:
            return

        lines.extend([
            "### 📈 当日行情",
            "",
            "| 收盘 | 昨收 | 开盘 | 最高 | 最低 | 涨跌幅 | 涨跌额 | 振幅 | 成交量 | 成交额 |",
            "|------|------|------|------|------|-------|-------|------|--------|--------|",
            f"| {snapshot.get('close', 'N/A')} | {snapshot.get('prev_close', 'N/A')} | "
            f"{snapshot.get('open', 'N/A')} | {snapshot.get('high', 'N/A')} | "
            f"{snapshot.get('low', 'N/A')} | {snapshot.get('pct_chg', 'N/A')} | "
            f"{snapshot.get('change_amount', 'N/A')} | {snapshot.get('amplitude', 'N/A')} | "
            f"{snapshot.get('volume', 'N/A')} | {snapshot.get('amount', 'N/A')} |",
        ])

        if "price" in snapshot:
            raw_source = snapshot.get('source', 'N/A')
            display_source = self._SOURCE_DISPLAY_NAMES.get(raw_source, raw_source)
            lines.extend([
                "",
                "| 当前价 | 量比 | 换手率 | 行情来源 |",
                "|-------|------|--------|----------|",
                f"| {snapshot.get('price', 'N/A')} | {snapshot.get('volume_ratio', 'N/A')} | "
                f"{snapshot.get('turnover_rate', 'N/A')} | {display_source} |",
            ])

        lines.append("")
    
    def _truncate_to_bytes(self, text: str, max_bytes: int) -> str:
        """
        按字节数截断字符串，确保不会在多字节字符中间截断
        
        Args:
            text: 要截断的字符串
            max_bytes: 最大字节数
            
        Returns:
            截断后的字符串
        """
        encoded = text.encode('utf-8')
        if len(encoded) <= max_bytes:
            return text
        
        # 从 max_bytes 位置往前找，确保不截断多字节字符
        truncated = encoded[:max_bytes]
        # 尝试解码，如果失败则继续往前
        while truncated:
            try:
                return truncated.decode('utf-8')
            except UnicodeDecodeError:
                truncated = truncated[:-1]
        return ""

    def _should_use_image_for_channel(
        self, channel: NotificationChannel, image_bytes: Optional[bytes]
    ) -> bool:
        """
        Decide whether to send as image for the given channel (Issue #289).

        Fallback rules (send as Markdown text instead of image):
        - image_bytes is None: conversion failed / imgkit not installed / content over max_chars
        - WeChat: image exceeds ~2MB limit
        """
        if channel.value not in self._markdown_to_image_channels or image_bytes is None:
            return False
        if channel == NotificationChannel.WECHAT and len(image_bytes) > WECHAT_IMAGE_MAX_BYTES:
            logger.warning(
                "企业微信图片超限 (%d bytes)，回退为 Markdown 文本发送",
                len(image_bytes),
            )
            return False
        return True

    def send(
        self,
        content: str,
        email_stock_codes: Optional[List[str]] = None,
        email_send_to_all: bool = False
    ) -> bool:
        """
        统一发送接口 - 向所有已配置的渠道发送

        遍历所有已配置的渠道，逐一发送消息

        Fallback rules (Markdown-to-image, Issue #289):
        - When image_bytes is None (conversion failed / imgkit not installed /
          content over max_chars): all channels configured for image will send
          as Markdown text instead.
        - When WeChat image exceeds ~2MB: that channel falls back to Markdown text.

        Args:
            content: 消息内容（Markdown 格式）
            email_stock_codes: 股票代码列表（可选，用于邮件渠道路由到对应分组邮箱，Issue #268）
            email_send_to_all: 邮件是否发往所有配置邮箱（用于大盘复盘等无股票归属的内容）

        Returns:
            是否至少有一个渠道发送成功
        """
        context_success = self.send_to_context(content)

        if not self._available_channels:
            if context_success:
                logger.info("已通过消息上下文渠道完成推送（无其他通知渠道）")
                return True
            logger.warning("通知服务不可用，跳过推送")
            return False

        # Markdown to image (Issue #289): convert once if any channel needs it.
        # Per-channel decision via _should_use_image_for_channel (see send() docstring for fallback rules).
        image_bytes = None
        channels_needing_image = {
            ch for ch in self._available_channels
            if ch.value in self._markdown_to_image_channels
        }
        if channels_needing_image:
            from src.md2img import markdown_to_image
            image_bytes = markdown_to_image(
                content, max_chars=self._markdown_to_image_max_chars
            )
            if image_bytes:
                logger.info("Markdown 已转换为图片，将向 %s 发送图片",
                            [ch.value for ch in channels_needing_image])
            elif channels_needing_image:
                logger.warning("Markdown 转图片失败，将回退为文本发送")

        channel_names = self.get_channel_names()
        logger.info(f"正在向 {len(self._available_channels)} 个渠道发送通知：{channel_names}")

        success_count = 0
        fail_count = 0

        for channel in self._available_channels:
            channel_name = ChannelDetector.get_channel_name(channel)
            use_image = self._should_use_image_for_channel(channel, image_bytes)
            try:
                if channel == NotificationChannel.WECHAT:
                    if use_image:
                        result = self._send_wechat_image(image_bytes)
                    else:
                        result = self.send_to_wechat(content)
                elif channel == NotificationChannel.FEISHU:
                    result = self.send_to_feishu(content)
                elif channel == NotificationChannel.TELEGRAM:
                    if use_image:
                        result = self._send_telegram_photo(image_bytes)
                    else:
                        result = self.send_to_telegram(content)
                elif channel == NotificationChannel.EMAIL:
                    receivers = None
                    if email_send_to_all and self._stock_email_groups:
                        receivers = self.get_all_email_receivers()
                    elif email_stock_codes and self._stock_email_groups:
                        receivers = self.get_receivers_for_stocks(email_stock_codes)
                    if use_image:
                        result = self._send_email_with_inline_image(
                            image_bytes, receivers=receivers
                        )
                    else:
                        result = self.send_to_email(content, receivers=receivers)
                elif channel == NotificationChannel.PUSHOVER:
                    result = self.send_to_pushover(content)
                elif channel == NotificationChannel.PUSHPLUS:
                    result = self.send_to_pushplus(content)
                elif channel == NotificationChannel.SERVERCHAN3:
                    result = self.send_to_serverchan3(content)
                elif channel == NotificationChannel.CUSTOM:
                    if use_image:
                        result = self._send_custom_webhook_image(
                            image_bytes, fallback_content=content
                        )
                    else:
                        result = self.send_to_custom(content)
                elif channel == NotificationChannel.DISCORD:
                    result = self.send_to_discord(content)
                elif channel == NotificationChannel.ASTRBOT:
                    result = self.send_to_astrbot(content)
                else:
                    logger.warning(f"不支持的通知渠道: {channel}")
                    result = False

                if result:
                    success_count += 1
                else:
                    fail_count += 1

            except Exception as e:
                logger.error(f"{channel_name} 发送失败: {e}")
                fail_count += 1

        logger.info(f"通知发送完成：成功 {success_count} 个，失败 {fail_count} 个")
        return success_count > 0 or context_success
   
    def save_report_to_file(
        self, 
        content: str, 
        filename: Optional[str] = None
    ) -> str:
        """
        保存日报到本地文件
        
        Args:
            content: 日报内容
            filename: 文件名（可选，默认按日期生成）
            
        Returns:
            保存的文件路径
        """
        from pathlib import Path
        
        if filename is None:
            date_str = datetime.now().strftime('%Y%m%d')
            filename = f"report_{date_str}.md"
        
        # 确保 reports 目录存在（使用项目根目录下的 reports）
        reports_dir = Path(__file__).parent.parent / 'reports'
        reports_dir.mkdir(parents=True, exist_ok=True)
        
        filepath = reports_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        logger.info(f"日报已保存到: {filepath}")
        return str(filepath)


class NotificationBuilder:
    """
    通知消息构建器
    
    提供便捷的消息构建方法
    """
    
    @staticmethod
    def build_simple_alert(
        title: str,
        content: str,
        alert_type: str = "info"
    ) -> str:
        """
        构建简单的提醒消息
        
        Args:
            title: 标题
            content: 内容
            alert_type: 类型（info, warning, error, success）
        """
        emoji_map = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "success": "✅",
        }
        emoji = emoji_map.get(alert_type, "📢")
        
        return f"{emoji} **{title}**\n\n{content}"
    
    @staticmethod
    def build_stock_summary(results: List[AnalysisResult]) -> str:
        """
        构建股票摘要（简短版）
        
        适用于快速通知
        """
        lines = ["📊 **今日自选股摘要**", ""]
        
        for r in sorted(results, key=lambda x: x.sentiment_score, reverse=True):
            emoji = r.get_emoji()
            lines.append(f"{emoji} {r.name}({r.code}): {r.operation_advice} | 评分 {r.sentiment_score}")
        
        return "\n".join(lines)


# 便捷函数
def get_notification_service() -> NotificationService:
    """获取通知服务实例"""
    return NotificationService()


def send_daily_report(results: List[AnalysisResult]) -> bool:
    """
    发送每日报告的快捷方式
    
    自动识别渠道并推送
    """
    service = get_notification_service()
    
    # 生成报告
    report = service.generate_daily_report(results)
    
    # 保存到本地
    service.save_report_to_file(report)
    
    # 推送到配置的渠道（自动识别）
    return service.send(report)


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.DEBUG)
    
    # 模拟分析结果
    test_results = [
        AnalysisResult(
            code='600519',
            name='贵州茅台',
            sentiment_score=75,
            trend_prediction='看多',
            analysis_summary='技术面强势，消息面利好',
            operation_advice='买入',
            technical_analysis='放量突破 MA20，MACD 金叉',
            news_summary='公司发布分红公告，业绩超预期',
        ),
        AnalysisResult(
            code='000001',
            name='平安银行',
            sentiment_score=45,
            trend_prediction='震荡',
            analysis_summary='横盘整理，等待方向',
            operation_advice='持有',
            technical_analysis='均线粘合，成交量萎缩',
            news_summary='近期无重大消息',
        ),
        AnalysisResult(
            code='300750',
            name='宁德时代',
            sentiment_score=35,
            trend_prediction='看空',
            analysis_summary='技术面走弱，注意风险',
            operation_advice='卖出',
            technical_analysis='跌破 MA10 支撑，量能不足',
            news_summary='行业竞争加剧，毛利率承压',
        ),
    ]
    
    service = NotificationService()
    
    # 显示检测到的渠道
    print("=== 通知渠道检测 ===")
    print(f"当前渠道: {service.get_channel_names()}")
    print(f"渠道列表: {service.get_available_channels()}")
    print(f"服务可用: {service.is_available()}")
    
    # 生成日报
    print("\n=== 生成日报测试 ===")
    report = service.generate_daily_report(test_results)
    print(report)
    
    # 保存到文件
    print("\n=== 保存日报 ===")
    filepath = service.save_report_to_file(report)
    print(f"保存成功: {filepath}")
    
    # 推送测试
    if service.is_available():
        print(f"\n=== 推送测试（{service.get_channel_names()}）===")
        success = service.send(report)
        print(f"推送结果: {'成功' if success else '失败'}")
    else:
        print("\n通知渠道未配置，跳过推送测试")
