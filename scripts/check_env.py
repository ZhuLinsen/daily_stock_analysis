# -*- coding: utf-8 -*-
"""
===================================
A股自选股智能分析系统 - 环境验证测试
===================================

用于验证 .env 配置是否正确，包括：
1. 配置加载测试
2. 数据库查看
3. 数据源测试
4. LLM 调用测试
5. 通知推送测试

使用方法：
    python scripts/check_env.py              # 运行所有测试
    python scripts/check_env.py --db         # 仅查看数据库
    python scripts/check_env.py --llm        # 仅测试 LLM
    python scripts/check_env.py --fetch      # 仅测试数据获取
    python scripts/check_env.py --notify     # 仅测试通知

"""
import os
# Proxy config - controlled by USE_PROXY env var, off by default.
# Set USE_PROXY=true in .env if you need a local proxy (e.g. mainland China).
# GitHub Actions always skips this regardless of USE_PROXY.
if os.getenv("GITHUB_ACTIONS") != "true" and os.getenv("USE_PROXY", "false").lower() == "true":
    proxy_host = os.getenv("PROXY_HOST", "127.0.0.1")
    proxy_port = os.getenv("PROXY_PORT", "10809")
    proxy_url = f"http://{proxy_host}:{proxy_port}"
    os.environ["http_proxy"] = proxy_url
    os.environ["https_proxy"] = proxy_url

