# 贡献指南

感谢你对本项目的关注！欢迎任何形式的贡献。

## 🐛 报告 Bug

1. 先搜索 [Issues](https://github.com/ZhuLinsen/daily_stock_analysis/issues) 确认问题未被报告
2. 使用 Bug Report 模板创建新 Issue
3. 提供详细的复现步骤和环境信息

## 💡 功能建议

1. 先搜索 Issues 确认建议未被提出
2. 使用 Feature Request 模板创建新 Issue
3. 详细描述你的使用场景和期望功能

## 🔧 提交代码

### 开发环境

```bash
# 克隆仓库
git clone https://github.com/ZhuLinsen/daily_stock_analysis.git
cd daily_stock_analysis

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
```

### 提交流程

1. Fork 本仓库
2. 创建特性分支：`git checkout -b feature/your-feature`
3. 提交改动：`git commit -m 'feat: add some feature'`
4. 推送分支：`git push origin feature/your-feature`
5. 创建 Pull Request

用 PR 标题描述合入后发生的变化，在正文写清谁受益、哪些入口受影响，以及如何验证。Web、桌面端或报告有展示变化时，附上对应页面或报告的截图。发布说明按合入 PR 的标题和标签自动汇总，维护者确认分类并归档，贡献者无需手写 `docs/CHANGELOG.md`。

### Commit 规范

使用 [Conventional Commits](https://www.conventionalcommits.org/) 规范：

```
feat: 新功能
fix: Bug 修复
docs: 文档更新
style: 代码格式（不影响功能）
refactor: 重构
perf: 性能优化
test: 测试相关
chore: 构建/工具相关
```

示例：
```
feat: 添加钉钉机器人支持
fix: 修复 429 限流重试逻辑
docs: 更新 README 部署说明
```

### 代码规范

- Python 代码遵循 PEP 8
- 运行日志（`logger.*` / `logging.*`）统一使用简洁英文；用户可见报告、推送通知与机器人回复保留多语言配置
- 函数和类需要添加 docstring
- 重要逻辑添加注释
- 新功能需要更新相关文档

### CI 自动检查

提交 PR 后，CI 会自动运行以下检查：

仅修改普通 `docs/**`、非治理类 Markdown 或 `LICENSE` 时，CI 保留轻量的变更检测、治理校验和门禁汇总，但跳过 3 个后端测试 shard、Docker、Web 与桌面打包。被离线测试直接读取的契约文档、静态 API 规格与 Markdown fixture 仍会触发后端测试。`AGENTS.md`、`.github/instructions/**`、`.agents/skills/**` 等治理资产仍会由 `ai-governance` 校验；配置、依赖、工作流等会影响运行的文本文件仍执行对应完整检查。

| 检查项 | 说明 | 必须通过 |
|--------|------|:--------:|
| backend-gate | `scripts/ci_gate.sh`（py_compile + flake8 严重错误 + 本地核心脚本 + offline pytest） | ✅ |
| docker-build | Docker 镜像构建与关键模块导入 smoke | ✅ |
| web-gate | 按路径执行前端 lint、构建、测试与 Playwright 截图，产物名为 `web-ui-evidence-<head SHA>` | ✅（触发时） |
| pr-review | 暂停 PR 自动触发，仅保留维护者通过 `workflow_dispatch` 按 PR 编号手动运行；通过 GitHub API 读取 PR 元数据和 diff，不检出或执行 fork PR 代码 | ❌（辅助项） |
| network-smoke | 定时/手动执行 `pytest -m network` + `scripts/test.sh quick`（非阻断） | ❌（观测项） |

**本地运行检查：**

```bash
# backend gate（推荐）
python -m pip install -r .github/requirements-ci.txt
./scripts/ci_gate.sh

# 单独检查运行时日志是否为英文
python scripts/check_english_logs.py

# 前端 gate（如修改了 apps/dsa-web）
cd apps/dsa-web
npm ci
npm run lint
npm run build
```

## 📋 产品演进原则与优先贡献方向

项目已具备完整核心主链路，后续坚持 **「做减法、重核心、做简单」** 原则：优先把核心功能做稳做深，克制新增边角料功能、重复模板、平行入口或低频开关。**开发较大新功能前，建议先开 Issue 对齐必要性（避免白做功）；常规 Bug 修复、体验优化和小改进可直接提 PR。**

优先欢迎的贡献方向（按优先级排序，核心入口见 [README](../README.md)）：

- 🐛 **核心链路 Bug 修复与稳定性提升**（数据抓取、分析准确率、容错超时、推送可靠）
- ✨ **做减法与体验简化**（精简复杂配置、收敛重复代码与交互噪音、提升排障效率）
- ⚡ **性能优化与测试补强**（覆盖真实风险路径的确定性测试）
- 📖 **文档纠偏与精简**（保持与实际代码一致，不堆叠重复说明）
- 🧩 **经 Issue 对齐的高价值核心能力**（明确解决高频刚需且不破坏现有简洁性）

## ❓ 问题解答

如有任何问题，欢迎：
- 创建 Issue 讨论
- 查看已有 Issue 和 Discussion

再次感谢你的贡献！ 🎉
