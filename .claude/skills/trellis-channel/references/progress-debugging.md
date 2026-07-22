# Progress And Debugging

Pretty output is for operators. Raw output is the audit log. Subcommands
(`forum`, `thread`, `messages`, `context`) are the audit *interface* — reach
for them before grepping `events.jsonl` by hand.

## Pretty vs `--raw`

`trellis channel messages <channel>` renders a compact, human-readable view:
timestamps, identities, kind, and a short body. It is meant for operators
scanning a channel, not for diagnostics.

Pretty output can and will truncate:

- long progress deltas (`text_delta`, partial tool args)
- tool names and command lines
- multi-line status fields and structured `detail` blobs
- forum thread titles past the column budget

When something looks "off" — a worker appears stuck, a progress line ends
mid-word, an action field shows `...` — switch to `--raw`. Raw mode emits
one JSON event per line exactly as it lives in `events.jsonl`, so nothing
is dropped.

```bash
# Pretty (operator view)
trellis channel messages <channel> --kind done --last 10
trellis channel messages <channel> --kind error --last 10

# Raw (diagnostic view) — one JSON per line
trellis channel messages <channel> --raw --kind progress --last 20
trellis channel messages <channel> --raw --last 50
```

Rule of thumb: never diagnose a worker from a truncated progress line.

### Rebuild Streaming Text

To reconstruct what a model actually streamed during a turn, concatenate
`detail.text_delta` from progress events:

```bash
trellis channel messages <channel> --raw --kind progress --last 80 \
  | python -c 'import json,sys; [print((json.loads(l).get("detail") or {}).get("text_delta",""), end="") for l in sys.stdin if l.strip()]'
```

## Stalled Worker Diagnosis

Symptom: `trellis channel list` shows the worker as running, but no new
events appear in `messages` and `wait` keeps timing out.

Triage order:

1. **Locate the channel files.** Use `list --all --all-projects` if you are
   not sure which bucket the channel lives in.

   ```bash
   trellis channel list --all --all-projects
   CHAN=~/.trellis/channels/<bucket>/<channel>
   ```

2. **Confirm the supervisor and worker PIDs are alive.**

   ```bash
   cat "$CHAN/<worker>.pid"            # supervisor PID
   cat "$CHAN/<worker>.worker-pid"     # actual CLI subprocess PID
   ps -p "$(cat "$CHAN/<worker>.pid")"
   ps -p "$(cat "$CHAN/<worker>.worker-pid")"
   ```

   If the supervisor PID is gone but the channel still lists the worker,
   you have a ghost entry — clean it with
   `trellis channel kill <name> --as <worker> --force`.

3. **Tail the worker log.** This is the canonical place to see provider /
   MCP / tool startup output that never makes it onto the channel.

   ```bash
   tail -f "$CHAN/<worker>.log"
   ```

4. **Check the last raw events.** A worker that emitted `progress` but no
   `message`/`done` is usually mid-stream or blocked on a tool call:

   ```bash
   trellis channel messages <channel> --raw --last 50
   ```

Common "alive but silent" causes:

- Provider cold start before the first token (long, but eventually moves).
- A blocking MCP server during startup — visible in the worker log.
- Worker is waiting for a tool result whose subprocess hung.
- Prompt is huge / model is rate-limited; check provider-side errors in the
  worker log.

## Progress Event Interpretation

A `progress` event represents an in-flight piece of work. Its shape varies
by `action` field, but the load-bearing fields are always under `detail`:

- `detail.text_delta` — incremental model output (concatenate across events
  to rebuild the streamed reply).
- `detail.tool_name`, `detail.tool_input` — tool call about to run or
  currently running.
- `detail.status` — short string used by long-running actions
  (`starting`, `running`, `flushing`, `done`).
- `detail.action` — semantic label (e.g. `status` for thread heartbeats).

Progress events are **noisy** by design. `wait` ignores them unless you
pass `--include-progress`. When you do want to see them, prefer:

```bash
trellis channel messages <channel> --raw --kind progress --last 80
```

A stream that emits progress at a steady cadence but never closes with
`done`/`error`/`message` is the classic shape of a hung tool call —
inspect the worker log for the subprocess.

