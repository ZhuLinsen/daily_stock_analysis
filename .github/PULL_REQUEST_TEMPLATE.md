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

关键输出/结论 / Key output & conclusion:

## Visual Evidence (if applicable)

若本 PR 修改报告格式、报告渲染效果或 Web UI 界面，请在此处附受影响报告 / 页面截图；涉及前后差异时，优先附前后对比。Issue / PR 过程截图、审查截图、一次性验收截图和临时可视证据请放在 PR 描述、PR 评论、GitHub 附件、Actions artifact 或外部可访问链接中，不要作为仓库文件合入。
*(EN) If this PR changes report formatting, report rendering, or Web UI, attach screenshots of the affected report/page here; before/after screenshots are preferred when relevant. Issue/PR process screenshots, review screenshots, one-off acceptance screenshots, and temporary visual evidence should be linked from the PR body/comments, GitHub attachments, Actions artifacts, or external accessible evidence; do not commit them as repository files.)*

> 如截图无法获取，请在“原因”中明确写明替代证据（如 Playwright/e2e 产物路径、审查链接）及其可追溯命令，不得留空。
>
> 若本 PR 修改 Web UI，建议至少补一条可复现路径，例如：
>
> - Playwright 截图产物：`apps/dsa-web/e2e/smoke.spec.ts`（`npx playwright test apps/dsa-web/e2e/smoke.spec.ts --grep "backtest page renders filter controls after login"`）
> - 审查证据链接：可直接使用 Actions 产物、GitHub 评论附件或外部可访问链接。

- 截图链接 / Screenshot links（必填）：
- 前后对比 / Before & After（如有）：
- 不适用原因 / Reason if not applicable（必填）：

## Compatibility And Risk

请说明兼容性影响、潜在风险（如无请写 `None`）。  
*(EN) Describe compatibility impact and potential risks (write `None` if not applicable).*

- 若本 PR 修改第三方模型 / API 的兼容语义、请求参数、路由前缀或 provider fallback，请提供**官方来源链接或公告**，并说明这是长期约束、当前运行时约束还是临时兼容处理。  
  *(EN) If this PR changes third-party model/API compatibility, request parameters, routing prefixes, or provider fallback behavior, include an **official source link or announcement** and clarify whether the rule is permanent, runtime-specific, or a temporary compatibility workaround.)*
- 若本 PR 依赖特定运行时 / 锁定依赖窗口（例如 LiteLLM 版本范围、OpenAI-compatible 路由、YAML alias 行为），请写明当前验证过的兼容范围与覆盖路径。  
  *(EN) If this PR depends on a specific runtime or pinned dependency window (for example a LiteLLM version range, OpenAI-compatible routing, or YAML alias behavior), state the compatibility window you verified and which code paths were covered.)*
- 若本 PR 触及运行时配置保存、清理、迁移或回填逻辑，请明确说明旧配置是否会被自动改写、清空、迁移或保持不变，以及用户如何恢复原行为。  
  *(EN) If this PR touches runtime config save/cleanup/migration/backfill logic, explicitly describe whether existing config is rewritten, cleared, migrated, or left intact, and how users can restore the previous behavior.)*

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
- [ ] 若涉及用户可见变更，已同步更新相关文档与 `docs/CHANGELOG.md`；`README.md` 仅在首页级信息变化时更新，细节优先写入 `docs/*.md` / If user-visible changes are included, relevant docs and `docs/CHANGELOG.md` are updated; `README.md` is updated only for homepage-level changes, with details kept in `docs/*.md`
