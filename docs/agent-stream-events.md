# Agent Stream Progress Events

This document records the progress-event contract used by:

- `POST /api/v1/agent/chat/stream`
- Web Ask Stock chat progress rendering
- single-agent `run_agent_loop`
- multi-agent `AgentOrchestrator`

The endpoint still streams Server-Sent Events (`text/event-stream`) where each
SSE payload is a JSON object with a top-level `type` field.

## Compatibility Boundary

The event changes are additive. Existing clients can keep consuming the legacy
top-level fields:

- `type`
- `step`
- `tool`
- `display_name`
- `success`
- `duration`
- `message`
- `content`

New clients may additionally read:

- `stage`
- `status`
- `elapsed`
- `timeout`
- `remaining`
- `minimum`
- `reason`
- `meta`

Unknown event types should be ignored or displayed with a generic fallback.
`done` and `error` keep their existing completion semantics.

## Event Types

| Type | Producer | Meaning | Important Fields |
| --- | --- | --- | --- |
| `accepted` | SSE endpoint | Context preparation and the user-turn/state transaction succeeded; execution has not started yet. | `backend`, `request_id`, `session_id`, `active_stock_context`, `session_state_version`, `session_generation`, `session_state` |
| `stage_start` | single-agent loop, multi-agent orchestrator | An agent or pipeline stage has started. | `stage`, `message` |
| `stage_done` | single-agent loop, multi-agent orchestrator | An agent or pipeline stage has completed. | `stage`, `status`, `duration` |
| `thinking` | single-agent loop | The agent is deciding the next action. | `step`, `message` |
| `tool_start` | single-agent loop | A tool call has started. | `step`, `tool`, `display_name` |
| `tool_done` | single-agent loop | A tool call has completed or failed. | `step`, `tool`, `success`, `duration`, `display_name` |
| `generating` | single-agent loop | The final response is being generated. | `step`, `message` |
| `pipeline_timeout` | multi-agent orchestrator | The orchestrator stopped because the stage or pipeline budget expired. | `stage`, `elapsed`, `timeout` |
| `pipeline_budget_skipped` | multi-agent orchestrator | The orchestrator stopped before starting the next stage because the remaining budget was too low for useful work. | `stage`, `elapsed`, `timeout`, `remaining`, `minimum`, `reason`, `message` |
| `done` | SSE endpoint | The request completed. | `success`, `content`, `error`, `total_steps`, `session_id` |
| `error` | SSE endpoint | The request failed before normal completion, including preparation rejection before `accepted`. | `message`, `error_code`, `request_id`, `session_id` |

## Acceptance And Session State

The endpoint checks the existing access and backend capability boundaries first.
It prepares analysis context outside the acceptance write transaction, then
commits the user message, explicit Skill selection and main discussion object
together. Only a successful commit emits `accepted`. Analysis progress and
`done` must not precede it; a terminal preparation `error` is allowed before it.

`accepted`, `GET /api/v1/agent/chat/sessions/{session_id}`, and the supported
non-stream `POST /api/v1/agent/chat` response share these state fields:

```json
{
  "active_stock_context": {
    "stock_code": "sh000001",
    "stock_name": "上证指数",
    "canonical_id": "sh000001",
    "asset_type": "index"
  },
  "session_state_version": 3,
  "session_generation": "opaque-server-assigned-instance",
  "session_state": {"selected_skill_ids": []}
}
```

- `active_stock_context` may be `null`; `stock_name` may be `null`. Preserve
  `canonical_id` and `asset_type`, not just a bare numerical code. A comparison
  can permit several tool targets while leaving the main object unchanged or null.
- `session_generation` identifies a session instance, not authorization. It
  changes when a deleted session ID is recreated. A client that knows it may
  send it with its next Chat request; a stale instance is rejected.
- Versions increase on accepted turns and are comparable only within one
  generation. Detail version 0 is a conservative legacy-history view, not a
  newly accepted turn. A genuinely empty detail can have a null generation.
- `session_state.selected_skill_ids` is the saved user selection: null means
  unspecified, `[]` selects the built-in default, and a nonempty list selects
  named Skills. Configured effective defaults are not written as user choices.
- Confirmation provenance and provider traces stay private. Non-stream state
  comes from that turn's acceptance snapshot, not a later detail read.
- Clients must reject partially missing or malformed state fields. All three
  object/version/generation fields absent indicates an old API, not version 0.

Detail reads do not repair or increment business state. If old-code writes
make an accepted object's provenance unreliable, detail may return null with
the same generation and version as an earlier accepted object. A valid current
detail takes precedence over a delayed accepted response at the same version.
Response ownership, local instance binding and generation must be checked
before comparing versions; a stale detail cannot replace a newer bound instance.

Preparation/commit conflicts emit `error_code=session_state_conflict` without
`accepted`, `done`, tool progress, or partial message/Skill/stock updates.
The non-stream API returns HTTP 409 with an `error`/`message` JSON payload.
Clients should preserve the draft and request an explicit refresh/retry, not
automatically resend. A fixed clarification is a normal accepted user turn
followed by `done` (`total_steps=0`), without analysis preparation or a model call.

Failure, timeout, stop or disconnect after commit does not undo accepted state.
Terminal writes verify the accepted session/message instance; a late reply cannot
recreate a deleted session or contaminate a same-named new one. This contract
does not enable unsupported Codex non-stream/multi combinations or change Gate 0B.

## Web Behavior

The Web chat UI now recognizes `stage_start`, `stage_done`,
`pipeline_timeout`, and `pipeline_budget_skipped` in addition to the existing
thinking/tool/generating events.
If a future backend event is not recognized, the UI keeps the event in the
message progress history and renders a generic fallback instead of an empty
progress row.

## Runtime And Provider Scope

This event contract does not change model routing or runtime configuration.
It does not modify:

- provider selection
- model names
- Base URL handling
- LiteLLM route resolution
- API keys or credential loading
- configuration cleanup or migration semantics

Provider/model/Base URL behavior remains governed by the existing LLM
configuration docs and runtime code. Any provider/model strings used in tests
are mock identifiers only.

## Validation

Recommended checks for changes to this contract:

```bash
python -m pytest tests/test_agent_stream_events.py tests/test_agent_sse_cleanup.py tests/test_agent_chat_api.py tests/test_agent_active_stock_integration.py
```

```bash
cd apps/dsa-web
npm test -- src/stores/__tests__/agentChatStore.test.ts src/pages/__tests__/ChatPage.test.tsx
```

The focused tests should confirm that:

- event helper output preserves legacy fields and drops unset fields
- stage metadata is preserved
- `run_agent_loop` emits paired `stage_start` / `stage_done` events plus
  `thinking` and `generating`
- orchestrator timeout events remain separate from budget-skip events
- SSE cleanup behavior remains unchanged
- Web chat state and Chat page rendering still pass

## Rollback

To roll back this event-contract change, revert the commit that introduced:

- `src/agent/stream_events.py`
- the event-helper wiring in `src/agent/runner.py`
- the stage-event wiring in `src/agent/orchestrator.py`
- the Web `ProgressStep` and Chat page rendering updates

Because the change is additive and keeps `done` / `error` semantics unchanged,
existing clients can also ignore the new stage events without a migration step.

For the session-state extension, stop the new backend before rolling back the
matching backend/Web code. Keep the added nullable columns and database-level
version default; do not drop columns or rebuild the database. Do not run old and
new writing backends concurrently. Old-code user writes during rollback require
reconfirmation after re-upgrade; preserved messages and Skill choices remain
available. Platform upgrade acceptance is separate from this wire contract.
