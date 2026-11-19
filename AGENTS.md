# AGENTS.md

本文件用于约束本仓库的默认开发流程，目标是减少重复沟通、减少返工，并让改动和当前项目结构保持一致。

如果本文件与仓库中的脚本、工作流、代码现状不一致，以实际可执行内容为准，并在相关改动中顺手修正文档，避免规则继续漂移。

## 1. 硬规则

- 遵循现有目录边界：
  - 后端逻辑优先放在 `src/`、`data_provider/`、`api/`、`bot/`
  - Web 前端改动在 `apps/dsa-web/`
  - 桌面端改动在 `apps/dsa-desktop/`
  - 部署与流水线改动在 `scripts/`、`.github/workflows/`、`docker/`
- 未经明确确认，不执行 `git commit`、`git tag`、`git push`。
- commit message 使用英文，不添加 `Co-Authored-By`。
- 不写死密钥、账号、路径、模型名、端口或环境差异逻辑。
- 优先复用现有模块、配置入口、脚本和测试，不新增平行实现。
- 默认稳定性优先于“顺手优化”；非当前任务直接需要的重构、抽象和基础设施迁移一律克制。
- 新增配置项时，必须同步更新 `.env.example` 和相关文档。
- 用户可见能力、CLI/API、部署、通知或报告行为发生变化时，更新对应的使用文档。普通 PR 用标题概括用户或维护者得到的变化，选择对应标签，在描述中说明兼容性和需要用户执行的操作。
- 修改报告格式、报告渲染效果或 Web UI 界面时，PR 描述必须附受影响报告 / 页面截图；涉及前后差异时优先附前后对比，无法截图时说明原因与替代可视证据。
- Issue / PR 过程截图、审查截图、一次性验收截图和临时可视证据不得作为仓库文件合入；应放在 PR 描述、PR 评论、GitHub 附件、Actions artifact 或外部可访问证据链接中。产品长期文档确需保留的示意图除外，但文件名和文档语义必须脱离具体 issue / PR 编号。
- 发布流程根据已合入 PR 的标题和标签生成版本说明，分类及 `skip-changelog` 见 `.github/release.yml`。`docs/CHANGELOG.md` 是版本归档，由维护者按第 9 节集中更新。已有 PR 的旧条目可以随迁移保留。
- `README.md` 只用于项目定位、核心能力总览、快速开始、主要入口、赞助/合作等首页级信息；非必要不更新 README，避免持续膨胀。
- 更细的模块行为、页面交互、专题配置、排障说明、字段契约、实现语义和边界条件，优先更新对应 `docs/*.md` 或专题文档，不写入 README。
- 变更中英双语文档之一时，需评估另一份是否需要同步；若未同步，交付说明里要写明原因。
- 注释、docstring、日志文案以清晰准确为准，不强制要求英文，但应与文件语境保持一致。

## 1.1 PR 标题规范（非阻断建议）

- 推荐使用 `<类型>: <修改内容>` 作为 PR 标题，例如 `fix: 修复大盘分析历史记录丢失`，优先类型为 `fix`/`feat`/`refactor`/`docs`/`chore`/`test`/`ci`。
- 标题应描述实际变更内容，建议不添加 `[codex]`、`codex`、`autocode`、`copilot` 或其他工具/agent 来源前缀。
- 该规范仅用于协作可读性与一致性提示，不应单独作为 review process blocker。

## 1.2 贡献质量底线

- 每个 PR 应解决明确问题，将改动限定在必要范围，保持相关入口的行为一致，并验证真实风险路径。评审以这些证据判断贡献价值。
- 作者须理解现有业务契约，完成自审、集成和验证。使用 AI 辅助生成的改动同样须经作者逐项核对实际行为。
- 收到评审反馈后，按第 8.1 节处理。

## 2. AI 协作资产治理

- `AGENTS.md` 是仓库内 AI 协作规则的唯一真源。
- `CLAUDE.md` 必须是指向 `AGENTS.md` 的软链接，用于兼容 Claude 生态。
- `.github/copilot-instructions.md` 与 `.github/instructions/*.instructions.md` 是 GitHub Copilot / Coding Agent 的镜像或分层补充；若与本文件冲突，以 `AGENTS.md` 为准。
- 仓库协作 skill 存放在 `.claude/skills/`，分析产物存放在 `.claude/reviews/`；前者可以入库，后者默认视为本地产物。
- 根目录 `SKILL.md` 与 `docs/openclaw-skill-integration.md` 属于产品或外部集成说明，不是仓库协作规则真源。
- 若未来新增 `.agents/skills/` 或其他 agent 专用目录，必须先明确单一真源，再通过脚本或镜像同步；禁止手工长期维护多份同义内容。
- 修改 AI 协作治理资产时，执行：

