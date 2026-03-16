## PR Type

- [ ] fix
- [ ] feat
- [ ] refactor
- [ ] docs
- [ ] chore
- [ ] test

## Background And Problem

请描述当前问题、影响范围与触发场景。

## Scope Of Change

请列出本 PR 修改的模块和文件范围。

## Issue Link

必须填写以下之一：
- `Fixes #<issue_number>`
- `Refs #<issue_number>`
- 无 Issue 时说明原因与验收标准

## Verification Commands And Results

请填写你实际执行过的命令和关键结果（不要只写“已测试”）：

```bash
# example
./scripts/ci_gate.sh
python -m pytest -m "not network"
```

关键输出/结论：

## Compatibility And Risk

请说明兼容性影响、潜在风险（如无请写 `None`）。

## Rollback Plan

请至少写一句可执行的回滚方案（必填）。

## EXTRACT_PROMPT 变更（如适用）

若本 PR 修改了 `src/services/image_stock_extractor.py` 中的 `EXTRACT_PROMPT`，请在此处粘贴完整变更后的 prompt，便于审查者评估指令效果：

<details>
<summary>点击展开：完整 EXTRACT_PROMPT</summary>

```
（在此粘贴完整 prompt 内容）
```

</details>

## Checklist

- [ ] 我已确认本 PR 有明确动机和业务价值
- [ ] 我已提供可复现的验证命令与结果
- [ ] 我已评估兼容性与风险
- [ ] 我已提供回滚方案
- [ ] 若涉及用户可见变更，我已同步更新 `README.md` 与 `docs/CHANGELOG.md`
