#!/bin/bash
# ===================================
# A股/港股/美股 智能分析系统 - 测试脚本
# ===================================
#
# 使用方法：
#   ./test.sh [测试场景]
#
# 测试场景：
#   market      - 仅大盘复盘
#   a-stock     - A股个股分析（茅台、平安银行）
#   etf         - etf分析(卫星etf 563230)
#   hk-stock    - 港股分析（腾讯、阿里）
#   us-stock    - 美股分析（苹果、特斯拉）
#   mixed       - 混合市场分析
#   single      - 单股模式测试
#   dry-run     - 仅获取数据不分析
#   full        - 完整流程测试
#   quick       - 快速测试（单只股票）
#   all         - 运行所有测试
#
# 示例：
#   ./test.sh market      # 测试大盘复盘
#   ./test.sh us-stock    # 测试美股分析
#   ./test.sh quick       # 快速测试
#

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 打印带颜色的信息
info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

header() {
    echo ""
    echo "=============================================="
    echo -e "${GREEN}$1${NC}"
    echo "=============================================="
    echo ""
}

# 检查Python环境
check_python() {
    if ! command -v python3 &> /dev/null; then
        error "Python3 未安装"
        exit 1
    fi
    info "Python版本: $(python3 --version)"
}

# 检查依赖
check_deps() {
    info "检查依赖..."
    python3 -c "import yfinance" 2>/dev/null || { warn "yfinance 未安装，美股测试可能失败"; }
    python3 -c "import akshare" 2>/dev/null || { warn "akshare 未安装，A股/港股测试可能失败"; }
    success "依赖检查完成"
}

# ==================== 测试场景 ====================

# 测试1: 大盘复盘
test_market() {
    header "测试场景: 大盘复盘"
    info "运行大盘复盘分析..."
    python3 main.py --market-review "$@"
    success "大盘复盘测试完成"
}

# 测试2: A股分析
test_a_stock() {
    header "测试场景: A股分析"
    info "分析A股: 600519(茅台), 000001(平安银行)"
    python3 main.py --stocks 600519,000001  --no-market-review "$@"
    success "A股分析测试完成"
}

# 测试2.5: ETF分析
test_etf() {
    header "测试场景: ETF分析"
    info "分析ETF: 563230(卫星ETF)"
    python3 main.py --stocks 563230,512400 --no-market-review "$@"
    success "ETF分析测试完成"
}

# 测试3: 港股分析
test_hk_stock() {
    header "测试场景: 港股分析"
    info "分析港股: hk00700(腾讯), hk09988(阿里)"
    python3 main.py --stocks hk00700,hk09988 --no-market-review "$@"
    success "港股分析测试完成"
}

# 测试4: 美股分析
test_us_stock() {
    header "测试场景: 美股分析"
    info "分析美股: AAPL(苹果), TSLA(特斯拉)"
    # 允许透传参数，默认不带 --no-notify
    python3 main.py --stocks AAPL --no-market-review "$@"
    success "美股分析测试完成"
}

# 测试5: 混合市场
test_mixed() {
    header "测试场景: 混合市场分析"
    info "分析混合市场: 600519(A股), hk00700(港股), AAPL(美股)"
    python3 main.py --stocks 600519,hk00700,AAPL --no-market-review
    success "混合市场测试完成"
}

# 测试6: 单股推送模式
test_single() {
    header "测试场景: 单股推送模式"
    info "测试单股推送模式..."
    python3 main.py --stocks 600519 --single-notify --no-market-review
    success "单股推送模式测试完成"
}

# 测试7: dry-run模式
test_dry_run() {
    header "测试场景: Dry-Run 模式"
    info "仅获取数据，不进行AI分析..."
    python3 main.py --stocks 600519,AAPL --dry-run --no-notify
    success "Dry-Run 测试完成"
}

# 测试8: 完整流程
test_full() {
    header "测试场景: 完整流程"
    info "运行完整分析流程（个股+大盘）..."
    python3 main.py --stocks 600519 --no-notify
    success "完整流程测试完成"
}

# 测试9: 快速测试
test_quick() {
    header "测试场景: 快速测试"
    info "单只股票快速测试..."
    python3 main.py --stocks 600519 --no-market-review
    success "快速测试完成"
}

# 测试10: 代码识别测试
test_code_recognition() {
    header "测试场景: 代码识别"
    info "测试股票代码识别逻辑..."

    python3 << 'PYTEST'
import sys
sys.path.insert(0, '.')
from data_provider.akshare_fetcher import _is_hk_code, _is_us_code

test_cases = [
    # (代码, 预期HK, 预期US, 描述)
    ("AAPL", False, True, "美股-苹果"),
    ("TSLA", False, True, "美股-特斯拉"),
    ("BRK.B", False, True, "美股-伯克希尔B"),
    ("hk00700", True, False, "港股-腾讯"),
    ("HK09988", True, False, "港股-阿里"),
    ("600519", False, False, "A股-茅台"),
    ("000001", False, False, "A股-平安"),
]

print("\n股票代码识别测试:")
print("-" * 60)
all_pass = True
for code, exp_hk, exp_us, desc in test_cases:
    is_hk = _is_hk_code(code)
    is_us = _is_us_code(code)
    hk_ok = is_hk == exp_hk
    us_ok = is_us == exp_us
    status = "✅" if (hk_ok and us_ok) else "❌"
    all_pass = all_pass and hk_ok and us_ok
    print(f"{status} {code:10} | HK:{is_hk:5} US:{is_us:5} | {desc}")

print("-" * 60)
print(f"{'✅ 所有测试通过!' if all_pass else '❌ 有测试失败!'}")
sys.exit(0 if all_pass else 1)
PYTEST

    success "代码识别测试完成"
}

