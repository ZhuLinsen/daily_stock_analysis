# ===================================
# MoneyChange 免费大模型快速配置指南
# ===================================
# 专为国内用户优化的免费大模型接入方案
# 总费用：0元/月
# ===================================

## 🎯 推荐方案（按优先级）

### 🏆 主力模型：智谱 GLM-4.7-Flash
- **费用**：完全免费，无额度限制
- **能力**：中文最强，代码能力优秀
- **推荐场景**：主力分析、文章生成、策略解读
- **注册地址**：https://open.bigmodel.cn

### 🥈 备选模型：火山方舟 豆包 Lite
- **费用**：每天 200 万 Token 免费（每月约 6000 万）
- **能力**：中文理解好，字节出品
- **推荐场景**：备用模型、批量任务
- **注册地址**：https://www.volcengine.com/product/ark

### 🥉 批量任务：硅基流动 Qwen2.5-7B
- **费用**：9B 以下模型永久免费 + 新用户送 2000 万 Token
- **能力**：开源模型，性价比高
- **推荐场景**：数据清洗、简单分析、批量处理
- **注册地址**：https://cloud.siliconflow.cn

---

## ⚡ 快速配置（3 步搞定）

### 第 1 步：注册并获取 API Key

#### 智谱 AI（必选，主力模型）
1. 访问 https://open.bigmodel.cn
2. 手机号注册登录
3. 进入「API Keys」→ 创建新 Key
4. 复制保存（格式：`sk-xxxxxxxxxxxxxxxx`）

#### 火山方舟（可选，备用模型）
1. 访问 https://www.volcengine.com/product/ark
2. 注册火山引擎账号
3. 进入「方舟」→ 创建 API Key
4. 复制保存

#### 硅基流动（可选，批量任务）
1. 访问 https://cloud.siliconflow.cn
2. 注册账号
3. 进入「API 密钥」→ 创建新 Key
4. 复制保存

---

### 第 2 步：配置环境变量

#### 方案 A：本地 / Docker 部署

复制以下内容到 `.env` 文件中，填入你的 API Key：

```env
# ===================================
# 免费大模型配置（总费用：0元/月）
# ===================================

# 生成后端（默认 litellm，无需修改）
GENERATION_BACKEND=litellm
GENERATION_FALLBACK_BACKEND=litellm

# 启用的模型渠道（用逗号分隔，按优先级排序）
LLM_CHANNELS=zhipu,volcengine,siliconflow

# ---------- 1. 智谱 AI（主力模型，完全免费）----------
# 模型：glm-4.7-flash（推荐）、glm-4-flash
LLM_ZHIPU_PROTOCOL=openai
LLM_ZHIPU_BASE_URL=https://open.bigmodel.cn/api/paas/v4
LLM_ZHIPU_API_KEY=你的智谱API_KEY
LLM_ZHIPU_MODELS=glm-4.7-flash,glm-4-flash

# ---------- 2. 火山方舟（备用模型，每天200万Token免费）----------
# 模型：doubao-seed-2-0-lite
LLM_VOLCENGINE_PROTOCOL=openai
LLM_VOLCENGINE_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_VOLCENGINE_API_KEY=你的火山方舟API_KEY
LLM_VOLCENGINE_MODELS=doubao-seed-2-0-lite

# ---------- 3. 硅基流动（批量任务，9B以下永久免费）----------
# 模型：Qwen/Qwen2.5-7B-Instruct
LLM_SILICONFLOW_PROTOCOL=openai
LLM_SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
LLM_SILICONFLOW_API_KEY=你的硅基流动API_KEY
LLM_SILICONFLOW_MODELS=Qwen/Qwen2.5-7B-Instruct

# ---------- 默认主模型 ----------
# 格式：渠道名/模型名
LITELLM_MODEL=zhipu/glm-4.7-flash

# ---------- Agent 模型（可选，留空继承主模型）----------
# AGENT_LITELLM_MODEL=zhipu/glm-4.7-flash

# ---------- LLM 通用配置 ----------
LLM_TIMEOUT_SEC=60
LLM_MAX_TOKENS=2048
LLM_TEMPERATURE=0.7
```

#### 方案 B：GitHub Actions 部署

在 GitHub 仓库的 `Settings → Secrets and variables → Actions` 中添加以下 Secrets：

| Secret 名称 | 说明 | 示例值 |
|------------|------|--------|
| `LLM_CHANNELS` | 启用的模型渠道 | `zhipu,volcengine,siliconflow` |
| `LITELLM_MODEL` | 默认主模型 | `zhipu/glm-4.7-flash` |
| `LLM_ZHIPU_API_KEY` | 智谱 API Key | `sk-xxxxxxxxxxxxxxxx` |
| `LLM_ZHIPU_MODELS` | 智谱可用模型 | `glm-4.7-flash,glm-4-flash` |
| `LLM_VOLCENGINE_API_KEY` | 火山方舟 API Key | `xxxxxx` |
| `LLM_VOLCENGINE_MODELS` | 豆包可用模型 | `doubao-seed-2-0-lite` |
| `LLM_SILICONFLOW_API_KEY` | 硅基流动 API Key | `sk-xxxxxxxxxxxxxxxx` |
| `LLM_SILICONFLOW_MODELS` | 硅基流动可用模型 | `Qwen/Qwen2.5-7B-Instruct` |

