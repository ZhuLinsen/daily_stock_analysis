#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tushare 股票列表获取脚本

从 Tushare Pro 获取 A股、港股、美股列表信息，保存为 CSV 文件

使用方法：
    python3 scripts/fetch_tushare_stock_list.py

环境要求：
    - 需要在 .env 中配置 TUSHARE_TOKEN
    - 需要安装 tushare: pip install tushare
    - 账号积分要求：
        * A股/港股：2000积分
        * 美股：120积分试用，5000积分正式权限

输出文件：
    - data/stock_list_a.csv      A股列表
    - data/stock_list_hk.csv     港股列表
    - data/stock_list_us.csv     美股列表
    - data/README_stock_list.md  数据说明文档
"""

import os
import sys
import time
import random
from pathlib import Path
from datetime import datetime
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import tushare as ts
except ImportError:
    print("[错误] 未安装 tushare 库")
    print("请执行: pip install tushare")
    sys.exit(1)


# 配置
load_dotenv()

TUSHARE_TOKEN = os.getenv('TUSHARE_TOKEN')
OUTPUT_DIR = Path(__file__).parent.parent / "data"
PAGE_SIZE = 5000  # 美股每页读取数量（API 最大6000，设置5000留余量）
SLEEP_MIN = 5     # 最小睡眠时间（秒）
SLEEP_MAX = 10    # 最大睡眠时间（秒）


def get_tushare_api() -> Optional[ts.pro_api]:
    """
    获取 Tushare API 实例

    Returns:
        Tushare API 实例，失败返回 None
    """
    if not TUSHARE_TOKEN:
        print("[错误] 未找到 TUSHARE_TOKEN")
        print("请在 .env 文件中配置: TUSHARE_TOKEN=你的token")
        return None

    try:
        api = ts.pro_api(TUSHARE_TOKEN)
        # 测试连接
        api.trade_cal(exchange='SSE', start_date='20240101', end_date='20240101')
        print("✓ Tushare API 连接成功")
        return api
    except Exception as e:
        print(f"[错误] Tushare API 连接失败: {e}")
        print("请检查：")
        print("  1. TUSHARE_TOKEN 是否正确")
        print("  2. 账号积分是否足够（A股/港股需要2000积分）")
        return None


def random_sleep(min_seconds: int = SLEEP_MIN, max_seconds: int = SLEEP_MAX):
    """
    随机睡眠，避免频繁请求

    Args:
        min_seconds: 最小睡眠时间
        max_seconds: 最大睡眠时间
    """
    sleep_time = random.uniform(min_seconds, max_seconds)
    print(f"  ⏱  休息 {sleep_time:.1f} 秒...")
    time.sleep(sleep_time)


def fetch_a_stock_list(api: ts.pro_api) -> Optional[pd.DataFrame]:
    """
    获取 A股列表

    接口：stock_basic
    限量：单次最多6000行（覆盖全市场A股）

    Args:
        api: Tushare API 实例

    Returns:
        A股数据 DataFrame，失败返回 None
    """
    print("\n[1/3] 正在获取 A股列表...")

    try:
        # 获取所有正常上市的股票
        df = api.stock_basic(
            exchange='',        # 空：全部交易所
            list_status='L',    # L: 上市, D: 退市, P: 暂停上市
            fields='ts_code,symbol,name,area,industry,fullname,enname,cnspell,market,exchange,curr_type,list_status,list_date,delist_date,is_hs,act_name,act_ent_type'
        )

        if df is not None and len(df) > 0:
            print(f"✓ A股列表获取成功，共 {len(df)} 只股票")
            print("  - 交易所分布：")
            for exchange, count in df['exchange'].value_counts().items():
                print(f"    {exchange}: {count} 只")
            return df
        else:
            print("[错误] A股数据为空")
            return None

    except Exception as e:
        print(f"[错误] 获取 A股列表失败: {e}")
        return None


def fetch_hk_stock_list(api: ts.pro_api) -> Optional[pd.DataFrame]:
    """
    获取港股列表

    接口：hk_basic
    限量：单次可提取全部在交易的港股

    Args:
        api: Tushare API 实例

    Returns:
        港股数据 DataFrame，失败返回 None
    """
    print("\n[2/3] 正在获取港股列表...")

    try:
        # 获取所有正常上市的港股
        df = api.hk_basic(
            list_status='L'    # L: 上市, D: 退市
        )

        if df is not None and len(df) > 0:
            print(f"✓ 港股列表获取成功，共 {len(df)} 只股票")
            return df
        else:
            print("[错误] 港股数据为空")
            return None

    except Exception as e:
        print(f"[错误] 获取港股列表失败: {e}")
        return None


def fetch_us_stock_list(api: ts.pro_api) -> Optional[pd.DataFrame]:
    """
    获取美股列表（分页读取）

    接口：us_basic
    限量：单次最大6000，需要分页提取

    Args:
        api: Tushare API 实例

    Returns:
        美股数据 DataFrame，失败返回 None
    """
    print("\n[3/3] 正在获取美股列表（分页读取）...")

    all_data = []
    offset = 0
    page = 1

    try:
        while True:
            print(f"  第 {page} 页（offset={offset}）...")

            df = api.us_basic(
                offset=offset,
                limit=PAGE_SIZE
            )

            if df is None or len(df) == 0:
                print(f"  ✓ 第 {page} 页无数据，读取完成")
                break

            all_data.append(df)
            print(f"  ✓ 第 {page} 页获取 {len(df)} 只股票")

            # 如果返回数据少于页大小，说明已经到最后一页
            if len(df) < PAGE_SIZE:
                break

            offset += PAGE_SIZE
            page += 1

            # 随机休息（最后一页不需要休息）
            random_sleep()

        if all_data:
            result_df = pd.concat(all_data, ignore_index=True)
            print(f"✓ 美股列表获取成功，共 {len(result_df)} 只股票（{page} 页）")

            # 按分类统计
            if 'classify' in result_df.columns:
                print("  - 分类分布：")
                for classify, count in result_df['classify'].value_counts().items():
                    print(f"    {classify}: {count} 只")

            return result_df
        else:
            print("[错误] 美股数据为空")
            return None

    except Exception as e:
        print(f"[错误] 获取美股列表失败: {e}")
        return None


def save_to_csv(df: pd.DataFrame, filename: str, market_name: str) -> bool:
    """
    保存数据到 CSV 文件

    Args:
        df: 数据 DataFrame
        filename: 文件名
        market_name: 市场名称（用于日志）

    Returns:
        是否保存成功
    """
    if df is None or len(df) == 0:
        print(f"[跳过] {market_name} 数据为空，不保存文件")
        return False

    try:
        output_path = OUTPUT_DIR / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)

        df.to_csv(output_path, index=False, encoding='utf-8-sig')

        file_size = output_path.stat().st_size / 1024  # KB
        print(f"✓ {market_name} 数据已保存：{output_path} ({file_size:.2f} KB)")
        return True

    except Exception as e:
        print(f"[错误] 保存 {market_name} 数据失败: {e}")
        return False


def generate_data_documentation(
    a_df: Optional[pd.DataFrame],
    hk_df: Optional[pd.DataFrame],
    us_df: Optional[pd.DataFrame]
):
    """
    生成数据说明文档

    Args:
        a_df: A股数据
        hk_df: 港股数据
        us_df: 美股数据
    """
    doc_path = OUTPUT_DIR / "README_stock_list.md"

    content = f"""# Tushare 股票列表数据说明

