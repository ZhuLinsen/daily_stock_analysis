# AGENTS.md

本文件是本仓库 AI 协作规则的唯一真源，目标是减少返工并保持改动与项目契约一致。如本文件与可执行代码/脚本/工作流不一致，以实际可执行内容为准，并在相关改动中顺手修正文档。

## 0. 产品演进原则（做减法，重核心价值）

- **做减法优先于做加法**：产品主链路已完整，后续迭代以**收敛、精简、做深核心体验**为主，避免堆砌边角料功能、平行入口、重复模板或低频兼容开关。
- **聚焦必要且高价值的改动**：新增能力须有清晰的用户价值；能通过复用或精简现有能力解决的，默认不新增开关、入口或独立模板。
- **把核心功能做简单、做可靠**：优先提升分析质量、数据与调度稳定性、交互简洁度及排障效率；每新增一个配置项、CLI 参数、页面入口或文档文件，都应审视是否真有必要、能否删旧替新。
- **取舍边界（防止矫枉过正）**：需求规划、Issue 评估与 PR 审查（`analyze-issue` / `analyze-pr`）须附带「必要性与减法评估」，但该评估属于**产品取舍建议（由维护者决策）**，**不作为 AI 自动评审的硬性合入阻断条件**（硬阻断仍以 §7 列表为准）；正常的 Bug 修复、稳定性提升、文档纠偏及清晰低耦合的实用改进不应被机械拦截。

## 1. 硬规则

- 遵循目录边界：后端 `src/`、`data_provider/`、`api/`、`bot/`；Web `apps/dsa-web/`；桌面端 `apps/dsa-desktop/`；部署与流水线 `scripts/`、`.github/workflows/`、`docker/`。
- 未经明确确认，不执行 `git commit`、`git tag`、`git push`；commit message 使用英文，不添加 `Co-Authored-By`。
- 不写死密钥、账号、路径、模型名、端口或环境差异逻辑；优先复用现有模块、配置入口、脚本和测试，不新增平行实现。
- 默认稳定性优先，克制与当前任务无关的重构；禁止在仓库工作树内创建 `git worktree`（临时 worktree 放仓库外目录）。
- 新增或变更配置项/环境变量时，必须同步 `.env.example` 与相关文档，并评估本地、Docker、GitHub Actions、API、Web、Desktop 影响。
- 涉及用户可见能力、CLI/API 行为、部署方式、通知方式、报告结构变化时，必须同步更新相关 `docs/*.md` 与 `docs/CHANGELOG.md`：
  - `docs/CHANGELOG.md` 的 `[Unreleased]` 段使用**扁平格式**：每条一行 `- [类型] 描述`（类型取值：`新功能`/`改进`/`修复`/`文档`/`测试`/`chore`），**禁止新增 `### 类目标题`**。
  - `README.md` 仅承载首页级信息（定位、核心能力总览、快速开始、主要入口、赞助/合作），细则写入 `docs/*.md`。
  - 修改中英双语文档之一时，评估另一份是否同步；未同步须在交付说明中写明原因。
- 修改报告格式、报告渲染或 Web UI 界面时，PR 描述须附受影响报告/页面截图（涉及前后差异优先附前后对比），无法截图时写明原因与可复现替代证据；一次性验收截图不得作为仓库文件合入。
- 注释、docstring、日志文案以清晰准确为准，与文件语境保持一致。

### 1.1 PR 标题规范（非阻断建议）

- 推荐 `<类型>: <修改内容>`（`fix`/`feat`/`refactor`/`docs`/`chore`/`test`/`ci`），不添加 `[codex]`、`codex`、`autocode`、`copilot` 等工具前缀；仅作协作提示，不作为合入阻断项。

### 1.2 贡献质量底线与 Review 反馈收敛