## Wait Semantics (Quick Reference)

`channel wait` watches `events.jsonl` from EOF and wakes on:

- `message`
- `done`
- `error`
- `killed`
- `progress` only with `--include-progress`

Useful filters:

```bash
trellis channel wait T --as main --from check --kind done --timeout 15m
trellis channel wait T --as main --from check,check-cx --kind done --all --timeout 15m
trellis channel wait T --as worker --tag interrupt --timeout 1h
trellis channel wait T --as main --thread release-note --action status --timeout 10m
```

Exit codes: `0` matched, `124` timeout, `1`/`2` errors. On `wait --all`
timeout, stderr names the workers still missing.

## Auditing `events.jsonl` — Use Subcommands, Not `grep`

Every channel persists its full history at `$CHAN/events.jsonl`. It is
tempting to `tail` / `grep` / `jq` this file directly during debugging.
Don't make it a habit, and **never** do it for forum channels.

Why subcommands first:

- `messages` already replays the file with filters (`--kind`, `--from`,
  `--last`, `--tag`, `--thread`, `--action`) and gives you `--raw` for the
  exact JSON. Anything you would write a one-liner for, `messages` already
  does.
- `wait` consumes the same file with EOF semantics — re-implementing that
  with `tail -f | jq` will drop events under load and misorder them under
  rotation.
- `context` materializes a worker's inbox view, including cursor state.
  Hand-rolled filters do not respect `<worker>.inbox-cursor`.

### Forum channels: never parse `events.jsonl` directly

Forum channels multiplex many logical threads onto a single `events.jsonl`.
Each event carries `thread`, `action`, and tag fields that the forum
subcommands know how to fold together. Parsing the file by hand will:

- Mix threads together and make a thread look incoherent.
- Miss thread lifecycle events (open / status / close) that change how
  later events should be interpreted.
- Ignore worker inbox cursors, so you will "see" events a worker has
  already consumed and assume they are pending.

Use the forum-aware views instead:

```bash
# List logical threads inside the forum channel
trellis channel forum list <channel>

# Inspect one thread end-to-end
trellis channel thread show <channel> <thread>

# Replay messages for a thread (supports --raw, --kind, --last)
trellis channel messages <channel> --thread <thread> --raw --last 100

# What a specific worker still has pending
trellis channel context <channel> --as <worker>
```

Direct reads of `events.jsonl` are reserved for the case where the CLI
itself is suspect — e.g. confirming an event was actually persisted, or
diffing against `<worker>.inbox-cursor` while debugging the supervisor.

## Common Failures

| Symptom | Cause | Fix |
|---|---|---|
| `trellis: command not found` | CLI not installed globally | `npm install -g @mindfoldhq/trellis` |
| `wait` exits immediately | wrong filter or identity collision | use distinct `--as`, inspect raw messages |
| zsh errors on message text | shell interpreted punctuation | use `--stdin` or `--text-file` |
| progress line is cut off | pretty output truncation | use `messages --raw --kind progress` |
| worker never speaks | provider startup / prompt / MCP delay | inspect `<worker>.log`, `ps`, raw events |
| channel not found in another cwd | project bucket mismatch | `cd` to project, use `--scope global`, or `list --all-projects` |
| ghost worker in list | supervisor died without cleanup | `trellis channel kill <name> --as <worker> --force` |
| forum thread looks scrambled | parsed `events.jsonl` directly | use `forum`, `thread`, `messages --thread` |

## Storage Layout

```text
~/.trellis/channels/
└── <bucket>/
    └── <channel-name>/
        ├── events.jsonl
        ├── <channel>.lock
        ├── <worker>.log
        ├── <worker>.pid
        ├── <worker>.worker-pid
        ├── <worker>.config
        ├── <worker>.session-id
        ├── <worker>.thread-id
        ├── <worker>.inbox-cursor
        └── <worker>.spawnlock
```

Agents normally use the CLI, not direct file reads. Direct file reads are
for debugging when CLI views are insufficient — and even then, never on a
forum channel's `events.jsonl`.
