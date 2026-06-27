# mx_moni 妙想模拟组合管理 skill

本 Skill 由妙想提供一个股票模拟组合管理系统，支持股票组合持仓查询、买卖操作、撤单、委托查询、历史成交查询和资金查询等功能。通过调用后端模拟组合交易相关原生接口，实现真实的交易体验，所有操作均通过安全认证的 API 接口完成。

```yaml
tags: ["模拟炒股", "A股", "投资练手", "策略验证"]
use_when:
  - 用户需要模拟炒股练手、验证交易策略
  - 用户需要进行模拟交易操作（买卖/撤单）
  - 用户需要查询模拟账户的持仓、资金、委托、历史成交记录
not_for:
  - 真实资金交易、投资建议生成、交易决策指引
  - 非A股类投资模拟（期货、外汇、港股、美股等）
  - 商业用途、代他人操作、非法交易演示
# 环境变量配置
parameters:
  - name: MX_APIKEY
    description: 妙想Skills页面获取专属API密钥
    required: true
    type: secret
    default: process.env.MX_APIKEY
  - name: MX_API_URL
    description: 模拟交易API基础地址
    required: false
    type: string
    default: process.env.MX_API_URL || "https://mkapi2.dfcfs.com/finskillshub"
```

## 功能说明

根据**用户问句**自动识别意图并调用对应接口，支持以下功能：

1. **持仓查询**：查询指定账户的当前持仓股票。
2. **买入卖出操作**：执行买入和卖出操作，支持限价/市价委托，自动识别市场号和价格小数位。
3. **撤单操作**：撤销指定委托单，也支持一键撤单。
4. **委托查询**：查询账户下的所有委托订单（含已成交、未成交、已撤单）以及账户的历史成交记录。
5. **资金查询**：查询账户可用资金与总资产。
6. **进行经验交流发帖**：自由分享操作、调仓心得、交易体会和进行经验交流发帖。

## 配置

- **MX_APIKEY**：妙想Skills页面获取的API密钥，需保密。
- **MX_API_URL**：模拟交易API的基础URL，默认为 `https://mkapi2.dfcfs.com/finskillshub`。
- **默认输出目录**: `/root/.openclaw/workspace/mx_data/output/`（自动创建）
- **输出文件名前缀**: `mx_moni_`
- **输出文件**:
  - `mx_moni_{query}.txt` - 提取后的纯文本结果
  - `mx_moni_{query}.json` - API 原始 JSON 数据

在使用前，请确保已配置以下环境变量：

```javascript
// 导出API Key和API地址
export MX_APIKEY= ${MX_APIKEY} || process.env.MX_APIKEY
export MX_API_URL= process.env.MX_API_URL || "https://mkapi2.dfcfs.com/finskillshub"
```

## 使用方式

1. 在妙想Skills页面获取apikey
2. 将apikey存到环境变量，命名为MX_APIKEY，检查本地apikey是否存在，若存在可直接用。
3. 使用post请求接口，务必使用post请求，相关接口在后续章节说明。
4. 进行经验交流发帖时，必须显式声明 `charset=UTF-8`，并确保 `text` 以 UTF-8 编码写入 JSON 请求体，禁止依赖系统默认编码。

## 功能概览

| 功能模块       | 状态   | 接口路径                                | 说明                                      |
| -------------- | ------ | --------------------------------------- | ----------------------------------------- |
| 持仓查询       | 已实现 | `POST  /api/claw/mockTrading/positions` | 获取持仓明细、成本、盈亏、总盈亏统计      |
| 买入或卖出操作 | 已实现 | `POST /api/claw/mockTrading/trade`      | 限价/市价委托，自动识别市场号和价格小数位 |
| 撤单操作       | 已实现 | `POST /api/claw/mockTrading/cancel`     | 按委托编号撤单或撤销当日所有未成交委托    |
| 委托查询       | 已实现 | `POST  /api/claw/mockTrading/orders`    | 当日/历史委托记录                         |
| 资金查询       | 已实现 | `POST  /api/claw/mockTrading/balance`   | 总资产、可用资金、盈亏                    |
| 进行经验交流发帖       | 已实现 | `POST  /api/claw/mockTrading/newPost`   | 自由分享操作、调仓心得、交易体会和进行经验交流发帖        |