# 测试11: YFinance代码转换测试
test_yfinance_convert() {
    header "测试场景: YFinance 代码转换"
    info "测试YFinance代码转换逻辑..."

    python3 << 'PYTEST'
import sys
sys.path.insert(0, '.')
from data_provider.yfinance_fetcher import YfinanceFetcher

fetcher = YfinanceFetcher()

test_cases = [
    ("AAPL", "AAPL", "美股"),
    ("tsla", "TSLA", "美股小写"),
    ("BRK.B", "BRK.B", "美股特殊"),
    ("hk00700", "0700.HK", "港股"),
    ("HK09988", "9988.HK", "港股大写"),
    ("600519", "600519.SS", "A股沪市"),
    ("000001", "000001.SZ", "A股深市"),
    ("300750", "300750.SZ", "A股创业板"),
]

print("\nYFinance 代码转换测试:")
print("-" * 60)
all_pass = True
for input_code, expected, desc in test_cases:
    result = fetcher._convert_stock_code(input_code)
    status = "✅" if result == expected else "❌"
    all_pass = all_pass and (result == expected)
    print(f"{status} {input_code:10} -> {result:12} (期望: {expected:12}) | {desc}")

print("-" * 60)
print(f"{'✅ 所有测试通过!' if all_pass else '❌ 有测试失败!'}")
sys.exit(0 if all_pass else 1)
PYTEST

    success "YFinance 代码转换测试完成"
}

# 测试12: 语法检查
test_syntax() {
    header "测试场景: Python 语法检查"
    info "检查所有Python文件语法..."

    python3 -m py_compile main.py src/config.py src/notification.py \
        data_provider/akshare_fetcher.py \
        data_provider/yfinance_fetcher.py \
        bot/commands/analyze.py

    success "语法检查通过"
}

# 测试13: Flake8 静态检查
test_flake8() {
    header "测试场景: Flake8 静态检查"
    info "运行 Flake8 检查严重错误..."

    if command -v flake8 &> /dev/null; then
        flake8 main.py src/config.py src/notification.py --select=F821,E999 --max-line-length=120
        success "Flake8 检查通过"
    else
        warn "Flake8 未安装，跳过检查"
    fi
}

# 运行所有测试
test_all() {
    header "运行所有测试"

    test_syntax
    test_code_recognition
    test_yfinance_convert
    test_flake8

    echo ""
    info "以下测试需要网络和API配置，可能会失败:"
    echo ""

    test_dry_run || warn "Dry-Run 测试失败（可能是网络问题）"
    test_quick || warn "快速测试失败（可能是API问题）"

    success "所有测试完成!"
}

# ==================== 主程序 ====================

main() {
    header "A股/港股/美股 智能分析系统 - 测试"

    check_python
    check_deps

    case "${1:-help}" in
        market)
            shift
            test_market "$@"
            ;;
        a-stock|a_stock|astock)
            shift
            test_a_stock "$@"
            ;;
        etf)
            shift
            test_etf "$@"
            ;;
        hk-stock|hk_stock|hkstock|hk)
            shift
            test_hk_stock "$@"
            ;;
        us-stock|us_stock|usstock|us)
            shift
            test_us_stock "$@"
            ;;
        mixed|mix)
            shift
            test_mixed "$@"
            ;;
        single)
            shift
            test_single "$@"
            ;;
        dry-run|dryrun|dry)
            shift
            test_dry_run "$@"
            ;;
        full)
            shift
            test_full "$@"
            ;;
        quick|q)
            shift
            test_quick "$@"
            ;;
        code|recognition)
            shift
            test_code_recognition "$@"
            ;;
        yfinance|yf)
            shift
            test_yfinance_convert "$@"
            ;;
        syntax)
            shift
            test_syntax "$@"
            ;;
        flake8|lint)
            shift
            test_flake8 "$@"
            ;;
        all)
            shift
            test_all "$@"
            ;;
        help|--help|-h|*)
            echo "使用方法: $0 [测试场景]"
            echo ""
            echo "测试场景:"
            echo "  market      - 仅大盘复盘"
            echo "  a-stock     - A股个股分析"
            echo "  etf         - ETF分析"
            echo "  hk-stock    - 港股分析"
            echo "  us-stock    - 美股分析"
            echo "  mixed       - 混合市场分析"
            echo "  single      - 单股推送模式"
            echo "  dry-run     - 仅获取数据"
            echo "  full        - 完整流程"
            echo "  quick       - 快速测试（推荐）"
            echo "  code        - 代码识别测试"
            echo "  yfinance    - YFinance转换测试"
            echo "  syntax      - 语法检查"
            echo "  flake8      - 静态检查"
            echo "  all         - 运行所有测试"
            echo ""
            echo "示例:"
            echo "  $0 quick     # 快速测试"
            echo "  $0 us-stock  # 测试美股"
            echo "  $0 code      # 测试代码识别"
            echo "  $0 all       # 运行所有测试"
            ;;
    esac
}

main "$@"