> 数据来源：[Tushare Pro](https://tushare.pro)
> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 文件说明

| 文件 | 说明 | 记录数 |
|------|------|--------|
| `stock_list_a.csv` | A股列表 | {len(a_df) if a_df is not None else 0} |
| `stock_list_hk.csv` | 港股列表 | {len(hk_df) if hk_df is not None else 0} |
| `stock_list_us.csv` | 美股列表 | {len(us_df) if us_df is not None else 0} |

---

## A股数据（stock_list_a.csv）

### 数据接口
- **接口名称**：`stock_basic`
- **数据权限**：2000积分起，每分钟请求50次
- **数据限量**：单次最多6000行（覆盖全市场A股）

### 字段说明

| 字段名 | 类型 | 说明 | 示例 |
|--------|------|------|------|
| ts_code | str | TS代码 | 000001.SZ |
| symbol | str | 股票代码 | 000001 |
| name | str | 股票名称 | 平安银行 |
| area | str | 地域 | 深圳 |
| industry | str | 所属行业 | 银行 |
| fullname | str | 股票全称 | 平安银行股份有限公司 |
| enname | str | 英文全称 | Ping An Bank Co., Ltd. |
| cnspell | str | 拼音缩写 | PAYH |
| market | str | 市场类型 | 主板/创业板/科创板/CDR |
| exchange | str | 交易所代码 | SSE上交所/SZSE深交所/BSE北交所 |
| curr_type | str | 交易货币 | CNY |
| list_status | str | 上市状态 | L上市/D退市/P暂停上市 |
| list_date | str | 上市日期 | 19910403 |
| delist_date | str | 退市日期 | - |
| is_hs | str | 是否沪深港通标的 | N否/H沪股通/S深股通 |
| act_name | str | 实控人名称 | - |
| act_ent_type | str | 实控人企业性质 | - |

### 数据样例
```csv
ts_code,symbol,name,area,industry,fullname,enname,cnspell,market,exchange,curr_type,list_status,list_date,delist_date,is_hs,act_name,act_ent_type
000001.SZ,000001,平安银行,深圳,银行,平安银行股份有限公司,Ping An Bank Co., Ltd.,PAYH,主板,SZSE,CNY,L,19910403,,S,,
000002.SZ,000002,万科A,深圳,全国地产,万科企业股份有限公司,China Vanke Co., Ltd.,ZKA,主板,SZSE,CNY,L,19910129,,S,,
```

---

## 港股数据（stock_list_hk.csv）

### 数据接口
- **接口名称**：`hk_basic`
- **数据权限**：用户需要至少2000积分才可以调取
- **数据限量**：单次可提取全部在交易的港股列表数据

### 字段说明

| 字段名 | 类型 | 说明 | 示例 |
|--------|------|------|------|
| ts_code | str | TS代码 | 00001.HK |
| name | str | 股票简称 | 长和 |
| fullname | str | 公司全称 | 长江和记实业有限公司 |
| enname | str | 英文名称 | CK Hutchison Holdings Ltd. |
| cn_spell | str | 拼音 | ZH |
| market | str | 市场类别 | 主板/创业板 |
| list_status | str | 上市状态 | L上市/D退市/P暂停上市 |
| list_date | str | 上市日期 | 19720731 |
| delist_date | str | 退市日期 | - |
| trade_unit | float | 交易单位 | 1000 |
| isin | str | ISIN代码 | KYG217651051 |
| curr_type | str | 货币代码 | HKD |

### 数据样例
```csv
ts_code,name,fullname,enname,cn_spell,market,list_status,list_date,delist_date,trade_unit,isin,curr_type
00001.HK,长和,长江和记实业有限公司,CK Hutchison Holdings Ltd.,ZH,主板,L,19720731,,1000,KYG217651051,HKD
00002.HK,中电控股,中华电力有限公司,CLP Holdings Ltd.,ZDKG,主板,L,19860125,,1000,HK0002007356,HKD
```

---

## 美股数据（stock_list_us.csv）

### 数据接口
- **接口名称**：`us_basic`
- **数据权限**：120积分可以试用，5000积分有正式权限
- **数据限量**：单次最大6000，可分页提取

### 字段说明

| 字段名 | 类型 | 说明 | 示例 |
|--------|------|------|------|
| ts_code | str | 美股代码 | AAPL |
| name | str | 中文名称 | 苹果 |
| enname | str | 英文名称 | Apple Inc. |
| classify | str | 分类 | ADR/GDR/EQT |
| list_date | str | 上市日期 | 19801212 |
| delist_date | str | 退市日期 | - |

### 分类说明
- **ADR**：美国存托凭证（American Depositary Receipt）
- **GDR**：全球存托凭证（Global Depositary Receipt）
- **EQT**：普通股（Equity）

### 数据样例
```csv
ts_code,name,enname,classify,list_date,delist_date
AAPL,苹果,Apple Inc.,EQT,19801212,
TSLA,特斯拉,Tesla Inc.,EQT,20100629,
BABA,阿里巴巴,Alibaba Group Holding Ltd.,ADR,20140919,
```

---

## 使用说明

### 读取数据

```python
import pandas as pd

# 读取 A股数据
a_stocks = pd.read_csv('data/stock_list_a.csv')

# 读取港股数据
hk_stocks = pd.read_csv('data/stock_list_hk.csv')

# 读取美股数据
us_stocks = pd.read_csv('data/stock_list_us.csv')
```

### 代码格式说明

**A股代码格式**：
- 沪市：`600000.SH`（主板）、`688xxx.SH`（科创板）、`900xxx.SH`（B股）
- 深市：`000001.SZ`（主板）、`300xxx.SZ`（创业板）、`200xxx.SZ`（B股）
- 北交所：`8xxxxx.BJ`、`4xxxxx.BJ`、`920xxx.BJ`

**港股代码格式**：
- 格式：`xxxxx.HK`（5位数字 + .HK）
- 示例：`00700.HK`（腾讯控股）

**美股代码格式**：
- 格式：代码字母（无后缀）
- 示例：`AAPL`（苹果）、`TSLA`（特斯拉）

---

## 注意事项

1. **数据更新**：建议定期更新数据（如每月一次）
2. **积分要求**：
   - A股/港股：需要2000积分
   - 美股：120积分试用，5000积分正式权限
3. **请求限制**：注意 API 的每分钟请求次数限制
4. **数据完整性**：本数据仅包含基础信息，如需更多数据请参考 Tushare 官方文档

---

## 相关链接

- [Tushare 官网](https://tushare.pro)
- [Tushare 文档](https://tushare.pro/document/2)
- [积分获取办法](https://tushare.pro/document/1)
- [API 数据调试](https://tushare.pro/document/2)
"""

    try:
        with open(doc_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✓ 数据说明文档已生成：{doc_path}")
    except Exception as e:
        print(f"[错误] 生成说明文档失败: {e}")


def main():
    """主函数"""
    print("=" * 60)
    print("Tushare 股票列表获取工具")
    print("=" * 60)

    # 1. 获取 API 实例
    api = get_tushare_api()
    if not api:
        return 1

    # 2. 获取 A股数据
    a_df = fetch_a_stock_list(api)
    if a_df is not None:
        save_to_csv(a_df, 'stock_list_a.csv', 'A股')

    # 3. 获取港股数据
    random_sleep()  # 休息后再获取港股
    hk_df = fetch_hk_stock_list(api)
    if hk_df is not None:
        save_to_csv(hk_df, 'stock_list_hk.csv', '港股')

    # 4. 获取美股数据（分页）
    random_sleep()  # 休息后再获取美股
    us_df = fetch_us_stock_list(api)
    if us_df is not None:
        save_to_csv(us_df, 'stock_list_us.csv', '美股')

    # 5. 生成数据说明文档
    print("\n正在生成数据说明文档...")
    generate_data_documentation(a_df, hk_df, us_df)

    # 6. 总结
    print("\n" + "=" * 60)
    print("任务完成！")
    print("=" * 60)

    total_count = 0
    if a_df is not None:
        total_count += len(a_df)
        print(f"  ✓ A股：{len(a_df)} 只")
    if hk_df is not None:
        total_count += len(hk_df)
        print(f"  ✓ 港股：{len(hk_df)} 只")
    if us_df is not None:
        total_count += len(us_df)
        print(f"  ✓ 美股：{len(us_df)} 只")

    print(f"\n总计：{total_count} 只股票")
    print(f"输出目录：{OUTPUT_DIR}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n[中断] 用户取消操作")
        sys.exit(1)
    except Exception as e:
        print(f"\n[错误] 未预期的异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
