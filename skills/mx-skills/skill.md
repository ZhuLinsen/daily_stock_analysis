---
# 东方财富妙想金融技能集合元数据
name: mx_skills
description: 东方财富妙想提供的金融技能集合，涵盖金融数据查询、资讯搜索、智能选股、自选股管理和模拟组合管理，所有技能均需通过MX_APIKEY进行认证。
version: 1.0.0
required env vars:
  - MX_APIKEY
环境变量:
  - MX_APIKEY
required_env_vars:
  - MX_APIKEY
credentials:
  - type: api_key
    name: MX_APIKEY
    description: 从东方财富技能市场（https://dl.dfcfs.com/m/itc4）获取的API Key，用于所有子技能的调用鉴权。
skills:
  - name: eastmoney_financial_data
    description: 提供东方财富妙想的金融数据查询能力，包括股票、基金、债券、指数等行情数据、财务数据、基本面数据等。适用于需要获取结构化金融数据的任务。
  - name: eastmoney_financial_search
    description: 基于东方财富妙想搜索能力，对金融场景进行信源智能筛选，用于获取涉及时效性信息或特定事件的任务，包括新闻、公告、研报、政策、交易规则、具体事件、影响分析等。可避免AI引用非权威或过时信息。
  - name: eastmoney_select_stock
    description: 智能选股功能，根据用户指定的财务指标、市场指标、技术指标等条件筛选股票，支持多维度组合查询，返回符合条件的股票列表。
  - name: eastmoney_self_select
    description: 自选股管理功能，支持添加、删除、查询自选股，并可获取自选股的实时行情、公告提醒等信息，便于用户跟踪关注标的。
  - name: eastmoney_stock_simulator
    description: 模拟组合管理功能，允许用户创建模拟投资组合，进行买卖交易记录，查看持仓、收益和交易历史，用于策略回测和投资演练。
required_tools:
  - mx_data_query
  - mx_search_query
  - mx_xuangu_query
  - mx_zixuan_query
---

# 东方财富妙想Skills安装指南

## daily_stock_analysis 兼容说明

本项目会扫描 `skills/` 下的 `SKILL.md`，并把妙想脚本包装为以下 Agent 工具：`mx_data_query`、`mx_search_query`、`mx_xuangu_query`、`mx_zixuan_query`。这些工具只在服务端读取 `MX_APIKEY`，返回受限预览和输出文件路径，不会把 API Key 暴露到前端或报告。

妙想工具用于数据查询、资讯搜索、智能选股和自选股管理复盘，不做自动交易、不接券商接口、不承诺收益。

本文档介绍了如何在本地环境中安装和验证东方财富妙想提供的金融skill集合，按照以下步骤操作，确保skill正确安装并可用。

## 前提条件

- 确保已安装Node.js环境（版本22或以上）。

```bash
# 检查 Node.js 版本
if ! command -v node &> /dev/null; then
  echo "错误：未安装 Node.js。请先安装 Node.js 22 或以上版本。"
  exit 1
fi
```

- 确保已获取并提供有效的`MX_APIKEY`。
  如果缺少API密钥，提示用户前往妙想Skills页面（地址：https://dl.dfcfs.com/m/itc4），获取并设置后再继续使用。
- 在进行http请求时，Header 中必须携带 `apikey` 进行认证。

## 安装步骤

### 1. 清理旧版本

安装前，请先删除`~/.openclaw/skills`目录下任何以`mx-skills`开头的现有技能目录，以避免版本冲突：

```bash
rm -rf ~/.openclaw/skills/mx-skills*
```

### 2. 下载妙想Skill

从云端下载最新的`mx-skills`skill 定义，保持所有文件在同一目录下：

