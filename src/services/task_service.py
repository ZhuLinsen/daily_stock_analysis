# -*- coding: utf-8 -*-
"""
===================================
异步任务服务层
===================================

职责：
1. 管理异步分析任务（线程池）
2. 执行股票分析并推送结果
3. 查询任务状态和历史

迁移自 web/services.py 的 AnalysisService 类
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional, Dict, Any, List, Union

from src.enums import ReportType
from src.storage import get_db
from bot.models import BotMessage

logger = logging.getLogger(__name__)


class TaskService:
    """
    异步任务服务

    负责：
    1. 管理异步分析任务
    2. 执行股票分析
    3. 触发通知推送
    """

    _instance: Optional['TaskService'] = None
    _lock = threading.Lock()

    def __init__(self, max_workers: int = 3):
        self._executor: Optional[ThreadPoolExecutor] = None
        self._max_workers = max_workers
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._tasks_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> 'TaskService':
        """获取单例实例"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @property
    def executor(self) -> ThreadPoolExecutor:
        """获取或创建线程池"""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self._max_workers,
                thread_name_prefix="analysis_"
            )
        return self._executor

    def submit_analysis(
        self,
        code: str,
        report_type: Union[ReportType, str] = ReportType.SIMPLE,
        source_message: Optional[BotMessage] = None,
        save_context_snapshot: Optional[bool] = None,
        query_source: str = "bot"
    ) -> Dict[str, Any]:
        """
        提交异步分析任务

        Args:
            code: 股票代码
            report_type: 报告类型枚举
            source_message: 来源消息（用于回复）
            save_context_snapshot: 是否保存上下文快照
            query_source: 任务来源标识（bot/api/cli/system）

        Returns:
            任务信息字典
        """
        # 确保 report_type 是枚举类型
        if isinstance(report_type, str):
            report_type = ReportType.from_str(report_type)

        task_id = f"{code}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"

        # 提交到线程池
        self.executor.submit(
            self._run_analysis,
            code,
            task_id,
            report_type,
            source_message,
            save_context_snapshot,
            query_source
        )

        logger.info(f"[TaskService] 已提交股票 {code} 的分析任务, task_id={task_id}, report_type={report_type.value}")

        return {
            "success": True,
            "message": "分析任务已提交，将异步执行并推送通知",
            "code": code,
            "task_id": task_id,
            "report_type": report_type.value
        }

    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        with self._tasks_lock:
            return self._tasks.get(task_id)

    def list_tasks(self, limit: int = 20) -> List[Dict[str, Any]]:
        """列出最近的任务"""
        with self._tasks_lock:
            tasks = list(self._tasks.values())
        # 按开始时间倒序
        tasks.sort(key=lambda x: x.get('start_time', ''), reverse=True)
        return tasks[:limit]

    def get_analysis_history(
        self,
        code: Optional[str] = None,
        query_id: Optional[str] = None,
        days: int = 30,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """获取分析历史记录"""
        db = get_db()
        records = db.get_analysis_history(code=code, query_id=query_id, days=days, limit=limit)
        return [r.to_dict() for r in records]

    def _run_analysis(
        self,
        code: str,
        task_id: str,
        report_type: ReportType = ReportType.SIMPLE,
        source_message: Optional[BotMessage] = None,
        save_context_snapshot: Optional[bool] = None,
        query_source: str = "bot"
    ) -> Dict[str, Any]:
        """
        执行单只股票分析

        内部方法，在线程池中运行
        """
        # 初始化任务状态
        with self._tasks_lock:
            self._tasks[task_id] = {
                "task_id": task_id,
                "code": code,
                "status": "running",
                "start_time": datetime.now().isoformat(),
                "result": None,
                "error": None,
                "report_type": report_type.value
            }

        try:
            # 延迟导入避免循环依赖
            from src.config import get_config
            from main import StockAnalysisPipeline

            logger.info(f"[TaskService] 开始分析股票: {code}")

            # 创建分析管道
            config = get_config()
            pipeline = StockAnalysisPipeline(
                config=config,
                max_workers=1,
                source_message=source_message,
                query_id=task_id,
                query_source=query_source,
                save_context_snapshot=save_context_snapshot
            )

            # 执行单只股票分析（启用单股推送）
            result = pipeline.process_single_stock(
                code=code,
                skip_analysis=False,
                single_stock_notify=True,
                report_type=report_type
            )

            if result:
                result_data = {
                    "code": result.code,
                    "name": result.name,
                    "sentiment_score": result.sentiment_score,
                    "operation_advice": result.operation_advice,
                    "trend_prediction": result.trend_prediction,
                    "analysis_summary": result.analysis_summary,
                }

                with self._tasks_lock:
                    self._tasks[task_id].update({
                        "status": "completed",
                        "end_time": datetime.now().isoformat(),
                        "result": result_data
                    })

                logger.info(f"[TaskService] 股票 {code} 分析完成: {result.operation_advice}")
                return {"success": True, "task_id": task_id, "result": result_data}
            else:
                with self._tasks_lock:
                    self._tasks[task_id].update({
                        "status": "failed",
                        "end_time": datetime.now().isoformat(),
                        "error": "分析返回空结果"
                    })

                logger.warning(f"[TaskService] 股票 {code} 分析失败: 返回空结果")
                return {"success": False, "task_id": task_id, "error": "分析返回空结果"}

        except Exception as e:
            error_msg = str(e)
            logger.error(f"[TaskService] 股票 {code} 分析异常: {error_msg}")

            with self._tasks_lock:
                self._tasks[task_id].update({
                    "status": "failed",
                    "end_time": datetime.now().isoformat(),
                    "error": error_msg
                })

            return {"success": False, "task_id": task_id, "error": error_msg}


# ============================================================
# 便捷函数
# ============================================================

def get_task_service() -> TaskService:
    """获取任务服务单例"""
    return TaskService.get_instance()