- 贡献质量以解决明确问题、最小化影响面、保持契约一致、覆盖真实风险路径为准，不接受堆叠补丁、broad fallback/静默降级、或 mock 掉真实风险层的测试。
- 收到 review 反馈后，禁止只在评论行打局部 patch：须逐条列出原问题与根因，排查同一业务语义涉及的全部入口（runtime、API/Web、CLI、docs、workflow、tests），修复完整契约并补回归测试，同时保持 PR 描述与实际 diff 一致。CI 通过不能替代人工语义收敛。

## 2. AI 协作资产治理

- 规则真源：根目录 `AGENTS.md`。
- Claude 兼容入口：根目录 `CLAUDE.md`（指向 `AGENTS.md` 的软链接）与 `.claude/skills`（包含与 `.agents/skills/` 同步的兼容副本；支持软链接的平台也可使用指向 `../.agents/skills` 的软链接）。Windows 使用 `core.symlinks=false` 时直接读取 `.claude/skills/` 副本，不依赖创建软链接。
- 仓库协作 skill 真源：`.agents/skills/`（含 `analyze-pr`、`analyze-issue`、`fix-issue`，须带 YAML frontmatter 并引用 `AGENTS.md`）。
- Copilot 入口：`.github/copilot-instructions.md` 与 `.github/instructions/*.instructions.md`；如与本文件冲突，以 `AGENTS.md` 为准。
- 本地审查/分析产物：**默认直接输出在对话中，不落盘**；仅当用户明确要求存档时写入 `.reviews/`（已加入 `.gitignore`）。
- 根目录 `SKILL.md` 与 `docs/openclaw-skill-integration.md` 属于产品外部集成说明，不是仓库协作治理真源。
- 修改 AI 协作治理资产后，必须执行：`python scripts/check_ai_assets.py`。

## 3. 仓库速览与常用命令

- 定位：覆盖 A 股、港股、美股、日股、韩股、台股的股票智能分析系统（抓取数据 -> 技术/新闻分析 -> LLM 分析 -> 报告 -> 推送）。
- 入口：`main.py`（分析/CLI）、`server.py`（FastAPI）、`apps/dsa-web/`（Web）、`apps/dsa-desktop/`（Electron）。

```bash
# 运行
python main.py [--debug | --dry-run | --stocks 600519,hk00700,AAPL | --market-review | --schedule | --serve | --serve-only | --doctor]
uvicorn server:app --reload --host 0.0.0.0 --port 8000

# 验证（Windows 运行 ci_gate.sh 需 Git Bash / WSL）
./scripts/ci_gate.sh
python -m pytest -m "not network"
python -m py_compile <changed_python_files>
cd apps/dsa-web && npm ci && npm run lint && npm run build
cd apps/dsa-desktop && npm install && npm run build
python scripts/check_ai_assets.py
```

## 4. 默认工作流

1. 判断任务类型与改动边界（后端 / API / Web / Desktop / Workflow / Docs / AI 治理），识别高风险区域（配置语义、API/Schema、数据源 fallback、报告结构、认证、调度、发布、桌面启动链路）。
2. 先读现有实现、配置、测试、工作流与文档，再做最小改动；文档与实际代码冲突时优先信可执行代码。
3. 按 §5 验证矩阵检查，并按 §8 交付结构输出结果。

## 5. 验证矩阵

| CI 作业名 | 来源 | 说明 | 阻断 |
| --- | --- | --- | --- |
| `🔎 Change Detection` | `.github/workflows/ci.yml` | 路径变更检测 | 是 |
| `ai-governance` | `.github/workflows/ci.yml` | `python scripts/check_ai_assets.py` | 是 |
| `backend-tests (1/3)`..`(3/3)` | `.github/workflows/ci.yml` | 语法、flake8、确定性检查与 3 分片离线 pytest | 是（触发时） |
| `backend-gate` | `.github/workflows/ci.yml` | 汇总前置与后端测试门禁 | 是 |
| `docker-build` | `.github/workflows/ci.yml` | Docker 构建与关键模块导入 smoke | 是（触发时） |
| `web-gate` | `.github/workflows/ci.yml` | `npm run lint` + `npm run build` + Playwright smoke | 是（触发时） |
| `desktop-futu-package-windows` / `desktop-futu-package-macos` | `.github/workflows/ci.yml` | 桌面端 Futu 打包验证 | 是（触发时） |
| `network-smoke` | `.github/workflows/network-smoke.yml` | `pytest -m network` + `scripts/test.sh quick` | 否 |
| `pr-review` | `.github/workflows/pr-review.yml` | 手动触发的只读静态检查 + AI 审查 | 否 |

