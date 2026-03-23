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

### 3. 查看输出

数据将保存到 `data/` 目录：

```
data/
├── stock_list_a.csv       # A股列表
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

### 更新自动补全索引

获取数据后，可以更新自动补全索引：

```bash
# 将 Tushare CSV 数据生成为前端自动补全索引
python3 scripts/generate_index_from_csv.py --test  # 先测试
python3 scripts/generate_index_from_csv.py         # 确认后生成
```

## 注意事项

1. **积分要求**：确保账号积分足够（A股/港股2000，美股120试用）
2. **请求限制**：注意 API 的每分钟请求次数限制
3. **数据更新**：建议每月更新一次数据
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
**A**: 建议每月更新一次，或根据需求调整

## 相关链接

- [Tushare 官网](https://tushare.pro)
- [Tushare 文档](https://tushare.pro/document/2)
- [积分获取办法](https://tushare.pro/document/1)
- [API 数据调试](https://tushare.pro/document/2)
