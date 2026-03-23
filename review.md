# DSA 项目问题梳理与优先级总结（已核验版）

> 导出日期：2026-03-19
> 核验范围：当前本地仓库代码、配置、文档、Web/Bot/CLI/API 入口
> 核验方式：静态核对，不包含远端 GitHub PR/commit 链路复原，不包含运行期在线验证
> 状态说明：下文“已完成”均指当前修复分支 / PR 中已经落地的改动，不代表主干已合入

---

## 一、文档结论

这次核验后，可以把原始报告里的信息收敛成 4 类问题：

1. **能力漂移**：文档、配置项、Web 设置入口与实际实现状态不完全一致。
2. **稳定性缺口**：部分核心链路存在确定性的异常处理、超时、配置解析和跨域兼容问题。
3. **可用性缺口**：有些能力已经有后端或 CLI/Bot 能力，但 API / Web 闭环仍不完整。
4. **语义不完整**：部分功能“看起来支持”，但底层统计或契约语义并不完整。

从当前仓库状态看，最优先的仍然是：

- 对齐 Deep Research / EventMonitor 的真实状态；
- 修复 `pipeline.py` 异常掩盖、`formatters.py` 类型签名、单 Agent / 工具并发超时治理、CORS 兼容与配置解析容错；
- 随后处理 Scheduler 时区、策略回测语义、大盘复盘 API / Web 闭环与代理配置统一；
- 最后再做交易理念解耦、舆情增强、长会话裁剪与独立爬虫服务等中长期治理。

---

## 二、本轮已完成修复

### 2.1 已完成：对齐 Deep Research / EventMonitor 的真实状态

当前分支已做的收敛动作：

- 在 `src/core/config_registry.py` 中将 Deep Research / EventMonitor 相关配置标记为兼容保留、只读且不可编辑；
- 在 Web 设置页隐藏当前分支无实现支撑的 Deep Research / EventMonitor 配置项；
- 保留配置读取兼容，避免已有 `.env` 在升级时直接失效。

需要明确的是：

> 这次修复的是“能力状态对齐”，不是“恢复 Deep Research / EventMonitor 实现”。

### 2.2 已完成：修复 `pipeline.py` 异常掩盖原始错误

`fetch_and_save_stock_data()` 已在进入 `try` 前给 `stock_name` 提供安全默认值，避免在股票名称查询本身失败时再次抛出未绑定变量错误并覆盖原始异常。

### 2.3 已完成：修复 `slice_at_max_bytes()` 返回类型签名

`src/formatters.py` 中 `slice_at_max_bytes()` 的类型标注已从错误的 `str` 修正为与实际实现一致的二元组返回。

### 2.4 已完成：为 single-agent / tool fan-out 增加超时保护

当前分支已补齐：

- LLM 调用会继承剩余 wall-clock timeout 预算；
- single-agent 共享执行循环的 wall-clock timeout 预算；
- 单工具步骤也会受工具等待超时约束；
- tool fan-out `as_completed()` 的批次等待超时；
- 超时后对未完成工具调用返回结构化错误结果，而不是无限等待；
- multi-agent orchestrator 向下传递剩余预算，避免 stage 之间失控扩张。

仍需保留的边界是：

> 当前是 cooperative timeout / stop-waiting 级别治理，不是对底层阻塞线程的强制中断。

### 2.5 已完成：修复 CORS wildcard + credentials 冲突

`api/app.py` 已避免在 `CORS_ALLOW_ALL=true` 时继续启用 `allow_credentials=True`，从而消除浏览器 credential 模式下的显式不兼容配置。

### 2.6 已完成：建立统一安全数值配置解析层

当前分支已在 `src/config.py` 中引入统一的安全数值解析辅助函数，并应用到一批核心数值配置项上，使非法 `.env` 值会回退到默认值或夹逼到合法区间，而不是直接在启动期抛异常。

### 2.7 已完成：同步文档与设置页说明

本轮还同步更新了：

- `.env.example`
- `docs/CHANGELOG.md`
- Web 设置页文案与可见项
- `AGENT_ORCHESTRATOR_TIMEOUT_S` 在配置元数据中的默认值已与运行时默认 `600` 秒对齐

以保证“实际行为 / 配置元数据 / 前端展示”三者尽量一致。

---

## 三、已确认事实

### 3.1 Deep Research / EventMonitor 存在“文档和配置仍在，但实现缺失”的能力漂移

当前仓库中：

- `docs/CHANGELOG.md` 仍将 `ResearchAgent`、`/research`、`EventMonitor` 作为已发布能力记录；
- `src/config.py` 与 `src/core/config_registry.py` 仍保留了 `AGENT_DEEP_RESEARCH_BUDGET`、`AGENT_DEEP_RESEARCH_TIMEOUT`、`AGENT_EVENT_MONITOR_*` 等配置；
- 但当前 `src/agent/` 目录下未找到 `research.py`、`events.py` 等对应核心实现文件；
- 当前仓库中也未找到 `bot/commands/research.py`。

因此，可以确认的问题是：

> 当前仓库存在明显的能力漂移，至少对外宣称过的 Deep Research / EventMonitor 在当前代码状态下无法确认完整可用。