```bash
python scripts/check_ai_assets.py
```

## 3. 仓库速览

- 项目定位：股票智能分析系统，覆盖 A 股、港股、美股。
- 主流程：抓取数据 -> 技术分析/新闻检索 -> LLM 分析 -> 生成报告 -> 通知推送。
- 关键入口：
  - `main.py`：分析任务主入口
  - `server.py`：FastAPI 服务入口
  - `apps/dsa-web/`：Web 前端
  - `apps/dsa-desktop/`：Electron 桌面端
  - `.github/workflows/`：CI、发布、每日任务
- 核心职责：
  - `src/core/`：主流程编排
  - `src/services/`：业务服务层
  - `src/repositories/`：数据访问层
  - `src/services/report_renderer.py`、`templates/`：报告模板渲染；`src/notification.py` 编排通知；`apps/dsa-web/src/components/report/` 展示 Web 和桌面端的报告
  - `src/schemas/`：Schema / 数据结构
  - `data_provider/`：多数据源适配与 fallback
  - `api/`：FastAPI API
  - `bot/`：机器人接入
  - `scripts/`：本地脚本
  - `.github/scripts/`：GitHub 自动化脚本
  - `tests/`：pytest 测试
  - `docs/`：文档与说明

## 4. 常用命令

### 运行应用

```bash
python main.py
python main.py --debug
python main.py --dry-run
python main.py --stocks 600519,hk00700,AAPL
python main.py --market-review
python main.py --schedule
python main.py --serve
python main.py --serve-only
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

### 后端验证

```bash
python -m pip install -r .github/requirements-ci.txt
./scripts/ci_gate.sh
python -m pytest -m "not network"
python -m py_compile <changed_python_files>
```

### Web / Desktop

```bash
cd apps/dsa-web
npm ci
npm run lint
npm run build

