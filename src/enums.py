# -*- coding: utf-8 -*-
"""
===================================
枚举类型定义
===================================

集中管理系统中使用的枚举类型，提供类型安全和代码可读性。
"""

from enum import Enum


class ReportType(str, Enum):
    """
    报告类型枚举
    
    用于 API 触发分析时选择推送的报告格式。
    继承 str 使其可以直接与字符串比较和序列化。
    """
    SIMPLE = "simple"  # 精简报告：使用 generate_single_stock_report
    FULL = "full"      # 完整报告：使用 generate_dashboard_report
    
    @classmethod
    def from_str(cls, value: str) -> "ReportType":
        """
        从字符串安全地转换为枚举值
        
        Args:
            value: 字符串值
            
        Returns:
            对应的枚举值，无效输入返回默认值 SIMPLE
        """
        try:
            return cls(value.lower().strip())
        except (ValueError, AttributeError):
            return cls.SIMPLE
    
    @property
    def display_name(self) -> str:
        """获取用于显示的名称"""
        return {
            ReportType.SIMPLE: "精简报告",
            ReportType.FULL: "完整报告",
        }.get(self, "精简报告")