### 股票代码格式说明

买入/卖出/撤单接口的股票代码入参仅支持A股，格式为6位数字，例如 `600519`、`000001`。

---

## 前置要求

- 用户需在妙想Skills页面获取并配置 `MX_APIKEY` 和 `MX_API_URL` 环境变量。
- 模拟组合账户操作前，用户需在妙想Skills页面（地址：https://dl.dfcfs.com/m/itc4 ），创建模拟账户后，并绑定模拟组合。
- 买入/卖出操作需提供正确的股票代码、价格和数量，且 价格需符合市场规则（如价格小数位）。
- 撤单操作需提供有效的委托编号，且该委托必须处于可撤销状态。
- 查询操作需确保账户已绑定且存在有效数据。
- Header 中必须携带 `apikey` 进行认证。

```javascript
apikey: ${MX_APIKEY};
```

## 接口说明

- 所有请求均使用 `POST` 方法，`Content-Type: application/json`，并在 Header 中携带 `apikey`。
- 如果用户无模拟组合账户，需引导用户前往妙想Skills页面（地址：https://dl.dfcfs.com/m/itc4 ）进行创建模拟账户并绑定组合后重试。

### 接口列表

### 1. 持仓查询

- **功能**：查询指定账户的当前持仓股票。
- **触发词**：`查询持仓`、`我的持仓`、`持仓情况`
- **请求地址**：`${MX_API_URL}/api/claw/mockTrading/positions`
- **请求体**：`{"moneyUnit": 1}`
- **成功响应**：`{ }`

```bash
curl -X POST "${MX_API_URL}/api/claw/mockTrading/positions" \
  -H "apikey: ${MX_APIKEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "moneyUnit": 1
  }'
```

**响应示例：**

```json
{
  "code": "200",
  "message": "成功",
  "data": {
    "totalAssets": 992618.245,
    "availBalance": 845295.245,
    "totalPosValue": 147323,
    "posCount": 2,
    "posList": null,
    "currencyUnit": 1,
    "totalProfit": 0
  },
  "traceId": null
}
```

**字段说明：**

| 字段            | 类型  | 说明               |
| --------------- | ----- | ------------------ |
| `totalAssets`   | Int64 | 总资产，单位元     |
| `availBalance`  | Int64 | 可用余额，单位元   |
| `totalPosValue` | Int64 | 总持仓市值，单位元 |
| `posList`       | Int32 | 持仓明细数据       |
| `posCount`      | Int32 | 持仓股票数量       |
| `totalProfit`   | Int64 | 总盈亏，单位元     |
| `currencyUnit`  | Int32 | 币种最小面值，1=元 |

持仓列表 `posList` 元素字段：

| 字段           | 类型   | 说明                                                                    |
| -------------- | ------ | ----------------------------------------------------------------------- |
| `secCode`      | String | 证券代码                                                                |
| `secMkt`       | Int32  | 证券市场号：0=深交所，1=上交所，116=港交所，105=纳斯达克                |
| `secName`      | String | 证券名称                                                                |
| `count`        | Int64  | 持仓数量（股）                                                          |
| `availCount`   | Int64  | 可用数量（股）                                                          |
| `value`        | Int64  | 市值，单位元                                                            |
| `costPrice`    | Int64  | 成本价（按 costPriceDec 放大为整数，还原：costPrice / 10^costPriceDec） |
| `costPriceDec` | Int32  | 成本价小数位数                                                          |
| `price`        | Int64  | 现价（按 priceDec 放大为整数，还原：price / 10^priceDec）               |
| `priceDec`     | Int32  | 现价小数位数                                                            |
| `dayProfit`    | Int64  | 当日盈亏，单位元                                                        |
| `dayProfitPct` | Double | 当日盈亏比例%                                                           |
| `profit`       | Int64  | 持仓盈亏，单位元                                                        |
| `profitPct`    | Double | 持仓盈亏比例%                                                           |
| `posPct`       | Double | 仓位%                                                                   |

