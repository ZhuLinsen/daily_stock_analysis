---
name: analyze-pr
description: 审查 daily_stock_analysis 仓库的 GitHub PR，基于完整 diff 输出前因后果、函数级改动、改前改后行为、14 维影响面清单（环境变量/配置/API/Web/桌面/报告/通知等）、描述与实现差异、问题清单与合入判定。用户给出 PR 号或链接并要求分析、审查、评估能否合入时使用。
---

# Analyze PR

规则真源：仓库根目录 [`AGENTS.md`](../../../AGENTS.md)（基线同步与阻断标准见 §7，此处不重复原文）。

- 原则：**检查从严、输出从简**。内部必须逐文件、全维度核查，对外只呈现高信息密度事实，不刷空表和套话。
- 输出语言：简洁中文；**默认直接在对话中输出**，仅当用户明确要求存档时写入 `.reviews/prs/pr-<number>.md`。

## 硬约束

1. **必须读完所有改动文件**：内部逐文件核对（已读文件数 == `changedFiles`）前，不得给出合入结论。
2. **每条结论必须带证据**：标注 `path:line`、diff 片段、命令输出或 CI 链接；无证据写“未核实”并说明缺什么。
3. **14 维影响面必须全部核查**：输出时只展开**命中**的维度，未命中项合并为一行说明依据（不得跳过检查）。
4. **禁止空泛套话**：不得出现无具体触发条件与对象的「风险较低」「影响可控」「建议充分测试」「注意兼容性」「可能会影响」，以及在无不可逆变更时写「回滚：revert 本 PR」。
5. **不污染工作树**：不执行 `gh pr checkout`、不切换当前分支、不在仓库内建 worktree；需看完整上下文用 `git fetch origin pull/<n>/head:refs/remotes/pr/<n>` + `git show`。

## 内部检查步骤（必须全部执行，不直接照搬成冗长输出）

1. **采集事实**：按 `AGENTS.md` §7 同步基线后拉取 PR 元数据、完整 diff、普通评论、行内 review 线程、CI 状态及关联 Issue：
   ```bash
   gh pr view <n> --repo ZhuLinsen/daily_stock_analysis --json number,title,body,author,baseRefName,headRefName,headRefOid,mergeable,isDraft,additions,deletions,changedFiles,closingIssuesReferences,commits
   gh pr diff <n> --repo ZhuLinsen/daily_stock_analysis --name-only
   gh pr diff <n> --repo ZhuLinsen/daily_stock_analysis
   gh pr view <n> --repo ZhuLinsen/daily_stock_analysis --comments
   gh api repos/ZhuLinsen/daily_stock_analysis/pulls/<n>/comments --paginate
   gh pr checks <n> --repo ZhuLinsen/daily_stock_analysis
   ```
   - diff 超长时按文件分页拉取：`gh api repos/ZhuLinsen/daily_stock_analysis/pulls/<n>/files --paginate`。
   - 有失败 CI 时先看 `gh run view <run_id> --log-failed`，并核对 CI 对应 SHA 是否等于当前 `headRefOid`。
2. **文件覆盖核对**：确认已读完 `changedFiles` 中的每一个文件（lockfile/快照等生成文件可标“生成文件”），区分**新增文件**与**修改的既有运行时文件**。
3. **14 维影响面检索**（按路径与关键字逐项判定）：
   - `环境变量 / 配置`：`src/config.py`、`config_registry.py`、`config_manager.py`、`.env.example`、`docker-compose*.yml`、`00-daily-analysis.yml` env 段，或新增 `os.getenv`/`os.environ`
   - `Web 设置页`：`settingsHelp.ts`、`components/settings/**`、`systemConfigI18n.ts`
   - `Web UI`：`apps/dsa-web/src/{pages,components}/**`（非测试）
   - `API / Schema`：`api/**`、`src/schemas/**` 及前端 `src/api/**`、`src/types/**` 消费方
   - `Desktop`：`apps/dsa-desktop/**`、`scripts/build-*`、`scripts/run-desktop.ps1`
   - `报告结构 / 渲染`：`src/reports/**`、报告模板、Markdown/图表渲染组件
   - `通知`：`src/notification*.py`、`src/notification_sender/**`、`bot/**`
   - `Prompt / LLM`：`src/llm/**`、`src/agent/**`、prompt 常量、`EXTRACT_PROMPT`
   - `数据源 / fallback`：`data_provider/**`
   - `存储 / 持久化`：`src/storage.py`、`src/repositories/**`、ORM 模型、迁移脚本、本地缓存格式
   - `CLI / 调度`：`main.py` 参数、`--schedule`
   - `依赖`：`requirements*.txt`、`apps/*/package.json`
   - `CI / Docker / 发布`：`.github/**`、`docker/**`、`scripts/**`
   - `文档`：`docs/**`、`docs/CHANGELOG.md`、`README.md`、中英对照文档
