# -*- coding: utf-8 -*-
"""
Ask command - analyze a stock using a specific Agent skill.

Usage:
    /ask 600519                        -> Analyze with default skill
    /ask 600519 用缠论分析              -> Parse skill from message
    /ask 600519 chan_theory             -> Specify skill id directly
"""

import re
import logging
import uuid
from typing import List, Optional

from bot.commands.base import BotCommand
from bot.models import BotMessage, BotResponse
from data_provider.base import canonical_stock_code
from src.config import get_config

logger = logging.getLogger(__name__)


class AskCommand(BotCommand):
    """
    Ask command handler - invoke Agent with a specific skill to analyze a stock.

    Usage:
        /ask 600519                    -> Analyze with default skill
        /ask 600519 用缠论分析          -> Automatically selects chan_theory
        /ask 600519 chan_theory         -> Directly specify skill id
        /ask hk00700 波浪理论看看       -> HK stock with wave_theory
    """

    @property
    def name(self) -> str:
        return "ask"

    @property
    def aliases(self) -> List[str]:
        return ["问股"]

    @property
    def description(self) -> str:
        return "使用 Agent 技能分析股票"

    @property
    def usage(self) -> str:
        return "/ask <股票代码> [技能名称]"

    def validate_args(self, args: List[str]) -> Optional[str]:
        """Validate arguments."""
        if not args:
            return "请输入股票代码。用法: /ask <股票代码> [技能名称]\n示例: /ask 600519 用缠论分析"

        code = args[0].upper()
        is_a_stock = re.match(r"^\d{6}$", code)
        is_hk_stock = re.match(r"^HK\d{5}$", code)
        is_us_stock = re.match(r"^[A-Z]{1,5}(\.[A-Z]{1,2})?$", code)

        if not (is_a_stock or is_hk_stock or is_us_stock):
            return f"无效的股票代码: {code}（A股6位数字 / 港股HK+5位数字 / 美股1-5个字母）"

        return None

    @staticmethod
    def _load_skills() -> List[object]:
        try:
            from src.agent.factory import get_skill_manager

            sm = get_skill_manager()
            return list(sm.list_skills())
        except Exception:
            return []

    @classmethod
    def _get_default_skill_id(cls) -> str:
        try:
            from src.agent.skills.defaults import get_primary_default_skill_id

            return get_primary_default_skill_id(cls._load_skills())
        except Exception:
            return ""

    @classmethod
    def _build_skill_alias_pairs(cls) -> List[tuple[str, str]]:
        alias_pairs: List[tuple[str, str]] = []
        for skill in cls._load_skills():
            skill_id = str(getattr(skill, "name", "")).strip()
            if not skill_id:
                continue
            aliases = [skill_id, getattr(skill, "display_name", "")] + list(getattr(skill, "aliases", []) or [])
            for alias in aliases:
                alias_text = str(alias).strip()
                if alias_text:
                    alias_pairs.append((alias_text, skill_id))

        alias_pairs.sort(key=lambda item: (len(item[0]), item[0]), reverse=True)
        return alias_pairs

    def _parse_skill(self, args: List[str]) -> str:
        """Parse skill from arguments, returning the resolved skill id."""
        default_skill_id = self._get_default_skill_id()
        if len(args) < 2:
            return default_skill_id

        skill_text = " ".join(args[1:]).strip()
        available_ids = {str(getattr(skill, "name", "")).strip() for skill in self._load_skills()}
        if skill_text in available_ids:
            return skill_text

        for alias_text, skill_id in self._build_skill_alias_pairs():
            if alias_text in skill_text:
                return skill_id

        return default_skill_id

    def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
        """Execute the ask command via Agent pipeline."""
        config = get_config()

        if not config.agent_mode:
            return BotResponse.text_response(
                "⚠️ Agent 模式未开启，无法使用问股功能。\n请在配置中设置 `AGENT_MODE=true`。"
            )

        code = canonical_stock_code(args[0])
        skill_id = self._parse_skill(args)
        skill_text = " ".join(args[1:]).strip() if len(args) > 1 else ""

        logger.info(f"[AskCommand] Stock: {code}, Skill: {skill_id}, Extra: {skill_text}")

        try:
            from src.agent.factory import build_agent_executor
            executor = build_agent_executor(config, skills=[skill_id] if skill_id else None)

            # Build message
            user_msg = f"请分析股票 {code}"
            if skill_id:
                user_msg = f"请使用 {skill_id} 技能分析股票 {code}"
            if skill_text:
                user_msg = f"请分析股票 {code}，{skill_text}"

            # Each /ask invocation is a self-contained single-shot analysis; isolate
            # sessions per request so that different stocks or retry attempts never
            # bleed context into each other.
            session_id = f"ask_{code}_{uuid.uuid4()}"
            result = executor.chat(message=user_msg, session_id=session_id)

            if result.success:
                skill_name = skill_id
                for skill in self._load_skills():
                    if str(getattr(skill, "name", "")).strip() == skill_id:
                        skill_name = str(getattr(skill, "display_name", skill_id)).strip() or skill_id
                        break

                header = f"📊 {code}\n{'─' * 30}\n"
                if skill_name:
                    header = f"📊 {code} | 技能: {skill_name}\n{'─' * 30}\n"
                return BotResponse.text_response(header + result.content)
            else:
                return BotResponse.text_response(f"⚠️ 分析失败: {result.error}")

        except Exception as e:
            logger.error(f"Ask command failed: {e}")
            logger.exception("Ask error details:")
            return BotResponse.text_response(f"⚠️ 问股执行出错: {str(e)}")
