# 选股引擎

DSA 将选股能力作为主项目的一部分维护。实现参考 [AlphaSift](https://github.com/ZhuLinsen/alphasift) 提交 [`9f522747caafd3c0b1ddb7e14d5cf44c8580b6cf`](https://github.com/ZhuLinsen/alphasift/commit/9f522747caafd3c0b1ddb7e14d5cf44c8580b6cf)，并按 Apache License 2.0 修改和分发。衍生文件保留来源头，许可证位于 `src/services/screening/LICENSE`，第三方声明见根目录 `THIRD_PARTY_NOTICES.md`。

## 代码边界

- `src/services/screening/`：快照、日 K、策略加载、过滤、评分、风险、LLM 重排与热点实现。
- `src/services/screening/strategies/`：随 DSA 版本发布的策略 YAML。
- `src/services/screening/pipeline.py`：筛选流程的直接入口。
- `src/services/screening_service.py`：DSA 业务编排，直接调用 pipeline，负责配置、数据源上下文、响应归一化、缓存与错误映射。
- `src/storage.py`：使用 DSA 现有 SQLAlchemy/SQLite 基础设施持久化已完成的选股运行，不另建文件数据库。
- `api/v1/endpoints/screening.py`：`/api/v1/screening` API。
- `apps/dsa-web/src/api/screening.ts` 与 `StockScreeningPage.tsx`：Web 调用与展示。

服务层静态调用 `screening.pipeline`、`screening.strategy` 和 `screening.hotspot`。核心逻辑不通过模块名探测、动态适配器或多套路由分发，因此代码结构、错误边界和打包收集目标均由主项目直接定义。

## 配置

默认关闭：

```dotenv
SCREENING_ENABLED=false
```

Web“基础设置”页展示“选股”开关。开启后左侧显示“选股”入口并允许执行策略、热点和选股任务；关闭后入口隐藏，选股 API 继续拒绝业务请求。

常用可选项：

```dotenv
SCREENING_DATA_DIR=data/screening
SCREENING_SNAPSHOT_CACHE_TTL_SEC=300
SCREENING_SOURCE_CALL_TIMEOUT_SEC=
SCREENING_HOTSPOT_CALL_TIMEOUT_SEC=8
SCREENING_HOTSPOT_SEARCH_TIMEOUT_SEC=12
SCREENING_SNAPSHOT_CALL_TIMEOUT_SEC=60
SCREENING_DAILY_CALL_TIMEOUT_SEC=20
SCREENING_EASTMONEY_MIN_INTERVAL_SEC=1.0
SCREENING_EASTMONEY_JITTER_SEC=0.3
```

路径、缓存、超时和限流项只影响选股链路。`SCREENING_SNAPSHOT_CACHE_TTL_SEC` 默认 300 秒，设为 `0` 可关闭新鲜快照复用。`SCREENING_HOTSPOT_CALL_TIMEOUT_SEC` 的正数值是默认热点 provider 单次板块、成分股或直接详情 fallback 调用的总预算，后续 fallback 和并行成分股源共用同一截止时间，并把剩余时间传入可终止的 AkShare 子进程与 HTTP socket；设为 `0/off/disabled` 只关闭这层总预算，各真实数据源仍保留自身硬超时。`SCREENING_HOTSPOT_SEARCH_TIMEOUT_SEC` 是用户主动新闻搜索的端到端截止时间，缓存 owner 等待、重新竞争和 provider 子进程共享同一个绝对 deadline；`0/off/disabled` 会回退到安全默认值 12 秒，而不是无限等待。完整示例以 `.env.example` 为准。

## API 契约

| 路径 | 方法 | 行为 |
| --- | --- | --- |
| `/api/v1/screening/status` | GET | 返回开关、引擎状态、契约版本、参考项目和数据源健康信息 |
| `/api/v1/screening/strategies` | GET | 返回选股策略 |
| `/api/v1/screening/hotspots` | GET | 读取缓存或显式刷新热点题材 |
| `/api/v1/screening/hotspots/{topic}` | GET | 返回题材路线、成分股与核心股；`include_search=true` 时按需搜索近期消息 |
| `/api/v1/screening/screen` | POST | 同步执行选股；可传匿名 `variant_seed` 在每次运行中生成有界的近分候选组合 |
| `/api/v1/screening/screen/tasks` | POST | 提交后台选股任务；请求字段与同步接口一致 |
| `/api/v1/screening/screen/tasks/{task_id}` | GET | 查询任务进度、错误或最终结果 |
| `/api/v1/screening/history` | GET | 按策略、市场查询最近完成的选股运行摘要 |
| `/api/v1/screening/history/{run_id}` | GET | 读取一条持久化的完整选股结果 |
| `/api/v1/screening/source-history` | GET | 汇总历史运行中的快照源命中、错误和降级次数 |

后台任务使用 `report_type=screening_screen`，Web 会保存活动任务 ID，并在页面恢复时继续轮询。任务状态会分别提示全市场快照、候选上下文、LLM 重排、最终评分和新闻事件增强等阶段；完成后的结果同时写入 DSA 数据库，因此服务重启后仍可按 `run_id` 查询。

## 核心流程

```text
策略加载
  -> 全市场快照与字段标准化
  -> 硬过滤
  -> 因子评分与风险调整
  -> 候选上下文补充
  -> LLM 重排（可降级）
  -> 风险/组合约束与近分候选轮换
  -> Top 候选 DSA 行情/基本面/新闻增强
  -> API 归一化响应与 DSA 数据库持久化
  -> 用户按需进入 DSA 单股深度分析
```

- 全市场快照在短 TTL 内优先复用最近成功结果；新缓存会记录完整且有序的数据源优先级，只在当前优先级与写入时一致时复用，因此同一来源链中的后备源结果可以加速后续请求，修改来源配置后则会重新读取实时数据。缓存过期后按配置优先级逐源尝试，单一数据源失败后继续降级，并记录 source health 与 last-good 缓存。当前 Sina、Efinance、AkShare/东财和 Tushare 快照接口均不提供增量游标或变更序列，因此 TTL 内可以零请求复用，TTL 到期后仍需重新读取全表；本地比较前后差异不能减少上游传输量，不作为“增量拉取”宣传。
- 有 `TUSHARE_TOKEN` 时默认优先 Tushare，否则默认从 Sina 开始；显式 `SNAPSHOT_SOURCE_PRIORITY` 始终优先。
- 日 K 优先通过请求级 fetcher 复用 DSA 历史行情链路，无结果时再走筛选引擎的数据源降级；该桥接不会替换进程级函数，因此重叠选股请求之间不会共享 wrapper 或阻塞彼此。
- LLM 重排前只补充有限候选上下文，最终候选再补行情、基本面、新闻和摘要，控制请求量。
- 默认本地 `scorecard` 会覆盖完整短名单，保证所有可能进入近分轮换的候选使用同一最终评分口径；多个后置分析器串联时，每一步完成后都会按最新分数重排，因此后续 `dsa` 与 `external_http` 的 `POST_ANALYSIS_MAX_PICKS` 上限作用于当前真实前列。远程状态按实际提交候选记录，外部响应中的超限代码不会改写未提交候选；启用远程分析时轮换只会在已完成相同分析的候选之间发生。
- 模型、渠道、base URL、额外 headers、fallback、timeout 和 token 上限在单次调用范围内注入，不改写用户配置；主模型即使 HTTP 调用成功，但返回空内容、非 JSON 或覆盖率不足，也会继续尝试已配置的备用模型。最终 JSON 必须在 `content` 块或 `output` 块中；`reasoning_content`（链式思考）被视为内部辅助，不作为最终结果。
- 热点榜单刷新与选股长流程可并行执行；列表默认不批量预取详情，用户选中具体题材时才加载该题材详情；显式刷新后若继续保留当前题材，Web 会同步绕过详情缓存重拉该题材，保证榜单与详情来自同次刷新。
- 热点成分股并行获取东方财富与同花顺数据，并按固定数据源优先级合并，避免响应先后改变重复股票的字段：正数 `SCREENING_HOTSPOT_CALL_TIMEOUT_SEC` 作为默认 provider 整次调用的共享预算，板块列表、成分股以及引擎失败后的直接详情 fallback 都进入该预算；AkShare/东方财富的可终止子进程与同花顺 HTTP connect/read timeout 每一步只使用剩余时间，fallback 不会重新获得完整预算。直接详情 fallback 不再额外启动无法由该预算强制回收的实时行情预取，行情字段以已受控的成分股源结果为准。超时子进程会 terminate/kill 并回收；进程级并发槽限制活跃任务数量，方法返回前会等待已接纳的 worker 结束，不遗留后台线程。关闭整次调用预算时，各单源仍保留默认硬超时；单源失败不会阻止另一源和本地核心股回退。
- “搜索最新消息”复用 DSA 原生搜索服务的 provider 优先级、SearXNG 公共实例能力、结果缓存与请求合并，同一缓存键只有 owner 可以启动供应商链；owner 未产出可缓存结果时，等待者重新竞争且未获得所有权的请求继续等待，但缓存等待、抢占和 provider 执行共用请求的绝对 deadline，不会在排队后重新获得完整超时。搜索只补充有链接的事件/催化，不从网页内容推断板块成分股；增强记录分别追加到展示路线和原始时间线，不覆盖已有 `timeline`。搜索由用户主动触发，摘要在本地确定性压缩，不调用 LLM；响应以 `available`、`no_results`、`unavailable` 区分有结果、有效空结果和超时/容量/供应商失败，Web 不会再把运行失败提示成“没有近期消息”。搜索增强仅存在于本次响应，不写入或续期共享热点详情缓存，默认详情请求不会看到搜索状态或增加搜索等待。供应商子进程在启动、执行或清理任一阶段失败时都会释放进程级容量。
- 热点实时请求失败时优先使用 last-good cache；无缓存时返回稳定空态与明确错误。

## 结果轮换

Web 会在浏览器本地生成一个不含用户信息的匿名种子，并随同步或后台选股请求传入 `variant_seed`。如果 Web Storage 不可读写，则在当前页面会话的模块内存中复用同一个临时种子，保证同步和后台任务入口一致。服务端将匿名种子与本次运行 ID、市场和策略共同作为扰动输入：不同浏览器以及同一浏览器的不同运行，都可能在质量接近的候选中看到不同股票。

扰动不是随机改分，也不会绕过策略：硬过滤、风险否决、因子/LLM 得分、最终评分和组合集中度惩罚全部先执行。默认本地评分覆盖完整短名单；启用有数量上限的远程后置分析时，只有完成相同分析的候选才可参与轮换。分析器产出的候选顺序是轮换输入的权威顺序，并列分不会再按股票代码重新排序；原 Top-N 的前半部分和明显高于截止分的候选始终受保护，只有后半部分名额可从不低于原截止分 1.5 分的近分池中抽取，入选候选继续保持该输入相对顺序。种子不写入选股结果或运行历史。未传 `variant_seed` 或将轮换比例设为 0 时返回严格输入 Top-N，保持脚本与旧客户端兼容。

## 缓存与持久化

| 数据 | 位置 | 有效期/行为 |
| --- | --- | --- |
| 全市场快照 | `data/screening/snapshot.last_good.json` | 默认 5 分钟内直接复用且不标记 fallback；过期后请求实时源，实时源全部失败时仍可按最大陈旧时间约束回退并标记 stale/fallback |
| 个股日 K | `data/screening/daily_history/` | 按代码、来源和回看窗口分键，默认 TTL 24 小时；实时源全部失败时可使用过期缓存并标记 stale |
| 行业/概念映射 | `data/screening/industry_provider_cache/` | 默认 TTL 24 小时，并保存板块热度历史用于趋势计算 |
| 热点列表与历史 | `data/screening/hotspots.json`、`hotspot.history.jsonl` | 显式刷新写入；实时失败时回退最近可用快照 |
| 热点详情 | `data/screening/hotspot_details/` | 默认 TTL 30 分钟；只缓存结构化基础详情，显式消息搜索不写入或续期该缓存；实时失败时可回退过期详情并返回陈旧时长 |
| DSA 实时行情 | `DataFetcherManager` 的行情缓存 | 默认 TTL 10 分钟，沿用 `REALTIME_CACHE_TTL` |
| DSA 基本面/资金流 | `DataFetcherManager` 的基本面缓存 | 默认 TTL 120 秒，沿用 `FUNDAMENTAL_CACHE_TTL_SECONDS` |
| DSA 新闻/公告事件 | `SearchService` 内存缓存 | 成功结果默认 TTL 10 分钟；同题材并发请求在父进程合并，实际供应商链在限流、可终止的子进程中执行；服务重启后重新查询 |
| 完整选股结果 | DSA 数据库 `screening_runs` 表 | 完成后按 `run_id` 幂等写入；数据库写入失败不阻断选股主流程 |

候选上下文模块也支持 24 小时文件缓存，但 DSA 集成默认关闭其独立新闻/公告抓取，改用 DSA 自己的资讯、基本面和实时行情链路，避免同一候选重复请求两套数据源。

## 两类策略的边界

DSA 中存在两类用途不同的策略文件：

| 位置 | 解决的问题 | 加载方 | 执行阶段 |
| --- | --- | --- | --- |
| `src/services/screening/strategies/*.yaml` | 从全市场筛出哪些候选 | `src/services/screening/strategy.py` | 快照过滤、因子评分、风险和排序 |
| `strategies/*.yaml` | 对单只股票如何分析和形成结论 | `src/agent/skills/base.py` | DSA Agent/报告分析 |

即使 `shrink_pullback`、`volume_breakout` 同名，两者也使用不同目录、Schema 和 loader，不会相互覆盖。筛选策略可通过 `analysis_skills` 声明下一阶段建议使用的分析 skill；Web 的“进一步深度分析”会显式携带这些 skill。未声明映射的筛选策略继续使用用户当前选择或默认分析策略，不做含义不可靠的强行映射。

## DSA 原生能力复用

- 行情：日 K 优先调用 DSA `DataFetcherManager`，无结果才进入筛选模块自己的多源 fallback；最终候选继续补 DSA 实时行情。
- 基本面与资讯：最终候选复用 DSA 基本面上下文和 `SearchService`；资本流向来自 DSA 基本面上下文，重要公告/业绩/减持事件调用 DSA `search_stock_events`，热点消息搜索沿用其数据源优先级、时效过滤、缓存和同请求合并，仅将真实供应商调用隔离到可终止子进程，不重复维护独立资讯入口。
- 模型：沿用 DSA LiteLLM 模型、渠道、fallback、base URL、额外 headers、超时和 token 配置。
- 任务与页面：复用 DSA 后台任务队列、Web 轮询和桌面端同源 Web 资源。
- 存储与后续分析：运行结果写入 DSA 数据库；候选可进入 DSA 原生单股分析并携带策略 skill。

对照固定参考提交，快照、日 K、美股、行业/概念、热点、候选新闻/公告/资金流、字段标准化、过滤、评分、风险、排序和数据源熔断等原始数据与选股能力均已纳入；其中公告/事件和资金流在 DSA 编排层分别接入原生事件搜索与基本面上下文。参考项目另外提供独立 CLI/server、JSON 文件 store、报告渲染、doctor、运行/数据源历史和 T+N 评估：本实现只吸收 DSA 确实缺少的运行历史与数据源历史，并接到 DSA 数据库；CLI/server 不重复建设，T+N 评估与表现统计继续复用 DSA 已有 BacktestService，避免形成第二套回测真源。实时 source health 已在 `/status` 返回，历史稳定性由 `/source-history` 补齐。

## 收益

1. 选股服务、策略、API、Web 和打包脚本在同一版本中演进，避免契约漂移。
2. 服务层只有一套原生调用路径，状态探针和业务请求反映相同实现。
3. Docker 与桌面产物直接收集同一份模块和策略资源，部署结果更一致。
4. 数据源降级、评分和策略变化可以在主仓库完成端到端审查与回归。
5. 来源 commit、许可证和逐文件归因明确，便于后续选择性同步上游修复。

## 风险与控制

| 风险 | 影响 | 控制措施 |
| --- | --- | --- |
| 主仓库维护面扩大 | 数据源或策略问题由 DSA 直接承担 | 模块边界、契约测试和 CI 打包探针共同约束 |
| 与参考项目逐渐分叉 | 上游修复不能直接覆盖 | 固定参考 revision，逐模块比较并选择性移植 |
| 数据源限流或字段变化 | 快照、热点或日 K 降级 | timeout、retry、source health 与 last-good cache |
| LLM 超时或格式异常 | 重排不可用或解释字段缺失 | 非结构化响应继续尝试备用模型；全部失败时保留因子排序，并返回尝试模型与失败原因 |
| 结果轮换扩大候选差异 | 临界候选可能因浏览器不同而变化 | 仅轮换近分尾部位，保持硬过滤、风险否决、分值和头部候选不变；无种子时关闭 |
| 缓存目录变化 | 升级后旧缓存不会自动复用 | 新目录独立为 `data/screening`；升级前按需备份 |
| 运行历史增长 | 完整候选结果会增加数据库体积 | 历史接口默认只读摘要，运维可按现有数据库备份/保留策略管理 |
| 配置与 API 更名 | 旧自动化需同步调整 | 在发布说明明确 `SCREENING_ENABLED` 与 `/api/v1/screening` |
| 许可证归因遗漏 | 发布合规风险 | 保留 LICENSE、THIRD_PARTY_NOTICES 和衍生文件头 |

选股结果仅用于研究和辅助判断，不构成投资建议，也不保证收益或数据完整性。

## 更新参考实现

AlphaSift 是参考来源，不是自动同步源。更新时应：

1. 记录目标 commit 和许可证变化；
2. 比较 `src/services/screening/` 的 DSA 特有修改，按模块选择性移植；
3. 更新衍生文件头、`REFERENCE_REVISION` 和 `THIRD_PARTY_NOTICES.md`；
4. 检查 pipeline、API/Web 字段、数据源降级、策略资源与冻结打包；
5. 更新本文档和 `docs/CHANGELOG.md`，完成后端、Web、Docker/桌面验证。

## 回滚

- 业务回滚：设置 `SCREENING_ENABLED=false` 并重启；普通个股分析、报告、通知和问股不受影响。
- 代码回滚：revert 引入选股引擎的提交并重建后端、Docker 与桌面产物。
- 数据回滚：如需保留选股缓存和运行历史，先备份 `data/screening/` 与 DSA 数据库；代码回滚不会主动删除 `screening_runs` 用户数据。