import argparse
import logging
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def print_header(title: str):
    """打印标题"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_section(title: str):
    """打印小节"""
    print(f"\n--- {title} ---")


def check_config():
    """测试配置加载"""
    print_header("1. 配置加载测试")
    
    from src.config import get_config
    config = get_config()
    
    print_section("基础配置")
    print(f"  股票列表: {config.stock_list}")
    print(f"  数据库路径: {config.database_path}")
    print(f"  最大并发数: {config.max_workers}")
    print(f"  调试模式: {config.debug}")
    
    print_section("API 配置")
    print(f"  Tushare Token: {'已配置 ✓' if config.tushare_token else '未配置 ✗'}")
    if config.tushare_token:
        print(f"    Token 前8位: {config.tushare_token[:8]}...")
    
    print(f"  Gemini API Key: {'已配置 ✓' if config.gemini_api_key else '未配置 ✗'}")
    if config.gemini_api_key:
        print(f"    Key 前8位: {config.gemini_api_key[:8]}...")
    print(f"  Gemini 主模型: {config.gemini_model}")
    print(f"  Gemini 备选模型: {config.gemini_model_fallback}")
    
    print(f"  企业微信 Webhook: {'已配置 ✓' if config.wechat_webhook_url else '未配置 ✗'}")
    
    print_section("配置验证")
    issues = config.validate_structured()
    _prefix = {"error": "  ✗", "warning": "  ⚠", "info": "  ·"}
    for issue in issues:
        print(f"{_prefix.get(issue.severity, '  ?')} [{issue.severity.upper()}] {issue.message}")
    if not any(i.severity in ("error", "warning") for i in issues):
        print("  ✓ 关键配置项验证通过")
    
    return True


def view_database():
    """查看数据库内容"""
    print_header("2. 数据库内容查看")
    
    from src.storage import get_db
    from sqlalchemy import text
    
    db = get_db()
    
    print_section("数据库连接")
    print(f"  ✓ 连接成功")
    
    # 使用独立的 session 查询
    session = db.get_session()
    try:
        # 统计信息
        result = session.execute(text("""
            SELECT 
                code,
                COUNT(*) as count,
                MIN(date) as min_date,
                MAX(date) as max_date,
                data_source
            FROM stock_daily 
            GROUP BY code
            ORDER BY code
        """))
        stocks = result.fetchall()
        
        print_section(f"已存储股票数据 (共 {len(stocks)} 只)")
        if stocks:
            print(f"  {'代码':<10} {'记录数':<8} {'起始日期':<12} {'最新日期':<12} {'数据源'}")
            print("  " + "-" * 60)
            for row in stocks:
                print(f"  {row[0]:<10} {row[1]:<8} {row[2]!s:<12} {row[3]!s:<12} {row[4] or 'Unknown'}")
        else:
            print("  暂无数据")
        
        # 查询今日数据
        today = date.today()
        result = session.execute(text("""
            SELECT code, date, open, high, low, close, pct_chg, volume, ma5, ma10, ma20, volume_ratio
            FROM stock_daily 
            WHERE date = :today
            ORDER BY code
        """), {"today": today})
        today_data = result.fetchall()
        
        print_section(f"今日数据 ({today})")
        if today_data:
            for row in today_data:
                code, dt, open_, high, low, close, pct_chg, volume, ma5, ma10, ma20, vol_ratio = row
                print(f"\n  【{code}】")
                print(f"    开盘: {open_:.2f}  最高: {high:.2f}  最低: {low:.2f}  收盘: {close:.2f}")
                print(f"    涨跌幅: {pct_chg:.2f}%  成交量: {volume/10000:.2f}万股")
                print(f"    MA5: {ma5:.2f}  MA10: {ma10:.2f}  MA20: {ma20:.2f}  量比: {vol_ratio:.2f}")
        else:
            print("  今日暂无数据")
        
        # 查询最近10条数据
        result = session.execute(text("""
            SELECT code, date, close, pct_chg, volume, data_source
            FROM stock_daily 
            ORDER BY date DESC, code
            LIMIT 10
        """))
        recent = result.fetchall()
        
        print_section("最近10条记录")
        if recent:
            print(f"  {'代码':<10} {'日期':<12} {'收盘':<10} {'涨跌%':<8} {'成交量':<15} {'来源'}")
            print("  " + "-" * 70)
            for row in recent:
                vol_str = f"{row[4]/10000:.2f}万" if row[4] else "N/A"
                print(f"  {row[0]:<10} {row[1]!s:<12} {row[2]:<10.2f} {row[3]:<8.2f} {vol_str:<15} {row[5] or 'Unknown'}")
    finally:
        session.close()
    
    return True


def check_data_fetch(stock_code: str = "600519"):
    """测试数据获取"""
    print_header("3. 数据获取测试")
    
    from data_provider import DataFetcherManager
    
    manager = DataFetcherManager()
    
    print_section("数据源列表")
    for i, name in enumerate(manager.available_fetchers, 1):
        print(f"  {i}. {name}")
    
    print_section(f"获取 {stock_code} 数据")
    print(f"  正在获取（可能需要几秒钟）...")
    
    try:
        df, source = manager.get_daily_data(stock_code, days=5)
        
        print(f"  ✓ 获取成功")
        print(f"    数据源: {source}")
        print(f"    记录数: {len(df)}")
        
        print_section("数据预览（最近5条）")
        if not df.empty:
            preview_cols = ['date', 'open', 'high', 'low', 'close', 'pct_chg', 'volume']
            existing_cols = [c for c in preview_cols if c in df.columns]
            print(df[existing_cols].tail().to_string(index=False))
        
        return True
        
    except Exception as e:
        print(f"  ✗ 获取失败: {e}")
        return False


def check_llm():
    """测试 LLM 调用"""
    print_header("4. LLM (Gemini) 调用测试")
    
    from src.analyzer import GeminiAnalyzer
    from src.config import get_config
    import time
    
    config = get_config()
    
    print_section("模型配置")
    print(f"  主模型: {config.gemini_model}")
    print(f"  备选模型: {config.gemini_model_fallback}")
    
    # 检查网络连接
    print_section("网络连接检查")
    try:
        import socket
        socket.setdefaulttimeout(10)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("generativelanguage.googleapis.com", 443))
        print(f"  ✓ 可以连接到 Google API 服务器")
    except Exception as e:
        print(f"  ✗ 无法连接到 Google API 服务器: {e}")
        print(f"  提示: 请检查网络连接或配置代理")
        print(f"  提示: 可以设置环境变量 HTTPS_PROXY=http://your-proxy:port")
        return False
    
    analyzer = GeminiAnalyzer()
    
    print_section("模型初始化")
    if analyzer.is_available():
        print(f"  ✓ 模型初始化成功")
    else:
        print(f"  ✗ 模型初始化失败（请检查 API Key）")
        return False
    
    # 构造测试上下文
    test_context = {
        'code': '600519',
        'date': date.today().isoformat(),
        'today': {
            'open': 1420.0,
            'high': 1435.0,
            'low': 1415.0,
            'close': 1428.0,
            'volume': 5000000,
            'amount': 7140000000,
            'pct_chg': 0.56,
            'ma5': 1425.0,
            'ma10': 1418.0,
            'ma20': 1410.0,
            'volume_ratio': 1.1,
        },
        'ma_status': '多头排列 📈',
        'volume_change_ratio': 1.05,
        'price_change_ratio': 0.56,
    }
    
    print_section("发送测试请求")
    print(f"  测试股票: 贵州茅台 (600519)")
    print(f"  正在调用 Gemini API（超时: 60秒）...")
    
    start_time = time.time()
    
    try:
        result = analyzer.analyze(test_context)
        
        elapsed = time.time() - start_time
        print(f"\n  ✓ API 调用成功 (耗时: {elapsed:.2f}秒)")
        
        print_section("分析结果")
        print(f"  情绪评分: {result.sentiment_score}/100")
        print(f"  趋势预测: {result.trend_prediction}")
        print(f"  操作建议: {result.operation_advice}")
        print(f"  技术分析: {result.technical_analysis[:80]}..." if len(result.technical_analysis) > 80 else f"  技术分析: {result.technical_analysis}")
        print(f"  消息面: {result.news_summary[:80]}..." if len(result.news_summary) > 80 else f"  消息面: {result.news_summary}")
        print(f"  综合摘要: {result.analysis_summary}")
        
        if not result.success:
            print(f"\n  ⚠ 注意: {result.error_message}")
        
        return result.success
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n  ✗ API 调用失败 (耗时: {elapsed:.2f}秒)")
        print(f"  错误: {e}")
        
        # 提供更详细的错误提示
        error_str = str(e).lower()
        if 'timeout' in error_str or 'unavailable' in error_str:
            print(f"\n  诊断: 网络超时，可能原因:")
            print(f"    1. 网络不通（需要代理访问 Google）")
            print(f"    2. API 服务暂时不可用")
            print(f"    3. 请求量过大被限流")
        elif 'invalid' in error_str or 'api key' in error_str:
            print(f"\n  诊断: API Key 可能无效")
        elif 'model' in error_str:
            print(f"\n  诊断: 模型名称可能不正确，尝试修改 .env 中的 GEMINI_MODEL")
        
        return False


def check_notification():
    """测试通知推送"""
    print_header("5. 通知推送测试")
    
    from src.notification import NotificationService
    from src.config import get_config
    
    config = get_config()
    service = NotificationService()
    
    print_section("配置检查")
    if service.is_available():
        print(f"  ✓ 企业微信 Webhook 已配置")
        webhook_preview = config.wechat_webhook_url[:50] + "..." if len(config.wechat_webhook_url) > 50 else config.wechat_webhook_url
        print(f"    URL: {webhook_preview}")
    else:
        print(f"  ✗ 企业微信 Webhook 未配置")
        return False
    
    print_section("发送测试消息")
    
    test_message = f"""## 🧪 系统测试消息

