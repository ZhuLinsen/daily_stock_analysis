> 状态：Phase 0 / Phase 1 设计预览草稿。未实现、未接入、未导入私有知识。
> 基线：DSA `ed848da6f0fc1080e1a61a1799b9c7d510a3eaca`；AI Berkshire `4ddc638fd5366e9779450e5685d7a2a3cdff5fd0`。

# 基线审计

## 仓库身份
| 项目 | 路径 | 分支/状态 | HEAD | origin | License |
|---|---|---|---|---|---|
| DSA 正式基线 | `/Volumes/future/projects/DSA Research OS/daily_stock_analysis` | detached HEAD，干净 | `ed848da6...eaca` | `https://github.com/ZhuLinsen/daily_stock_analysis.git` | MIT，Copyright 2026 ZhuLinsen |
| Phase 0 worktree | `/Volumes/future/projects/DSA Research OS/worktrees/dsa-phase-0` | `phase-0/orchestration-baseline` | 同 DSA 基线 | 共用 DSA Git 数据 | 同上 |
| AI Berkshire 正式参考 | `/Volumes/future/projects/DSA Research OS/ai-berkshire-reference` | detached HEAD，干净 | `4ddc638f...5fd0` | `https://github.com/xbtlin/ai-berkshire.git` | MIT，Copyright 2026 xbtlin |

实验目录 `/Volumes/future/projects/ai-berkshire-fork` 不是正式输入；Phase 0 未修改该目录。流程偏差 `P0-EXPERIMENTAL-REFERENCE-STAT-001`：Owner 排除该目录后，Hermes 未读取仓库内容、未运行 Git、未写入，但曾额外读取一次路径 `stat` 元数据；分类为非破坏性、无内容泄露、无工作树变化、不影响基线。此后禁止以任何方式再次访问该路径，本记录只依据既有 Phase 0 回执。

## 工具链
- Python：`/Volumes/future/projects/DSA Research OS/.venvs/dsa-phase-0-py311/bin/python`，3.11.15。
- 虚拟环境：`/Volumes/future/projects/DSA Research OS/.venvs/dsa-phase-0-py311`，位于 Git 仓库外。
- 依据：README 声明 Python 3.10+；主要 CI 与 network-smoke 使用 3.11，部分任务使用 3.12；选择 3.11 对齐主要后端门禁。
- 隔离：该虚拟环境独立于系统 Python 3.14.4；解释器来源与 Hermes 3.11.15 同版本分发，但依赖安装在独立 venv，不使用 Hermes 的运行环境。
- Node `v22.23.2`；npm `10.9.8`；Codex `0.146.0`；Hermes `0.20.0`。

## GenerationBackend
`SUPPORTED_GENERATION_BACKENDS`：`litellm`、`codex_cli`、`claude_code_cli`、`opencode_cli`。LiteLLM 可声明工具能力；三个本地 CLI 当前仅生成文本，`supports_tools=False`。Hermes 是 LiteLLM 内的本地 OpenAI 兼容生成通道，限定 loopback `/v1`，不支持工具、流、视觉，不能冒充 Agent。

## AgentBackend
可选标识：`auto`、`litellm`、`codex_app_server`；`auto` 解析为 LiteLLM。LiteLLM 由 DSA 持有工具循环；Codex App Server 由运行时持有循环，必须保留真实 tool roundtrip、超时、取消和工具日志。

## DSA Tool Surface
当前源码注册集合由 `ALL_DATA_TOOLS + ALL_ANALYSIS_TOOLS + ALL_SEARCH_TOOLS + ALL_MARKET_TOOLS + ALL_BACKTEST_TOOLS` 组成，共列出 18 个只读研究工具：`get_realtime_quote`、`get_daily_history`、`get_chip_distribution`、`get_analysis_context`、`get_stock_info`、`get_portfolio_snapshot`、`get_capital_flow`、`analyze_trend`、`calculate_ma`、`get_volume_analysis`、`analyze_pattern`、`search_stock_news`、`search_comprehensive_intel`、`get_market_indices`、`get_sector_rankings`、`get_skill_backtest_summary`、`get_strategy_backtest_summary`、`get_stock_backtest_summary`。Phase 1 若获批，应以运行时 registry 枚举生成可复现快照，避免静态清单漂移。Tool Surface 是内部 Python API，不是 REST/MCP。

## Skill 真源
- DSA AI 协作规则唯一真源：`AGENTS.md`。
- DSA 仓库协作 Skill：`.claude/skills/`；根 `SKILL.md` 不是协作规则真源。
- AI Berkshire canonical workflow：`skills/*.md`；`codex-skills/*/SKILL.md` 多数由 `scripts/sync-codex-skills.py` 生成。

## 存储与历史报告
- 默认 SQLite：`./data/stock_analysis.db`；SQLAlchemy 模型在 `src/storage.py`，schema 基线标识 `2026-06-05-create-all-baseline`。
- `analysis_history` 保存 query、股票、报告类型、结论、原始结果、新闻、上下文和点位；Repository 为 `src/repositories/analysis_repo.py`。
- Markdown 报告由 `src/notification.py` 写入仓库根 `reports/`；现有历史比较从数据库读取。

## 门禁结果
| 命令 | 结果 |
|---|---|
| `python scripts/check_ai_assets.py` | 通过 |
| `./scripts/ci_gate.sh` | 通过：5740 passed，4 deselected，501 subtests |
| `python -m pytest -m "not network"` | 通过：同上 |
| `npm ci` | 通过，安装 461 包 |
| `npm run test` | **失败**：1 failed，1090 passed，2 skipped；JP/KR 中文市场选项缺失 |
| `npm run lint` | 通过 |
| `npm run build` | 通过 |
| AI `sync-codex-skills.py --check` | 通过：20 skills |
| AI pytest | 通过：26 passed，3 subtests |

前端失败发生在未修改基线，归类为既存代码/测试契约失败；Owner 已在 Phase 0.1 选择 `fix_first`，要求在独立 worktree 诊断和最小收口。另有 React `act(...)`、嵌套 button、无效相对 URL、重复 key 等非阻断告警，本阶段不顺手修复。
