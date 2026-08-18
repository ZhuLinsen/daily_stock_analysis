# Grok Bot Skill 示例

给 2026-08-11 [Grok Bot](https://x.ai/bot) 用的最小 Skill 包。只调用 DSA 已有 REST，不引入新 API、环境变量或 MCP server。

把 [`SKILL.md`](SKILL.md) 拷进 Bot 的 Skills 目录，设置 `DSA_BASE_URL`（例如 `http://127.0.0.1:8000`），并先让 DSA 以 `python main.py --serve-only` 或 Docker 长期运行。

完整边界、DecisionSignal Routine、认证限制见 [Grok Bot 集成](../../grok-bot-integration.md)。openclaw 用户看 [openclaw Skill](../../openclaw-skill-integration.md)，契约相同。
