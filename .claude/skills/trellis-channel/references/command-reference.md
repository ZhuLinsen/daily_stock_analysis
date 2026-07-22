# Command Reference

Authoritative current command reference for `trellis channel` subcommands,
validated against the source in `packages/cli/src/commands/channel/`
(`index.ts` Commander wiring and each subcommand handler).

Every subcommand accepts `--scope <project|global>` unless noted; `project`
is the default and resolves against the current cwd's project bucket.

## Top-level

```
trellis channel <subcommand>
```

> Multi-agent collaboration runtime — spawn / coordinate / interrupt worker
> agents through a shared event log.

---

## Create / List

### `create <name>`

```bash
trellis channel create <name>
  [--scope project|global]                # default: project
  [--type chat|forum]                     # default: chat
  [--task <path>]                         # associated Trellis task dir
  [--project <slug>]
  [--labels a,b,c]
  [--description <text>]                  # stable channel description
  [--context-file <abs-path>] ...         # repeatable
  [--context-raw  <text>]      ...        # repeatable
  [--linked-context-file <abs-path>]      # [deprecated alias]
  [--linked-context-raw  <text>]          # [deprecated alias]
  [--cwd <path>]                          # recorded in create event
  [--by <agent>]                          # default: main
  [--force]                               # overwrite existing channel
  [--ephemeral]                           # hide from default list, prunable
```

Behavior:
- Appends a `create` event; immutable `type` (cannot mutate forum↔chat after).
- `--ephemeral` channels are hidden from `channel list` by default and are
  the sweep target for `channel prune --ephemeral`.
- `--linked-context-*` are folded into `--context-*`; emit a deprecation
  notice when used.

### `list`

```bash
trellis channel list
  [--scope project|global]
  [--json]
  [--project <slug>]                      # substring match on task field
  [--all]                                 # include ephemeral (suffix '*')
  [--all-projects]                        # scan every project bucket
```

Behavior:
- Default scope: current cwd's project. `--all-projects` scans every bucket.
- Pretty mode prints `NAME WORKERS EVENTS LAST KIND TYPE TASK`, sorted by
  recency, with a footer noting hidden ephemeral count.
- `--json` switches to a JSON array.

---

## Chat Messages

### `send <name> [text]`

```bash
trellis channel send <name> [text]
  --as <agent>                            # REQUIRED — author
  [--scope project|global]
  [--to <agents,csv>]                     # default: broadcast
  [--stdin | --text-file <path>]          # body from stdin or file
  [--delivery-mode appendOnly|requireKnownWorker|requireRunningWorker]
```

Behavior:
- Body precedence: positional `[text]` → `--stdin` → `--text-file`.
- `--to` with one entry stores a string; multiple stores an array; omitted
  means broadcast.
- `--delivery-mode` selects targeted-delivery validation:
  - `appendOnly` (default-ish — just record),
  - `requireKnownWorker` (the named target must have a `spawned` event),
  - `requireRunningWorker` (the worker must currently be live).
- Prints the appended event as one JSON line on stdout.