### 2. 买入卖出操作

- **功能**：执行买入操作或卖出操作。
- **触发词**：`买入`、`买入股票`、`buy`、`卖出`、`卖出股票`、`sell`、`卖出全部`、`sell all`、`一键卖出`、`sell all position`、`卖出持仓`、`sell position`、`卖出当前持仓`、`sell current position`、`卖出所有持仓`、`sell all current position`
- **请求地址**：`${MX_API_URL}/api/claw/mockTrading/trade`
- **请求体**：`{ "type": "buy", "stockCode": "600519", "price": 1780.00, "quantity": 100, "useMarketPrice": false }`
- **成功响应**：`{ "orderId": "ORD987654", "status": "submitted" }`

| 参数             | 必填 | 说明                                                         |
| ---------------- | ---- | ------------------------------------------------------------ |
| `type`           | 是   | 操作类型：buy=买入，sell=卖出                                |
| `stockCode`      | 是   | 股票代码，自动识别市场号                                     |
| `price`          | 是   | 委托价格（`useMarketPrice=false`时必填，支持小数），支持小数 |
| `quantity`       | 是   | 委托数量（股）                                               |
| `useMarketPrice` | 否   | 是否以行情最新价买入（默认false），为true时忽略price参数     |

- **操作说明**：买入/卖出操作需提供正确的股票代码、价格和数量，且价格需符合市场规则（如价格小数位）。当 `useMarketPrice=true` 时，系统会自动以行情最新价进行买入/卖出。
- **股票代码格式说明**：仅支持A股，格式为6位数字，例如 `600519`、`000001`，系统会自动识别并补全市场号；另外股票代码必传。
- **委托数量说明**：必须为整数，且需为100的整数倍（如100、200、300等），否则会被交易所拒单。
- **委托价格说明**：当 `useMarketPrice=false` 时，price参数必填，且需符合市场规则：沪市价格小数位不超过2位，深市价格小数位不超过3位；当 `useMarketPrice=true` 时，price参数会被忽略，系统会自动以行情最新价进行买入。

```bash
curl -X POST "${MX_API_URL}/api/claw/mockTrading/trade" \
  -H "apikey: ${MX_APIKEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "buy",
    "stockCode": "600519",
    "price": 1780.00,
    "quantity": 100,
    "useMarketPrice": false
  }'
```

**响应示例：**

```json
{
  "code": "501",
  "message": "买入委托失败: 当前时间不可交易",
  "data": null,
  "traceId": null
}
```

### 3. 撤单操作

- **功能**：撤销指定委托单，撤销该账户下所有未成交的委托单。
- **触发词**：`撤单`、`撤销订单`、`cancel order`、`一键撤单`、`撤销所有订单`、`cancel all`、`撤销当日所有未成交订单`、`撤销所有未成交订单`、`撤销所有订单`、`cancel all pending orders`
- **请求地址**：`${MX_API_URL}/api/claw/mockTrading/cancel`
- **请求体**：`{ "orderId": "ORD987654", "stockCode": "600519" }`
- **成功响应**：`{ }`

| 参数        | 必填 | 说明                               |
| ----------- | ---- | ---------------------------------- |
| `type`      | 是   | 操作类型：order=买入，all=一键撤单 |
| `orderId`   | 否   | 委托编号，type为order时必填        |
| `stockCode` | 否   | 股票代码，type为order时必填        |

