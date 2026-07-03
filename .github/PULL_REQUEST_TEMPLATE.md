<!--
For Chinese contributors: 请直接用中文填写。
For English contributors: please fill in English. All fields marked (EN) accept English.
-->

## PR Type

- [ ] fix
- [ ] feat
- [ ] refactor
- [ ] docs
- [ ] chore
- [ ] test

## Background And Problem

请描述当前问题、影响范围与触发场景。  
*(EN) Describe the problem, its impact, and what triggers it.*

## Scope Of Change

请列出本 PR 修改的模块和文件范围。  
*(EN) List the modules and files changed in this PR.*

> 注意：请按实际 `git diff` 全量列出文件范围（建议注明文件总数），避免遗漏文档/后端/API/前端文件导致描述不一致。

> 若本 PR 修改了 `.github/PULL_REQUEST_TEMPLATE.md`、`.github/copilot-instructions.md`、`AGENTS.md`、`.github/instructions/*` 或 `.claude/skills/**` 等协作与治理文件，请补充“变更原因 + 影响面 + 回滚方式（默认 revert）”到 Summary / Compatibility / Rollback，避免 Scope 与描述不一致。

> 建议先执行并粘贴以下命令输出，避免与实际 diff 不一致：

```bash
BASE_REF=$(git merge-base HEAD origin/main)
git diff --stat "$BASE_REF"..HEAD
git diff --name-only "$BASE_REF"..HEAD
```

- 文件总数 / 变更行数（建议粘贴 `git diff --stat "$BASE_REF"..HEAD`）：
- 文件清单（按实际 diff 全量，逐项列出）：
- 文档更新文件（`docs/*`）：

## Issue Link

必须填写以下之一 / Fill in one of:
- `Fixes #<issue_number>`
- `Refs #<issue_number>`
- 无 Issue 时说明原因与验收标准 / If no issue, explain the motivation and acceptance criteria

## Verification Commands And Results

请填写你实际执行过的命令和关键结果（不要只写"已测试"）。  
*(EN) Paste the commands you actually ran and their key output (don't just write "tested"):*

```bash
# example
./scripts/ci_gate.sh
python -m pytest -m "not network"
```

> `Full-suite note` 必须与当次 PR 的当前 Head CI 结果保持一致；若本地复现存在环境相关失败，请明确标注“本地环境差异”并给出 GitHub CI 的结论与链接。  
> 请避免保留与本 PR 无关的历史失败措辞，按本次实际结果填报。
> 如历史描述中仍保留 `./scripts/ci_gate.sh` 失败记录，请先改为当前 Head CI 状态或说明与 Head CI 的差异来源。
> 若 `Full-suite note` 与当前 Head CI 不一致，PR 文本不完整，请先更新 PR 描述后再提交。

- 请在下面按实际结果填写并与 `Full-suite note` 保持一致（任一未填视为信息缺失）：
  - ai-governance：`pass` / `fail`，附链接
  - backend-gate：`pass` / `fail`，附链接
  - docker-build：`pass` / `fail`，附链接
  - web-gate：`pass` / `fail`，附链接
  - 若本 PR 修改 `.github/PULL_REQUEST_TEMPLATE.md` 等流程模板协作文件，请先说明变更必要性、影响边界，并明确回滚方式（默认 `revert this PR`）；否则请在下一版中拆为单独 chore PR。

关键输出/结论 / Key output & conclusion:

- 【必填】当前 Head CI：`ai-governance:pass / backend-gate:pass / docker-build:pass / web-gate:pass`（按实际结果替换）并附对应链接。  
- 若需保留本地失败现象，请在同段写明“本地环境差异 + 当前 CI 通过/失败结果 + CI 链接”。  
- 若全部通过，需补充一句：`当前状态：全部通过（pass）`，并明确 Head CI 全部为 pass。  

- 建议将本行直接粘贴到 PR 描述正文首段：`当前 Head CI：ai-governance:pass / backend-gate:pass / docker-build:pass / web-gate:pass`（仅示例，按实际结果替换）。

> 若上述核验项与 PR 文本冲突，建议先更新 PR 描述再提交，避免审查因状态不一致被阻塞。

## Visual Evidence (if applicable)

【必填】若本 PR 修改报告格式、报告渲染效果或 Web UI 界面，请在此处附受影响报告 / 页面截图；涉及前后差异时，优先附前后对比。Issue / PR 过程截图、审查截图、一次性验收截图和临时可视证据请放在 PR 描述、PR 评论、GitHub 附件、Actions artifact 或外部可访问链接中，不要作为仓库文件合入。
*(EN) If this PR changes report formatting, report rendering, or Web UI, attach screenshots of the affected report/page here; before/after screenshots are preferred when relevant. Issue/PR process screenshots, review screenshots, one-off acceptance screenshots, and temporary visual evidence should be linked from the PR body/comments, GitHub attachments, Actions artifacts, or external accessible evidence; do not commit them as repository files.)*

