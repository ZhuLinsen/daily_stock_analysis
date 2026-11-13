# TickPlus 接入（A 股 / ETF 首选推荐）

[注册 TickPlus](http://www.tickplus.org/register?reg=5433cf922395)，在控制台获取自己的 API Key。
这是项目合作推广链接；注册归属和返佣规则以平台确认为准。

```dotenv
TICKPLUS_API_KEY=your_tickplus_key
TICKPLUS_PRIORITY=0
```

本地 / Docker 通过环境变量或 `.env` 配置；Web 配置管理中可填写 TickPlus API Key。
GitHub Actions 使用同名 Secret `TICKPLUS_API_KEY`，优先级可用同名 Variable `TICKPLUS_PRIORITY`。未设置 `REALTIME_SOURCE_PRIORITY` Variable 时，工作流保留空值，由运行时自动首选 TickPlus；显式设置时保持用户顺序。
请勿将测试 Key 或个人 Key 写入代码、README、日志或公开配置。

- 普通 A 股 / ETF 日 K：配置后默认优先尝试 TickPlus（优先级 0，同值先于内置源），失败沿现有链回退。
- ETF 轮动：单独创建 `dividend=2` 前复权实例，保持普通股票 / ETF 分析为不复权；不修改共享数据源。
- 批量实时预取：按股票 / ETF 分组，单批最多 100 个，只请求当前自选股，缓存 30 秒并在返回时复制，避免跨分析污染。
- 实时行情：未显式设置 `REALTIME_SOURCE_PRIORITY` 时，配置 Key 后自动把 `tickplus` 放在首位；显式设置时保持用户顺序。如需首选可设 `REALTIME_SOURCE_PRIORITY=tickplus,tencent,akshare_sina,efinance,akshare_em`。
- 日 K 使用 Basic `daykline`，`period=1d`、`dividend=1`（不复权）；实时优先使用 `fullfactor`（行情指标），失败再用 `fullquotes`，股票名称使用 `list` 并缓存。
- 成交量由手转换为股，成交额保持元；涨跌幅按昨收计算。`fullfactor` 提供量比、换手率、振幅、市值及 A 股 PE / PB；这些百分比已经是百分数，不再乘 100。ETF 的 PE / PB 哨兵零值保持缺失，不当作股票估值。
- 当前接入范围为沪深京 A 股和 ETF。裸 `000001` / `000016` 等与指数同码的股票按股票处理，只有显式指数身份才进入原指数链。已登记指数使用原固定路由；港美股及其他海外市场继续使用现有来源。未接入 WebSocket、逐笔及财务接口。
- 请求超时为 15 秒，网络 / HTTP / 权限响应错误后按接口冷却 60 秒，防止批量任务重复消耗请求；错误信息不回显带 token 的 URL。
- 北交所建议使用当前 `92xxxx` 新代码；抽测的旧 `834185` / `830799` / `430047` 指标接口未返回行情，接入不自动猜测新旧代码映射。停牌 / 无有效现价时不会把零价或昨收伪装成实时行情。
- 套餐额度、频率限制和 Key 有效期由平台决定，本项目不预设无限额度。

官方接口参考：[TickPlus 教程](http://www.tickplus.org/tutorial)。[官方 SDK 的 BasicApi](https://github.com/tickplusx/TickPlusSkill/blob/main/tickplus/scripts/api/BasicApi.py) 与实测确认指标接口为 `fullfactor`；在线教程中的 `fullmetric` 当前返回不存在，接入未使用该路径。官方文档当前使用 HTTP API，请按平台实际支持情况部署。

## English

Register through the project link above and configure your own `TICKPLUS_API_KEY`.
Ordinary daily bars use unadjusted prices; ETF rotation uses an isolated forward-adjusted instance. Volume is converted from lots to shares. TickPlus
is tried first for ordinary mainland stocks and ETFs at the default priority. Explicit
realtime priority overrides are respected. Registered indices and overseas routes
are unchanged. Failed requests fall back to existing providers; HTTP/network errors
trigger a per-endpoint 60-second cooldown. Realtime uses `fullfactor` with `fullquotes` fallback; batches separate stocks and ETFs (up to 100 symbols) and cache for 30 seconds. Never publish a test or personal API key.
