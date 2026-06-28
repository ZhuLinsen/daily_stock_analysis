# Tushare 股票列表获取工具使用说明

## 功能概述

从 Tushare Pro 获取 A股、港股、美股列表信息，保存为 CSV 文件到本地。

## 快速开始

### 1. 配置 Token

在项目根目录的 `.env` 文件中添加 Tushare Token：

```bash
TUSHARE_TOKEN=你的tushare_token
```

> 获取 Token：访问 [Tushare Pro](https://tushare.pro/weborder/#/login) 注册并获取

### 2. 运行脚本

```bash
python3 scripts/fetch_tushare_stock_list.py
```

如需针对 A 股名称状态做修正，可以加上 `--a-rk`，脚本会保持 `stock_basic` 作为基础来源，再用 `rt_k` 对带 `XD`、`XR`、`DR`、`N`、`C` 前缀的名称进行回填，并覆盖输出到 `data/stock_list_a.csv`：

```bash
python3 scripts/fetch_tushare_stock_list.py --a-rk
```

### 3. 查看输出

数据将保存到 `data/` 目录：

```
data/
├── stock_list_a.csv       # A股列表（--a-rk 时为修正后名称）
├── stock_list_hk.csv      # 港股列表
├── stock_list_us.csv      # 美股列表
└── README_stock_list.md   # 数据说明文档
```

## 功能特性

✅ **自动分页**：美股数据自动分页读取（每页5000条）
✅ **智能限流**：每次请求之间随机休息5-10秒
✅ **错误处理**：单个市场失败不影响其他市场
✅ **进度提示**：实时显示读取进度
✅ **自动文档**：生成详细的数据说明文档

## 市场说明

| 市场 | 接口 | 积分要求 | 数据量 |
|------|------|----------|--------|
| A股 | stock_basic | 2000积分 | ~5000只 |
| 港股 | hk_basic | 2000积分 | ~2000只 |
| 美股 | us_basic | 120试用/5000正式 | ~10000只 |

## 输出文件格式

### A股（stock_list_a.csv）

执行 `--a-rk` 时，这个文件会写入修正后的 A 股名称。

```csv
ts_code,symbol,name,area,industry,market,exchange,list_date,...
000001.SZ,000001,平安银行,深圳,银行,主板,SZSE,19910403,...
600519.SH,600519,贵州茅台,贵州,白酒,主板,SSE,20010827,...
```

### 港股（stock_list_hk.csv）

```csv
ts_code,name,fullname,market,list_date,trade_unit,curr_type,...
00700.HK,腾讯控股,腾讯控股有限公司,主板,20040616,100,HKD,...
00005.HK,汇丰控股,汇丰控股有限公司,主板,19750401,100,HKD,...
```

### 美股（stock_list_us.csv）

```csv
ts_code,name,enname,classify,list_date,...
AAPL,苹果,Apple Inc.,EQT,19801212,...
TSLA,特斯拉,Tesla Inc.,EQT,20100629,...
BABA,阿里巴巴,Alibaba Group,ADR,20140919,...
```

## 使用示例

### Python 读取数据

```python
import pandas as pd

# 读取 A股
a_stocks = pd.read_csv('data/stock_list_a.csv')
print(f"A股数量: {len(a_stocks)}")

# 筛选主板股票
main_board = a_stocks[a_stocks['market'] == '主板']
print(f"主板数量: {len(main_board)}")

# 查找特定股票
stock = a_stocks[a_stocks['ts_code'] == '600519.SH']
print(stock[['name', 'industry', 'list_date']])
```

### 刷新股票自动补全索引

推荐直接使用一键刷新脚本，它会默认在抓取 A 股时使用 `--a-rk`，然后生成并同步自动补全索引：

```bash
pip install -r requirements.txt
python3 scripts/refresh_stock_index.py
```

生成自动补全索引依赖 `pypinyin` 写入中文股票的完整拼音和拼音首字母字段；缺少该依赖时脚本会直接失败，避免生成无法支持拼音搜索的降级索引。

如果你只想单独更新 CSV，可以先抓取数据：

```bash
python3 scripts/fetch_tushare_stock_list.py --a-rk
```

如果已经有新的 CSV，只想重新生成索引：

```bash
python3 scripts/generate_index_from_csv.py --test  # 先测试
python3 scripts/generate_index_from_csv.py         # 确认后生成
```

### 本地客户端自动获取最新索引

新版客户端默认会从项目 GitHub `main` 分支读取最新的 `apps/dsa-web/public/stocks.index.json`，并缓存到本地 `data/cache/stocks.index.json`。前端仍访问本地 `/stocks.index.json`，不需要直接跨域请求 GitHub。

远程索引地址、检查频率和网络超时时间为系统内置值，不提供用户配置项；用户只需要决定是否启用：

```bash
STOCK_INDEX_REMOTE_UPDATE_ENABLED=true
```

默认开启时，系统最多每 48 小时检查一次更新。若运行环境无法访问 GitHub raw、请求超时、返回内容不是合法股票索引，应用会保留已有缓存；如果没有远程缓存，则继续使用随应用打包的内置索引。远程更新失败不会阻断 WebUI 启动、股票自动补全或分析流程；连续失败达到系统内置阈值后，会在本进程内暂停重试直到下一轮 48 小时窗口。

## 注意事项

1. **积分要求**：确保账号积分足够（A股/港股2000，美股120试用）
2. **请求限制**：注意 API 的每分钟请求次数限制
3. **数据更新**：维护者建议每三天刷新一次并提交到仓库；本地客户端默认最多每 48 小时检查一次 GitHub `main` 上的索引更新。后续可通过 GitHub Actions workflow 自动化刷新与提交 PR
4. **网络连接**：需要稳定的网络连接

## 常见问题

### Q: 提示"未找到 TUSHARE_TOKEN"？
**A**: 请在 `.env` 文件中配置 `TUSHARE_TOKEN=你的token`

### Q: 提示"账号积分不足"？
**A**:
- A股/港股需要2000积分
- 美股120积分试用，5000积分正式权限
- 访问 https://tushare.pro 查看积分获取办法

### Q: 读取失败怎么办？
**A**:
1. 检查网络连接
2. 检查 Token 是否正确
3. 查看账号积分是否足够
4. 当前脚本不会自动重试；单次请求失败后会输出错误并结束，请排查原因后重新运行

### Q: 数据更新频率？
**A**: 对维护者本地 CSV 与仓库索引，建议每三天更新一次并提交到仓库；遇到摘帽/更名等高影响事件可临时刷新。未来可通过 GitHub Actions workflow 自动化刷新与提交 PR。对普通本地客户端，系统默认最多每 48 小时从 GitHub `main` 检查一次最新索引。

### Q: 无法访问 GitHub raw 会影响使用吗？
**A**: 不会。远程索引更新是 best-effort：失败时会继续使用已有远程缓存或随应用打包的内置索引；如果索引完全不可用，Web 自动补全会进入现有 fallback，股票代码仍可手动输入。

## 相关链接

- [Tushare 官网](https://tushare.pro)
- [Tushare 文档](https://tushare.pro/document/2)
- [积分获取办法](https://tushare.pro/document/1)
- [API 数据调试](https://tushare.pro/document/2)
