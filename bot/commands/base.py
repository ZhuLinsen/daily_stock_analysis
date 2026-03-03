# -*- coding: utf-8 -*-
"""
===================================
命令基类
===================================

定义命令处理器的抽象基类，所有命令都必须继承此类。
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from bot.models import BotMessage, BotResponse


class BotCommand(ABC):
    """
    命令处理器抽象基类
    
    所有命令都必须继承此类并实现抽象方法。
    
    使用示例：
        class MyCommand(BotCommand):
            @property
            def name(self) -> str:
                return "mycommand"
            
            @property
            def aliases(self) -> List[str]:
                return ["mc", "我的命令"]
            
            @property
            def description(self) -> str:
                return "这是我的命令"
            
            @property
            def usage(self) -> str:
                return "/mycommand [参数]"
            
            def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
                return BotResponse.text_response("命令执行成功")
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """
        命令名称（不含前缀）
        
        例如 "analyze"，用户输入 "/analyze" 触发
        """
        pass
    
    @property
    @abstractmethod
    def aliases(self) -> List[str]:
        """
        命令别名列表
        
        例如 ["a", "分析"]，用户输入 "/a" 或 "分析" 也能触发
        """
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """命令描述（用于帮助信息）"""
        pass
    
    @property
    @abstractmethod
    def usage(self) -> str:
        """
        使用说明（用于帮助信息）
        
        例如 "/analyze <股票代码>"
        """
        pass
    
    @property
    def hidden(self) -> bool:
        """
        是否在帮助列表中隐藏
        
        默认 False，设为 True 则不显示在 /help 列表中
        """
        return False
    
    @property
    def admin_only(self) -> bool:
        """
        是否仅管理员可用
        
        默认 False，设为 True 则需要管理员权限
        """
        return False
    
    @abstractmethod
    def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
        """
        执行命令
        
        Args:
            message: 原始消息对象
            args: 命令参数列表（已分割）
            
        Returns:
            BotResponse 响应对象
        """
        pass
    
    def validate_args(self, args: List[str]) -> Optional[str]:
        """
        验证参数
        
        子类可重写此方法进行参数校验。
        
        Args:
            args: 命令参数列表
            
        Returns:
            如果参数有效返回 None，否则返回错误信息
        """
        return None
    
    def get_help_text(self) -> str:
        """获取帮助文本"""
        return f"**{self.name}** - {self.description}\n用法: `{self.usage}`"
