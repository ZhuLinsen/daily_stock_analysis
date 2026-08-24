# 数据源稳定性与故障处理图示

本文面向用户、部署者和维护者，说明 DSA 已接入的数据源如何参与分析、选股和大盘复盘，以及当数据源失败时系统会怎么降级。

核心原则：先用项目已经接入并验证过的数据源，把失败路径讲清楚；新增外部数据源应放在第二阶段，避免先扩大维护面。

## 一句话答复用户

如果遇到“数据源失败”，通常不是系统只能用一个源，而是免费源被限流、上游接口临时变更、网络抖动或当前市场/标的不支持。DSA 已经内置多数据源 fallback，会按场景自动尝试下一个源；如果你希望更稳定，建议至少配置一个 token 型稳定源：

- A 股个股与选股：优先配置 `TUSHARE_TOKEN`，并保留 AkShare / Efinance / Tencent / TickFlow / Baostock / YFinance 兜底；普通个股日线按 priority 配置排序。
- 已登记 A 股指数：固定按 Tencent → AkShare → TickFlow → YFinance 降级，不读取普通日 K 的 `*_PRIORITY` 配置。
- A 股大盘复盘：配置 `TICKFLOW_API_KEY` 后，复盘聚合所需的指数和市场宽度会优先尝试 TickFlow，失败后回退现有免费源；这与单标的指数日线的 Tencent-first 固定链是不同入口。
- 港股：配置 `FUTU_OPEND_HOST` 后，Futu 可作为港股实时与基本面主源；`FUTU_HK_REALTIME_SOURCE_PRIORITY` 控制港股实时行情顺序，Longbridge、AkShare、YFinance 保留为 fallback。
- 美股：配置 `LONGBRIDGE_*` 后优先使用 Longbridge，YFinance、Finnhub、AlphaVantage 继续兜底。
- 热点题材：选股的热点实现参考 AlphaSift，默认走 EastMoney provider，并使用本地 last-good cache 降低实时接口失败影响。

## 已接入数据源矩阵

| 场景 | 已接入源 | 默认使用方式 | 失败处理 |
| --- | --- | --- | --- |
| A 股个股日线 / 技术面 | Efinance、Tencent、AkShare、Tushare、TickFlow、Pytdx、Baostock、YFinance | `DataFetcherManager` 按 priority 尝试；配置 `TUSHARE_TOKEN` 后 Tushare 自动进入候选源 | 单源失败后尝试下一个源；连续失败会短期熔断该源 |
| 已登记 A 股指数日线 / 技术面 | Tencent、AkShare、TickFlow、YFinance | 当前 5 个 `IndexRegistry` 标的固定按 Tencent → AkShare → TickFlow → YFinance 尝试，不读取普通日 K 的 `*_PRIORITY` 配置 | 未配置、熔断、异常或空结果均继续下一源；全部失败返回空结果并记录汇总告警 |
| A 股实时行情 | Tencent、AkShare Sina、Efinance、AkShare EM、Tushare | `REALTIME_SOURCE_PRIORITY` 控制顺序，默认偏向 Tencent / Sina 这类轻量源 | 失败源记录 `fallback_from`，成功源继续返回 |
| A 股大盘复盘 | TickFlow、AkShare、Tushare、Efinance | 配置 `TICKFLOW_API_KEY` 后，复盘聚合的主指数和市场宽度优先尝试 TickFlow；不等同于单标的指数日线链 | TickFlow 权限不足或失败时回退 AkShare / Tushare / Efinance 链路 |
| 选股快照 | Tushare、Sina、Efinance、AkShare EM、EastMoney Datacenter | 有 `TUSHARE_TOKEN` 时自动把 `tushare` 放入快照优先级；否则使用免费源链路 | 选股引擎维护 source health；状态接口透出 snapshot/daily health |
| 选股日线补特征 | `DataFetcherManager` | 选股引擎优先复用现有日线与缓存链路 | 现有链路失败后才回到引擎自身的日线源 |
| 选股热点题材 | EastMoney provider、参考 AlphaSift 的 hotspot 实现、last-good cache | 未指定 provider 时默认使用 EastMoney provider | 实时失败时回退热点缓存；无缓存时返回稳定空态和可读错误 |
| 港股 | Futu、Longbridge、YFinance、AkShare、Tushare | 配置 `FUTU_OPEND_HOST` 后 Futu 作为实时与基本面主源，按 `FUTU_HK_REALTIME_SOURCE_PRIORITY` 顺序尝试 | Futu 失败时回退 Longbridge / AkShare / YFinance；Longbridge 冷却或失败时继续回退 YFinance / 其他可用源 |
| 美股 | Longbridge、YFinance、AkShare、Tushare、Finnhub、AlphaVantage、Stooq | 配置 Longbridge 凭证后参与美股日线/实时兜底；YFinance 保持基础兜底 | Longbridge 冷却或失败时回退 YFinance / 其他可用源 |

## 总体链路图