### 3.2 大盘复盘并非“完全没有入口”

原始报告中“大盘复盘无 API / Web / Bot 入口”的说法不准确。

当前可确认的是：

- CLI 入口存在：`main.py --market-review`
- Bot 入口存在：`/market`
- 核心逻辑存在：`src/core/market_review.py`
- 当前未发现正式 API endpoint
- 当前未发现 Web 专用页面或显式入口

更准确的结论应为：

> 大盘复盘已有 CLI + Bot + 核心逻辑，缺口主要在 API / Web 正式闭环。

### 3.3 Agent 历史并非“无限增长”，但缺少 token-aware 治理

原始报告中“对话历史无限增长”这一表述不准确。

当前链路是：

- `ConversationSession.get_history()` 读取数据库消息历史；
- `DatabaseManager.get_conversation_history()` 默认 `limit=20`；
- 因此并不是无上限加载。

但更深层的问题仍然成立：

- 当前仅按条数裁剪；
- 20 条长消息仍可能形成过大的上下文；
- 还没有摘要压缩或 token-aware 裁剪机制。

更准确的结论应为：

> 当前已有条数上限，但没有 token-aware 上下文治理。

### 3.4 策略回测存在“看似支持策略，实际不是策略级统计”的语义问题

`BacktestService.get_strategy_summary()` 当前实现会直接返回全局汇总，再补一个 `strategy_id` 字段。

这意味着：

- 当前并没有真实的策略级回测汇总；
- `AGENT_STRATEGY_AUTOWEIGHT` 这类能力不能建立在真实的策略表现统计上；
- 这属于“表面可用，实际语义不足”的问题。

这是当前仓库里最明确、最值得优先修正的回测语义问题之一。

### 3.5 交易理念被硬编码在多条分析路径中

当前仓库中，“趋势交易 + 不追高 + 多头排列”等规则明确硬编码在以下路径：

- `src/analyzer.py`
- `src/agent/executor.py`
- `src/agent/agents/technical_agent.py`

这说明：

- analyzer / 单 Agent / 多 Agent 技术分析路径共享同一类交易理念约束；
- 策略切换还未真正做到“交易哲学可替换”；
- 长期会限制策略体系的扩展性和一致性。

### 3.6 代理配置确实存在双套语义

当前仓库中同时存在两套代理入口：

- `USE_PROXY / PROXY_HOST / PROXY_PORT`
  - 用于 `main.py` 启动阶段的本地代理注入
  - 仍出现在 `.env.example` 和 FAQ 文档中
- `HTTP_PROXY / HTTPS_PROXY`
  - 由 `src/config.py` 读取并写回环境变量
  - 也在配置注册表和 Web 设置里暴露

因此更准确的结论不是“某一份文档一定写错了”，而是：

> 当前项目存在双套代理配置语义，用户侧理解和不同入口行为都可能不一致，值得统一。

---

## 四、已确认的 P0 稳定性问题

### 4.1 `pipeline.py` 存在异常掩盖原始错误的风险

在 `fetch_and_save_stock_data()` 中，`stock_name` 在 `try` 内赋值，但 `except` 中直接使用。

如果异常发生在 `stock_name = self.fetcher_manager.get_stock_name(code)` 之前或该行本身抛异常，则 `except` 中可能再次触发未绑定变量错误，覆盖原始异常。

该问题已在当前修复分支中处理，建议保留回归测试，防止后续重构再次引入同类问题。

### 4.2 `slice_at_max_bytes()` 的返回类型签名错误

`src/formatters.py` 中 `slice_at_max_bytes()` 的签名标注为返回 `str`，但实际返回 `(truncated, remaining)` 二元组。

这是确定性的类型签名错误，会影响静态检查和调用者理解；当前修复分支已完成修正。

### 4.3 单 Agent / 工具并发的超时治理不完整

这里需要修正原始报告中“Agent 主循环没有总超时”的表述强度。

当前状态更准确地说是：

- 多 Agent orchestrator 已有 cooperative timeout；
- 共享 `run_agent_loop()` 本身没有总 wall-clock timeout；
- `src/agent/runner.py` 中工具并发执行 `as_completed()` 未设置 timeout；
- 因此 single-agent 路径和工具 fan-out 路径仍有悬挂风险。

所以这条应表述为：

> Agent 超时治理并非完全缺失。当前修复分支已经补齐主要缺口，但仍未做到对阻塞线程的强制中断。

### 4.4 CORS 存在 `* + credentials` 冲突

`api/app.py` 中当 `CORS_ALLOW_ALL=true` 时，会将 `allow_origins=["*"]`，同时仍设置 `allow_credentials=True`。

这在浏览器 credential 模式下是不兼容的，属于明确的配置级错误风险；当前修复分支已完成修正。

### 4.5 配置解析存在直接 `int()` / `float()` 转换

`src/config.py` 中多个配置项直接执行 `int()` / `float()` 解析。

这意味着：

- 一处 `.env` 配置错误可能导致应用启动失败；
- 错误提示也不够友好；
- 多入口环境下排查成本较高。

