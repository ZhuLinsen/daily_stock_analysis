---
name: analyze-pr
description: 审查 daily_stock_analysis 仓库的 GitHub PR，基于完整 diff 输出前因后果、函数级改动、改前改后行为、14 维影响面清单（环境变量/配置/API/Web/桌面/报告/通知等）、描述与实现差异、问题清单与合入判定。用户给出 PR 号或链接并要求分析、审查、评估能否合入时使用。
---

# Analyze PR

规则真源：仓库根目录 [`AGENTS.md`](../../../AGENTS.md)（基线同步与审查顺序见 §7，此处不重复原文）。

- 输出语言：简洁中文。
- 产物策略：**默认直接在对话中输出**；仅当用户明确要求存档时，写入 `.reviews/prs/pr-<number>.md`。

## 硬约束

1. **必须读完所有改动文件**：未完成“文件覆盖账本”（已读文件数 == `changedFiles`）前，不得给出合入结论。
2. **每条结论必须带证据**：标注 `path:line`、diff 片段、命令输出或 CI 链接；无证据写“未核实”并说明缺什么。
3. **影响面 14 维逐项核验**：每一项必须标明 `命中 / 未命中` 并给出证据；“未命中”的证据为“diff 无对应路径且关键字检索为空”。
4. **禁止空泛套话**：出现以下未附具体触发条件与对象的表述即视为未完成——「风险较低」「影响可控」「建议充分测试」「注意兼容性」「可能会影响」，以及在无不可逆变更时写「回滚：revert 本 PR」。
5. **不污染工作树**：不执行 `gh pr checkout`、不切换当前分支、不在仓库内创建 worktree；需要完整文件上下文时使用 `git fetch origin pull/<n>/head:refs/remotes/pr/<n>` + `git show` / `git diff`。

## Step 1: 采集事实（全部执行）

按 `AGENTS.md` §7 同步远端基线（记录本地 HEAD 与使用的远端基线），再拉取 PR 完整数据：

```bash
gh pr view <n> --repo ZhuLinsen/daily_stock_analysis --json number,title,body,author,baseRefName,headRefName,headRefOid,mergeable,isDraft,additions,deletions,changedFiles,labels,closingIssuesReferences,commits
gh pr diff <n> --repo ZhuLinsen/daily_stock_analysis --name-only
gh pr diff <n> --repo ZhuLinsen/daily_stock_analysis
gh pr view <n> --repo ZhuLinsen/daily_stock_analysis --comments
gh api repos/ZhuLinsen/daily_stock_analysis/pulls/<n>/comments --paginate
gh pr checks <n> --repo ZhuLinsen/daily_stock_analysis
```

- diff 超长时按文件分页拉取：`gh api repos/ZhuLinsen/daily_stock_analysis/pulls/<n>/files --paginate`。
- 有失败 CI 时先看失败日志：`gh run view <run_id> --repo ZhuLinsen/daily_stock_analysis --log-failed`，并核对 CI 对应 commit SHA 是否等于当前 `headRefOid`。
- 若有关联 Issue，执行 `gh issue view <issue_id> --repo ZhuLinsen/daily_stock_analysis --comments`。

## Step 2: 建立文件覆盖账本

逐文件核对改动，行数必须等于 `changedFiles`（lockfile/快照等生成文件可标“生成文件”并说明依据）：

| # | 文件 | 类别（新增/修改既有运行时/测试/文档） | 改动要点（函数/字段/配置键级） | 已读完整 diff | 已核对调用方/上下文 |
|---|---|---|---|---|---|

## Step 3: 14 维影响面检索（不靠印象，按路径与关键字判定）

| 维度 | 判定方法（命中任一即“命中”） |
|---|---|
| 环境变量 / 配置 | diff 触及 `src/config.py`、`src/core/config_registry.py`、`src/core/config_manager.py`、`.env.example`、`docker-compose*.yml`、`.github/workflows/00-daily-analysis.yml` env 段，或新增 `os.getenv`/`os.environ` |
| Web 设置页 | `apps/dsa-web/src/locales/settingsHelp.ts`、`apps/dsa-web/src/components/settings/**`、`apps/dsa-web/src/utils/systemConfigI18n.ts` |
| Web UI | `apps/dsa-web/src/{pages,components}/**`（非测试） |
| API / Schema | `api/**`、`src/schemas/**`；同时核对 `apps/dsa-web/src/api/**`、`apps/dsa-web/src/types/**` 消费方 |
| Desktop | `apps/dsa-desktop/**`、`scripts/build-*`、`scripts/run-desktop.ps1` |
| 报告结构 / 渲染 | `src/reports/**`、报告模板、Markdown/图表渲染组件 |
| 通知 | `src/notification*.py`、`src/notification_sender/**`、`bot/**` |
| Prompt / LLM | `src/llm/**`、`src/agent/**`、prompt 常量、`src/services/image_stock_extractor.py` 的 `EXTRACT_PROMPT` |
| 数据源 / fallback | `data_provider/**` |
| 存储 / 持久化 | `src/storage.py`、`src/repositories/**`、ORM 模型、迁移脚本、本地缓存/文件格式 |
| CLI / 调度 | `main.py` 参数、`--schedule` 及调度逻辑 |
| 依赖 | `requirements*.txt`、`apps/*/package.json` |
| CI / Docker / 发布 | `.github/**`、`docker/**`、`scripts/**` |
| 文档 | `docs/**`、`docs/CHANGELOG.md`、`README.md`、中英对照文档 |

