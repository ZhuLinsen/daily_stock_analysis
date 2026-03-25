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

## Compatibility And Risk

请说明兼容性影响、潜在风险（如无请写 `None`）。  
*(EN) Describe compatibility impact and potential risks (write `None` if not applicable).*

## Rollback Plan

请至少写一句可执行的回滚方案（必填）。  
*(EN) Provide at least one actionable rollback step (required).*

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
- [ ] 若涉及用户可见变更，已同步更新相关文档与 `docs/CHANGELOG.md`；若未更新 `README.md`，已说明原因与文档落点 / If user-visible changes are included, the relevant docs and `docs/CHANGELOG.md` are updated; if `README.md` was not updated, the reason and documentation location are explained
