# `trellis mem` CLI Reference

Full flag reference for the five subcommands. Pin this as the authoritative source — `trellis mem help` prints the same content at runtime, so anything here that drifts is a bug.

## Subcommands

| Command                | Purpose                                                                                                                |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `list`                 | List sessions. Default subcommand when none is given.                                                                  |
| `search <keyword>`     | Find sessions whose contents match a keyword.                                                                          |
| `context <session-id>` | Drill into one session: top-N hit turns + surrounding context. Pair with `--grep` for keyword anchoring.               |
| `extract <session-id>` | Dump cleaned dialogue. Combine with `--phase` / `--grep` to slice.                                                     |
| `projects`             | List active project `cwd` values with session counts. Use this to discover which `--cwd` to pass to other subcommands. |

## Flags (apply where meaningful)

| Flag                                          | Subcommands       | Meaning                                                                                                                                                    |
| --------------------------------------------- | ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--platform claude\|codex\|opencode\|pi\|all` | all               | Default `all`. OpenCode adapter is currently a stub on `0.6.0-beta.*` — see "Caveats" below.                                                               |
| `--since YYYY-MM-DD`                          | list / search     | Inclusive lower date bound.                                                                                                                                |
| `--until YYYY-MM-DD`                          | list / search     | Inclusive upper date bound.                                                                                                                                |
| `--global`                                    | list / search     | Include sessions from every project on this machine. Default is the current project `cwd`.                                                                 |
| `--cwd <path>`                                | list / search     | Force a specific project cwd instead of inferring from where you are.                                                                                      |
| `--limit N`                                   | list / search     | Cap output rows. Default `50`.                                                                                                                             |
| `--grep KW`                                   | extract / context | Filter turns by keyword. Multi-token AND when whitespace-separated.                                                                                        |
| `--phase brainstorm\|implement\|all`          | extract           | Slice session by Trellis task boundaries. `brainstorm` = `[task.py create, task.py start)`. `implement` = turns outside brainstorm windows. Default `all`. |
| `--turns N`                                   | context           | Number of hit turns to return. Default `3`.                                                                                                                |
| `--around N`                                  | context           | Surrounding turns to include per hit. Default `1`.                                                                                                         |
| `--max-chars N`                               | context           | Total character budget. Default `6000` (~1500 tokens).                                                                                                     |
| `--include-children`                          | search / context  | Merge OpenCode sub-agent sessions into their parent session.                                                                                               |
| `--json`                                      | all               | Emit machine-parseable JSON instead of human-readable output.                                                                                              |

## Common one-liners

```bash
# What past sessions discussed "deadlock" anywhere on this machine?
trellis mem search "deadlock" --global --limit 20

# Inside a specific session, surface the top 5 turns that mention "lock contention"
# plus 2 turns of surrounding context.
trellis mem context 5842592d --grep "lock contention" --turns 5 --around 2

# Recover the brainstorm window for a session — useful when continuing a task
# the user started a week ago.
trellis mem extract 5842592d --phase brainstorm

# List every project this machine has Trellis sessions for, with counts.
trellis mem projects
```

## Output shapes

- **Default human output** (no `--json`): wrapped to a terminal, with session ids highlighted and turn markers visible. Suitable to read inline but messy to paste into a markdown file.
- **`--json`**: stable schema, safe to parse and process. When piping `mem` output into a follow-up step (e.g. summarizing for a Lessons section), prefer `--json`.

## Caveats

- **OpenCode adapter is a stub on `0.6.0-beta.*`.** When `--platform` resolves to OpenCode (or `all` and OpenCode would be included), `mem` prints a one-line "reader unavailable" notice and continues with the other platforms. Don't promise OpenCode coverage in your reply until the adapter ships.
- **`--phase` slicing depends on `task.py create` / `task.py start` invocations appearing in the recorded bash calls of the session.** Sessions where the user ran `task.py` from a different terminal — outside the recorded AI loop — will not have phase boundaries. `--phase all` is the safe fallback.
- **`mem` indexes platform JSONL files directly.** If the user has cleared their Claude / Codex / Pi session storage, `mem` cannot recover what is no longer on disk.
- **`mem` is read-only.** No remote sync, no edits to platform JSONL. Any write you do based on `mem` findings is your own follow-up call into the editing tools available to you.

## When you need more than this reference

Run `trellis mem help` in the user's shell. The runtime help is authoritative and will be ahead of this reference during fast-moving beta releases.