> 如截图无法获取，请在“原因”中明确写明替代证据（如 Playwright/e2e 产物路径、审查链接）及其可追溯命令，不得留空。涉及 Web 设置/报告渲染变更时，需确保截图或替代证据明确指向变更项。
>
> 若本 PR 修改 Web UI，建议至少补一条可复现路径，例如（优先 settings page）：
>
> - Playwright 截图产物：`apps/dsa-web/e2e/smoke.spec.ts`（`cd apps/dsa-web && npx playwright test e2e/smoke.spec.ts --grep "settings page renders title and save actions after login"`）
> - 审查证据链接：可直接使用 Actions 产物、GitHub 评论附件或外部可访问链接。

> 替代证据模板（设置页变更建议）：
> - 命令：`cd apps/dsa-web && npx playwright test e2e/smoke.spec.ts --grep "settings page"`
> - 产物路径：`apps/dsa-web/test-results/**/smoke-settings-page-*.png`
> - 说明：截图中应可见本次修改的系统设置项（字段、标签、帮助文案）

- 截图链接 / Screenshot links（Web UI/报告改动项必填，未提供请在下方“不适用原因”给出替代证据）：
- settings 页建议命名：`smoke-settings-page-zh` / `smoke-settings-page-en`
- 前后对比 / Before & After（如有）：
- settings 字段变更说明：截图或产物应明确包含 `MARKET_REVIEW_REGION` 字段与帮助文案区块（中文/英文）。
- 不适用原因 / Reason if not applicable（若未附截图，此项务必填写，且包含可复现证据与命令）：
  - Playwright 命令（无截图时）：`cd apps/dsa-web && npx playwright test e2e/smoke.spec.ts --grep "settings page"`
  - 产物路径（无截图时）：`apps/dsa-web/test-results/**/smoke-settings-page-*.png`
  - 说明：截图（或产物）必须可见本次修改的设置字段文案与帮助信息。

> 若本 PR 修改 Web 设置字段（字段、文案或帮助文案），截图或替代证据必须可定位到对应设置项区域并可追溯至变更项；该项为必填。

> 若本 PR 修改 Web UI 或报告展示且无法获取截图，原因栏必须给出可复现替代证据（例如 Playwright 截图产物路径 + 命令），且不得留空。

## Compatibility And Risk

请说明兼容性影响、潜在风险（如无请写 `None`）。  
*(EN) Describe compatibility impact and potential risks (write `None` if not applicable).*

- 若本 PR 修改第三方模型 / API 的兼容语义、请求参数、路由前缀或 provider fallback，请提供**官方来源链接或公告**，并说明这是长期约束、当前运行时约束还是临时兼容处理。  
  请在下方补充所影响外部 API/服务、回归范围与回退方式。  
  *(EN) If this PR changes third-party model/API compatibility, request parameters, routing prefixes, or provider fallback behavior, include an **official source link or announcement** and clarify whether the rule is permanent, runtime-specific, or a temporary compatibility workaround.)*
