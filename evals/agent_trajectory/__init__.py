# -*- coding: utf-8 -*-
"""Agent trajectory evaluation pipeline (Issue #1956).

评估管线与生产链路解耦：本包只消费 ``tool_calls_log`` 轨迹数据（纯函数指标层），
不修改 ``src/`` 下任何执行语义。PR-1 提供指标与 golden 样例，PR-2 提供 live-run 驱动。
"""
