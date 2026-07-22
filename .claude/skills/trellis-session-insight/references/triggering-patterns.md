# Triggering Patterns

Verbatim user phrasings that should make an AI reach for `trellis mem`. Calibrate instinct against these — if a user message hits one of these patterns and you do not reach for `mem`, you probably missed an obvious recall.

Patterns are grouped by the *intent* behind the phrasing, not the surface words. The same intent shows up in different languages and registers.

## Past-solution recall

The user is asking "how did we (or I) solve this before". Past dialogue holds the answer; the codebase shows the result but not the reasoning.

- "How did we solve this last time?"
- "What did we end up doing about X?"
- "We dealt with this once already, didn't we?"
- "上次怎么解的?"
- "之前是怎么搞定 X 的?"
- "我记得以前修过类似的"

Reach: `trellis mem search "<symptom keyword>" --global --limit 10`, then `context` into the hit that looks closest.

## Decision retrieval

The user is referencing a decision that lives in old dialogue, not in any committed file. Look in brainstorm windows.

- "What was the decision on X?"
- "Did we decide to use Postgres or SQLite?"
- "The rationale for choosing X over Y was…?"
- "我们当时为啥选了 X 而不是 Y?"
- "关于 X 我们之前是怎么定的?"
- "之前讨论过 X 的方案吗?"

Reach: `trellis mem search "<decision keyword>"` to find the session, then `extract <id> --phase brainstorm` to recover the discussion.

## Cross-session continuation

The user resumed work after a gap and the context is implicit.

- "Where were we?"
- "Continue from last time."
- "Pick up where we left off."
- "继续上次的"
- "我们上次做到哪了"
- "接着昨天那个任务"

Reach: `trellis mem list --task <current-task-dir>` to find the most recent sessions tied to the active task, then `extract` the last one.

## Familiar-bug debugging

The current bug feels like one already seen. Past sessions probably hold the resolution path.

- "I feel like I've hit this before."
- "Doesn't this look like that bug from last month?"
- "Same kind of timeout I had in X."
- "这个错好像之前见过"
- "这个 bug 是不是上次那个?"
- "怎么又是这个 error?"

Reach: `trellis mem search "<error message fragment>" --global`. Anchor on a short, distinctive token from the actual error string.

## Self-pattern spotting

The user is asking whether they keep repeating the same kind of mistake or decision.

- "Do I always make this mistake?"
- "How often have I run into X?"
- "Is this a recurring thing for me?"
- "我每次都踩这个坑吗?"
- "我老犯这个错?"
- "这类问题之前出现过几次?"

Reach: `trellis mem search "<topic>" --global --limit 50` and scan the dates / projects in the listing. Optionally `extract` two or three for comparison.

## Finish-work retrospective (on demand)

The user explicitly wants to look back at this task — not as a forced step, only when they ask.

- "Summarize what we did in this task."
- "What were the key decisions / surprises?"
- "Write up the lessons from this round."
- "总结一下这次的经验"
- "记一下这次踩的坑"
- "复盘下这个任务"

Reach: identify the current task's session id (from `.trellis/.runtime/sessions/*.json` or `mem list --task <task-dir>`), then `extract <id> --phase brainstorm` and `--phase implement`. Present a summary — surface concrete file:line citations where possible. Whether to also write the summary somewhere (PRD, spec, notes file) is the user's call; offer, don't auto-write.

## Anti-patterns: do NOT reach for `mem` here

- "What does this function do?" → read the file.
- "Why is this test failing?" → read the test output and the file.
- "What's the right pattern for X in our codebase?" → grep / read spec files.
- "What's the latest npm version of Y?" → call `npm view`.
- "Fix this bug." → debug. Reach for `mem` only if you suspect prior context exists; otherwise it is noise.

The bar stays: would a senior teammate ask "didn't we already talk about this?" before answering? If yes, reach for `mem`. If no, don't.