> **Note:** `send` has **no** `--tag` and **no** `--kind` flag. See
> [`tag-vs-kind`](#tag-vs-kind--how-event-shape-is-actually-controlled) below.

### `messages <name>`

```bash
trellis channel messages <name>
  [--scope project|global]
  [--raw]                                 # one JSON event per line
  [--follow]                              # stream new events
  [--last <N>]                            # last N matching events
  [--since <seq>]                         # seq > N
  [--kind <kind>]                         # one of CHANNEL_EVENT_KINDS
  [--from <csv>]                          # author filter
  [--to <target>]                         # routing target filter
  [--thread <key>]                        # forum-only
  [--action <thread-action>]              # forum-only
  [--no-progress]                         # hide progress events
```

Behavior:
- Auto-detects forum channels: with no filters it renders the thread board
  instead of the event stream. `--thread` / `--action` are forum-only and
  error against chat channels.
- `--kind` is validated against `CHANNEL_EVENT_KINDS` (single value, not
  CSV — that's the `wait` side).

### `wait <name>`

```bash
trellis channel wait <name>
  --as <agent>                            # REQUIRED — self for filter ctx
  [--scope project|global]
  [--timeout <Ns|Nm|Nh|Nms>]              # parsed by parseDuration
  [--from <a,b>]                          # author CSV
  [--kind <k1,k2>]                        # CSV, OR semantics
  [--thread <key>]                        # forum filter
  [--action <thread-action>]              # forum filter
  [--to <target>]                         # default: own agent (broadcast + me)
  [--include-progress]                    # also wake on progress events
  [--all]                                 # require every --from to match
```

Behavior:
- Streams matching events as JSON, one per line.
- Default `--to` filter is the caller's own agent (broadcast events still
  match — broadcast + explicit-to-me).
- `--all` requires `--from` and blocks until every listed agent has produced
  a matching event.
- **Timeout exits 124** and prints `timeout: still waiting on ...` to stderr
  when `--all` was in play.

---

## tag-vs-kind — how event shape is actually controlled

There is **no `--tag` flag** anywhere in the v0.6.0 channel CLI; `--kind` is
not a legacy alias for any `--tag` flag.

Concrete model in the current source:

- `--kind` is the only event-type filter, and it is constrained to the
  trellis-emitted whitelist (`CHANNEL_EVENT_KINDS` in
  `packages/core/src/channel/internal/store/events.ts`):
  - `create`, `join`, `leave`, `message`, `thread`, `context`, `channel`,
    `spawned`, `killed`, `respawned`, `progress`, `done`, `error`,
    `waiting`, `awake`, `undeliverable`, `interrupt_requested`,
    `turn_started`, `turn_finished`, `interrupted`, `supervisor_warning`
  - Passing anything else throws
    `Invalid --kind '<x>'. Must be one of: …`.
- `--kind` lives on `wait` (CSV, OR semantics) and `messages` (single
  value). `send` and `run` cannot emit a custom kind — every `send` writes
  a `message` event.
- Mid-turn worker abort is **not** a tag. It is the dedicated
  `channel interrupt` command, which appends an `interrupt_requested` /
  `interrupted` pair and provider-level interrupts the worker.

Practical rule for dispatchers waiting on workers:

- Use `--kind done,turn_finished` for "worker finished a turn" — these are
  system events that the supervisor fires automatically. Do not depend on
  the worker LLM remembering to emit any custom signal.
- Use `trellis channel interrupt` (the command) only when you actually want
  mid-turn abort behavior.
- Do **not** invent user-side tags as completion signals. There is no
  `--tag` filter; a worker writing a custom string into its final message
  is just text inside a `message` event and cannot be matched by `wait`.

Long bodies always go through stdin or a file:

```bash
trellis channel send T --as A --stdin < /tmp/message.md
trellis channel send T --as A --text-file /tmp/message.md
```

---

## Interrupt

### `interrupt <name> [text]`

```bash
trellis channel interrupt <name> [text]
  --as <agent>                            # REQUIRED — caller
  --to <agent>                            # REQUIRED — target worker
  [--scope project|global]
  [--stdin | --text-file <path>]
```

Behavior:
- Appends an `interrupt` event with `reason: "user"` and a replacement
  instruction body; supervisor performs provider-level interrupt where
  supported (Claude `/interrupt`, Codex turn cancel).
- Prints the appended event JSON on stdout.

---

## Workers

### `spawn <name>`

```bash
trellis channel spawn <name>
  [--scope project|global]
  [--agent <agent-name>]                  # loads .trellis/agents/<name>.md
  [--provider claude|codex]               # overrides agent file
  [--as <worker-name>]                    # default: agent name
  [--cwd <path>]
  [--model <id>]
  [--resume <id>]                         # session/thread id resume
  [--timeout <Ns|Nm|Nh>]                  # auto-kill after duration
  [--warn-before <Ns|Nm|Nh>]              # supervisor_warning lead time
                                          # default 5m, 0ms disables
  [--file <path>] ...                     # glob, repeatable; inject content
  [--jsonl <path>] ...                    # Trellis manifest, repeatable
  [--by <agent>]                          # spawn-event author
                                          # default: TRELLIS_CHANNEL_AS env or 'main'
  [--inbox-policy explicitOnly|broadcastAndExplicit]
                                          # default explicitOnly
  [--idle-timeout <Ns|Nm|Nh>]             # OOM-guard idle TTL
                                          # default 5m, 0 disables
  [--max-live-workers <n>]                # spawn-time live-worker budget
                                          # default 6, 0 disables
```

Behavior:
- Provider is validated against the adapter registry
  (`packages/cli/src/commands/channel/adapters/`); current: `claude`,
  `codex`.
- Worker stays inbox-idle until the first `send --to <worker>`.
- Records a `spawned` event with `pid`, `provider`, `agent`, `files`,
  `manifests`.
- OOM-guard precedence: CLI flag → env var
  (`TRELLIS_CHANNEL_WORKER_IDLE_TIMEOUT`,
  `TRELLIS_CHANNEL_MAX_LIVE_WORKERS`) →
  `.trellis/config.yaml#channel.worker_guard` → built-in defaults.

### `run [name]`

```bash
trellis channel run [name?]
  [--agent <name>]
  [--provider claude|codex]
  [--as <worker-name>]
  [--cwd <path>]
  [--model <id>]
  [--file <path>] ...                     # repeatable, glob
  [--jsonl <path>] ...                    # repeatable
  [--message <text> | --message-file <path> | --stdin]
  [--timeout <Ns|Nm|Nh>]                  # default 5m
```

Behavior:
- One-shot. Auto-generates `run-<hex>` if `name` omitted.
- Creates an ephemeral channel (`createMode=run`), spawns a single worker,
  sends the prompt, waits for `done`, prints the final assistant text to
  stdout, then removes the channel on success. On failure the channel is
  kept for inspection and exit code is 1.

> `run` has **no** `--tag` flag. Completion is detected via the `done`
> event the supervisor emits.

### `kill <name>`

```bash
trellis channel kill <name>
  --as <agent>                            # REQUIRED — worker agent name
  [--scope project|global]
  [--force]                               # SIGKILL immediately
```

Behavior:
- Default path: SIGTERM → 8 s grace → SIGKILL escalation; the CLI writes a
  `killed` event when SIGKILL was needed so the log stays truthful.
- Cleans `pid`, `worker-pid`, `config`, `spawnlock` sidecar files; keeps
  `log`, `session-id`, `thread-id` for forensics / resume.

### `rm <name>`

```bash
trellis channel rm <name>
  [--scope project|global]
```

Behavior:
- Kills any live workers, then deletes the entire channel directory.
- Prints `Removed channel '<name>'`.

### `prune`

```bash
trellis channel prune
  [--scope project|global]                # omitted: scan every project
  [--all | --empty | --idle <Ns|Nm|Nh|Nd> | --ephemeral]   # mutually exclusive
  [--yes]                                 # actually delete (default: dry-run)
  [--dry-run]                             # default true; redundant with default
  [--keep <names,csv>]                    # exclusion list
```

Behavior:
- Filter flags are mutually exclusive — error otherwise.
- Default is dry-run; `--yes` flips to real delete.
- Without `--scope`, scans **every** project bucket (intentional, repo-wide
  cleanup); with `--scope project|global`, limited to that bucket.
- Live-worker channels are always skipped regardless of filter.
- Output: per-candidate line `name  last-ts  (reason)` plus a final summary.

---

## Forum Channels

### `post <name> <action>`

```bash
trellis channel post <name> <action>
  --as <agent>                            # REQUIRED
  [--scope project|global]
  [--thread <key>]                        # required except action=opened
  [--title <text>]
  [--text <text> | --stdin | --text-file <path>]
  [--description <text>]                  # stable thread description
  [--status <status>]
  [--labels a,b]                          # REPLACES thread labels
  [--assignees a,b]                       # REPLACES assignees
  [--summary <text>]
  [--context-file <abs-path>] ...
  [--context-raw  <text>]      ...
  [--linked-context-file <abs-path>]      # [deprecated alias]
  [--linked-context-raw  <text>]          # [deprecated alias]
```

Behavior:
- `<action>` is free-form on the CLI surface; conventional values include
  `opened`, `comment`, `status`, `labels`, `assignees`, `summary`,
  `processed`.
- `action=rename` is rejected — use `thread rename` instead.
- `--labels` / `--assignees` are replace-semantics, not append.
- Output: appended event JSON on stdout.

### `forum <name>`

```bash
trellis channel forum <name>
  [--scope project|global]
  [--status <status>]
  [--raw]
```

Behavior:
- Lists threads (reduced state). `--status` filters by current thread
  status. `--raw` prints one JSON per thread.

### `thread <name> <thread>` / `thread rename`

```bash
trellis channel thread <name> <thread-key>
  [--scope project|global]
  [--raw]

trellis channel thread rename <name> <old-thread> <new-thread>
  --as <agent>                            # REQUIRED
  [--scope project|global]
```

Behavior:
- `thread <name> <key>` shows one thread's timeline:
  header `<thread> [<status>] <title>`, then description / labels /
  assignees / summary / timeline lines. `--raw` switches to raw events.
- `thread rename` is the only mutation; `post --action rename` is rejected.

---

## Context / Title

### `context add` / `context delete` / `context list`

```bash
trellis channel context add <name>
  [--as <agent>]                          # default: main
  [--scope project|global]
  [--thread <key>]                        # thread-level instead of channel-level
  [--file <abs-path>] ...                 # repeatable
  [--raw <text>]      ...                 # repeatable
                                          # at least one of --file or --raw

trellis channel context delete <name>
  [--as <agent>]                          # default: main
  [--scope project|global]
  [--thread <key>]
  [--file <abs-path>] ...
  [--raw <text>]      ...

trellis channel context list <name>
  [--scope project|global]
  [--thread <key>]
  [--raw]                                 # one JSON entry per line
```

Behavior:
- `add` / `delete` append a `context` event and print the event JSON.
- `list` projects current context entries; pretty output is
  `file <path>` / `raw <truncated text>` lines, `(no context)` when empty.

### `title set <name>` / `title clear <name>`

```bash
trellis channel title set <name>
  --title <text>                          # REQUIRED
  [--as <agent>]                          # default: main
  [--scope project|global]

trellis channel title clear <name>
  [--as <agent>]                          # default: main
  [--scope project|global]
```

Behavior:
- Appends a `title` event projecting a stable display title onto the
  channel. Output: event JSON.

---

## Hidden / Internal

| Command | Purpose |
|---|---|
| `channel __supervisor <channel> <worker> <config>` | Forked entry point invoked by `spawn`. Do not invoke directly. |
| `channel __parse-trace <adapter> <file>` | Dev helper — replays a recorded stream-json / wire trace through the matching adapter and prints the resulting channel events. Adapter is validated against the provider registry. |

---

## Event Model

`CHANNEL_EVENT_KINDS` (whitelist enforced by `parseChannelKind`):

`create`, `join`, `leave`, `message`, `thread`, `context`, `channel`,
`spawned`, `killed`, `respawned`, `progress`, `done`, `error`, `waiting`,
`awake`, `undeliverable`, `interrupt_requested`, `turn_started`,
`turn_finished`, `interrupted`, `supervisor_warning`.

`MEANINGFUL_EVENT_KINDS` (default-visible subset used by `wait` /
`messages` when no explicit `--kind` is given):

`create`, `join`, `leave`, `message`, `thread`, `context`, `channel`,
`spawned`, `killed`, `respawned`, `done`, `error`.

Non-meaningful kinds (e.g. `progress`, `waiting`, `awake`,
`supervisor_warning`, the `turn_*` / `interrupt*` set) still flow through
the store; opt in via `--kind` or `--include-progress`.

Forum channels are event-sourced; use the CLI reducers
(`forum`, `thread`, `context list`) for state projection.

---

## Output Conventions

- **Mutations** (`send`, `interrupt`, `post`, `context add/delete`,
  `title set/clear`, `thread rename`) print the appended event as one JSON
  line on **stdout**.
- **Streaming reads** (`wait`, `messages --follow`) print one JSON event
  per line on stdout.
- **Pretty reads** (`list`, `messages`, `forum`, `thread`, `context list`)
  print colored, padded tables / timelines.
- **`run`** prints only the final assistant text on stdout (so callers can
  pipe); diagnostic notes go to stderr.
- **Errors** go through `chalk.red("Error:")` to stderr and `exit 1`.
- **`wait` timeout** specifically exits **124**.

