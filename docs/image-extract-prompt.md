# Image Extract Prompt (Vision LLM)

本文档记录 `src/services/image_stock_extractor.py` 中 `EXTRACT_PROMPT` 的完整内容，便于 PR 审查时评估指令效果。

**当修改 EXTRACT_PROMPT 时**：请同步更新此文件，并在 PR 描述中展示完整变更（before/after），以便审查者评估针对 code+name+confidence 提取的优化程度。

---

## 当前 Prompt（完整）

```
请分析这张股票市场截图或图片，提取其中所有可见的股票代码及名称。

重要：若图中同时显示股票名称和代码（如自选股列表、ETF 列表），必须同时提取两者，每个元素必须包含 code 和 name 字段。

输出格式：仅返回有效的 JSON 数组，不要 markdown、不要解释。
每个元素为对象：{"code":"股票代码","name":"股票名称","confidence":"high|medium|low"}
- code: 必填，股票代码（A股6位、港股5位、美股1-5字母、ETF 如 159887/512880）
- name: 若图中有名称则必填（如 贵州茅台、银行ETF、证券ETF），与代码一一对应；仅当图中确实无名称时可省略
- confidence: 必填，识别置信度，high=确定、medium=较确定、low=不确定

示例（图中同时有名称和代码时）：
- 个股：600519 贵州茅台、300750 宁德时代
- 港股：00700 腾讯控股、09988 阿里巴巴
- 美股：AAPL 苹果、TSLA 特斯拉
- ETF：159887 银行ETF、512880 证券ETF、512000 券商ETF、512480 半导体ETF、515030 新能源车ETF

输出示例：[{"code":"600519","name":"贵州茅台","confidence":"high"},{"code":"159887","name":"银行ETF","confidence":"high"}]

禁止只返回代码数组如 ["159887","512880"]，必须使用对象格式。若未找到任何股票代码，返回：[]
```