4. **因果链与同语义排查**：核实问题现象 → 触发条件 → 根因（`path:line`）；对被改函数/配置键/字段做 `git grep`，查清 CLI / API / Bot / Web / Desktop / Scheduler 中未覆盖的同类入口。
5. **必要性与减法评估（产品取舍建议，非硬阻断）+ 声明 vs 事实 & 测试质量**：
   - 对照 `AGENTS.md` §0 评估改动是否聚焦核心痛点，还是在叠加低频开关、平行入口或重复模板；若存在明显冗余，在建议项中提示维护者可瘦身或关闭，但**不单凭主观范围直接判为合入阻断**，以免误伤正常的 Bug 修复与低耦合实用改进。
   - 对照 PR 描述与实际 diff（标出声明未兑现 / 未声明改动）；检查测试是否打到真实风险层（而非把被改模块 mock 掉）以及是否覆盖行内 review 提出的反例。

## 输出格式（固定 5 段，紧凑清晰）

```markdown
# PR #<number> <title>

## 1. 结论
- **判定**：`可合入` / `需修改后合入` / `不建议合入` —— <一句话核心理由>
- **基线与 CI**：`<base>@<sha7>` ← `<head>@<sha7>`（已读 N/N 文件）| 冲突：无/有 | CI：全绿/失败（附链接，核对 SHA 一致）| 本地同步：<HEAD 说明>

## 2. 前因、改了什么 & 改前改后
- **前因（解决什么问题）**：<关联 Issue / 现象 / 触发条件 / 根因 `path:line`>
- **新增文件**：<概要>
- **修改的既有运行时文件**：<函数/字段/配置键级，带 `path:line`>
- **改前 vs 改后**：
| 场景 / 输入 | 改前行为 | 改后行为 | 谁会感知 |
|---|---|---|---|

## 3. 影响面（14 维核查，仅展开命中项）
- **命中维度**：逐项写出具体内容与证据；若命中以下三类须附对应明细：
  - **配置 / 环境变量**：键名 | 增/改/删 | 默认值 | 不配置时行为 | `.env.example` / docs / Web 设置页 / Actions 是否同步
  - **API / Schema / CLI**：接口或参数变化 | Web / Desktop 消费方是否同步
  - **UI / 报告 / 通知可视变化**：受影响页面或渠道 | 截图或替代可视证据状态（已核对当前 Head 画面 / 仅有链接未看 / 缺失）
- **未命中维度**：其余 N 维均未命中（依据：<diff 路径范围与关键字检索为空>）。

## 4. 问题清单、描述差异 & 验证证据
- **阻断项 / 建议项**：`[阻断|建议] path:line` — 触发条件 → 后果 → 修改建议（无则写“无”）
- **未覆盖同语义入口 / 描述与 diff 差异**：<无，或逐条列出>
- **验证证据**：CI 结果、测试是否覆盖真实风险层、本地补验（如有）

## 5. 不可逆变更
- 仅当存在数据库/持久化格式变更、运行时配置自动改写/迁移、外部状态写入（自选/账本/通知）、或发布策略变化时展开旧数据/配置处理与恢复路径；否则只写：`无`。
```

> **评审评论草稿**：默认不输出，仅在用户要求“给评论草稿”时附在末尾。

## 输出前自检

- [ ] 已读文件数 == `changedFiles`
- [ ] 14 维影响面均已核查（命中项有明细，未命中项有依据）
- [ ] 每条问题有 `path:line` 与触发条件，全文无禁用套话
- [ ] 已核对 CI 对应 SHA == `headRefOid`

## 需用户确认的动作

发布评论、Approve、Request changes、Merge、关闭 PR 前必须先征得用户确认。