这是一条来自 **A股自选股智能分析系统** 的测试消息。

- 测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- 测试目的: 验证企业微信 Webhook 配置

如果您收到此消息，说明通知功能配置正确 ✓"""
    
    print(f"  正在发送...")
    
    try:
        success = service.send_to_wechat(test_message)
        
        if success:
            print(f"  ✓ 消息发送成功，请检查企业微信")
        else:
            print(f"  ✗ 消息发送失败")
        
        return success
        
    except Exception as e:
        print(f"  ✗ 发送异常: {e}")
        return False


def run_all_tests():
    """运行所有测试"""
    print("\n" + "🚀" * 20)
    print("  A股自选股智能分析系统 - 环境验证")
    print("  " + datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    print("🚀" * 20)
    
    results = {}
    
    # 1. 配置测试
    try:
        results['配置加载'] = check_config()
    except Exception as e:
        print(f"  ✗ 配置测试失败: {e}")
        results['配置加载'] = False
    
    # 2. 数据库查看
    try:
        results['数据库'] = view_database()
    except Exception as e:
        print(f"  ✗ 数据库测试失败: {e}")
        results['数据库'] = False
    
    # 3. 数据获取（跳过，避免太慢）
    # results['数据获取'] = check_data_fetch()
    
    # 4. LLM 测试（可选）
    # results['LLM调用'] = check_llm()
    
    # 汇总
    print_header("测试结果汇总")
    for name, passed in results.items():
        status = "✓ 通过" if passed else "✗ 失败"
        print(f"  {status}: {name}")
    
    print(f"\n提示: 使用 --llm 参数单独测试 LLM 调用")
    print(f"提示: 使用 --fetch 参数单独测试数据获取")
    print(f"提示: 使用 --notify 参数单独测试通知推送")


def query_stock_data(stock_code: str, days: int = 10):
    """查询指定股票的数据"""
    print_header(f"查询股票数据: {stock_code}")
    
    from src.storage import get_db
    from sqlalchemy import text
    
    db = get_db()
    
    session = db.get_session()
    try:
        result = session.execute(text("""
            SELECT date, open, high, low, close, pct_chg, volume, amount, ma5, ma10, ma20, volume_ratio
            FROM stock_daily 
            WHERE code = :code
            ORDER BY date DESC
            LIMIT :limit
        """), {"code": stock_code, "limit": days})
        
        rows = result.fetchall()
        
        if rows:
            print(f"\n  最近 {len(rows)} 条记录:\n")
            print(f"  {'日期':<12} {'开盘':<10} {'最高':<10} {'最低':<10} {'收盘':<10} {'涨跌%':<8} {'MA5':<10} {'MA10':<10} {'量比':<8}")
            print("  " + "-" * 100)
            for row in rows:
                dt, open_, high, low, close, pct_chg, vol, amt, ma5, ma10, ma20, vol_ratio = row
                print(f"  {dt!s:<12} {open_:<10.2f} {high:<10.2f} {low:<10.2f} {close:<10.2f} {pct_chg:<8.2f} {ma5:<10.2f} {ma10:<10.2f} {vol_ratio:<8.2f}")
        else:
            print(f"  未找到 {stock_code} 的数据")
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(
        description='A股自选股智能分析系统 - 环境验证测试',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument('--db', action='store_true', help='查看数据库内容')
    parser.add_argument('--llm', action='store_true', help='测试 LLM 调用')
    parser.add_argument('--fetch', action='store_true', help='测试数据获取')
    parser.add_argument('--notify', action='store_true', help='测试通知推送')
    parser.add_argument('--config', action='store_true', help='查看配置')
    parser.add_argument('--stock', type=str, help='查询指定股票数据，如 --stock 600519')
    parser.add_argument('--all', action='store_true', help='运行所有测试（包括 LLM）')
    
    args = parser.parse_args()
    
    # 如果没有指定任何参数，运行基础测试
    if not any([args.db, args.llm, args.fetch, args.notify, args.config, args.stock, args.all]):
        run_all_tests()
        return 0
    
    # 根据参数运行指定测试
    if args.config:
        check_config()
    
    if args.db:
        view_database()
    
    if args.stock:
        query_stock_data(args.stock)
    
    if args.fetch:
        check_data_fetch()
    
    if args.llm:
        check_llm()
    
    if args.notify:
        check_notification()
    
    if args.all:
        check_config()
        view_database()
        check_data_fetch()
        check_llm()
        check_notification()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