- 若本 PR 未触及第三方模型/API、provider/model/base URL 或运行时配置保存/清理/迁移逻辑，请在此段直接按以下文案确认（无须再次展开）：  
  `本 PR 未变更 provider/model/base URL、运行时配置清理迁移语义；历史配置保持不变；回滚方式为 revert 本提交。`
- 若本 PR 修改 `.github/PULL_REQUEST_TEMPLATE.md` / PR 流程模板类文件，请在此明确：仅影响协作流程与模板维护，不改 runtime 行为；回退方式为 revert；并补充是否影响自动化提交流程。  
  *(EN) If this PR changes `.github/PULL_REQUEST_TEMPLATE.md` or other PR workflow files, state that it only affects contribution governance templates (no runtime behavior), provide rollback by revert, and note any CI/checklist impact.)*
- 若本 PR 依赖特定运行时 / 锁定依赖窗口（例如 LiteLLM 版本范围、OpenAI-compatible 路由、YAML alias 行为），请写明当前验证过的兼容范围与覆盖路径。  
  *(EN) If this PR depends on a specific runtime or pinned dependency window (for example a LiteLLM version range, OpenAI-compatible routing, or YAML alias behavior), state the compatibility window you verified and which code paths were covered.)*
- 若本 PR 触及运行时配置保存、清理、迁移或回填逻辑，请明确说明旧配置是否会被自动改写、清空、迁移或保持不变，以及用户如何恢复原行为。  
  *(EN) If this PR touches runtime config save/cleanup/migration/backfill logic, explicitly describe whether existing config is rewritten, cleared, migrated, or left intact, and how users can restore the previous behavior.)*
- 若本 PR **未触及** provider/model/base URL 或运行时配置保存/清理/迁移逻辑（本条仅作为声明），请明确写：`本 PR 未变更 provider/model/base URL、运行时配置清理迁移语义；历史配置保持不变；回滚方式为 revert 本提交。`

## Rollback Plan

请至少写一句可执行的回滚方案（必填）。  
*(EN) Provide at least one actionable rollback step (required).*

- 如果是兼容性修复，默认应写出**最小回滚方式**（例如 `revert this PR`），并说明是否需要额外回滚配置或数据迁移。  
  *(EN) For compatibility fixes, include the **minimal rollback path** (for example `revert this PR`) and whether any additional config or data rollback is required.)*

## EXTRACT_PROMPT Change (if applicable)

若本 PR 修改了 `src/services/image_stock_extractor.py` 中的 `EXTRACT_PROMPT`，请在此处粘贴完整变更后的 prompt。  
*If this PR changes `EXTRACT_PROMPT` in `src/services/image_stock_extractor.py`, paste the full updated prompt here:*

<details>
<summary>展开 / Expand: Full EXTRACT_PROMPT</summary>

```
(paste full prompt here)
```

</details>

## Checklist

- [ ] 本 PR 有明确动机和业务价值 / This PR has a clear motivation and value
- [ ] 已提供可复现的验证命令与结果 / Reproducible verification commands and results are included
- [ ] 已评估兼容性与风险 / Compatibility and risk have been assessed
- [ ] 已提供回滚方案 / A rollback plan is provided
- [ ] 若修改报告格式或 Web UI 界面，已在 PR 描述/评论附受影响报告 / 页面截图，且未把一次性验收截图作为仓库文件合入 / If report formatting or Web UI changed, affected report/page screenshots are linked in the PR body/comments and one-off acceptance screenshots are not committed as repository files
- [ ] 若本 PR 修改 Web 设置字段（字段、文案或帮助文本），请补充设置页截图；无法截图时需提供替代可视证据（命令 + 产物路径），并指向对应变更项 / If Web settings fields changed (labels or help text), screenshots of the settings page are required; if unavailable, provide alternative visual evidence with command + artifact path that points to the changed item.
- [ ] 若涉及用户可见变更，已同步更新相关文档与 `docs/CHANGELOG.md`；`README.md` 仅在首页级信息变化时更新，细节优先写入 `docs/*.md` / If user-visible changes are included, relevant docs and `docs/CHANGELOG.md` are updated; `README.md` is updated only for homepage-level changes, with details kept in `docs/*.md`
