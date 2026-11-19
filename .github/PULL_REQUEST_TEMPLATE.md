<!-- 可用中文或英文填写。Use Chinese or English. Keep the details relevant to this PR. -->

## PR Type

<!-- fix / feat / perf / refactor / docs / test / ci / chore -->

## Background And Problem

<!-- 谁在什么场景遇到什么问题？为什么值得做？ / Who is affected, what happens today, and why is this change useful? -->

## Scope Of Change

<!-- 按独立改动说明改前、改后和原因，列出涉及的模块或文件。治理改动说明影响哪份规则及其执行入口。 / Describe each change, its previous and new behavior, and the modules or files involved. -->

## Issue Link

<!-- Fixes #... / Refs #...。无 Issue 时说明动机和验收标准。 / Without an issue, give the motivation and acceptance criteria. -->

## User Impact

<!-- Web 和 Desktop 界面或交互、报告内容或版式、通知展示有何变化？说明受影响的 CLI/API、配置或部署入口、默认是否启用、旧用户是否需要操作。 / Describe visible Web/Desktop, report and notification changes, affected CLI/API/configuration, defaults, and any steps for existing users. -->

## Verification Commands And Results

<!-- 列出实际运行的命令、关键结果和未验证项。给出当前 Head 的 CI 链接，说明适用的 ai-governance / backend-gate / docker-build / web-gate 等检查是通过、失败、待完成或按路径跳过。 / Link current-head CI and distinguish passed, failed, pending and path-skipped jobs from local verification. -->

## Visual Evidence (if applicable)

<!-- 涉及 Web / Desktop 界面、设置字段或报告/通知渲染时，附对应页面或报告截图，最好包含前后对比。写明页面、状态、Head 和证据链接。可用评论附件或 Actions artifact；无法截图时给原因、复现步骤和可查看的替代产物。一次性证据放在 PR 或 CI 中。纯内部改动说明为何不适用。 / For visible changes, link screenshots or before/after images for the specific state. If unavailable, explain why and provide reproducible alternative evidence. -->

## Compatibility And Risk

<!-- 写明受影响的数据与回退路径。涉及第三方模型、API、路由、固定参数或依赖版本时，引用官方依据，说明锁定版本和已验证调用链。配置保存/迁移需说明对旧配置的处理。 / Cover relevant data, fallback, upstream contracts, verified dependency versions and migration behavior. -->

## Rollback Plan

<!-- 给出可执行的最小回滚步骤，包括必要的配置、数据或工作流处理。 / Give actionable rollback steps, including configuration or data recovery where applicable. -->

## EXTRACT_PROMPT Change (if applicable)

<!-- 若改动 src/services/image_stock_extractor.py 的 EXTRACT_PROMPT，请附完整最新 prompt。 / Include the full updated EXTRACT_PROMPT when changed. -->

## Checklist

- [ ] PR 标题和标签能准确描述变更，供发布说明自动汇总。 / The PR title and labels describe the change for generated release notes.
- [ ] 已更新受影响的使用文档，说明必要的升级操作。 / Affected usage docs and required upgrade steps are covered.