```mermaid
flowchart TD
    Q[用户触发分析/选股/大盘复盘] --> S{场景}

    S --> D[个股日线与技术面]
    S --> R[实时行情]
    S --> A[选股/热点]
    S --> M[大盘复盘]

    D --> C[本地 stock_daily 缓存]
    C -->|命中且新鲜| COK[复用缓存]
    C -->|缺失或过期| DM{市场}
    DM -->|A 股个股/未登记标的| CN[按 priority 动态排序: Efinance/AkShare/Tushare/TickFlow/Pytdx/Baostock/YFinance/Tencent]
    DM -->|已登记沪深指数| CNI[Tencent -> AkShare -> TickFlow -> YFinance]
    DM -->|港股| HK[Futu if configured -> Longbridge/AkShare/YFinance fallback]
    DM -->|美股| US[Longbridge/YFinance -> Finnhub/AlphaVantage -> Stooq]

    R --> RP[REALTIME_SOURCE_PRIORITY]
    RP --> RS[Tencent -> AkShare Sina -> Efinance -> AkShare EM]
    RP --> RT[Tushare can be placed first when token/points are available]

    A --> AS[Snapshot: Tushare/Sina/Efinance/AkShare EM/EM Datacenter]
    A --> AD[Daily features: DSA DataFetcherManager]
    A --> AH[Hotspots: DSA EastMoney provider]
    AH --> AC[hotspots.json / hotspot_details last-good cache]

    M --> TF{TICKFLOW_API_KEY configured?}
    TF -->|yes| TFM[TickFlow indices and market breadth]
    TF -->|no or failed| MF[AkShare/Tushare/Efinance fallback]

    CN --> QL[质量标记: source/fallback/stale/fetch_failed]
    CNI --> QL
    HK --> QL
    US --> QL
    RS --> QL
    RT --> QL
    AS --> QL
    AD --> QL
    AC --> QL
    TFM --> QL
    MF --> QL
```

## 失败与降级图

```mermaid
flowchart LR
    A[请求某个数据块] --> B{当前源成功且数据有效?}
    B -->|是| OK[返回数据并记录 source]
    B -->|否| E[记录失败原因]
    E --> F{还有下一个可用源?}
    F -->|有| N[切换到下一源]
    N --> B
    F -->|没有| C{有 last-good cache?}
    C -->|有| STALE[返回 stale/fallback 数据并提示降级]
    C -->|没有| FAIL[返回 fetch_failed/稳定空态]

    E --> H{同源连续失败达到阈值?}
    H -->|是| CB[短期熔断该源]
    H -->|否| KEEP[保留在候选链中]
    CB --> SKIP[后续请求先跳过该源]
    SKIP --> RECOVER[冷却后半开探测恢复]
```

当前日线源熔断策略为连续失败 3 次后短期冷却约 5 分钟。它的目的不是永久禁用数据源，而是避免一个短时间不可用的源拖慢整批分析。

## 选股与热点链路

```mermaid
flowchart TD
    UI[Web 选股/热点入口] --> API[/api/v1/screening/]

    API --> SCREEN{screen}
    SCREEN --> ENV[注入 DSA LLM 与数据源运行环境]
    ENV --> CACHE{5 分钟内有成功快照?}
    CACHE -->|yes| RESULT
    CACHE -->|no| SNAP[内建 snapshot 源优先级]
    SNAP --> TS{TUSHARE_TOKEN?}
    TS -->|yes| SP1[tushare -> sina -> efinance -> akshare_em -> em_datacenter]
    TS -->|no| SP2[sina -> efinance -> akshare_em -> em_datacenter]
    ENV --> DAILY[DSA provider context]
    DAILY --> DFM[DataFetcherManager: Tushare/Efinance/Tencent/AkShare/TickFlow/Pytdx/Baostock/YFinance]
    DFM --> RESULT[候选股 + source_errors/warnings/llm_parse_errors]

    API --> HOT{hotspots，与 screen 并行}
    HOT --> HP{provider specified?}
    HP -->|no| EM[DSA EastMoney provider]
    HP -->|yes| CUSTOM[指定 provider/env provider]
    EM --> LIVE[实时热点榜单，详情按需加载]
    LIVE -->|成功| HCACHE[写入热点 last-good cache]
    LIVE -->|失败| OLD[读取 hotspots.json / hotspot_details]
    OLD -->|无缓存| EMPTY[稳定空态 + eastmoney_hotspot_unavailable]
```

## 推荐配置档

### 免费模式

适合个人试用，依赖免费源自动 fallback。优点是不需要 token；缺点是更容易遇到上游限流或临时接口变化。

```env
REALTIME_SOURCE_PRIORITY=tencent,akshare_sina,efinance,akshare_em
ENABLE_EASTMONEY_PATCH=true
```

### A 股稳定模式

适合经常跑选股、批量分析或对外服务。Tushare 用于增强普通 A 股日线与快照稳定性；TickFlow 可增强普通 A 股日 K、已登记指数固定 fallback、实时行情和大盘复盘（实时行情需显式加入 `REALTIME_SOURCE_PRIORITY`）；免费源继续作为兜底。

