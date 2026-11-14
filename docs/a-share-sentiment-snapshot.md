# A 股收盘情绪快照

用户手动触发生成后，后端计算收盘情绪指标并保存到 `DATABASE_PATH` 指定的 SQLite 数据库。列表、详情和趋势查询只读取已保存的结果。

## 默认东方财富数据源

手动生成、详情、列表、趋势和回填 CLI 同样默认选择 `eastmoney`。东方财富和国泰安分别使用 `CN_A_EASTMONEY_POOL` 和 `CN_A_MAIN_NORMAL_LIMITED_CSMAR` 保存快照。已有国泰安调用请显式传入 `source=csmar` 或 `--source csmar`。

当日快照通过 AkShare 获取当日涨停池、炸板池和昨日涨停池。涨停家数和炸板率沿用股票池统计。最高连板使用当日池的连板数并校验其与昨日池的衔接，1 进 2 使用昨日池中连板数为 1 的股票作分母。该口径使用新版本，与逐日核对历史涨停池的旧版回填分开比较。必要股票池不可用、字段不一致或存在重复时拒绝生成。

跌停覆盖率和上涨股票占比使用同一份沪深京有效行情作为分母，要求价格为正、成交量为正且涨跌幅有效。程序核对已知触板股和当日涨停池价格，统计范围以供应商实际返回数据为准。

- **跌停覆盖率**（`limit_down_coverage`）为有效行情中东方财富跌停股池家数除以有效股票数。
- **上涨股票占比**（`advancing_ratio`）为有效行情中涨跌幅大于零的股票数除以有效股票数。

详情同时返回有效股票数、跌停家数和上涨家数。行情或跌停池不可用时，对应指标为 `null`，已核验的其他指标仍可保存为 `partial`。跌停池为空时，只有东财原响应确认目标交易日及零条记录，才记为零家。两项指标使用当日行情，旧日期回填不会填入当天行情。股票池请求最多尝试两次，每次超时 15 秒，分页行情请求最多等待 120 秒。

`complete` 表示内部检查通过，统计范围仍以数据供应商实际返回的股票为准。手动重算相同输入返回 `unchanged`。输入或指标版本变化会返回冲突并保留已保存结果。

### 连板梯队、高阶晋级率与成交额

| 指标 | 定义及覆盖范围 |
| --- | --- |
| 连板梯队 `limit_up_ladder` | 按当日收盘涨停股的精确连续板数统计家数。例如 `{"1": 4, "3": 2}` 代表四只首板、两只三板。整个指标有效时，未出现的板位家数为零。 |
| 高阶晋级率 `higher_board_promotions` | 分别取上一个交易日的二板、三板、四板及以上为分母，统计其中今天再封板的数量。每组包含分子、分母和比例，分母为零时比例为 `null`。无法核实昨日连板时，高阶指标整体为 `null`。 |
| 成交额变化 | `turnover_yuan` 是东方财富当日有效成交行情的成交额之和，单位为元。查询时与上一交易日已保存的同源同口径有效成交额对照，返回 `previous_turnover_yuan`、`turnover_change_yuan`（当日减昨日）及 `turnover_change_ratio`（变化额除以昨日额）。 |

连板梯队和高阶晋级率适用于当日东方财富行情，以及能验证连板历史的东方财富回填和国泰安数据。统计范围随各来源定义。成交额仅适用于东方财富当日有效行情，不能用于断言交易所全市场覆盖。有效行情中任一成交额缺失或无效时，当日汇总为 `null`。缺少可比的上一交易日记录时，变化额和变化比例均为空。历史回填和国泰安当前格式均不生成该成交额指标。

### 近期回填与交易日趋势

东方财富回填按交易日逐日获取并保存快照，无需设置国泰安路径；不要把过早日期当成已有历史。具体可获取范围取决于接口及 AkShare 版本，先用 `--dry-run` 检查，正式执行时仍可能因为网络或源数据变化而失败：

```bash
python scripts/backfill_sentiment.py --source eastmoney --start-date 2026-10-28 --end-date 2026-10-30 --dry-run
python scripts/backfill_sentiment.py --source eastmoney --start-date 2026-10-28 --end-date 2026-10-30
```

