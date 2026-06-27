# 第三方 Provider 兼容性说明

> 本文档记录 AI 股票复盘工作台新增的第三方数据源依赖、迁移路径和兼容边界。

---

## 1. 同花顺 Fuyao API

| 项目 | 说明 |
| --- | --- |
| 用途 | A 股实时快照、指数、板块、成分股、涨跌停池 |
| 配置 | `FUYAO_API_KEY` |
| API 文档 | https://fuyao.aicubes.cn/llms.txt |
| 是否必填 | 否（不填则降级到 EastMoney / AkShare / efinance） |

**迁移/回退：**
- 不配置 `FUYAO_API_KEY` 时，市场快照和板块数据回退至 `akshare` / `efinance` 等原生源。
- K 线数据始终优先 `ths.get_stock_daily_kline`，空响应时回退至 `eastmoney.get_daily_kline`。
- 接口调用增加了 `try/except` 兜底和 `source/stale/error` 返回结构。

## 2. 东方财富妙想 MX Skill

| 项目 | 说明 |
| --- | --- |
| 用途 | 资讯搜索、智能选股、自选股管理、股票/行业/公告/资金查询 |
| 配置 | `MX_APIKEY`（永久环境变量） |
| 文档 | https://marketing.dfcfw.com/res/download/A620260623NIYC2U.md |
| 是否必填 | 否 |

**迁移/回退：**
- 不配置则相关查询走 `eastmoney_provider` 自带的 akshare/efinance 封装。
- MX 调用全部包裹 `try/except`，异常不会影响页面。
- 客户端需自行从东方财富渠道获取 API Key。

## 3. Provider Router 降级优先级

```
请求 -> THS/Fuyao（如果有 Key）
       ├── 有数据 → 返回
       └── 无数据/超时 → EastMoney Provider（缓存或远程）
                              ├── 有数据 → 返回
                              └── 无数据 → manager.xxx (DataFetcherManager 兜底)
```

- Provider 返回结构统一：`{ source, stale, error, updated_at, data }`。
- 前端展示"数据延迟/接口异常"提示的条件：`stale=True` 或 `error!=null`。
- cache TTL: 行情 15-30s / K 线 60-300s / 板块 300s / 新闻 600s。

## 4. 配置变更

| 变量 | 新增/变更 | 默认值 | 旧版兼容 |
| --- | :---: | :---: | :---: |
| `FUYAO_API_KEY` | 新增 | 空（降级） | ✅ 无需改动 |
| `MX_APIKEY` | 新增 | 空（降级） | ✅ 无需改动 |
| `STOCK_LIST` | 保留 | 无 | ✅ 无变化 |
| `NOTIFICATION_TIMEZONE` | 保留 | `Asia/Shanghai` | ✅ 无变化 |
| LLM API Keys | 保留 | 无 | ✅ 无变化 |

## 5. 验证命令

```bash
# 语法检查
python -m compileall data_provider/ api/ src/

# flake8 致命错误
flake8 --count --select=E9,F63,F7,F82

# 离线测试（需要安装 CI 依赖）
python -m pytest -m "not network" -x --timeout=30

# 前端构建
cd apps/dsa-web && npm run build
```
