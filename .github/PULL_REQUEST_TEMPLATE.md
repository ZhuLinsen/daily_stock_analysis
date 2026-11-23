<!--
For Chinese contributors: 请直接用中文填写。
For English contributors: please fill in English.
-->

## PR Type

- [ ] fix
- [ ] feat
- [ ] refactor
- [ ] docs
- [ ] chore
- [ ] test
- [ ] ci

## Background And Problem

描述当前问题现象、触发条件、关联 Issue（`Fixes #xxx` / `Refs #xxx`，无 Issue 时写动机与验收标准）以及根因定位（`path:line`）；如新增配置、开关或独立入口，请说明为何不能直接复用或精简既有能力。

## Scope Of Change

按实际 `git diff` 列出改动（区分**新增文件**与**修改的既有运行时文件**，避免描述与实际 diff 不一致）：

- 文件总数 / 变更行数：
- 新增文件：
- 修改的既有运行时文件：
- 文档更新（`docs/*` / `docs/CHANGELOG.md`）：

## Behavior Changes (Before vs After)

| 场景 / 输入 | 改前行为 | 改后行为 | 谁会感知（配置/渠道/页面） |
|---|---|---|---|
|  |  |  |  |

## Config / API / UI Impact

- **环境变量 / `.env` 配置变更**（无则写 `无`；有则逐项列键名、默认值、不配置时行为，并确认 `.env.example` / docs / Web 设置页 / Actions 同步情况）：
- **API / Schema / CLI 变更**（无则写 `无`；有则写字段/参数变化与 Web/Desktop 兼容情况）：
- **第三方模型 / API 兼容变更**（如涉及，附官方来源链接、锁定依赖兼容窗口、是否改写旧配置；否则写 `不适用`）：

## Verification Commands And Results

贴实际执行的命令与关键结果，并与当前 Head CI 保持一致：

- 当前 Head CI：`ai-governance: pass/fail` | `backend-gate: pass/fail` | `docker-build: pass/fail/skipped` | `web-gate: pass/fail/skipped`（附链接）
- 本地验证命令与结果（如有环境差异请注明）：

## Visual Evidence (if applicable)

若修改了报告格式、报告渲染、通知卡片或 Web/Desktop UI 界面，请附受影响页面/报告截图（涉及前后差异优先附前后对比；勿将一次性截图作为仓库文件提交）。无法截图时写明原因与可复现替代证据（如 Playwright 命令与 Actions artifact 链接）。

- 截图 / 产物链接：

## Irreversible Changes And Recovery (if applicable)

仅当涉及**数据库/持久化格式变更、运行时配置自动改写/迁移、外部系统状态写入（自选/账本/通知）、或发布策略变化**时，写明旧数据/旧配置如何处理及恢复方式；纯代码变更直接写 `无`。

- 

## EXTRACT_PROMPT Change (if applicable)

若修改了 `src/services/image_stock_extractor.py` 中的 `EXTRACT_PROMPT`，请粘贴完整最新 prompt：

<details>
<summary>展开 / Expand: Full EXTRACT_PROMPT</summary>

```
(paste full prompt here)
```

</details>

## Checklist

- [ ] PR 描述与实际 `git diff` 完全一致
- [ ] 已说明行为变化与配置/API/UI/报告/通知影响面
- [ ] 已提供可复现的验证命令与当前 Head CI 结论
- [ ] 若修改报告/通知/Web UI，已附截图或可复现替代可视证据，且未将临时截图提交入库
- [ ] 若涉及用户可见变更，已同步相关 `docs/*.md` 与 `docs/CHANGELOG.md`（`[Unreleased]` 扁平格式）
