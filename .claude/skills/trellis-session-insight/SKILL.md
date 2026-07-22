---
name: trellis-session-insight
description: "Reach into past AI conversation history through the `trellis mem` CLI. Use whenever the user asks 'how did we solve X last time', 'have we discussed this before', 'what was the decision on X', 'remind me what we did in this task', '上次怎么解的', '之前讨论过吗', '想起一段对话', or when starting a brainstorm that overlaps prior work, debugging a familiar bug, continuing a task across sessions, or doing a finish-work review. Returns raw past dialogue; decide for the moment whether to update spec, append to task notes, quote inline in the answer, or just internalize."
---

# Trellis Session Insight

This skill teaches an AI **how to call `trellis mem`** — the project's cross-session memory feedstock — and **when reaching for it is the right move**.

It is intentionally a **capability skill, not a workflow**. There is no fixed output file, no required write-back step, no "always run after finish-work" rule. What to do with what `mem` returns is a judgement call made in the moment of the conversation. The skill exists so the AI knows the capability is there and can decide.

## What `trellis mem` is

A local CLI that indexes the user's past Claude Code, Codex, and Pi Agent conversation logs and lets you list, search, slice by Trellis task boundaries, and dump cleaned dialogue from them. Claude and Codex use `~/.claude/projects/` and `~/.codex/sessions/`. Pi uses its default or environment-configured session root, global `~/.pi/agent/settings.json`, and the scoped project's `.pi/settings.json`; relative `sessionDir` values resolve from the settings file directory. Project-local Pi settings require project-scoped lookup through the current cwd or `--cwd`. OpenCode logs are not yet indexable (provider adapter pending) — when an OpenCode session is the obvious target, surface that limitation rather than guessing.

Nothing in `mem` is uploaded. All reads are local.

## When to reach for it

The bar is "would a senior teammate ask 'didn't we already talk about this?'" — those are the moments. Some concrete patterns:

- **Brainstorm rerun risk.** Starting a new task that touches an area the user has been in before, and you want to check whether a decision was already made — before re-asking the user.
- **Familiar-bug debugging.** The current bug pattern feels like one the user reported / fixed before. Pulling the relevant past session can save a full debugging loop.
- **Cross-session continuation.** The user resumes work after a gap and says "where were we" / "继续上次的" without being specific.
- **Decision retrieval.** The user references "the decision we made about X" but the decision lives in an old brainstorm, not in any `prd.md` / `spec/`.
- **Finish-work retrospective.** When the user explicitly asks for a wrap-up of what was decided / what hurt / what surprised them in this task — not as a forced step on every finish-work.
- **Pattern-spotting across past work.** The user asks "do I keep making the same mistake on X" / "我每次都踩这个坑吗" — search across sessions answers that.

If none of these apply, don't call `mem`. It is a tool, not a ceremony.

## When NOT to reach for it

- The relevant context is already in the current turn, `prd.md`, `design.md`, recent `git log`, or the open files. `mem` is for stuff that has fallen out of immediate reach.
- The user is asking about a fact in the code, not a fact from a past conversation. `git log -p` / `grep` / reading the file directly is faster and more authoritative.
- You are in a sub-agent (`trellis-implement` / `trellis-check`) whose dispatch prompt already includes the curated `implement.jsonl` / `check.jsonl` context. Adding `mem` on top usually just clutters.
- The user has explicitly said "don't dig through history, just answer what I asked".

## What to do with what `mem` returns

Treat the output as **raw material**, not a deliverable. Once you have it, decide based on the live conversation:

- **Quote inline in your reply** if a specific past exchange answers the user's current question — and cite the session-id / phase so the user can verify.
- **Update `<task>/prd.md` or `<task>/design.md`** if `mem` surfaced a load-bearing decision that should have been written down but wasn't. Surface the proposed edit to the user first.
- **Append to a task-local notes file** (e.g. `<task>/notes.md` or extending an existing one) if the finding belongs to the current task's record but doesn't fit the PRD.
- **Update `.trellis/spec/`** if the finding is a project-wide convention or gotcha that would help future tasks. Run the `trellis-update-spec` skill for that — `session-insight` ends at the discovery.
- **Just absorb it** for the next few turns and answer better, without writing anything. This is often the right move for one-off recall.

Trellis does not prescribe a single destination. Forcing every recall into a fixed file makes the file grow into noise. Let the situation decide.

## How to call it

Full CLI reference is in `references/cli-quick-reference.md`. The 80% case is one of:

```bash
# Find sessions whose contents mention a keyword (project-scope is default;
# add --global to search every project on this machine).
trellis mem search "<keyword>"

# Dump dialogue from one session, optionally filtered by phase or keyword.
trellis mem extract <session-id> --phase brainstorm
trellis mem extract <session-id> --grep "<keyword>"

# Drill into a session: top-N hit turns + surrounding context.
trellis mem context <session-id> --turns 3 --around 2

# When you do not know the session id yet, start with list + filter.
trellis mem list --cwd <project-path>
trellis mem projects   # → list active project cwds, then narrow
```

Phase slicing (`--phase brainstorm|implement|all`) cuts the session at `task.py create` and `task.py start` boundaries. For a finish-work review of the current task, `--phase brainstorm` recovers the planning discussion and `--phase implement` recovers the execution loop. Default is `all`.

## Triggering patterns

`references/triggering-patterns.md` lists more verbatim user phrasings (English + Chinese) that should make you think "reach for `mem`" — keep that handy when training instinct.

## Out of scope

- `mem` does not edit code or update files. Any write-back is your decision in the moment.
- `mem` is read-only on the platform JSONL stores. It does not push or sync to remote.
- This skill does not replace `trellis-update-spec` (which is the right tool for promoting a finding into project-wide guidance) or the platform-native task / spec workflow.
