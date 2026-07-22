---
name: trellis-channel
description: Use Trellis channel for live multi-agent collaboration, spawned workers, cross-agent review, progress inspection, forum channels, and channel log debugging.
---

# trellis-channel

`trellis channel` is the local multi-agent collaboration runtime. Reach for it when agents need to talk through a durable event log, when a worker should be spawned as a peer process, when an in-flight worker needs interrupt / debugging, or when feedback should be recorded on a durable `--type forum` channel.

Typical user signals: "和 codex/claude 讨论", "brainstorm with another agent", "spawn an implement/check worker", "let agent review", "open an issue board / changelog forum", "look at this thread", "channel is stuck / no output", "progress was truncated", "how do I write that channel command".

This skill is an index. Load only the reference file for the current job — do not preload all of them.

## First Commands

```bash
trellis --version
trellis channel --help
trellis channel list --all
trellis channel list --scope global --all
```

If the user names a channel or thread, inspect it before asking for background:

```bash
trellis channel forum <board> --scope global
trellis channel thread <board> <thread> --scope global
trellis channel context list <board> --scope global --thread <thread>
```

## Route By User Intent

| User intent | Read |
|---|---|
| "和 codex/claude 讨论一下", "brainstorm with another agent" | `references/workflows.md` |
| "派一个 implement/check agent", "让 agent review", "spawn a worker" | `references/workflows.md`, then `references/workers.md` |
| "开 issue 区 / topic 群 / changelog / board", "make a forum" | `references/forum.md` |
| "看看这个 thread / linked context", "inspect a thread" | `references/forum.md` |
| "channel 卡住了 / 没输出 / progress 被截断", "worker stalled" | `references/progress-debugging.md` |
| "具体命令怎么写", "what flags does X take" | `references/command-reference.md` |

## Core Rules

- New forum channels use `--type forum`. A `thread` is one item inside a forum channel.
- Use `--context-file` / `--context-raw` and `trellis channel context add/delete/list`. `--linked-context-*` is deprecated terminology.
- Use `--stdin` or `--text-file` for long messages. Do not put long mixed Chinese/English text in the positional shell argument.
- Pretty `messages` output is an operator dashboard and may truncate progress. Use `--raw` for audit.
- `--as` is the speaker or worker handle, depending on the command. Use explicit, stable names when multiple agents or sessions are involved.
- `--scope project` (default) operates on the current cwd's project bucket; `--scope global` operates on the shared `__global__` bucket. Pick scope deliberately — a global board is invisible from project listings unless `--scope global` is passed.
- For brainstorm, do multiple pressure-test rounds. One answer plus one confirmation is review, not brainstorm.
- **Dispatcher wait pattern**: use `--kind done` / `--kind turn_finished` (trellis-emitted system events), NOT a user `--tag` as the completion signal. CLI help lists `phase_done` / `question` as `--tag` examples but only `interrupt` is a reserved tag with hardcoded trellis behavior; the others are opaque user labels. Relying on a worker to run `send --tag <my_signal>` is unreliable — LLM workers commonly write the tag string into prose instead of running the actual CLI command. See `references/command-reference.md` "tag vs kind".
- Forum channels are event-sourced. Do not parse `events.jsonl` first; use `forum`, `thread`, `messages --thread`, and `context list`.
- `@mindfoldhq/trellis-core` owns reusable channel/thread state, event append, seq allocation, context/title projection, reducers, and task helpers. The CLI owns flags, terminal rendering, prompts, worker lifecycle, and process exits.

## Reference Files

- `references/workflows.md` — canonical collaboration patterns A–F (peer brainstorm, spawned review, dispatch-and-wait, forum issue capture, interrupt-and-redirect, one-shot run).
- `references/forum.md` — forum channels, context, title, rename, changelog forums, thread filtering.
- `references/workers.md` — spawn, agent cards, context injection (`--file` / `--jsonl`), interrupts, kill semantics.
- `references/progress-debugging.md` — progress/raw inspection, stalled worker diagnosis, OOM guard, exit codes.
- `references/command-reference.md` — current CLI command reference (every subcommand, every flag, output conventions, scope/type model).

## Not For

- One static review where a markdown file and prompt are enough.
- Replacing normal tool calls with self-logging.
- Long-term memory retrieval. Use durable forum channels for actionable issues, and `trellis mem` (the `trellis-session-insight` skill) for session/history search.