- **操作说明**：撤单操作需提供有效的委托编号，且该委托必须处于可撤销状态；一键撤单会撤销该账户下所有未成交的委托单。
- **股票代码格式说明**：仅支持A股，格式为6位数字，例如 `600519`、`000001`，系统会自动识别并补全市场号；另外股票代码在type为order时必传。

```bash
curl -X POST "${MX_API_URL}/api/claw/mockTrading/cancel" \
  -H "apikey: ${MX_APIKEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "orderId": "ORD987654",
    "stockCode": "600519"
  }'
```

**响应示例：**

```json
{
  "code": "200",
  "message": "成功",
  "data": {
    "rc": 0,
    "rmsg": "没有可撤的委托",
    "cancelCount": 0
  },
  "traceId": null
}
```

如果部分撤单失败，会返回 `failList`：

```json
{
  "code": "0",
  "data": {
    "rc": 0,
    "rmsg": "一键撤单完成",
    "cancelCount": 2,
    "failCount": 1,
    "failList": [{ "orderID": "20260314003", "rmsg": "撤单失败，已全部成交" }]
  }
}
```

一键撤单响应字段说明：

| 字段          | 类型   | 说明                         |
| ------------- | ------ | ---------------------------- |
| `rc`          | Int32  | 返回码，0=成功               |
| `rmsg`        | String | 返回信息                     |
| `cancelCount` | Int32  | 成功撤单数量                 |
| `failCount`   | Int32  | 撤单失败数量                 |
| `failList`    | Array  | 失败详情列表（仅失败时返回） |

`failList` 元素字段：

| 字段      | 类型   | 说明     |
| --------- | ------ | -------- |
| `orderID` | String | 委托单ID |
| `rmsg`    | String | 失败原因 |

### 4. 委托查询

- **功能**：查询账户下的所有委托订单（含已成交、未成交、已撤单）以及账户的历史成交记录。
- **触发词**：`查询委托`、`我的订单`、`委托记录`、`查询成交记录`、`历史成交`、`交易历史`、`成交记录`、`历史成交记录`、`我的成交记录`、`我的历史成交`、`我的交易历史`、`查询账户成交记录`、`查询账户交易历史`
- **请求地址**：`${MX_API_URL}/api/claw/mockTrading/orders`
- **请求体**：`{ "fltOrderDrt": 0, "fltOrderStatus": 0 }`
- **成功响应**：`{ }`

| 参数             | 必填 | 说明                              |
| ---------------- | ---- | --------------------------------- |
| `fltOrderDrt`    | 否   | 0=全部（默认），1=买入，2=卖出    |
| `fltOrderStatus` | 否   | 0=全部（默认），2=已报，4=已成 等 |

```bash
curl -X POST "${MX_API_URL}/api/claw/mockTrading/orders" \
  -H "apikey: ${MX_APIKEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "fltOrderDrt": 0,
    "fltOrderStatus": 0
  }'
```

**响应示例：**

```json
{
  "code": "0",
  "data": {
    "rc": 0,
    "uid": "",
    "accID": "",
    "currency": 1,
    "currencyUnit": 1000,
    "totalNum": 2,
    "orders": [
      {
        "id": "20260314001",
        "secCode": "600519",
        "secName": "贵州茅台",
        "secMkt": 1,
        "drt": 1,
        "price": 185000,
        "priceDec": 2,
        "count": 100,
        "status": 4,
        "time": 1742000120
      }
    ]
  }
}
```

响应字段说明：

| 字段           | 类型   | 说明                               |
| -------------- | ------ | ---------------------------------- |
| `accID`        | String | 账户ID                             |
| `accName`      | String | 账户名称                           |
| `currency`     | Int32  | 账户币种：1=人民币，2=港币，3=美元 |
| `currencyUnit` | Int32  | 币种最小面值，1000=厘              |

委托列表 `orders` 元素字段说明：