每个交易日输出 `inserted`、`unchanged`、`partial`、`conflict`、`failed` 或 `dry-run`，末行给出汇总；发生 `failed` 或 `conflict` 时退出码为 1。失败日期不会写入数值为零的快照，也不覆盖现有数据；终端输出可自行留存，接口稍后会将没有快照的交易日列为缺失。回填逐日调用源接口，可能较慢；不会启动定时任务。

趋势接口 `GET /api/v1/sentiment/trend?end_date=2026-10-29&limit=30` 返回目标日前的 10、30 或 60 个交易日。`session_dates` 给出整个交易日窗口，`missing_dates` 标记缺失日。`definition_version` 使用目标日快照的口径，目标日无快照时使用窗口内最近记录的口径。不同口径的记录日期列在 `different_definition_dates`，`items` 只包含可按该口径比较的历史快照。目标日当天值通过详情读取。日期不受交易日历支持或窗口不可用时返回 422。日期列表的 `limit` 仍表示最多返回多少条记录。

项目使用 `sentiment_snapshots` 表保存结果。旧快照可以直接读取，缺失的新增字段显示为空。

## 可选本地国泰安数据源

默认 `CSMAR_ZIP_PATH` 为空。用户可配置自行取得授权的 `TRD_Dalyr.xlsx` 压缩包，并手动选择 `csmar` 生成快照。请勿提交原始 ZIP、生成的数据库或其中的股票名单。

读取器目前只支持 ZIP 根目录下**一个** `TRD_Dalyr.xlsx`、且工作簿只有一个工作表；允许国泰安的字段说明文件 `TRD_Dalyr[DES][xlsx].txt` 和 PDF 元数据。包含其他数据文件、分卷、额外工作表或未知附件时会明确报错，不会只读取第一卷。多卷文件需要先用可信流程合并并核对完整性，本功能暂不提供合并工具。

## 配置与调用

在个人 `.env` 中设置 `CSMAR_ZIP_PATH` 为压缩包绝对路径；仓库里的 `.env.example` 只保留空值。服务启动后，手动调用：

```text
POST /api/v1/sentiment/snapshots/2026-10-29/generate?source=csmar
GET  /api/v1/sentiment/snapshots/2026-10-29?source=csmar
GET  /api/v1/sentiment/snapshots?source=csmar&end_date=2026-10-29&limit=30
GET  /api/v1/sentiment/trend?source=csmar&end_date=2026-10-29&limit=30
```

生成接口只接收日期；文件路径来自本地配置，不接受请求传入任意服务器路径。启用管理员认证后，这些接口跟随现有 `/api/v1/*` 认证中间件。对外响应只给出指标、分子分母、来源和质量摘要，不返回授权数据的逐股名单；逐股构成仅保存在本地数据库供核验。

以下是合成测试数据生成的响应片段，不代表真实行情：

```json
{
  "action": "inserted",
  "snapshot": {
    "trade_date": "2026-10-28",
    "quality_status": "complete",
    "metrics": {
      "limit_up_count": 2,
      "break_rate": 0.3333333333333333,
      "max_consecutive": 2,
      "promotion_1_to_2": 1.0
    },
    "break_numerator": 1,
    "break_denominator": 3,
    "promotion_numerator": 1,
    "promotion_denominator": 1
  }
}
```

同一 `(market, trade_date)` 再次提交相同输入返回 `unchanged`。如已保存的数据、来源或口径不同，接口返回 `409 snapshot_conflict`，不会自动覆盖；如果只有 Excel 的工作表范围标记发生变化，其他来源信息、截至当日指纹和计算结果完全相同，则保留原快照并返回 `unchanged`。无文件配置返回 `409 source_not_configured`；指定日期无数据、缺少前两交易日、交易日历不可用或源文件格式不合要求返回 `422 source_unavailable`。缺失数据不当作数值零。

## 第一版统计口径