---

### 第 3 步：验证配置

启动系统后，运行诊断命令检查模型是否正常：

```bash
# 本地运行
python main.py --diagnostics

# 或通过 API
curl http://localhost:8080/api/v1/system/config
```

检查输出中 LLM 相关配置是否正确，模型是否可用。

---

## 🔄 多模型切换与 Fallback

### 如何切换主模型

修改 `LITELLM_MODEL` 环境变量即可：

| 模型 | 配置值 | 费用 |
|------|--------|------|
| 智谱 GLM-4.7-Flash | `zhipu/glm-4.7-flash` | 完全免费 |
| 智谱 GLM-4-Flash | `zhipu/glm-4-flash` | 完全免费 |
| 豆包 Lite | `volcengine/doubao-seed-2-0-lite` | 每天 200 万免费 |
| 硅基流动 Qwen2.5-7B | `siliconflow/Qwen/Qwen2.5-7B-Instruct` | 永久免费 |
| DeepSeek V4 Flash | `deepseek/deepseek-v4-flash` | 新用户免费额度 |

### 自动 Fallback 机制

系统已内置自动 Fallback：
- 主模型调用失败 → 自动尝试同渠道备用模型
- 整个渠道失败 → 自动切换到下一个渠道
- 按 `LLM_CHANNELS` 配置的顺序依次尝试

**示例流程**：
```
zhipu/glm-4.7-flash 失败
    ↓
zhipu/glm-4-flash 失败
    ↓
volcengine/doubao-seed-2-0-lite 失败
    ↓
siliconflow/Qwen/Qwen2.5-7B-Instruct 成功 ✓
```

---

## 🎯 按场景选择模型

### 场景 1：日常股票分析（推荐）
```env
LITELLM_MODEL=zhipu/glm-4.7-flash
```
- 中文金融数据理解最好
- 完全免费，无额度焦虑
- 速度快，质量好

### 场景 2：复杂策略代码生成
```env
LITELLM_MODEL=deepseek/deepseek-v4-flash
```
- 代码能力最强
- 量化策略回测准确率高
- 数学推理能力优秀

### 场景 3：批量数据处理 / 简单任务
```env
LITELLM_MODEL=siliconflow/Qwen/Qwen2.5-7B-Instruct
```
- 永久免费，量大管饱
- 适合简单分析、数据清洗
- 成本为 0

### 场景 4：高可用配置（推荐生产环境）
```env
LLM_CHANNELS=zhipu,volcengine,siliconflow
LITELLM_MODEL=zhipu/glm-4.7-flash
```
- 三个免费模型互为备份
- 任何一个服务挂了都不影响
- 总费用仍然是 0 元/月

---

## 📊 模型能力对比

| 维度 | 智谱 GLM-4.7-Flash | 豆包 Lite | 硅基流动 Qwen2.5-7B | DeepSeek V4 Flash |
|------|-------------------|-----------|---------------------|-------------------|
| **费用** | 永久免费 | 200万/天免费 | 永久免费 | 新用户额度 |
| **中文写作** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| **代码生成** | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **金融分析** | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **响应速度** | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| **上下文长度** | 200K | 128K | 32K | 128K |
| **国内访问** | ✅ 直连 | ✅ 直连 | ✅ 直连 | ✅ 直连 |

---

## ❓ 常见问题

### Q1: 这些模型真的免费吗？会不会突然收费？

**智谱 GLM-4.7-Flash**：官方明确永久免费，无额度限制，无功能阉割。
**豆包 Lite**：每天 200 万 Token 免费，每日刷新。
**硅基流动 9B 以下**：官方承诺永久免费，不限量。

> 💡 建议三个都配置上，互为备份，即使一个收费了还有其他的。

### Q2: 免费模型效果怎么样？够用吗？

对于股票分析、研报解读、策略生成等场景，**完全够用**。
- GLM-4.7-Flash 是 300 亿参数 MoE 模型，能力接近很多付费模型
- 日常分析、文章生成、数据处理都能高质量完成
- 复杂策略代码可以用 DeepSeek，新用户额度足够用很久

### Q3: 如何知道当前用的是哪个模型？

在生成的分析报告底部会显示使用的模型名称。
也可以通过 API 查看当前配置：
```bash
curl http://localhost:8080/api/v1/usage
```

### Q4: 可以同时用多个模型做对比分析吗？

可以！系统支持多模型并行分析。
在高级配置中可以开启多模型对比模式，同一个股票用不同模型分析，然后对比结果。

### Q5: GitHub Actions 部署需要额外配置吗？

不需要，和本地配置一样，只需要在 Secrets 中添加对应的环境变量即可。
GitHub Actions 可以直接访问国内 API，无需翻墙。

---

## 🔗 相关文档

- [完整 LLM 配置指南](./docs/LLM_CONFIG_GUIDE.md)
- [LLM 服务商配置详情](./docs/llm-providers.md)
- [免费 API 替代方案大全](./FREE_API_ALTERNATIVES.md)
- [国内用户快速开始](./QUICKSTART_CN.md)

---

## ⚠️ 免责声明

本配置指南仅供学习和研究使用。
各平台的免费政策可能随时调整，请以官方最新公告为准。
建议定期检查各平台的计费规则，避免意外产生费用。