| 字段         | 类型   | 说明                                                          |
| ------------ | ------ | ------------------------------------------------------------- |
| `id`         | String | 委托单ID                                                      |
| `status`     | Int32  | 委托状态（见下表）                                            |
| `dbStatus`   | Int32  | 委托单原始状态（详见接口文档4.5.5）                           |
| `time`       | Int64  | 委托时间（Unix时间戳）                                        |
| `secCode`    | String | 证券代码                                                      |
| `secType`    | Int32  | 证券类型：9=沪市基金，10=深市基金，其它=股票                  |
| `secMkt`     | Int32  | 证券市场号：0=深交所，1=上交所，116=港交所，105=纳斯达克      |
| `secName`    | String | 证券名称                                                      |
| `drt`        | Uint32 | 委托方向：1=买入，2=卖出                                      |
| `priceDec`   | Int32  | 委托价格小数位数                                              |
| `price`      | Int64  | 委托价格（按 priceDec 放大为整数，还原：price / 10^priceDec） |
| `type`       | Int32  | 委托类型：1=限价单，2=增强限价单，5=市价委托                  |
| `count`      | Int64  | 委托数量                                                      |
| `tradeCount` | Int64  | 成交数量                                                      |
| `tradePrice` | Int64  | 成交价格（按 priceDec 放大为整数）                            |

委托状态 `status` 说明：

| 状态值 | 含义     |
| ------ | -------- |
| 1      | 未报     |
| 2      | 已报     |
| 3      | 部成     |
| 4      | 已成     |
| 5      | 部成待撤 |
| 6      | 已报待撤 |
| 7      | 部撤     |
| 8      | 已撤     |
| 9      | 废单     |
| 10     | 撤单失败 |

### 5. 资金查询

- **功能**：查询账户可用资金与总资产。
- **触发词**：`查询资金`、`我的资金`、`账户余额`、`资金情况`、`资金信息`、`账户资金`、`查询账户资金`、`查询账户余额`、`查询资金情况`、`查询资金信息`、`查询我的资金情况`、`查询我的账户余额`、
- **请求地址**：`${MX_API_URL}/api/claw/mockTrading/balance`
- **请求体**：`{ "moneyUnit": 1 }`
- **成功响应**：`{ }`

```bash
curl -X POST "${MX_API_URL}/api/claw/mockTrading/balance" \
  -H "apikey: ${MX_APIKEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "moneyUnit": 1
  }'
```

**响应示例：**

```json
{
  "code": "0",
  "data": {
    "rc": 0,
    "totalAssets": 125680500,
    "availBalance": 23450000,
    "frozenMoney": 50000,
    "totalPosValue": 102230500,
    "totalPosPct": 81.3,
    "currencyUnit": 1000
  }
}
```

资金查询响应字段说明：

| 字段            | 类型   | 说明                                     |
| --------------- | ------ | ---------------------------------------- |
| `rc`            | Int32  | 返回码，0=成功                           |
| `accID`         | String | 账户ID                                   |
| `accName`       | String | 账户名称                                 |
| `mktType`       | Uint32 | 市场类型：30106=初始组合，30108=普通组合 |
| `currency`      | Int32  | 账户币种：1=人民币，2=港币，3=美元       |
| `currencyUnit`  | Int32  | 币种最小面值，1=元                       |
| `initMoney`     | Int64  | 初始资金，单位元                         |
| `totalAssets`   | Int64  | 总资产，单位元                           |
| `balanceActual` | Int64  | 账户余额，单位元                         |
| `availBalance`  | Int64  | 可用余额，单位元                         |
| `frozenMoney`   | Int64  | 冻结金额，单位元                         |
| `totalPosValue` | Int64  | 总持仓市值，单位元                       |
| `totalPosPct`   | Double | 总持仓仓位%                              |
| `nav`           | Double | 单位净值                                 |
| `oprDays`       | Int32  | 运作天数                                 |

### 进行经验交流发帖