cd ../dsa-desktop
npm ci
npm run build
```

### PR / CI 证据

```bash
gh pr view <pr_number>
gh pr checks <pr_number>
gh run view <run_id> --log-failed
```

## 5. 默认工作流

1. 先判断任务类型：`fix / feat / refactor / docs / chore / test / review`
2. 先读现有实现、配置、测试、脚本、工作流和文档，再动手修改。
3. 识别改动边界：后端 / API / Web / Desktop / Workflow / Docs / AI 协作资产。
4. 先判断是否命中高风险区域：配置语义、API / Schema、数据源 fallback、报告结构、认证、调度、发布流程、桌面端启动链路。
5. 只做和当前任务直接相关的最小改动，不顺手夹带无关重构。
6. 如果发现文档、脚本、工作流描述不一致，优先信任实际代码与工作流，再决定是否顺手修正文档。
7. 改完后按下面的验证矩阵执行检查。
8. 按第 9 节整理交付说明。

## 6. 验证矩阵

### CI 覆盖原则

当前仓库 CI 主要包含：

| 检查项 | 来源 | 说明 | 是否阻断 |
| --- | --- | --- | --- |
| `ai-governance` | `.github/workflows/ci.yml` | 校验 `AGENTS.md` / `CLAUDE.md` / `.github` 指令 / `.claude/skills` 关系 | 是 |
| `backend-gate` | `.github/workflows/ci.yml` | 汇总按路径触发的三个后端测试分片，涵盖 ci_gate.sh 的语法、Flake8、确定性检查及离线测试 | 是 |
| `docker-build` | `.github/workflows/ci.yml` | 镜像构建及关键模块导入 smoke | 是（触发时） |
| `web-gate` | `.github/workflows/ci.yml` | Web lint、构建、Playwright smoke 和 fixtures，上传 `web-ui-evidence-<head SHA>` | 是（触发时） |
| `desktop-futu-package-windows/macos` | `.github/workflows/ci.yml` | 命中打包路径时验证冻结后端的 Futu SDK，macOS 另验未签名包 | 是（触发时） |
| `network-smoke` | `.github/workflows/network-smoke.yml` | `pytest -m network` + `scripts/test.sh quick` | 否，观测项 |
| `PR Review` | `.github/workflows/pr-review.yml` | 维护者通过 `workflow_dispatch` 指定 PR，审查正文与该版本的证据保存在运行摘要，PR 评论提供摘要链接，工作流也生成辅助标签 | 否，辅助项 |

若 PR 上已有对应 CI 结果，可直接引用 CI 结论；若 CI 未覆盖改动面，或本地与 CI 环境差异较大，需要补充说明本地验证与缺口。

### 按改动面执行

- Python 后端改动：
  - 适用范围：`main.py`、`src/`、`data_provider/`、`api/`、`bot/`、`tests/`
  - 优先执行：`./scripts/ci_gate.sh`
  - 最低要求：`python -m py_compile <changed_python_files>`
  - 若影响 API、任务编排、报告生成、通知发送、数据源 fallback、认证、调度，交付说明中要写明是否覆盖了对应路径。

- Web 前端改动：
  - 适用范围：`apps/dsa-web/`
  - 默认执行：`cd apps/dsa-web && npm ci && npm run lint && npm run build`
  - 若涉及 API 联调、路由、状态管理、Markdown/图表渲染或认证状态，交付说明中要明确说明联动面和未覆盖风险。

- 桌面端改动：
  - 适用范围：`apps/dsa-desktop/`、`scripts/run-desktop.ps1`、`scripts/build-desktop*.ps1`、`scripts/build-*.sh`、`docs/desktop-package.md`
  - 默认执行：先构建 Web，再构建桌面端
  - 如受平台限制未能完整验证，需要明确说明是否验证了 Web 构建产物、Electron 构建以及 Release 工作流影响。

- API / Schema / 认证联动改动：
  - 适用范围：`api/**`、`src/schemas/**`、`src/services/**`、`apps/dsa-web/**`、`apps/dsa-desktop/**`
  - 至少覆盖对应后端验证 + 受影响客户端构建验证。
  - 若涉及登录、Cookie、会话、轮询状态、字段增删或枚举变化，必须明确写出兼容性影响。

- 文档与治理文件改动：
  - 适用范围：`README.md`、`docs/**`、`AGENTS.md`、`.github/copilot-instructions.md`、`.github/instructions/**`、`.claude/skills/**`
  - 不强制代码测试。
  - 需确认命令、配置项、文件名、工作流名称与实际仓库一致。
  - 改动 AI 协作治理资产时，执行 `python scripts/check_ai_assets.py`。

- 工作流 / 脚本 / Docker 改动：
  - 适用范围：`.github/**`、`scripts/**`、`docker/**`
  - 运行最接近改动面的本地验证。
  - 交付时说明影响了哪条流水线、发布路径或部署路径。
  - 若未执行 Docker / GitHub Actions 相关验证，明确说明原因与潜在风险。

- 网络或三方依赖相关改动：
  - 先跑离线或确定性检查。
  - 优先确认 timeout、retry、fallback、异常文案、降级路径是否仍然成立。
  - 若未执行在线验证，必须明确写出原因。

## 7. 稳定性护栏

- 配置与运行入口：
  - 修改 `.env` 语义、默认值、CLI 参数、服务启动方式、调度语义时，要同时评估本地运行、Docker、GitHub Actions、API、Web、Desktop 的影响。
  - 新配置优先做到“不配置也可运行，配置后增强能力”，避免叠加开关和互斥模式。

- 数据源与 fallback：
  - 修改 `data_provider/` 时，要关注数据源优先级、失败降级、字段标准化、缓存与超时策略。
  - 单一数据源失败不应拖垮整个分析流程，除非需求明确要求 fail-fast。

- API / Web / Desktop 兼容：
  - 改 API / Schema / 认证 / 报告载荷时，要同时检查后端、Web、Desktop 的兼容性。
  - 默认优先追加字段、保留旧字段或提供兼容层，避免无提示破坏现有客户端。

- 报告 / Prompt / 通知：
  - 修改报告结构、Prompt、提取器、通知模板、机器人链路时，要检查上游输入与下游消费方是否仍兼容。
  - 单一通知渠道失败不应拖垮整个分析主流程，除非需求明确要求 fail-fast。
  - 修改 `src/services/image_stock_extractor.py` 中 `EXTRACT_PROMPT` 时，要在 PR 描述中附完整最新 prompt。

- 工作流 / 发布 / 打包：
  - 修改自动 tag、Release、Docker 发布、日常分析或桌面端打包流程时，要评估触发条件、产物路径、权限边界和回滚方式。
  - 自动 tag 默认保持 opt-in：只有 commit title 含 `#patch`、`#minor`、`#major` 才触发版本号更新，除非需求明确要求改变发布策略。

## 8. Issue / PR / Skill 工作流

- 仓库内已有以下 skill，可优先复用：
  - `.claude/skills/analyze-issue/SKILL.md`
  - `.claude/skills/analyze-pr/SKILL.md`
  - `.claude/skills/fix-issue/SKILL.md`
- 如果任务明确是 issue 分析、PR 审查、issue 修复，优先按对应 skill 执行，并将产物保存到 `.claude/reviews/`。
- skill 中的命令、模板、验证顺序和交付结构必须与 `AGENTS.md` 保持一致。
- 每次进行 PR 创建 / 更新、PR 审查或 issue 分析前，必须先同步最新代码基线：先检查工作区状态并执行 `git fetch --all --prune`；若工作区干净且当前分支可 fast-forward，则执行 `git pull --ff-only`。如存在本地改动、冲突状态、未跟踪风险文件或无法 fast-forward，不得强行切分支、stash、reset 或覆盖本地状态；PR 审查 / issue 分析可改用已 fetch 的远端 refs/PR head 做分析，并在分析文档中明确记录未更新本地工作树的原因、当前本地 HEAD 与使用的远端基线；PR 创建 / 更新应先说明当前分支与目标基线差异，必要时请求用户确认 rebase、merge 或继续基于当前分支推进。
- skill 默认优先读取 CI / 工作流证据，再决定是否补本地验证。
- 除上述 PR 创建 / 更新、PR 审查 / issue 分析的安全 fast-forward 同步外，skill 不得默认执行 `git pull`、`git push`、`git tag`、`gh pr create` 等会改变远端或当前分支状态的操作；这些操作必须要求用户确认。
- PR 审查先回答维护者的决定：谁遇到了什么问题，每一项独立改动如何改变原行为，是否值得合、是否值得拆。用一个实际操作或输入输出讲清楚原因，再给代码或测试依据。
- 明确回答 Web、Desktop 共用页面、报告和通知展示有何变化，并交代相关 CLI/API、配置、默认行为及旧版本兼容性。对适用的画面核对当前 Head 的截图、前后对比或可复现的替代证据，记录链接、覆盖状态和缺口。具体取证方式见 `.claude/skills/analyze-pr/SKILL.md`。
- 结合关联 Issue、实质性描述差异、回滚方式、已触发的 CI、冲突状态和未关闭的反例给出合入建议。代码判断与 GitHub 当前能否合并分别说明。
- 对 `fix` 类 PR，必须说明：原问题、根因、修复点、回归风险。
- 合入阻断条件：
  - 正确性或安全性问题
  - 阻断型 CI 未通过
  - PR 描述与实际改动内容实质性矛盾
  - 缺少回滚方案
  - 反复出现未收敛的契约漂移、补丁堆叠或验证证据失真

## 8.1 Review 反馈处理与补丁堆叠禁止

1. 逐条说明评审指出的问题及根因，明确应当成立的业务行为。
2. 从反例追踪所有相关入口和消费方，包括运行时、API/Web、CLI、配置、诊断、工作流、文档和测试。在受影响的路径上统一修复，避免用宽泛的 fallback 或静默返回值掩盖问题。
3. 用覆盖原反例的回归测试或实际入口验证修复。保留会触发问题的真实环节；若验证受限，在结论中写明缺口。仅凭 CI 通过不足以判定反例已解决。
4. 更新 PR 描述，使范围、验证结果、兼容性、风险和回滚方式与当前提交一致。

若现有范围无法完整修复，提出拆分、关闭重做或请维护者确认最小范围，暂缓合入。多轮评审仍反复出现同类问题时，维护者可以要求关闭重做。

## 9. 交付与发布

- 默认交付结构：
  - `改了什么`
  - `为什么这么改`
  - `验证情况`
  - `未验证项`
  - `风险点`
  - `回滚方式`
- 如果是 `docs` 任务，可直接写：`Docs only, tests not run`，但仍需说明是否核对了命令和文件名。
- 自动 tag 默认不触发，只有 commit title 包含 `#patch`、`#minor`、`#major` 才会触发版本号更新。
- 手动打 tag 必须使用 annotated tag。
- 用户可见变更优先通过 PR 合入，并补齐 label 与验证说明。
- 推送版本 tag 时，`create-release.yml` 调用 GitHub 根据 `.github/release.yml` 生成发布说明。维护者可在 GitHub Release 校订中文亮点、升级步骤。发布定稿后，在已获取该 tag 和上一版本 tag、已登录 GitHub CLI 的仓库中运行 `python .github/scripts/build_release_notes.py --archive vX.Y.Z`，核对差异后随发版维护 PR 归档。命令按相邻 tag 确定旧条目的归属，支持乱序归档，保留后来修改的条目及已有版本归档。