## Step 4: 因果链与同语义排查

- **前因**：问题现象 → 触发条件 → 根因（base 分支 `path:line`）。若 PR 未说明根因，由审查者从代码推导并标注“审查者推导”。
- **修法**：改动如何切断根因，是否仅修补症状。
- **同语义入口排查**：对被改函数、配置键、字段执行 `git grep`，列出 CLI / API / Bot / Web / Desktop / Scheduler 中**未被本 PR 覆盖**的同类入口。

## Step 5: 声明 vs 事实核对

- PR 描述中的每条声明 → 核对对应 diff 证据，无证据标“声明未兑现”。
- diff 中的每个实质改动 → 核对 PR 描述是否提及，未提及标“未声明改动”。
- 测试质量：新增/修改的测试是否打到真实风险层（是否把被修改的模块 mock 掉）；是否覆盖行内 review 线程提出的反例。
- 第三方模型 / API 兼容类 PR：核对是否给出官方来源链接、锁定依赖兼容窗口、已验证调用链路，以及是否会静默改写/清空旧配置。

## Step 6: 输出格式（固定结构）

```markdown
# PR #<number> <title>

- **基线与状态**：`<base>@<sha7>` ← `<head>@<sha7>` | 冲突：无/有 | CI 对应 SHA：一致/不一致 | 本地同步：<HEAD 与同步说明>
- **合入结论**：`可合入` / `需修改后合入` / `不建议合入` —— <一句话最关键理由>

## 1. 前因（解决什么问题）
- 关联 Issue：<#id 或 无（动机说明）>
- 现象与触发条件：
- 根因定位：`path:line`

## 2. 改了什么（账本 N/N 已读）
- **新增文件**：
- **修改的既有运行时文件**（函数/字段/配置键级，带 `path:line`）：
- **测试与文档**：

## 3. 改前 vs 改后
| 场景 / 输入 | 改前行为 | 改后行为 | 谁会感知（用户配置/渠道/页面） |
|---|---|---|---|

## 4. 影响面清单
| 维度 | 命中 | 具体内容 | 证据 |
|---|---|---|---|
（14 行全部列出，未命中也列）

### 4.1 配置项 / 环境变量变更（命中时必填）
| 键 | 增/改/删 | 默认值 | 不配置时行为 | `.env.example` | docs | Web 设置页 | Actions / Docker |
|---|---|---|---|---|---|---|---|

### 4.2 API / Schema / CLI 变更（命中时必填）
| 接口 / 模型 / 参数 | 字段或行为变化 | Web / Desktop 消费方是否同步 |
|---|---|---|

### 4.3 UI / 报告可视变化（命中时必填）
- 受影响页面 / 报告 / 通知渠道：
- 截图或替代可视证据状态（已核对当前 Head 画面 / 仅有链接未查看 / 缺失）：

## 5. 未覆盖的同语义入口
- <无，或逐项列出 `path:line`>

## 6. PR 描述 vs 实际 diff 差异
- 声明未兑现 / 未声明改动 / PR 标题非阻断建议（如有）：

## 7. 验证证据
- CI 结论（逐项列 `ai-governance` / `backend-gate` / `docker-build` / `web-gate` 与链接）：
- 测试是否覆盖真实风险层：
- 本地补充验证（如有）：

## 8. 问题清单
- [阻断|建议] `path:line` — 触发条件 → 后果 → 修改建议

## 9. 不可逆变更
- 仅当存在以下情形时展开：数据库表/持久化格式变更、运行时配置自动改写/清理/迁移、外部系统状态写入（如自选/账本/通知）、发布/tag 策略变化；需说明旧数据/旧配置如何处理与恢复。
- 若均不存在，只写：`无（依据：账本中无持久化、配置迁移、外部状态写入或发布策略改动）`。

## 10. 评审评论草稿
<如需发布到 GitHub 的简洁中文评论>
```

## Step 7: 输出前自检

- [ ] 账本文件数 == `changedFiles`
- [ ] 影响面 14 维全部列出且每行有证据
- [ ] §3 至少包含一行改前/改后对比（或明确“纯重构无行为变化”并给依据）
- [ ] 每条问题都包含 `path:line`、触发条件与后果
- [ ] 全文无禁用套话
- [ ] 已核对 CI 对应 SHA 与当前 `headRefOid`

## 需用户确认的动作

执行以下动作前必须先征得用户确认：发布评论、Approve、Request changes、Merge、关闭 PR。