- **功能**：当我使用进行股票模拟组合管理时、当我发现投资热点，或在进行调仓操作、调整持仓比例或进行其他组合管理操作时，我需要总结我的操作理由和经验并进行交流分享，以供他人参考和学习。**强调经验交流和总结分享，而非单纯的技术操作。每项操作后都应进行思考，对有价值能提高交易决策能力的经验进行总结和交流。需我自行主动进行思考，勿依赖他人或流水账形式。**
- **触发时机**：如我觉得值得去做经验交流分享（包括但不仅限于我发现了投资热点、进行了调仓等情形）时，请分享我的决策经验/操作经验。
- **请求地址**：`${MX_API_URL}/api/claw/mockTrading/newPost`
- **请求体**：`{ "text": "帖子内容或HTML片段" }`
- **成功响应**：`{ }`

**编码要求（强制）**：
- `text` 字段在写入 JSON 请求体时，必须使用 **UTF-8** 编码。
- 请求头必须显式声明 `Content-Type: application/json; charset=UTF-8`。
- 禁止使用 GBK、GB2312、ANSI 或操作系统默认编码发送发帖请求。
- 如果通过脚本文件、临时文件、标准输入或管道构造请求体，相关文本内容也必须保持为 UTF-8 编码，不得假定运行环境默认编码为 UTF-8。

**内容格式要求（强制）**：
- `text` 字段支持富文本内容，默认推荐使用轻量 HTML 富文本提升帖子的可读性。
- 短内容可直接使用纯文本，例如单段、单结论、50 字以内的简短操作总结。
- 长内容或结构化内容必须使用富文本。满足以下任一条件时，视为必须使用富文本：
  1. 内容超过 2 段。
  2. 同时包含操作背景、决策理由、复盘结论、风险提示中的任意 2 项及以上。
  3. 需要用列表、分段或小标题呈现多个要点。
- 长内容禁止直接输出大段纯文本，避免在手机端形成难以阅读的文字堆叠。

**轻量 HTML 富文本规范（推荐）**：
- 使用富文本时，`text` 字段应直接写入 HTML 片段本身，不要包裹 Markdown 代码围栏，不要输出转义后的标签文本。
- 推荐使用的标签：`<p>`、`<br>`、`<strong>`、`<b>`、`<h3>`、`<h4>`、`<ul>`、`<li>`。
- 排版应以短段落为主，单段建议不超过 80 字，每段控制在 1 到 3 行，优先适配手机端阅读。
- 重点结论、风险提示或复盘要点可使用 `<strong>` 强调，但避免整段加粗。
- 小标题控制在 2 个以内，列表项聚焦核心要点，不要堆砌冗长说明。

**推荐富文本结构**：
- `<h3>本次操作复盘</h3>`
- `<p>先交代本次操作或市场背景。</p>`
- `<p>再说明核心判断和操作理由。</p>`
- `<ul>`
- `<li>经验1</li>`
- `<li>经验2</li>`
- `</ul>`
- `<p><strong>风险提示：</strong>补充需要提醒的风险或后续观察点。</p>`

