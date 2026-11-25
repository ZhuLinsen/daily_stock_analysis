"""Credential-free registration metadata and session retirement projections."""
from __future__ import annotations


def registration_label(registration):
    return f"{registration['label']} ({registration['client_id']})"


def revocation(data, client_id):
    registration = data.get("registrations", {}).get(client_id)
    return {
        "owner": client_id if registration else None,
        "label": registration_label(registration) if registration else None,
    }


def grant_revocation(data, operation, verified_registration=None):
    owner = operation["client_id"] if operation["kind"] == "refresh" else (verified_registration or operation.get("verified_registration"))
    return revocation(data, owner)


def summarize(data, record):
    unknown = dict(data.get("unknown", {}))
    unknown[record["owner"] or ""] = record
    return {**data, "unknown": unknown}


def recover(stored, issuer):
    """Return the post-restart state. A pending remote result cannot be replayed."""
    data = stored
    if stored and "revision" not in stored:
        legacy = dict(stored.get("other_registrations", {}))
        current = stored.get("registration") or {}
        current_id = current.get("client_id")
        if current_id:
            legacy[current_id] = current
        registrations = {}
        for client_id, entry in legacy.items():
            if not entry.get("sub") or entry.get("client_id") != client_id or entry.get("issuer", issuer) != issuer:
                continue
            needs_scope = entry.get("needs_consent") or (
                client_id == current_id and stored.get("authorization_error") == "chatgpt_plan_permission_required"
            )
            registrations[client_id] = {
                "client_id": client_id, "issuer": issuer,
                "sub": entry["sub"], "label": entry.get("label") or "ChatGPT",
                "reauth_reason": "scope_required" if needs_scope else "legacy_import",
            }
        data = {"host_id": stored.get("host_id"), "registrations": registrations,
                "current_registration": current_id if current_id in registrations else None}
        last = stored.get("last_session_end") or {}
        if last.get("result") == "unconfirmed":
            data = summarize(data, revocation(data, last.get("registration_id")))
        if stored.get("connection"):
            data = summarize(data, revocation(data, current_id))
    operation = data.get("grant_pending")
    if operation:
        data = summarize(data, grant_revocation(data, operation))
        data = {**data, "grant_pending": None}
        if operation["kind"] == "refresh":
            data = retired(data, "credential_invalid")
    for record in data.get("revocations", {}).values():
        data = summarize(data, record)
    if data.get("revocations"):
        data = {**data, "revocations": {}}
    return data


def retired(data, reason):
    registrations = dict(data.get("registrations", {}))
    key = data.get("current_registration")
    if key in registrations and reason:
        registrations[key] = {**registrations[key], "reauth_reason": reason}
    return {**data, "connection": None, "identity": None, "registrations": registrations, "grant_pending": None}


def public_revocations(data):
    def row(record, operation_id):
        return {"owner_kind": "registered" if record["owner"] else "unverified",
                "label": record["label"], "state": "pending" if operation_id else "unknown",
                "operation_id": operation_id}

    return [row(record, key) for key, record in data.get("revocations", {}).items()] + [
        row(record, None) for record in data.get("unknown", {}).values()
    ]