```bash
mkdir -p ~/.openclaw/skills/mx-skills/scripts
# 下载 妙想金融数据skill
MX_DATA_DOWNLOAD_URL="https://marketdfs.dfcfw.com/file/download/E220260320DRQ9S9.zip"
MX_DATA_TEMP_FILE= "/temp/mx_data.zip"
MX_DATA_OUTPUT_PATH="~/.openclaw/skills/mx-skills/mx-data/"

curl -fSL MX_DATA_DOWNLOAD_URL -o MX_DATA_TEMP_FILE || { echo "下载 mx_data.zip 失败"; exit 1; }
unzip -o MX_DATA_TEMP_FILE -d MX_DATA_OUTPUT_PATH || { echo "解压 mx_data.zip 失败"; exit 1; }
rm -f MX_DATA_TEMP_FILE
# 下载 妙想资讯搜索skill
MX_SEARCH_DOWNLOAD_URL="https://marketdfs.dfcfw.com/file/download/E2202603204ELGGZ.zip"
MX_SEARCH_TEMP_FILE="/temp/mx_search.zip"
MX_SEARCH_OUTPUT_PATH="~/.openclaw/skills/mx-skills/mx-search/"

curl -fSL MX_SEARCH_DOWNLOAD_URL -o MX_SEARCH_TEMP_FILE || { echo "下载 mx_search.zip 失败"; exit 1; }
unzip -o MX_SEARCH_TEMP_FILE -d MX_SEARCH_OUTPUT_PATH || { echo "解压 mx_search.zip 失败"; exit 1; }
rm -f MX_SEARCH_TEMP_FILE
# 下载 妙想智能选股skill
MX_SELECT_STOCK_DOWNLOAD_URL="https://marketdfs.dfcfw.com/file/download/E1202603204ETIIS.zip"
MX_SELECT_STOCK_TEMP_FILE="/temp/mx_select_stock.zip"
MX_SELECT_STOCK_OUTPUT_PATH="~/.openclaw/skills/mx-skills/mx-select-stock/"

curl -fSL MX_SELECT_STOCK_DOWNLOAD_URL -o MX_SELECT_STOCK_TEMP_FILE || { echo "下载 mx_select_stock.zip 失败"; exit 1; }
unzip -o MX_SELECT_STOCK_TEMP_FILE -d MX_SELECT_STOCK_OUTPUT_PATH || { echo "解压 mx_select_stock.zip 失败"; exit 1; }
rm -f MX_SELECT_STOCK_TEMP_FILE
# 下载 妙想自选股管理skill
MX_SELFSELECT_DOWNLOAD_URL="https://marketdfs.dfcfw.com/file/download/E220260320556PGW.zip"
MX_SELFSELECT_TEMP_FILE="/temp/mx_selfselect.zip"
MX_SELFSELECT_OUTPUT_PATH="~/.openclaw/skills/mx-skills/mx-selfselect/"

curl -fSL MX_SELFSELECT_DOWNLOAD_URL -o MX_SELFSELECT_TEMP_FILE || { echo "下载 mx_selfselect.zip 失败"; exit 1; }
unzip -o MX_SELFSELECT_TEMP_FILE -d MX_SELFSELECT_OUTPUT_PATH || { echo "解压 mx_selfselect.zip 失败"; exit 1; }
rm -f MX_SELFSELECT_TEMP_FILE

#下载 妙想模拟组合管理skill
MX_STOCK_SIMULATOR_DOWNLOAD_URL="https://marketdfs.dfcfw.com/file/download/E220260320DECQBH.zip"
MX_STOCK_SIMULATOR_TEMP_FILE="/temp/mx_stock_simulator.zip"
MX_STOCK_SIMULATOR_OUTPUT_PATH="~/.openclaw/skills/mx-skills/mx-stock-simulator/"

curl -fSL MX_STOCK_SIMULATOR_DOWNLOAD_URL -o MX_STOCK_SIMULATOR_TEMP_FILE || { echo "下载 mx_stock_simulator.zip 失败"; exit 1; }
unzip -o MX_STOCK_SIMULATOR_TEMP_FILE -d MX_STOCK_SIMULATOR_OUTPUT_PATH || { echo "解压 mx_stock_simulator.zip 失败"; exit 1; }
rm -f MX_STOCK_SIMULATOR_TEMP_FILE
```

### 3. 设置API密钥

1. 在妙想Skills页面获取apikey
2. 将apikey存到环境变量，命名为MX_APIKEY，检查本地apikey是否存在，若存在可直接用。
   使用会话级别的环境变量设置，默认不修改`~/.bashrc`、`~/.zshrc`等shell启动文件，除非用户明确要求持久化配置。

```bash
# 检查并设置 MX_APIKEY
if [ -z " $ MX_APIKEY" ]; then
  echo "⚠️ 未检测到环境变量 MX_APIKEY。"
  read -p "请输入您的 API Key: " input_key
  if [ -n " $ input_key" ]; then
    export MX_APIKEY=" $ input_key"
    echo "✅ API Key 已临时设置（当前会话有效）。"
  else
    echo "❌ 输入为空，安装终止。"
    exit 1
  fi
else
  echo "✅ 检测到环境变量 MX_APIKEY，正在使用..."
fi
```

### 4. 验证已安装的Skill文件

所有这些Skill文件在复制后都应存在：

```bash
test -f ~/.openclaw/skills/mx-skills/mx-data/SKILL.md && echo "mx_data.md OK" || echo "mx_data.md MISSING"
test -f ~/.openclaw/skills/mx-skills/mx-search/SKILL.md && echo "mx_search.md OK" || echo "mx_search.md MISSING"
test -f ~/.openclaw/skills/mx-skills/mx-select-stock/SKILL.md && echo "mx_select_stock.md OK" || echo "mx_select_stock.md MISSING"
test -f ~/.openclaw/skills/mx-skills/mx-selfselect/SKILL.md && echo "mx_selfselect.md OK" || echo "mx_selfselect.md MISSING"
test -f ~/.openclaw/skills/mx-skills/mx-stock-simulator/SKILL.md && echo "mx_stock_simulator.md OK" || echo "mx_stock_simulator.md MISSING"
echo "MX_APIKEY=${MX_APIKEY:+is set}"
```
