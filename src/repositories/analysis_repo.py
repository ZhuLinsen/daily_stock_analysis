# -*- coding: utf-8 -*-
"""
===================================
分析历史数据访问层
===================================

职责：
1. 封装分析历史数据的数据库操作
2. 提供 CRUD 接口
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from src.storage import DatabaseManager, AnalysisHistory

logger = logging.getLogger(__name__)


class AnalysisRepository:
    """
    分析历史数据访问层
    
    封装 AnalysisHistory 表的数据库操作
    """
    
    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        """
        初始化数据访问层
        
        Args:
            db_manager: 数据库管理器（可选，默认使用单例）
        """
        self.db = db_manager or DatabaseManager.get_instance()
    
    def get_by_query_id(self, query_id: str) -> Optional[AnalysisHistory]:
        """
        根据 query_id 获取分析记录
        
        Args:
            query_id: 查询 ID
            
        Returns:
            AnalysisHistory 对象，不存在返回 None
        """
        try:
            records = self.db.get_analysis_history(query_id=query_id, limit=1)
            return records[0] if records else None
        except Exception as e:
            logger.error(f"查询分析记录失败: {e}")
            return None
    
    def get_list(
        self,
        code: Optional[str] = None,
        days: int = 30,
        limit: int = 50
    ) -> List[AnalysisHistory]:
        """
        获取分析记录列表
        
        Args:
            code: 股票代码筛选
            days: 时间范围（天）
            limit: 返回数量限制
            
        Returns:
            AnalysisHistory 对象列表
        """
        try:
            return self.db.get_analysis_history(
                code=code,
                days=days,
                limit=limit
            )
        except Exception as e:
            logger.error(f"获取分析列表失败: {e}")
            return []
    
    def save(
        self,
        result: Any,
        query_id: str,
        report_type: str,
        news_content: Optional[str] = None,
        context_snapshot: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        保存分析结果
        
        Args:
            result: 分析结果对象
            query_id: 查询 ID
            report_type: 报告类型
            news_content: 新闻内容
            context_snapshot: 上下文快照
            
        Returns:
            保存的记录数
        """
        try:
            return self.db.save_analysis_history(
                result=result,
                query_id=query_id,
                report_type=report_type,
                news_content=news_content,
                context_snapshot=context_snapshot
            )
        except Exception as e:
            logger.error(f"保存分析结果失败: {e}")
            return 0
    
    def count_by_code(self, code: str, days: int = 30) -> int:
        """
        统计指定股票的分析记录数
        
        Args:
            code: 股票代码
            days: 时间范围（天）
            
        Returns:
            记录数量
        """
        try:
            records = self.db.get_analysis_history(code=code, days=days, limit=1000)
            return len(records)
        except Exception as e:
            logger.error(f"统计分析记录失败: {e}")
            return 0