这条问题成立，当前修复分支已经引入统一安全解析层并覆盖了一批关键配置项。

---

## 五、已确认的 P1 / P2 级问题

### 5.1 Scheduler 目前没有显式时区配置

当前调度系统只读取 `SCHEDULE_TIME`，未发现独立的 `SCHEDULE_TIMEZONE` 或等价配置。

这意味着调度行为依赖运行环境本地时区，在 Docker、CI 或海外服务器场景下会带来偏移风险。

### 5.2 大盘复盘缺 API / Web 闭环

当前仓库可以确认：

- 有 CLI
- 有 Bot
- 有核心逻辑
- 没有正式 API endpoint
- 没有明确的 Web 页面/入口

因此“补齐 API / Web 闭环”仍然是合理的短期任务。

### 5.3 历史接口契约存在“后端更宽，前端更窄”的现状

当前后端历史详情接口支持：

- 传主键 ID
- 传 `query_id`

但当前 Web 前端实际主要按数值型 `id` 使用和建模。

因此更准确的问题不是“前后端完全冲突”，而是：

> 后端契约比前端公开使用方式更宽，是否正式支持 `query_id` 访问需要进一步明确。

### 5.4 搜索层舆情增强优先级高于直接接入重型爬虫

从当前架构看，项目已经具备：

- 多搜索 provider 架构；
- 新闻/情报聚合路径；
- 可扩展的搜索服务。

因此原始报告关于“先做搜索层舆情增强，再评估独立爬虫服务”的方向是合理的。  
但这部分属于方案建议，不是代码事实本身。

---

## 六、需要修正或保留谨慎表述的内容

### 6.1 关于 Git 丢失链路

当前本地仓库可以确认：

- `d1ec2c8 feat: multi-agent architecture` 对应能力轨迹在本地有痕迹；
- Deep Research / EventMonitor 当前实现缺失；
- CHANGELOG 与配置仍保留相关记录。

但当前本地核验 **不能单独坐实** 以下强结论：

- 某个具体 PR 一定被另一个具体 PR squash 覆盖；
- `28126db`、`a472b82`、`#648`、`#649` 的完整覆盖链路；
- 某些文件一定是在哪一次 merge 中被删除。

因此，这部分应保留为：

> 当前能确认“能力缺失/漂移”，但具体远端 Git 覆盖链路仍需进一步核实。

### 6.2 关于大盘复盘

应从“无 API / Web / Bot 入口”修正为：

> 已有 CLI + Bot，主要缺 API / Web 正式入口。

### 6.3 关于 Agent 历史

应从“无限增长”修正为：

> 当前已有条数上限，但没有 token-aware 裁剪和摘要机制。

### 6.4 关于 Agent 超时

应从“Agent 主循环没有总超时”修正为：

> 多 Agent orchestrator 已有 cooperative timeout，但 single-agent / tool fan-out 路径仍缺完整超时保护。

### 6.5 关于代理配置

应从“`.env.example` 与实际配置不一致”修正为：

> 项目中存在两套代理配置语义，需要明确主入口、兼容关系与优先级。

---

## 七、建议的执行顺序

### 第一批：当前分支已完成

1. 对齐 Deep Research / EventMonitor 的真实状态
2. 修复 `pipeline.py` 异常掩盖问题
3. 修复 `slice_at_max_bytes()` 类型签名
4. 为 single-agent / tool fan-out 路径补超时与取消保护
5. 修复 CORS wildcard + credentials
6. 建立统一安全配置解析层

### 第二批：建议紧接着处理

7. 为 Scheduler 增加显式时区语义
8. 修正策略回测语义，至少先停止将全局汇总伪装成策略汇总
9. 补齐大盘复盘 API / Web 闭环
10. 统一代理配置入口和文档说明

### 第三批：中期治理

11. 将交易理念从硬编码改为可注入结构
12. 先做搜索层舆情增强，再考虑独立爬虫服务
13. 为长会话增加 token-aware 裁剪与摘要压缩
14. 明确历史接口是否正式支持 `query_id`

### 第四批：长期规划

15. 独立舆情爬虫微服务
16. 将回测系统升级为多维度可比较体系
17. 为 Multi-Agent 增加智能编排与成本治理

---

## 八、核验所依据的关键文件

以下文件是本次核验中重点参考的依据：

- `review.md` 原始内容
- `docs/CHANGELOG.md`
- `src/config.py`
- `src/core/config_registry.py`
- `src/core/pipeline.py`
- `src/formatters.py`
- `src/agent/runner.py`
- `src/agent/orchestrator.py`
- `src/agent/conversation.py`
- `src/storage.py`
- `src/services/backtest_service.py`
- `src/core/backtest_engine.py`
- `api/app.py`
- `api/v1/endpoints/history.py`
- `bot/commands/market.py`
- `main.py`

---

## 九、一句话总结

DSA 当前最先该处理的，不是继续堆新功能，而是先把：

- 能力漂移
- 稳定性缺陷
- 回测与接口的语义不完整
- 已有能力但未形成 API / Web 闭环的可用性缺口

这几类问题先收敛掉。否则功能越多，越难判断“哪些真的可用、哪些只是看起来存在”。
