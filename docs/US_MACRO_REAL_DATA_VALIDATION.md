# 美国宏观 MVP 真实数据验证

验证日期：2026-07-19（Asia/Shanghai）

## 执行

```bash
python3 main.py --us-macro --dry-run --no-notify
```

受控网络运行退出码为 0，耗时约 54 秒；未发送通知。FRED 成功获取 7/7 个序列：目标利率上下限、DFF、SOFR、DGS2、DGS10、VIXCLS。最新观测日期为 2026-07-16 至 2026-07-18；均未超过日频 7 天过期阈值。2Y 为 4.16%、10Y 为 4.57%，曲线为 +0.41 个百分点（41bp）。

Yahoo Finance 对九项市场资产均返回上游限流，报告降级为 FRED 数据与中性/低置信度规则结果；未伪造行情。发现并修复了 Yahoo 特殊 ticker 被错误追加 `.SZ` 的问题，以及 FRED 请求异常可能在日志中包含 URL 查询参数的问题。

SQLite 默认路径为 `./data/stock_analysis.db`，使用 `analysis_history` 的 `global_macro` 记录保存快照和规则结果。初次验证发现同日重复运行会插入记录，现已改为按 `us_macro_YYYY-MM-DD` 更新；该更新路径已由专项回归覆盖。

## 已知限制

本次 Yahoo 验证受上游限流影响，未取得实际市场价格、均线和收益率，待限流窗口恢复后以可选网络测试复验。未接入 DeepSeek、飞书、Actions、晚报或预测复盘。
