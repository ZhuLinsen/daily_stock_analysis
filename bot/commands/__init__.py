# -*- coding: utf-8 -*-
"""
===================================
命令处理器模块
===================================

包含所有机器人命令的实现。
"""

from bot.commands.base import BotCommand
from bot.commands.help import HelpCommand
from bot.commands.status import StatusCommand
from bot.commands.analyze import AnalyzeCommand
from bot.commands.market import MarketCommand
from bot.commands.batch import BatchCommand
from bot.commands.ask import AskCommand
from bot.commands.chat import ChatCommand

# 所有可用命令（用于自动注册）
ALL_COMMANDS = [
    HelpCommand,
    StatusCommand,
    AnalyzeCommand,
    MarketCommand,
    BatchCommand,
    AskCommand,
    ChatCommand,
]

__all__ = [
    'BotCommand',
    'HelpCommand',
    'StatusCommand',
    'AnalyzeCommand',
    'MarketCommand',
    'BatchCommand',
    'AskCommand',
    'ChatCommand',
    'MarketCommand',
    'BatchCommand',
    'ALL_COMMANDS',
]