- 股票池：`Markettype` 为 1 或 4，`Trdsta=1`，`Dnshrtrd>0`，`LimitUp` 为有效正数，且状态、最高价、收盘价通过检查。这是按供应商字段筛选的沪深主板受限股票池，不是全 A 股；`Trdsta=1` 的含义以国泰安字段定义为准，并不独立证明已排除所有其他特殊状态。
- `LimitUp` 和 `LimitStatus` 同时为空时，无法仅凭缺失字段确认是否无涨跌幅限制：记录为来源问题，相关指标记为 `null`、质量标记为 `partial`。现有摘要字段 `target_no_price_limit_excluded` 为兼容旧快照而保留，实际是此类待核实记录的数量，不能当作已确认的无涨跌幅限制股票数量。
- 收盘涨停：`LimitStatus=1`；同时检查收盘价与涨停价是否一致。
- 炸板：最高价触及涨停价，收盘未涨停。炸板率的分母为触及涨停价的股票数；分母为零时比例是 `null`。
- 最高连板：按连续市场交易日的收盘涨停计算。中间停牌、个股无记录或未涨停均按本版本口径中断连板；无法据无记录本身判断是否停牌。如果整个交易日缺失，相关连板标记为不确定，不跨缺口连接。
- 1 进 2：昨日涨停且再前一个市场交易日未涨停的股票是昨日首板；其中今日涨停的数量除以昨日首板数。分母为零时比例是 `null`。

读取时只把目标日及之前的行加入计算和 as-of 摘要；指纹由原有九个必要字段、记录顺序和截至目标日的行生成，沿用第一版规则。Excel 中未来日期的行不参与历史计算和该指纹。国泰安导出文件可能把工作表范围错误标为只有 A 列；读取器按实际单元格重置工作表范围。若历史行内容、顺序或口径发生变化，会产生冲突而不是覆盖旧快照。

`complete` 仅表示本地源文件在上述口径下字段、交易日历和内部价格状态检查通过，且最高连板没有被文件起始日期截断；不表示全市场覆盖、源文件完整性已由独立数据源验证，也无法凭现有字段识别所有个股的缺行原因。出现源数据异常时保存 `partial`，受影响的指标为 `null`；分母确实为零时比例也为 `null`，不等同于数据缺失。公开部署前应检查机构的数据授权条款和现有服务的认证配置。

交易日期使用项目现有的 `exchange-calendars` 沪市交易日历核对；依赖不可用、日期超出其支持范围或文件出现非交易日记录时，拒绝生成。不同版本交易日历可能有不同覆盖范围，应保持版本一致并核对相应交易所公告。

## 本地历史批量回填

在个人 `.env` 或进程环境中设置 `CSMAR_ZIP_PATH` 和 `DATABASE_PATH`，从仓库根目录运行：

```bash
python scripts/backfill_sentiment.py --source csmar --start-date 2026-10-16 --end-date 2026-10-29 --dry-run
python scripts/backfill_sentiment.py --source csmar --start-date 2026-10-16 --end-date 2026-10-29
```

`--dry-run` 只计算，不初始化或写入数据库。正式运行使用项目现有的 `DatabaseManager` 与 SQLite 路径。程序按沪市交易日历逐日处理；交易日历不可用时停止，数据文件缺少目标交易日时报告 `failed`，缺少中间交易日时显式断开连板并对受影响指标标记 `partial`，不会把缺口两边的涨停接成连续序列。

每个交易日输出一行 JSON，含 `status`（`inserted`、`unchanged`、`partial`、`conflict` 或 `failed`）、`quality_status` 和 `save_action`；`partial` 也可能是新插入或重复未变，具体动作见 `save_action`。末行输出状态及写入动作汇总。出现 `conflict` 或 `failed` 时退出码为 1；配置、日期区间或日历不可用时退出码为 2。已有快照不自动覆盖。

回填故意逐日调用第一版读取器，保留每个目标日的 as-of 数据指纹和来源字段。真实文件单日读取可能需要几十秒，较长区间回填可能耗时数分钟甚至更久；实际速度取决于文件大小和设备。在证明新读取方式与既有快照逐字段等价之前，不改为共享扫描。历史异常仍记录在 `source_issues_through_target`，但只影响其可能改变的当日、晋级率或当前连板，不会让无关的早期异常永久压低后来快照的质量状态。

## 离线测试与回滚

维护者无需国泰安文件；测试在临时目录生成合成工作簿和 SQLite 数据库：

```bash
python -m pytest -q tests/test_sentiment_snapshot.py tests/test_sentiment_backfill.py tests/test_sentiment_api.py tests/test_eastmoney_backfill.py
```

清空 `CSMAR_ZIP_PATH` 可停用国泰安读取。回滚代码会移除 API 功能，现有 `sentiment_snapshots` 表和记录仍保留在数据库中。