按改动面执行本地检查：
- Python 后端：优先 `./scripts/ci_gate.sh`，最低 `python -m py_compile` + 最近确定性测试。
- Web / Desktop：Web 执行 `npm run lint && npm run build`；Desktop 先构建 Web 再构建 Electron，受平台限制未验证项须明确写出。
- API / Schema / 认证：后端验证 + 受影响客户端构建，并明确写出字段/会话兼容性影响。
- AI 治理与文档：治理资产改动须跑 `python scripts/check_ai_assets.py`；纯文档改动需核对命令与文件名与仓库一致。
- 网络或三方依赖：先跑离线/确定性检查，确认 timeout、retry、fallback 与降级路径，未做在线验证须说明原因。

## 6. 稳定性护栏

- 配置：新配置优先做到“不配置也可运行，配置后增强能力”，避免叠加互斥开关。
- 数据源与通知：单一数据源或单一通知渠道失败不应拖垮整个分析主流程（除非明确要求 fail-fast）。
- 客户端兼容：改 API / Schema / 认证 / 报告载荷时优先追加字段、保留旧字段或提供兼容层，同步评估 Web 与 Desktop。
- `EXTRACT_PROMPT`：修改 `src/services/image_stock_extractor.py` 中 `EXTRACT_PROMPT` 时，PR 描述须附完整最新 prompt。
- 发布：自动 tag 默认 opt-in（仅 commit title 含 `#patch` / `#minor` / `#major` 触发）；手动 tag 须用 annotated tag。

## 7. Issue / PR / Skill 工作流

- 仓库内置 skill：`.agents/skills/analyze-pr/SKILL.md`、`.agents/skills/analyze-issue/SKILL.md`、`.agents/skills/fix-issue/SKILL.md`；`.claude/skills/` 保留同步副本，兼容 Claude Code。
- 每次 PR 创建/更新、PR 审查或 Issue 分析前，必须先刷新基线：检查 `git status --short` 并执行 `git fetch --all --prune`；**仅当**工作区干净且当前分支可 fast-forward 时执行 `git pull --ff-only`。否则不得强行切分支、stash、reset 或覆盖本地状态，改用已 fetch 的远端 refs/PR head 分析并记录本地 HEAD 与远端基线。
- 除上述安全 fast-forward 同步外，不得未经确认执行 `git pull`、`git push`、`git tag`、`gh pr create/merge/close`。
- PR 审查遵循 `.agents/skills/analyze-pr/SKILL.md`（文件覆盖账本 + 14 维影响面清单 + 因果链 + 描述与 diff 核对）。
- **合入阻断条件**（仅限以下情形；§0 的产品减法/必要性评估属于维护者取舍建议，不单独作为硬阻断）：
  - 正确性或安全性问题
  - 阻断型 CI 未通过
  - PR 描述与实际 diff 存在实质性矛盾
  - 存在不可逆变更（持久化/配置自动改写/外部状态写入/发布策略）但未说明恢复路径
  - 反复出现未收敛的契约漂移、补丁堆叠或验证证据失真

## 8. 默认交付结构

交付结果直接聚焦事实与影响，禁止空泛套话：
- `改了什么`（新增文件 vs 修改的既有运行时文件，带 `path:line`）
- `行为变化`（改前 vs 改后，谁会感知）
- `影响面`（是否涉及配置/环境变量、API/CLI、UI/Web/Desktop、报告/通知、CI/Docker）
- `验证情况与未验证项`
- `不可逆变更`（仅在存在持久化/配置迁移/外部状态写入时展开恢复路径；否则写“无”）
