# -*- coding: utf-8 -*-
"""
===================================
命令分发器
===================================

负责解析命令、匹配处理器、分发执行。
"""

import logging
import time
from collections import defaultdict
from typing import Dict, List, Optional, Type, Callable

from bot.models import BotMessage, BotResponse
from bot.commands.base import BotCommand

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    简单的频率限制器
    
    基于滑动窗口算法，限制每个用户的请求频率。
    """
    
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        """
        Args:
            max_requests: 窗口内最大请求数
            window_seconds: 窗口时间（秒）
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: Dict[str, List[float]] = defaultdict(list)
    
    def is_allowed(self, user_id: str) -> bool:
        """
        检查用户是否允许请求
        
        Args:
            user_id: 用户标识
            
        Returns:
            是否允许
        """
        now = time.time()
        window_start = now - self.window_seconds
        
        # 清理过期记录
        self._requests[user_id] = [
            t for t in self._requests[user_id] 
            if t > window_start
        ]
        
        # 检查是否超限
        if len(self._requests[user_id]) >= self.max_requests:
            return False
        
        # 记录本次请求
        self._requests[user_id].append(now)
        return True
    
    def get_remaining(self, user_id: str) -> int:
        """获取剩余可用请求数"""
        now = time.time()
        window_start = now - self.window_seconds
        
        # 清理过期记录
        self._requests[user_id] = [
            t for t in self._requests[user_id] 
            if t > window_start
        ]
        
        return max(0, self.max_requests - len(self._requests[user_id]))


