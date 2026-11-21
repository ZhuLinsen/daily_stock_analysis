"""The ordered public conversation inputs confirmed for one ChatGPT turn."""
from __future__ import annotations

import hashlib
import json

HISTORY_LIMIT = 20
VISIBLE_ROLES = ("user", "assistant")


def make_preview(snapshot, connection_id, stock):
    messages = [
        {"message_id": str(row["id"]), "role": row["role"], "content": row["content"]}
        for row in snapshot["messages"] if row["role"] in VISIBLE_ROLES and row["content"]
    ][-HISTORY_LIMIT:]
    manifest = [1, snapshot["session_id"], snapshot["session_generation"], connection_id, stock, messages]
    encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"snapshot_id": hashlib.sha256(encoded).hexdigest(), "connection_id": connection_id,
            "stock": stock, "messages": messages}
