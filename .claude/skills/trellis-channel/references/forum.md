# Forum Channels

Forum channels are durable, topic-style channels. They are created with
`--type forum` at channel-creation time and are immutable after that. They are
not normal chat streams: the default read path is
**forum summary -> one thread timeline -> current context**.

## Forum vs Regular Channel

A channel's type is set with `--type` on `channel create` and never changes:

- `chat` (default) — flat message timeline. `channel messages` always renders
  the event stream. Forum-only flags such as `--thread` and `--action` are
  rejected here.
- `forum` — thread-oriented. `channel messages` without filters renders a
  thread-board summary instead of raw events. The `post`, `forum`, `thread`,
  and `thread rename` subcommands only apply to forum channels.

Both types share the same scope model (`--scope project` is the default;
`--scope global` puts the channel in the cross-project bucket).

## Create A Forum Channel

```bash
trellis channel create design-feedback \
  --type forum \
  --scope global \
  --description "Cross-project design feedback board." \
  --context-raw "One thread per design topic; close when resolved." \
  --by main
```

Use `--scope project` for a board scoped to one repo, `--scope global` for a
cross-project board.

## Threads: Open, Comment, Status, Summary

Threads live inside a forum channel. Each thread is identified by a stable
`--thread <key>` (lowercase kebab-case is conventional). The first action on
a thread is `opened`; everything afterwards uses the same `--thread` key.

```bash
trellis channel post design-feedback opened \
  --scope global \
  --as main \
  --thread login-empty-state \
  --title "Empty state on the login screen" \
  --description "Track design feedback for the new login empty state." \
  --labels design,login \
  --context-raw "Spotted during the 0.4 release review." \
  --text-file /tmp/thread-open.md

trellis channel post design-feedback comment \
  --scope global \
  --as reviewer \
  --thread login-empty-state \
  --text-file /tmp/review.md

trellis channel post design-feedback status \
  --scope global \
  --as main \
  --thread login-empty-state \
  --status closed

trellis channel post design-feedback summary \
  --scope global \
  --as main \
  --thread login-empty-state \
  --summary "Adopted the option-B layout; ticket TRELLIS-123 owns the fix."
```

Key distinctions:

- `--description` is the **durable** thread description (the answer to "what
  is this thread about?"). It is set on `opened` and edited by re-running
  `post` with `--description`.
- `--text` / `--stdin` / `--text-file` is the **event body** — the comment or
  payload attached to this specific timeline entry.
- `--labels` and `--assignees` are CSV and **replace** the current value; they
  do not append.
- `--summary` is the rolling thread summary. Setting it on `status closed` is
  the standard way to mark a thread resolved with context.

`--thread` is required for every action except `opened` (where it is also
required in practice — there is no anonymous thread).

## Read A Forum

```bash
trellis channel messages design-feedback --scope global
trellis channel forum design-feedback --scope global --status open
trellis channel thread design-feedback login-empty-state --scope global
trellis channel messages design-feedback --scope global --raw --thread login-empty-state
```

If a peer says "I commented on the forum", run `channel forum` first to see
which thread changed, then drill into that thread with `channel thread <name>
<thread>`. Do not jump straight to ad-hoc `events.jsonl` parsing.

## Context

Context entries are durable background that should always be in scope when
reading a channel or a thread. They are **not** timeline events; they are
projected separately and replayed for every reader.

Use the `context` subcommands. The legacy `--linked-context-file` /
`--linked-context-raw` flags on `create` and `post` are deprecated aliases
that fold into the canonical `--context-file` / `--context-raw`.

### Add Context

```bash
# Channel-level context (whole forum)
trellis channel context add design-feedback \
  --scope global \
  --raw "Upstream feedback board; please link tasks before opening threads."

# Thread-level context (one thread)
trellis channel context add design-feedback \
  --scope global \
  --thread login-empty-state \
  --file "$PWD/.trellis/tasks/05-13-login-redesign/design.md"
```

- `--thread <key>` switches between channel-level and thread-level context.
- `--file` paths **must be absolute**; relative paths are rejected.
- `--raw` is plain text inline content.
- Both flags are repeatable; at least one is required for `add` / `delete`.
- `--as <agent>` records authorship; defaults to `main`.

### List Context

```bash
trellis channel context list design-feedback --scope global
trellis channel context list design-feedback --scope global --thread login-empty-state --raw
```

`--raw` on `list` emits one JSON entry per line (useful for piping); without
it you get a human-readable `file <path>` / `raw <truncated text>` listing.
An empty store prints `(no context)`.

### Delete Context

```bash
trellis channel context delete design-feedback \
  --scope global \
  --thread login-empty-state \
  --raw "stale note"
```

You delete by **value**, not by id: pass the same `--file` or `--raw` value
that was added. Repeat the flag to delete multiple entries in one call.

### Reading Order

When reading a thread, work top-down:

1. Thread `description` (the durable "what is this about").
2. Context entries (channel-level + thread-level).
3. Timeline (`opened`, `comment`, `status`, `summary`).

If a context file is missing or unreadable, state that explicitly and
continue with the remaining data — do not fabricate the content.

## Title Projection

`title` projects a stable display title onto the channel without renaming the
storage address. The channel `name` you pass to every command stays the same.

```bash
trellis channel title set design-feedback \
  --scope global \
  --title "Design feedback board"

trellis channel title clear design-feedback --scope global
```

- `title set` requires `--title`.
- `--as <agent>` records authorship; defaults to `main`.
- This is a presentation-layer change. Tooling and scripts keep using the
  original channel name.

## Thread Rename

`thread rename` is the correction path when a thread was opened with the
wrong key (typo, wrong slug convention, etc.). Threads do not support hard
deletion — rename is the supported corrective action.

```bash
trellis channel thread rename design-feedback old-key new-key \
  --scope global \
  --as main
```

- `--as <agent>` is **required**.
- `post <name> rename` is rejected — you must use `thread rename`.

## Deletion Discipline

Do not model single-comment deletion or hard thread deletion as normal
workflow. Forum threads are append-only collaboration history. To correct
state, use:

- `post ... status` to mark a thread closed / blocked / etc.
- `post ... summary` to record the resolution.
- `post ... --labels` to re-label (replaces the set).
- `thread rename` to correct a bad thread key.

## Internal Changelog Pattern

A common use of a global forum channel is an internal release / runtime
changelog. One thread per notable change keeps history searchable:

```bash
trellis channel create release-notes \
  --type forum \
  --scope global \
  --description "Internal release and runtime changelog." \
  --context-raw "One thread per notable change; close when shipped." \
  --by main

trellis channel post release-notes opened \
  --scope global \
  --as main \
  --thread release-2026-q1 \
  --title "Channel threads and forum UX in 0.6" \
  --description "Forum channel UX shipped in the 0.6 line." \
  --labels channel,release \
  --text-file /tmp/release-notes.md
```

Use stable, descriptive thread keys (e.g. `release-2026-q1`,
`runtime-event-schema-change`) so later readers can find them by name.