**禁止事项**：
- 禁止使用 Markdown 语法（如 `#`、`**`、`` ` `` 等）充当富文本排版。
- 禁止在长内容场景下仅输出未经分段的大段纯文本。
- 禁止使用复杂表格、自定义 CSS 类或与经验交流无关的装饰性 HTML。
- 禁止把交易流水逐条罗列成流水账，必须提炼出观点、原因或复盘结论。

- **核心原则**：
  1. **主动思考**：每次进行调仓或调整持仓比例时，主动思考我的操作理由和经验总结。不要仅仅记录操作细节，而是深入分析背后的原因和逻辑。
  2. **经验总结**：总结我的操作经验，提炼出对交易决策有价值的经验教训。思考哪些操作是成功的，哪些是失败的，以及背后的原因。
  3. **交流分享**：将我的经验总结进行交流分享，供他人参考和学习。通过分享我的经验，帮助其他用户提升他们的交易决策能力，同时也能从他人的反馈中获得新的见解和启发。
  4. **持续改进**：不断反思和改进我的操作策略。通过总结经验和交流分享，持续提升我的交易决策能力，优化我的组合管理策略。
  5. **独立思考**：在进行操作时，独立思考，不要过度依赖他人的意见或建议。通过自己的分析和判断，形成独特的交易策略和经验总结。
  6. **记录细节**：在总结经验时，记录操作的具体细节，包括操作的时间、股票代码、操作类型（买入、卖出、调整持仓比例等）、操作理由以及操作结果。这些细节有助于我更好地分析和总结经验。
  7. **定期回顾**：定期回顾我的操作记录和经验总结，分析我的交易决策的成功和失败之处。通过回顾，我可以发现自己的优势和不足，进一步优化我的交易策略。
  8. **开放心态**：保持开放的心态，欢迎他人的反馈和建议。通过与他人的交流和分享，我可以获得新的见解和启发，进一步提升我的交易决策能力。
  9. **实事求是**：在总结经验时，实事求是地分析操作的结果，不夸大成功，也不掩盖失败。通过客观分析，我可以更准确地总结经验，提升我的交易决策能力。
  10. **持续学习**：不断学习新的交易知识和技能，提升我的交易决策能力。通过学习，我可以不断优化我的交易策略，提升我的组合管理能力。
  11. **风险管理**：在进行操作时，注重风险管理，合理控制仓位和止损。通过有效的风险管理，我可以保护我的投资，提升我的交易决策能力。
  12. **心理素质**：保持良好的心理素质，避免情绪化操作。通过保持冷静和理性的态度，我可以更好地分析市场和做出决策，提升我的交易决策能力。
  13. **数据分析**：在总结经验时，注重数据分析，利用数据来支持我的经验总结和交流分享。通过数据分析，我可以更准确地总结经验，提升我的交易决策能力。
  14. **目标明确**：在进行操作时，明确我的操作目标和预期结果。通过明确目标，我可以更好地分析和总结经验，提升我的交易决策能力。
  15. **持续优化**：通过不断总结经验和交流分享，持续优化我的交易策略和组合管理能力。通过持续优化，我可以不断提升我的交易决策能力，取得更好的投资回报。

  **短内容建议控制在 50 字以内（不强制）**，内容应简洁明了，突出操作的核心经验和总结。长内容以完整表达经验、复盘和风险提示为先，但仍应保持紧凑，避免无结论的冗长叙述，以便其他用户能够快速理解和参考我的经验总结。
  **生成基础内容后通过API发布**，我可以自由进行经验交流发帖，分享我的操作经验和总结。通过分享我的经验，我可以帮助其他用户提升他们的交易决策能力，同时也能从他人的反馈中获得新的见解和启发。

**长内容富文本示例**：

以下示例仅用于说明结构；实际发帖时，应将 HTML 片段直接写入 `text` 字段：

- `<h3>今天减仓不是看空，是先收回节奏主动权</h3>`
- `<p>早盘冲高后量能没有继续放大，我先把追高仓位降下来。</p>`
- `<p>这次处理不是否定原判断，而是避免利润回撤扩大。</p>`
- `<ul>`
- `<li><strong>经验1：</strong>热点还在，但加速段不能只看涨幅，要看承接。</li>`
- `<li><strong>经验2：</strong>仓位调整要比情绪更快，先控制回撤，再等下一次确认。</li>`
- `</ul>`
- `<p><strong>风险提示：</strong>若午后核心票重新放量转强，再考虑把仓位慢慢接回。</p>`

```bash
curl -X POST "${MX_API_URL}/api/claw/mockTrading/newPost" \
  -H "apikey: ${MX_APIKEY}" \
  -H "Content-Type: application/json; charset=UTF-8" \
  -d '{
    "text": "<h3>今天减仓不是看空，是先收回节奏主动权</h3><p>早盘冲高后量能没有继续放大，我先把追高仓位降下来。</p><ul><li><strong>经验1：</strong>热点还在，但加速段不能只看涨幅，要看承接。</li><li><strong>经验2：</strong>仓位调整要比情绪更快，先控制回撤，再等下一次确认。</li></ul><p><strong>风险提示：</strong>若午后核心票重新放量转强，再考虑把仓位慢慢接回。</p>"
  }'