class CommandDispatcher:
    """
    命令分发器
    
    职责：
    1. 注册和管理命令处理器
    2. 解析消息中的命令和参数
    3. 分发命令到对应处理器
    4. 处理未知命令和错误
    
    使用示例：
        dispatcher = CommandDispatcher()
        dispatcher.register(AnalyzeCommand())
        dispatcher.register(HelpCommand())
        
        response = dispatcher.dispatch(message)
    """
    
    def __init__(
        self, 
        command_prefix: str = "/",
        rate_limit_requests: int = 10,
        rate_limit_window: int = 60,
        admin_users: Optional[List[str]] = None
    ):
        """
        Args:
            command_prefix: 命令前缀，默认 "/"
            rate_limit_requests: 频率限制：窗口内最大请求数
            rate_limit_window: 频率限制：窗口时间（秒）
            admin_users: 管理员用户 ID 列表
        """
        self.command_prefix = command_prefix
        self.admin_users = set(admin_users or [])
        
        self._commands: Dict[str, BotCommand] = {}
        self._aliases: Dict[str, str] = {}
        self._rate_limiter = RateLimiter(rate_limit_requests, rate_limit_window)
        
        # 回调函数：获取帮助命令的命令列表
        self._help_command_getter: Optional[Callable] = None
    
    def register(self, command: BotCommand) -> None:
        """
        注册命令
        
        Args:
            command: 命令实例
        """
        name = command.name.lower()
        
        if name in self._commands:
            logger.warning(f"[Dispatcher] 命令 '{name}' 已存在，将被覆盖")
        
        self._commands[name] = command
        logger.debug(f"[Dispatcher] 注册命令: {name}")
        
        # 注册别名
        for alias in command.aliases:
            alias_lower = alias.lower()
            if alias_lower in self._aliases:
                logger.warning(f"[Dispatcher] 别名 '{alias_lower}' 已存在，将被覆盖")
            self._aliases[alias_lower] = name
            logger.debug(f"[Dispatcher] 注册别名: {alias_lower} -> {name}")
    
    def register_class(self, command_class: Type[BotCommand]) -> None:
        """
        注册命令类（自动实例化）
        
        Args:
            command_class: 命令类
        """
        self.register(command_class())
    
    def unregister(self, name: str) -> bool:
        """
        注销命令
        
        Args:
            name: 命令名称
            
        Returns:
            是否成功注销
        """
        name = name.lower()
        
        if name not in self._commands:
            return False
        
        command = self._commands.pop(name)
        
        # 移除别名
        for alias in command.aliases:
            self._aliases.pop(alias.lower(), None)
        
        logger.debug(f"[Dispatcher] 注销命令: {name}")
        return True
    
    def get_command(self, name: str) -> Optional[BotCommand]:
        """
        获取命令
        
        支持命令名和别名查询。
        
        Args:
            name: 命令名或别名
            
        Returns:
            命令实例，或 None
        """
        name = name.lower()
        
        # 先查命令名
        if name in self._commands:
            return self._commands[name]
        
        # 再查别名
        if name in self._aliases:
            return self._commands.get(self._aliases[name])
        
        return None
    
    def list_commands(self, include_hidden: bool = False) -> List[BotCommand]:
        """
        列出所有命令
        
        Args:
            include_hidden: 是否包含隐藏命令
            
        Returns:
            命令列表
        """
        commands = list(self._commands.values())
        
        if not include_hidden:
            commands = [c for c in commands if not c.hidden]
        
        return sorted(commands, key=lambda c: c.name)
    
    def is_admin(self, user_id: str) -> bool:
        """检查用户是否是管理员"""
        return user_id in self.admin_users
    
    def add_admin(self, user_id: str) -> None:
        """添加管理员"""
        self.admin_users.add(user_id)
    
    def remove_admin(self, user_id: str) -> None:
        """移除管理员"""
        self.admin_users.discard(user_id)
    
    def dispatch(self, message: BotMessage) -> BotResponse:
        """
        分发消息到对应命令
        
        Args:
            message: 消息对象
            
        Returns:
            响应对象
        """
        # 1. 检查频率限制
        if not self._rate_limiter.is_allowed(message.user_id):
            remaining_time = self._rate_limiter.window_seconds
            return BotResponse.error_response(
                f"请求过于频繁，请 {remaining_time} 秒后再试"
            )
        
        # 2. 解析命令和参数
        cmd_name, args = message.get_command_and_args(self.command_prefix)
        
        if cmd_name is None:
            # 不是命令，检查是否 @了机器人
            if message.mentioned:
                return BotResponse.text_response(
                    "你好！我是股票分析助手。\n"
                    f"发送 `{self.command_prefix}help` 查看可用命令。"
                )
            # 非命令消息，不处理
            return BotResponse.text_response("")
        
        logger.info(f"[Dispatcher] 收到命令: {cmd_name}, 参数: {args}, 用户: {message.user_name}")
        
        # 3. 查找命令处理器
        command = self.get_command(cmd_name)
        
        if command is None:
            return BotResponse.error_response(
                f"未知命令: {cmd_name}\n"
                f"发送 `{self.command_prefix}help` 查看可用命令。"
            )
        
        # 4. 检查权限
        if command.admin_only and not self.is_admin(message.user_id):
            return BotResponse.error_response("此命令需要管理员权限")
        
        # 5. 验证参数
        error_msg = command.validate_args(args)
        if error_msg:
            return BotResponse.error_response(
                f"{error_msg}\n用法: `{command.usage}`"
            )
        
        # 6. 执行命令
        try:
            response = command.execute(message, args)
            logger.info(f"[Dispatcher] 命令 {cmd_name} 执行成功")
            return response
        except Exception as e:
            logger.error(f"[Dispatcher] 命令 {cmd_name} 执行失败: {e}")
            logger.exception(e)
            return BotResponse.error_response(f"命令执行失败: {str(e)[:100]}")
    
    def set_help_command_getter(self, getter: Callable) -> None:
        """
        设置帮助命令的命令列表获取器
        
        用于让 HelpCommand 获取命令列表。
        
        Args:
            getter: 回调函数，返回命令列表
        """
        self._help_command_getter = getter


# 全局分发器实例
_dispatcher: Optional[CommandDispatcher] = None


def get_dispatcher() -> CommandDispatcher:
    """
    获取全局分发器实例
    
    使用单例模式，首次调用时自动初始化并注册所有命令。
    """
    global _dispatcher
    
    if _dispatcher is None:
        from src.config import get_config
        
        config = get_config()
        
        # 创建分发器
        _dispatcher = CommandDispatcher(
            command_prefix=getattr(config, 'bot_command_prefix', '/'),
            rate_limit_requests=getattr(config, 'bot_rate_limit_requests', 10),
            rate_limit_window=getattr(config, 'bot_rate_limit_window', 60),
            admin_users=getattr(config, 'bot_admin_users', []),
        )
        
        # 自动注册所有命令
        from bot.commands import ALL_COMMANDS
        for command_class in ALL_COMMANDS:
            _dispatcher.register_class(command_class)
        
        logger.info(f"[Dispatcher] 初始化完成，已注册 {len(_dispatcher._commands)} 个命令")
    
    return _dispatcher


def reset_dispatcher() -> None:
    """重置全局分发器（主要用于测试）"""
    global _dispatcher
    _dispatcher = None
