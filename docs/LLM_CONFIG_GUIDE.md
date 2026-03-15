# LLM (大模型) 配置指南

欢迎！无论你是刚接触 AI 的新手小白，还是精通各种 API 的高玩老手，这份指南都能帮你快速把大模型（LLM）跑起来。

本项目的大模型接入基于强大且通用的 [LiteLLM](https://docs.litellm.ai/)，这意味着几乎市面上所有的主流大模型（官方API或中转接口）我们都支持。为了照顾不同阶段的用户，我们设计了“三层优先级”配置，按需选择最适合你的方式即可。

---

## 快速导航：你应该看哪一节？

1. **【新手小白】** "我只想赶紧把系统跑起来，越简单越好！" -> [指路【方式一：极简单模型配置】](#方式一极简单模型配置适合新手)
2. **【进阶用户】** "我有好几个 Key，想配置备用模型，还要改自定义网址(Base URL)。" -> [指路【方式二：渠道(Channels)模式配置】](#方式二渠道channels模式配置适合进阶多模型)
3. **【高玩老手】** "我要做复杂的负载均衡、请求路由、甚至多异构平台高可用！" -> [指路【方式三：YAML 高级配置】](#方式三yaml高级配置适合老手自定义)
4. **【视觉模型】** "我想用图片识别股票代码！" -> [指路【扩展功能：看图模型(Vision)配置】](#扩展功能看图模型vision配置)

---

## 方式一：极简单模型配置（适合新手）

**目标：** 只要记得填入 API Key 和对应的模型名就能立刻用。不需要折腾复杂概念。

如果你只打算用一种模型，这是最快捷的办法。打开项目根目录下的 `.env` 文件（如果没有，复制一份 `.env.example` 并重命名为 `.env`）。

### 示例 1：使用通用第三方平台（兼容 OpenAI 格式，推荐）

现在市面上绝大多数第三方聚合平台（例如硅基流动、AIHubmix、阿里百炼、智谱等）都兼容 OpenAI 的接口格式。只要平台提供了 API Key 和 Base URL，你都可以按照以下格式无脑配置：

```env
# 填入平台提供给你的 API Key
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx
# 填入平台的接口地址 (非常重要：结尾通常必须带有 /v1)
OPENAI_BASE_URL=https://api.siliconflow.cn/v1
# 填入该平台上具体的模型名称（非常重要：注意前面必须加上 openai/ 前缀帮系统识别）
LITELLM_MODEL=openai/deepseek-ai/DeepSeek-V3 
```

### 示例 2：使用 DeepSeek 官方接口
```env
# 填入你在 DeepSeek 官方平台申请的 API Key
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
```
*提示：仅需这一行，系统会自动识别并默认使用 DeepSeek 模型。*

### 示例 3：使用 Gemini 免费 API
```env
# 填入你获取的 Google Gemini Key
GEMINI_API_KEY=AIzac...
```

> **恭喜！小白读到这里就可以去运行程序了！**
> 想测测看通没通？在主目录打开命令行输入：`python test_env.py --llm`

---

## 方式二：渠道(Channels)模式配置（适合进阶/多模型）

**目标：** 我有多个不同平台的 Key 想要混着用，如果主模型卡了/网络挂了，我希望它能自动切换到备用模型。

**网页端可以直接配：** 你可以启动程序后，在 **Web UI 的“系统设置 -> AI 模型 -> 渠道编辑器”** 中非常直观地进行可视化配置！

如果不方便用网页版，在 `.env` 文件中配置也非常丝滑，它能让你同时管理多个第三方平台。规则如下：

1. **先声明你有几个渠道**：`LLM_CHANNELS=渠道名称1,渠道名称2`
2. **给每个渠道分别填写配置**（注意全大写）：`LLM_{渠道名}_XXX`

### 示例：同时配置 DeepSeek 和某中转平台，并设置备用切换
```env
# 1. 开启渠道模式，声明这里有两个渠道：deepseek 和 aihubmix
LLM_CHANNELS=deepseek,aihubmix

# 2. 渠道一：配置 DeepSeek 官方
LLM_DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
LLM_DEEPSEEK_API_KEY=sk-1111111111111
LLM_DEEPSEEK_MODELS=deepseek-chat,deepseek-reasoner

# 3. 渠道二：配置一个常用的聚合中转 API
LLM_AIHUBMIX_BASE_URL=https://api.aihubmix.com/v1
LLM_AIHUBMIX_API_KEY=sk-2222222222222
LLM_AIHUBMIX_MODELS=gpt-4o-mini,claude-3-5-sonnet

# 4. 【关键】指定主模型和备用模型列表
# 平时首选用 deepseek 这款模型：
LITELLM_MODEL=deepseek/deepseek-chat
# 主模型崩了立刻挨个尝试下面这俩备用模型：
LITELLM_FALLBACK_MODELS=openai/gpt-4o-mini,anthropic/claude-3-5-sonnet
```

> **致命避坑说明**：如果你启用了 `LLM_CHANNELS`，那么你直接写在外面的 `DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY` 将**全部失效（系统一律无视）**！二者**选其一即可**，千万不要既写了新手模式又写了渠道模式结果产生冲突。

---

## 方式三：YAML 高级配置（适合老手自定义）

**目标：** 我不在乎学习门槛，我要最高控制权，我要用原生规则做企业级高可用！

本项目完全放开了 LiteLLM 原生能力，支持高并发、自动重试、按 RPM/TPM 负载均衡等操作。

### 本地运行 / Docker 部署模式配置说明

1. 在 `.env` 中只保留一行指向声明：
   ```env
   LITELLM_CONFIG=./litellm_config.yaml
   ```
2. 在项目根目录创建一个 `litellm_config.yaml`（可以参考自带的 `litellm_config.example.yaml`）。

示例 `litellm_config.yaml`：
```yaml
model_list:
  - model_name: my-smart-model
    litellm_params:
      model: openai/deepseek-chat
      api_base: https://api.deepseek.com/v1
      api_key: "os.environ/MY_CUSTOM_SECRET_KEY"  # 从环境变量读取 Key，安全防泄漏
```

### GitHub Actions配置说明

1. `Settings` → `Secrets and variables` → `Actions` → `Secret`标签页下的`New repository secret` 或者 `Variables`标签页下的`New repository variable`

2. 按下表配置，只有全部必填配置正确配置，YAML 高级配置模式才可以生效，YAML配置文件的写法，可以参考自带的 `litellm_config.example.yaml`

| Secret 名称 | 说明 | 必填 |
|------------|------|:----:|
| `LITELLM_CONFIG` | 配置文件路径，通常配置`./litellm_config.yaml` | 必填 |
| `LITELLM_MODEL` | 模型名称 | 必填 |
| `LITELLM_CONFIG_YAML` | 存放YAML配置文件，可以不用在存储库中提交文件 | 可选 |
| `LITELLM_API_KEY` | 用于存储API Key，可在配置文件中引用（环境变量引用方式）。由于GitHub Actions必须要指定导入的环境变量，因此你不能像本地运行模式那样自由命名环境变量 | 可选，必须配置到repository secret中 |
| `ANTHROPIC_API_KEY` | 如果要多个API Key，这个变量名称也能拿来用 | 可选，必须配置到repository secret中 |
| `OPENAI_API_KEY` | 同上，可以用来存储API Key | 可选，必须配置到repository secret中 |


> **三层配置互斥准则**：YAML 优先级最高！只要配置了 YAML，**渠道模式** 和 **新手极简模式** 统统被忽略。系统优先级为：`YAML配置 > 渠道模式 > 极简单模型`。

---

## 扩展功能：看图模型 (Vision) 配置

系统中有些特定功能（比如上传股票软件截图，让 AI 提取出截图里的股票代码并放入自选股池）必须用到具备“视觉能力”的模型。你需在 `.env` 单独给它指派一个懂图片的模型。

```env
# 指定你看图专用的模型名
VISION_MODEL=gemini/gemini-2.5-flash
# 别忘了填写它对应提供商的 API KEY，如果是 gemini 就提供 GEMINI_API_KEY：
# GEMINI_API_KEY=xxx
```

**备用看图机制：** 为了防止偶尔罢工，系统内置了切换策略。如果主视觉模型调用失败，它会按照下方的顺位尝试寻找是否有其他看图模型的 Key：
```env
# 默认的备用顺序：
VISION_PROVIDER_PRIORITY=gemini,anthropic,openai
```

---

## 检测与排错 (Troubleshooting)

配好了之后心惊胆战不知道对不对？在命令行（Terminal）里敲入下面代码帮你挂号问诊：

- `python test_env.py --config` ：纯检测 `.env` 配置文件里的逻辑写得对不对，是不是少写了什么。（秒出结果，不调用网络，纯检查本地文本拼写）
- `python test_env.py --llm` ：系统会真的发一句问候语给大模型，让你亲眼看到他的回答。这能彻底测出你的**网络通不通、账号有没有欠费**。

### 常见踩坑答疑台

| 遇到了什么诡异报错？ | 罪魁祸首可能是啥？ | 该怎么收拾它？ |
|----------------------|----------------------|------------------|
| **屏幕蹦出一句 LLM_MODEL 未配置** | 系统不知道你到底想用哪家的哪个模型 | 在 `.env` 中写上一句明白话：`LITELLM_MODEL=provider/你的模型名`。比如 `openai/gpt-4o-mini` |
| **我写了好几家的Key，为什么死活只有一个生效？修改还没用？** | 你把 **极简模式** 和 **渠道模式** 混着写了！ | 想好一条路走到黑——只要简单就删掉 `LLM_CHANNELS` 开头的；想要丰富备用切换就要全部转投到 `LLM_CHANNELS` 下的编制里。 |
| **错误码报 400 或 401 或 Invalid API Key** | API Key 填错、少复制了一截、账号充值没到账、或者模型名字敲错（极度常见）。 | 1. 检查复制的 Key 前后是否有误填空格。<br> 2. 检查 Base URL 最后是不是少了一个 `/v1`。<br> 3. 检查模型名是否少写了 `openai/` 之类的前缀！ |
| **转圈转不停，最后报 Timeout / ConnectionRefused 等** | 1. 在国内使用国外原版（像 Google、OpenAI），没开代理被墙了。<br>2. 你买的云服务器压根不能出境。 | 非常推荐使用**国内官方**（如DeepSeek、阿里）或者各种**兼容 OpenAI 的聚合中转接口**。因为中转站把网络问题帮你解决好了。 |

*进阶老手的叮嘱：如果你开启了 **Agent (深度思考网络搜索问股) 模式**，这里有个经验之谈，推荐选用如 `deepseek-reasoner` 这种自带强悍逻辑推导和思考机制的大模型。如果为了省钱用小微模型跑 Agent，它逻辑能力大概率跟不上，不仅达不到预期，还会白跑一堆空流程。*