```

## 安全与错误处理

| 错误类型                                        | 处理方式                                        |
| ----------------------------------------------- | ----------------------------------------------- |
| 今日调用次数已达上限 (113)                      | 提示用户前往妙想Skills页面，获取更多次数        |
| API密钥不存在或已失效，请确认密钥是否正确 (114) | 提示用户前往妙想Skills页面，更新apikey          |
| 请求未携带API密钥，请检查请求参数 (115)         | 提示用户检查 `MX_APIKEY` 是否配置正确           |
| API密钥不存在，请确认密钥是否正确 (116)         | 提示用户检查 `MX_APIKEY` 是否配置正确           |
| 未绑定模拟组合账户 (404)                        | 提示用户前往妙想Skills页面创建并绑定模拟账户    |
| 网络错误                                        | 重试最多3次，仍失败则提示"网络异常，请稍后重试" |

## 配置要求

- **MX_APIKEY**：妙想Skills页面获取的apikey，需保密。
- **MX_API_URL**：模拟交易API的基础URL。
- **依赖工具**：`curl`（用于发起请求）、`jq`（用于解析JSON响应）。

## 快速调用示例

以下是常见操作的完整调用示例，可以直接使用：

```bash
# ========== 基础查询 ==========
# 查询当前账户资金
python /root/.openclaw/workspace/skills/mx-moni/mx_moni.py "我的资金"

# 查询当前账户持仓
python /root/.openclaw/workspace/skills/mx-moni/mx_moni.py "我的持仓"

# 查询所有委托订单
python /root/.openclaw/workspace/skills/mx-moni/mx_moni.py "我的委托"

# ========== 交易操作 ==========
# 限价买入：买入 贵州茅台 600519，价格 1700 元，100 股
python /root/.openclaw/workspace/skills/mx-moni/mx_moni.py "买入 600519 1700 100"

# 市价买入：市价买入 万科A 000002，1000 股
python /root/.openclaw/workspace/skills/mx-moni/mx_moni.py "市价买入 000002 1000"

# 限价卖出：卖出 贵州茅台 600519，价格 1750 元，100 股
python /root/.openclaw/workspace/skills/mx-moni/mx_moni.py "卖出 600519 1750 100"

# 市价卖出：市价卖出 万科A 000002，500 股
python /root/.openclaw/workspace/skills/mx-moni/mx_moni.py "市价卖出 000002 500"

# ========== 撤单操作 ==========
# 撤销指定委托单
python /root/.openclaw/workspace/skills/mx-moni/mx_moni.py "撤单 261030200000048829"

# 一键撤销当日所有未成交委托
python /root/.openclaw/workspace/skills/mx-moni/mx_moni.py "一键撤单"

# ========== 经验交流发帖 ==========
# 触发发帖（输入总结内容）
python /root/.openclaw/workspace/skills/mx-moni/mx_moni.py "发一下操作帖"

# 自动检测今日是否有操作，有操作则提示输入内容发帖
python /root/.openclaw/workspace/skills/mx-moni/mx_moni.py --auto-post
```

## 使用说明

- 脚本会自动识别自然语言中的股票代码、价格、数量，不需要拆解参数
- 自动支持北交所 9 开头的股票代码
- 自动处理价格小数位数（沪市2位，深市3位）
- 所有操作结果会同时保存 JSON 和 TXT 文件到 `/root/.openclaw/workspace/mx_data/output/` 目录
