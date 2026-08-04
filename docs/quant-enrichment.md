# ABU、Kronos 与 vn.py 量化增强

DSA可以在每只A股或ETF完成原分析后，可选调用独立的量化增强流程：

- ABU输出明确的日线、周线规则信号和指标状态；
- Kronos输出未来价格路径的概率情景；
- vn.py Alpha只评价当前ABU规则信号在历史上的结果，不训练模型，也不输出另一项预测；
- DSA负责保存统一结果、展示报告并复用既有通知渠道。

三个结论保持分离。vn.py的“方向胜率”是相同规则信号在已完成历史窗口中的统计结果，不能解释为未来上涨概率。样本少于20次标记为低可信度，20至59次为中等，60次及以上为高。

## 配置

```bash
QUANT_ENRICHMENT_ENABLED=true
QUANT_ABU_ROOT=/absolute/path/to/abu
QUANT_ABU_CONFIG=/absolute/path/to/abu/daily_signal.kronos.json
QUANT_ABU_PYTHON=/absolute/path/to/abu/.venv/bin/python
QUANT_VNPY_ROOT=/absolute/path/to/vnpy
QUANT_VNPY_PYTHON=/absolute/path/to/vnpy/.venv/bin/python
QUANT_VNPY_VALIDATION_ENABLED=true
QUANT_ENRICHMENT_TIMEOUT_SECONDS=600
```

Python路径可留空，此时继承DSA解释器；独立虚拟环境部署时应显式配置。该能力默认关闭，路径不写死在代码中；ABU/Kronos或vn.py超时、缺失或运行失败时，DSA保留原分析结果并在量化区显示降级状态。当前只支持六位A股和ETF代码。机器调用模式不会改写ABU的人类报告和信号历史，避免并发标的互相覆盖。

ABU的标准JSON契约包含数据质量、拆分调整、技术指标、事件、Kronos结果和同口径历史行情。DSA持久化前会移除历史K线，只保存分析结果及vn.py评价。