```env
TUSHARE_TOKEN=your_tushare_token
TICKFLOW_API_KEY=your_tickflow_key

REALTIME_SOURCE_PRIORITY=tickflow,tushare,tencent,akshare_sina,efinance,akshare_em
SNAPSHOT_SOURCE_PRIORITY=tushare,sina,efinance,akshare_em,em_datacenter

# 选股运行期默认值；显式配置时会保留你的值
DAILY_FETCH_RETRIES=3
DAILY_FETCH_MAX_WORKERS=1
```

注意：TickFlow 能力按套餐权限分层；权限不足或请求失败时会 fail-open 回退到现有免费源，不建议把它当成所有市场行情的唯一来源。

### 港股 / 美股稳定模式

适合港美股组合、持仓和个股分析。Longbridge 配置后优先参与港美股链路；YFinance、Finnhub、AlphaVantage 作为兜底。

```env
LONGBRIDGE_OAUTH_CLIENT_ID=your_client_id
LONGBRIDGE_OAUTH_TOKEN_CACHE_B64=your_token_cache_base64

FINNHUB_API_KEY=your_finnhub_key
ALPHAVANTAGE_API_KEY=your_alphavantage_key
```

如果仍使用 Legacy Longbridge 凭证，也可以继续配置：

```env
LONGBRIDGE_APP_KEY=your_app_key
LONGBRIDGE_APP_SECRET=your_app_secret
LONGBRIDGE_ACCESS_TOKEN=your_access_token
```

## 用户可见提示建议

对外沟通时建议区分三类情况：

| 情况 | 建议提示 |
| --- | --- |
| 单个源失败但 fallback 成功 | 本次使用了降级数据源，分析仍可继续；报告中会标记实际成功源。 |
| 多个源失败但有缓存 | 实时源不可用，本次使用上一次成功缓存；结论会降低置信度。 |
| 全部源失败且无缓存 | 当前数据不可用，请稍后重试。普通 A 股可检查 Tushare/TickFlow；已登记指数应检查 Tencent/AkShare 连通性或配置 TickFlow；港美股可检查 Longbridge。 |

普通 A 股日线使用 `cn` 健康度命名空间，已登记指数固定链使用独立的 `cn_index` 命名空间；任一链的连续失败不会熔断另一条链。指数源返回空结果时会继续 fallback 并记录诊断，四源全部失败则返回空结果和空来源；普通股票保留既有最终异常语义。

### 新闻面证据缺失的报告标注（已实现）

报告会区分新闻检索**未执行**和**执行后零命中**，分别渲染对应提示：

> ⚠️ 未配置搜索渠道，本次分析未纳入新闻面证据。

> ⚠️ 本次未获取到可用的新闻面数据，以下结论未纳入新闻维度证据。

覆盖 dashboard、brief、个股与日报四个渲染路径，以及历史 Markdown、分享图片和 Web
报告详情；中文、英文、韩文报告使用各自的披露文案。该提示的判定独立于模型输出：
即使 LLM 按 schema 写出了 `market_sentiment` / `hot_topics`，只要检索零命中就照常提示，
避免出现「展示模型生成的情绪判断、却隐瞒无新闻证据」这一组合。

判定依据是 `AnalysisResult.news_result_count`：

| 取值 | 含义 | 是否提示 |
| --- | --- | --- |
| `None` | 未执行检索（未配置搜索渠道） | **是**——明确说明本次分析没有新闻面证据 |
| `0` | 执行了检索但零命中（搜索源限流、全部失败等） | **是** |
| `> 0` | 正常拿到新闻 | 否 |

新记录会把该三态值随分析结果持久化，保证实时报告和历史报告一致。旧记录若没有保存
`news_result_count`，其新闻检索状态只能视为未知，历史展示保持原样，不会倒推为“未配置搜索渠道”。

## 后续可做的产品化增强

1. 数据源 Doctor 页面：展示每个源最近成功时间、失败原因、熔断状态和下一次恢复探测时间。
2. 一键推荐配置：根据市场选择生成 `.env` 片段，例如“A 股稳定模式”“港美股稳定模式”“免费模式”。
3. 选股状态面板：直接展示 snapshot/daily source health，让用户知道是 Sina、Efinance、AkShare 还是 Tushare 出问题。
4. 批量任务限速策略：对免费源自动降低并发，优先复用本地日线缓存，减少触发上游限流。
5. 可选商业源接入：只有在现有 Tushare / TickFlow / Longbridge / Finnhub / AlphaVantage 仍不能覆盖需求时，再考虑新增 Twelve Data、Massive/Polygon、Nasdaq Data Link 等源。

## 官方资料

- Tushare: https://tushare.pro/document/2
- TickFlow: https://tickflow.org/
- AkShare: https://akshare.akfamily.xyz/
- Longbridge OpenAPI: https://open.longportapp.com/
- Finnhub API: https://finnhub.io/docs/api
- Alpha Vantage API: https://www.alphavantage.co/documentation/
