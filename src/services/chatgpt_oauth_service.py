"""One user-owned Sign in with ChatGPT connection for the local DSA server."""
from __future__ import annotations

import asyncio
import base64
import hashlib
from concurrent.futures import Future, TimeoutError as FutureTimeout
from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile
from threading import Event, RLock, Thread
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

import httpx
import jwt

from src.services import chatgpt_session_state as state
from src.auth import is_auth_enabled
from src.llm.model_source import ChatGPTModelSource

ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
TOKEN = ISSUER + "/api/accounts/oauth/token"
METADATA = ISSUER + "/.well-known/openid-configuration"
DYNAMIC_CLIENT = "dynamic_agent_client"
CALLBACK_PATH = "/auth/callback"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
REQUIRED_SCOPES = {"resource.invoke", "chatgpt.tokens.use.direct", "offline_access"}
APP_NAME = "Daily Stock Analysis"
PLAN_PERMISSION_REQUIRED = "chatgpt_plan_permission_required"
USAGE_LIMIT_PAUSED = "chatgpt_usage_limit_paused"
UPSTREAM_USAGE_LIMIT = "subscription_sharing_usage_limit_exceeded"
USAGE_LIMIT_MESSAGE = "Check ChatGPT usage in Settings before continuing"
UsageOwner = tuple[str, str, str]
DISCONNECT_TIMEOUT = 20
DISCONNECT_LOCK_TIMEOUT = 2
logger = logging.getLogger(__name__)


def _safe_identifier(value):
    if isinstance(value, str) and re.fullmatch(r"[\w.\[\]-]{1,120}", value, flags=re.ASCII):
        return value
    return None


def _record_digest(data):
    # Match either side of an atomic write without retaining a second credential set.
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).digest()


class ChatGPTError(Exception):
    """Safe error information shared by the OAuth and inference paths."""

    def __init__(self, code, message, *, status=None, upstream_code=None, param=None, request_id=None, request_may_have_arrived=False):
        self.request_may_have_arrived = request_may_have_arrived
        self.usage = None
        self.code = code
        self.status = status
        self.upstream_code = _safe_identifier(upstream_code)
        self.param = _safe_identifier(param)
        self.request_id = _safe_identifier(request_id)
        details = [code, message]
        if status:
            details.append(f"HTTP {status}")
        details.extend(value for value in (self.upstream_code, self.param, self.request_id) if value)
        super().__init__(" · ".join(details))

    @classmethod
    def upstream(cls, code, message, body, *, status=None, request_id=None, classify_usage_limit=False):
        body = body if isinstance(body, dict) else {}
        error = body.get("error", body)
        if classify_usage_limit and isinstance(error, dict) and error.get("code") == UPSTREAM_USAGE_LIMIT:
            code, message = USAGE_LIMIT_PAUSED, USAGE_LIMIT_MESSAGE
        return cls(
            code, message, status=status, request_id=request_id,
            upstream_code=(error.get("code") or error.get("reason")) if isinstance(error, dict) else error,
            param=error.get("param") if isinstance(error, dict) else None,
        )


class ChatGPTOAuthService:
    def __init__(self, directory: Path, loop: asyncio.AbstractEventLoop | None = None):
        import fcntl

        self.directory = directory
        self.lock = RLock()
        self.pending = None
        self.retry_target = None
        self.disconnect_retry_id = None
        self._unconfirmed_digest = None
        self._unconfirmed_usage_only = False
        self._unconfirmed_resume: tuple[UsageOwner, str] | None = None
        self._pending_usage_pauses: dict[UsageOwner, str] = {}
        self.revoking: dict[str, Future] = {}
        self.loop = loop
        self.error = None
        self.models_cache = None
        self.catalog_sequence = 0
        self.published_sequence = 0
        self.closed = False
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.getuid():
            raise PermissionError("ChatGPT credential directory must be owner-only")
        fd = os.open(directory / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        self.directory_lock = os.fdopen(fd, "r+")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.data = self._load()
            self._stored_digest = _record_digest(self.data)
            recovered = state.recover(self.data, ISSUER)
            if recovered is not self.data:
                try:
                    self._commit_retirement(recovered)
                except OSError:
                    logger.warning("ChatGPT recovery is using the in-memory retirement state")
        except BaseException:
            self.directory_lock.close()
            raise
        self.http = httpx.Client(timeout=15, trust_env=False, follow_redirects=False)

    def _load(self):
        try:
            fd = os.open(self.directory / "connection.json", os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return {}
        with os.fdopen(fd) as stream:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid():
                raise PermissionError("ChatGPT credential record must be owner-only")
            data = json.load(stream)
        return data

    def _save(self, data, *, usage_only=False, resume_owner=None):
        if self._unconfirmed_digest is not None:
            raise OSError("ChatGPT credential write has not been reconciled")
        revision = self.data.get("revision", 0)
        if data.get("revision", 0) != revision:
            raise ChatGPTError("chatgpt_target_changed", "ChatGPT session state changed")
        if self._pending_usage_pauses:
            registrations = dict(data.get("registrations", {}))
            for owner, pause_id in self._pending_usage_pauses.items():
                registration = self._usage_registration(registrations, owner)
                if owner != resume_owner and registration is not None:
                    registrations[owner[1]] = {**registration, "usage_pause_id": pause_id}
            data = {**data, "registrations": registrations}
        data = {**data, "revision": revision + 1}
        if self.directory_lock.closed:
            raise ChatGPTError("chatgpt_unavailable", "ChatGPT session storage is closed")
        digest = _record_digest(data)
        try:
            self._replace_file(data)
        except OSError:
            # Under the directory lock these are the only two attributable file images.
            self._unconfirmed_digest = digest
            self._unconfirmed_usage_only = usage_only
            try:
                observed_digest = _record_digest(self._load())
            except (OSError, ValueError) as exc:
                raise OSError("Cannot verify the ChatGPT credential write") from exc
            if observed_digest != digest:
                if observed_digest == self._stored_digest:
                    self._unconfirmed_digest = None
                    self._unconfirmed_usage_only = False
                raise
            self._unconfirmed_digest = None
            self._unconfirmed_usage_only = False
        self.data = data
        self._stored_digest = digest
        self._pending_usage_pauses.clear()

    def _reconcile_write(self):
        # Let callbacks finish projecting their outcomes before recovering orphaned operations.
        if (self.pending and self.pending.get("exchanging")) or self.data.get("revocations"):
            return False
        observed = self._load()
        digest = _record_digest(observed)
        if digest == self._unconfirmed_digest:
            current = observed
            if self._unconfirmed_resume is not None:
                owner, pause_id = self._unconfirmed_resume
                if self._pending_usage_pauses.get(owner) == pause_id:
                    del self._pending_usage_pauses[owner]
        elif digest == self._stored_digest:
            current = self.data
        else:
            return False
        for owner, pause_id in list(self._pending_usage_pauses.items()):
            registration = self._usage_registration(observed.get("registrations", {}), owner)
            if registration is not None and registration.get("usage_pause_id") == pause_id:
                del self._pending_usage_pauses[owner]
        self._unconfirmed_digest = None
        self._unconfirmed_usage_only = False
        self._unconfirmed_resume = None
        self.data = observed
        self._stored_digest = digest
        recovered = state.recover(current, ISSUER)
        if (recovered.get("connection") or {}).get("id") != self.disconnect_retry_id:
            self.disconnect_retry_id = None
        self.models_cache = None
        if recovered != observed:
            self._commit_retirement(recovered)
        if self.error == "chatgpt_store_unavailable" and not self.disconnect_retry_id:
            self.error = None
        return True

    def _replace_file(self, data):
        with tempfile.NamedTemporaryFile(mode="w", dir=self.directory, delete=False) as stream:
            path = Path(stream.name)
            try:
                json.dump(data, stream)
                stream.flush()
                os.fsync(stream.fileno())
                path.replace(self.directory / "connection.json")
            finally:
                path.unlink(missing_ok=True)

    def _commit_retirement(self, data):
        try:
            self._save(data)
        except OSError:
            # Keep the conservative projection until a subsequent durable write.
            self.data = data
            self.error = "chatgpt_store_unavailable"
            raise

    def _enabled(self, *, dispatched=False):
        if self._unconfirmed_digest is not None and not (dispatched and self._unconfirmed_usage_only):
            raise ChatGPTError("chatgpt_store_unavailable", "Check ChatGPT credential storage and refresh status", status=503)
        if self.closed or not is_auth_enabled():
            raise ChatGPTError("chatgpt_unavailable", "ChatGPT requires the local server and administrator authentication")

    def close(self):
        with self.lock:
            self.closed = True
            self.retry_target = None
            attempt = self.pending
            if attempt:
                attempt["cancelled"] = True
        if attempt:
            attempt["thread"].join()
        with self.lock:
            self.http.close()
            self.directory_lock.close()

    def status(self):
        with self.lock:
            if self._unconfirmed_digest is not None:
                try:
                    reconciled = self._reconcile_write()
                except (OSError, ValueError):
                    reconciled = False
            else:
                reconciled = True
            if reconciled and self._pending_usage_pauses:
                try:
                    self._save(self.data, usage_only=True)
                except OSError:
                    reconciled = self._unconfirmed_digest is None
            if not reconciled:
                return {
                    "available": False, "connected": False, "connection_id": None,
                    "error": "chatgpt_store_unavailable", "actions": [],
                    "revocations": state.public_revocations(self.data),
                }
            connection = self._active_connection() or {}
            identity = self.data.get("identity") or {}
            attempt_id = self.pending["id"] if self.pending else None
            if attempt_id == identity.get("id"):
                attempt_id = None
            registrations = self._registrations()
            key = self.data.get("current_registration")
            registration = registrations.get(key, {})
            reason = registration.get("reauth_reason")
            actions = []

            def action(kind, target, label=None):
                actions.append({"kind": kind, "target": target, "label": label})

            if self.disconnect_retry_id:
                action("retry_disconnect", {"connection_id": self.disconnect_retry_id})
            elif self.pending:
                if attempt_id and not self.pending.get("cancelled"):
                    action("cancel", {"attempt_id": attempt_id})
            elif connection:
                action("disconnect", {"connection_id": connection["id"]})
            else:
                if self.retry_target:
                    action("continue", {"retry_id": self.retry_target["id"]})
                for entry in registrations.values():
                    kind = "grant_plan" if entry["client_id"] == identity.get("client_id") else "reauth"
                    action(kind, {"registration_id": entry["client_id"]}, state.registration_label(entry))
                if identity:
                    action("sign_out", {"identity_id": identity["id"]})
                action("new", {"mode": "new"})
            return {
                "available": True, "connected": bool(connection), "plan_authorized": bool(connection),
                "connection_id": connection.get("id"), "disconnect_retry_connection_id": self.disconnect_retry_id,
                "usage_pause_id": self._usage_pause_id(self._usage_owner()) if connection else None,
                "account_label": state.registration_label(registration) if registration else None,
                "reauth_reason": reason, "revocations": state.public_revocations(self.data), "actions": actions,
                "retry_id": self.retry_target["id"] if self.retry_target else None,
                "pending": self.pending is not None,
                "attempt_id": attempt_id,
                "cancelling": bool(self.pending and self.pending.get("cancelled")),
                "error": self.error or (PLAN_PERMISSION_REQUIRED if reason == "scope_required" else None),
            }

    def _request(self, method, url, **kwargs):
        try:
            response = self.http.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise ChatGPTError(
                "chatgpt_network_error", "Could not reach OpenAI",
                request_may_have_arrived=not isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)),
            ) from None
        return self._checked_response(response)

    @staticmethod
    def _checked_response(response):
        if not response.is_success:
            try:
                body = response.json()
            except ValueError:
                body = {}
            raise ChatGPTError.upstream(
                "chatgpt_http_error", "OpenAI rejected the request", body,
                status=response.status_code, request_id=response.headers.get("x-request-id"),
            )
        return response

    def _json(self, method, url, **kwargs):
        return self._json_body(self._request(method, url, **kwargs))

    @staticmethod
    def _json_body(response):
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise ChatGPTError("chatgpt_protocol_error", "OpenAI returned an invalid JSON object", status=response.status_code)
        return body

    @staticmethod
    def _metadata_endpoint(metadata, field):
        if metadata.get("issuer") != ISSUER:
            raise ChatGPTError("chatgpt_protocol_error", "Unexpected OpenAI issuer")
        endpoint = metadata.get(field)
        if not isinstance(endpoint, str) or not endpoint.startswith(ISSUER + "/"):
            raise ChatGPTError("chatgpt_protocol_error", "Unexpected OpenAI metadata endpoint")
        return endpoint

    @staticmethod
    async def _grant_json(method, url, **kwargs):
        async with httpx.AsyncClient(timeout=15, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, url, **kwargs)
            return ChatGPTOAuthService._json_body(ChatGPTOAuthService._checked_response(response))

    def _grant_request(self, attempt, method, url, **kwargs):
        remaining = attempt["deadline"] - time.monotonic()
        try:
            return asyncio.run_coroutine_threadsafe(
                asyncio.wait_for(self._grant_json(method, url, **kwargs), remaining), attempt["loop"],
            ).result()
        except (httpx.HTTPError, asyncio.TimeoutError):
            raise ChatGPTError("chatgpt_network_error", "Could not reach OpenAI") from None

    def _identity(self, attempt, encoded, client_id, nonce):
        jwks = self._metadata_endpoint(self._grant_request(attempt, "GET", METADATA), "jwks_uri")
        keys = self._grant_request(attempt, "GET", jwks).get("keys", [])
        try:
            header = jwt.get_unverified_header(encoded)
            key, = [candidate for candidate in keys if candidate.get("kid") == header.get("kid")]
            claims = jwt.decode(
                encoded, jwt.PyJWK.from_dict(key).key, algorithms=["RS256"],
                issuer=ISSUER, audience=client_id, leeway=5,
                options={"require": ["iss", "aud", "exp", "iat", "sub", "nonce"]},
            )
        except (ValueError, TypeError, jwt.PyJWTError):
            raise ChatGPTError("chatgpt_invalid_identity", "OpenAI identity could not be verified") from None
        if claims["nonce"] != nonce or claims.get("azp", client_id) != client_id or not claims["sub"]:
            raise ChatGPTError("chatgpt_invalid_identity", "OpenAI identity does not match this attempt")
        return claims

    @staticmethod
    def _valid_refresh(value):
        return isinstance(value, str) and bool(value)

    @staticmethod
    def _token_fields(body):
        if (
            str(body.get("token_type", "")).lower() != "bearer"
            or not isinstance(body.get("access_token"), str) or not body["access_token"]
            or not isinstance(body.get("expires_in"), int) or body["expires_in"] <= 0
            or ("refresh_token" in body and not ChatGPTOAuthService._valid_refresh(body["refresh_token"]))
            or not isinstance(body.get("scope"), str)
        ):
            raise ChatGPTError("chatgpt_protocol_error", "OpenAI returned an incomplete token response")
        return {
            "access_token": body["access_token"], "refresh_token": body.get("refresh_token"),
            "expires_at": time.time() + body["expires_in"], "scopes": body["scope"].split(),
        }

    def _registrations(self):
        return self.data.get("registrations", {})

    def _check_revoking(self, client_id):
        task = self.revoking.get(client_id)
        if task is not None and not task.done():
            raise ChatGPTError("chatgpt_connection_busy", "ChatGPT authorization is still being revoked")

    def connect(self, loop, *, registration_id=None, retry_id=None, mode=None):
        with self.lock:
            self._enabled()
            if self.disconnect_retry_id:
                raise ChatGPTError("chatgpt_connection_busy", "Retry disconnecting the current ChatGPT connection first")
            retry = self.retry_target if retry_id else None
            if retry_id and (not retry or retry["id"] != retry_id):
                raise ChatGPTError("chatgpt_target_changed", "Refresh the ChatGPT authorization status")
            if self._active_connection() or self.pending:
                raise ChatGPTError("chatgpt_connection_busy", "Disconnect or cancel the current connection first")
            registration = self._registrations().get(registration_id)
            if registration_id and registration is None:
                raise ChatGPTError("chatgpt_target_changed", "Refresh the saved ChatGPT accounts")
            if not (registration_id or retry_id or mode) and self._registrations():
                raise ChatGPTError("chatgpt_target_changed", "Select a registration or explicitly start a new authorization")
            expected_client_id = registration_id or (retry["client_id"] if retry else None)
            self._check_revoking(expected_client_id)
            if not self.data.get("host_id"):
                self._save({**self.data, "host_id": f"urn:uuid:{uuid4()}"})
            attempt = {
                "loop": loop, "id": uuid4().hex, "state": secrets.token_urlsafe(32), "nonce": secrets.token_urlsafe(32),
                "verifier": secrets.token_urlsafe(64), "registration": registration,
                "expected_client_id": expected_client_id,
            }
            service = self

            class Callback(BaseHTTPRequestHandler):
                timeout = 5

                def log_message(self, *_args):
                    pass

                def do_GET(self):
                    parsed = urlsplit(self.path)
                    fields = parse_qs(parsed.query)
                    if parsed.path != CALLBACK_PATH or fields.get("state") != [attempt["state"]]:
                        self.send_error(400, "Invalid authorization callback")
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Referrer-Policy", "no-referrer")
                    self.end_headers()
                    self.wfile.write(b"Return to Daily Stock Analysis to see the authorization result.")
                    listener.server_close()
                    service._complete(attempt, fields)

            listener = HTTPServer(("127.0.0.1", 0), Callback)
            listener.timeout = 0.25
            attempt["listener"] = listener
            attempt["redirect_uri"] = f"http://127.0.0.1:{listener.server_port}{CALLBACK_PATH}"
            query = {
                "client_id": expected_client_id or DYNAMIC_CLIENT,
                "ext_agent_host_id": self.data["host_id"], "redirect_uri": attempt["redirect_uri"],
                "response_type": "code", "scope": SCOPES, "resource": RESOURCE,
                "state": attempt["state"], "nonce": attempt["nonce"],
                "code_challenge": base64.urlsafe_b64encode(
                    hashlib.sha256(attempt["verifier"].encode()).digest()
                ).decode().rstrip("="),
                "code_challenge_method": "S256",
            }
            if not expected_client_id:
                query["agent_name_hint"] = APP_NAME
            elif registration:
                identity = self.data.get("identity") or {}
                if identity.get("client_id") == registration_id:
                    query["id_token_hint"] = identity["id_token"]
                if registration.get("reauth_reason") == "scope_required":
                    query["prompt"] = "consent"
            attempt["thread"] = Thread(target=self._listen, args=(attempt,), daemon=True)
            self.pending = attempt
            try:
                attempt["thread"].start()
            except RuntimeError:
                listener.server_close()
                self.pending = None
                raise
            self.retry_target = None
            self.error = None
            return {
                "attempt_id": attempt["id"],
                "authorization_url": ISSUER + "/api/accounts/authorize?" + urlencode(query),
            }

    def _listen(self, attempt):
        with attempt["listener"] as listener:
            deadline = time.monotonic() + 600
            while self.pending is attempt and not attempt.get("cancelled") and time.monotonic() < deadline:
                listener.handle_request()
            with self.lock:
                if self.pending is attempt:
                    self.pending = None
                    self.error = "chatgpt_authorization_timeout"

    def _complete(self, attempt, fields):
        with self.lock:
            if self.pending is not attempt or attempt.get("cancelled"):
                return
            attempt["exchanging"] = True
            attempt["deadline"] = time.monotonic() + 45
        unused_refresh = None
        client_id = None
        exchange_started = False
        exchange_rejected = False
        exchange_returned = False
        verified_registration = None
        retry_client_id = None
        try:
            if "error" in fields:
                raise ChatGPTError("chatgpt_consent_declined", "ChatGPT authorization was declined")
            registration = attempt["registration"]
            existing_id = attempt["expected_client_id"]
            client_id, = fields.get("client_id", [existing_id])
            code, = fields.get("code", [None])
            if not code or not client_id or client_id == DYNAMIC_CLIENT or (existing_id and client_id != existing_id):
                raise ChatGPTError("chatgpt_invalid_callback", "OpenAI callback did not match the selected registration")
            with self.lock:
                if attempt.get("cancelled"):
                    return
                self._check_revoking(client_id)
                self._save({**self.data, "grant_pending": {"kind": "exchange", "id": attempt["id"], "client_id": client_id}})
                exchange_started = True
            body = self._grant_request(attempt, "POST", TOKEN, data={
                "grant_type": "authorization_code", "client_id": client_id, "code": code,
                "code_verifier": attempt["verifier"], "redirect_uri": attempt["redirect_uri"], "resource": RESOURCE,
            })
            exchange_returned = True
            if self._valid_refresh(body.get("refresh_token")):
                unused_refresh = body["refresh_token"]
            claims = self._identity(attempt, body.get("id_token"), client_id, attempt["nonce"])
            with self.lock:
                saved = registration or self._registrations().get(client_id)
                if saved:
                    if claims["sub"] != saved["sub"]:
                        raise ChatGPTError("chatgpt_invalid_identity", "OpenAI returned a different account")
                    verified_registration = client_id
                tokens = self._token_fields(body)
                complete = REQUIRED_SCOPES.issubset(tokens["scopes"]) and bool(tokens["refresh_token"])
                if not attempt.get("cancelled"):
                    self._enabled()
                    operation = self.data.get("grant_pending") or {}
                    if operation.get("id") != attempt["id"] or time.monotonic() >= attempt["deadline"]:
                        raise ChatGPTError("chatgpt_target_changed", "Authorization has expired")
                    registrations = dict(self._registrations())
                    latest = self._usage_registration(registrations, (ISSUER, client_id, claims["sub"]))
                    registrations[client_id] = {
                        "client_id": client_id, "issuer": ISSUER, "sub": claims["sub"],
                        "reauth_reason": None if complete else "scope_required",
                        "label": ((saved or {}).get("label") or claims.get("email") or claims.get("name") or "ChatGPT")[:160],
                    }
                    if latest and latest.get("usage_pause_id"):
                        registrations[client_id]["usage_pause_id"] = latest["usage_pause_id"]
                    self._save({
                        **self.data, "registrations": registrations, "current_registration": client_id,
                        "identity": {"id": attempt["id"], "client_id": client_id, "id_token": body["id_token"]},
                        "grant_pending": None if complete else {**operation, "verified_registration": client_id},
                        # Older builds still read generation when refreshing this connection.
                        "connection": {"id": uuid4().hex, "generation": uuid4().hex, **tokens} if complete else None,
                    })
                    if complete:
                        unused_refresh = None
                        self.pending = None
        except (OSError, ValueError, ChatGPTError) as exc:
            exchange_rejected = (
                isinstance(exc, ChatGPTError) and not exchange_returned
                and exc.status is not None and 400 <= exc.status < 500
            )
            with self.lock:
                if self.pending is attempt and not attempt.get("cancelled"):
                    self.error = (exc.code if isinstance(exc, ChatGPTError) else
                                  "chatgpt_store_unavailable" if isinstance(exc, OSError) else "chatgpt_authorization_failed")
                    if (
                        exchange_started and not exchange_returned and not registration
                        and isinstance(exc, ChatGPTError) and exc.upstream_code == "invalid_grant"
                    ):
                        retry_client_id = client_id
        finally:
            with self.lock:
                if self.pending is attempt:
                    try:
                        if exchange_started and not exchange_rejected:
                            self._end_session(
                                attempt["loop"], client_id, unused_refresh, time.monotonic() + DISCONNECT_TIMEOUT,
                                operation_id=attempt["id"], verified_registration=verified_registration,
                            )
                        elif exchange_started:
                            self._commit_retirement({**self.data, "grant_pending": None})
                    except OSError:
                        self.error = "chatgpt_store_unavailable"
                        logger.warning("Could not persist the ChatGPT authorization outcome")
                    finally:
                        if retry_client_id and not attempt.get("cancelled"):
                            self.retry_target = {"id": attempt["id"], "client_id": retry_client_id}
                        self.pending = None

    def _active_connection(self):
        connection = self.data.get("connection")
        if connection and not self.data.get("grant_pending") and connection["id"] != self.disconnect_retry_id:
            return connection
        return None

    def _connection(self, connection_id, *, dispatched=False):
        self._enabled(dispatched=dispatched)
        connection = self._active_connection()
        if not connection or connection["id"] != connection_id:
            raise ChatGPTError("chatgpt_connection_inactive", "Connect ChatGPT and select a model again")
        return connection

    def _bearer(self, connection_id):
        connection = self._connection(connection_id)
        if connection["expires_at"] > time.time() + 45:
            return connection["access_token"]
        client_id = self.data["current_registration"]
        operation = {"id": uuid4().hex, "kind": "refresh", "connection_id": connection_id, "client_id": client_id}
        deadline = time.monotonic() + DISCONNECT_TIMEOUT
        self._save({**self.data, "grant_pending": operation})
        latest = None
        reason = "credential_invalid"
        try:
            body = self._json("POST", TOKEN, data={
                "grant_type": "refresh_token", "resource": RESOURCE, "client_id": client_id,
                "refresh_token": connection["refresh_token"],
            })
        except ChatGPTError as exc:
            if exc.upstream_code in {"invalid_grant", "invalid_refresh_token", "token_expired",
                                     "refresh_token_expired", "refresh_token_invalidated", "refresh_token_reused"}:
                self.models_cache = None
                self._commit_retirement(state.retired(self.data, reason))
                raise ChatGPTError("chatgpt_reauthorization_required", "Sign in to ChatGPT again",
                                   status=exc.status, upstream_code=exc.upstream_code, request_id=exc.request_id) from None
            if exc.request_may_have_arrived or (exc.status and (exc.status >= 500 or 200 <= exc.status < 300)):
                self._end_session(self.loop, client_id, None, deadline, operation_id=operation["id"], reason=reason)
            else:
                self._commit_retirement({**self.data, "grant_pending": None})
            raise

        body.setdefault("scope", " ".join(connection["scopes"]))
        body.setdefault("refresh_token", connection["refresh_token"])
        latest = body["refresh_token"] if self._valid_refresh(body["refresh_token"]) else None
        try:
            tokens = self._token_fields(body)
            if not REQUIRED_SCOPES.issubset(tokens["scopes"]):
                reason = "scope_required"
                raise ChatGPTError(PLAN_PERMISSION_REQUIRED, "ChatGPT authorization no longer grants model use")
            if time.monotonic() >= deadline:
                raise ChatGPTError("chatgpt_network_error", "ChatGPT renewal timed out")
            self._save({**self.data, "grant_pending": None, "connection": {**connection, **tokens}})
        except (ChatGPTError, OSError):
            self._end_session(self.loop, client_id, latest, deadline, operation_id=operation["id"], reason=reason)
            raise
        return tokens["access_token"]

    def models(self, connection_id, *, refresh=False):
        with self.lock:
            self._connection(connection_id)
            if not refresh and self.models_cache and self.models_cache[0] == connection_id:
                return self.models_cache[1]
            bearer = self._bearer(connection_id)
            self.catalog_sequence += 1
            sequence = self.catalog_sequence
        body = self._json("GET", RESOURCE + "/models", headers={"Authorization": "Bearer " + bearer})
        if not isinstance(body.get("models"), list):
            raise ChatGPTError("chatgpt_protocol_error", "OpenAI did not return an account model directory")
        models = tuple(
            {"slug": item["slug"], "display_name": item.get("display_name") or item["slug"]}
            for item in body["models"]
            if isinstance(item, dict) and item.get("visibility") == "list" and isinstance(item.get("slug"), str)
        )
        with self.lock:
            self._connection(connection_id)
            if self.models_cache and sequence < self.published_sequence:
                return self.models_cache[1]
            self.published_sequence = sequence
            self.models_cache = (connection_id, models)
        return models

    def _usage_owner(self) -> UsageOwner:
        client_id = self.data["current_registration"]
        registration = self._registrations()[client_id]
        return registration["issuer"], client_id, registration["sub"]

    @staticmethod
    def _usage_registration(registrations, owner: UsageOwner):
        issuer, client_id, sub = owner
        registration = registrations.get(client_id)
        if registration and (registration.get("issuer"), registration.get("sub")) == (issuer, sub):
            return registration
        return None

    def _usage_pause_id(self, owner: UsageOwner):
        pending = self._pending_usage_pauses.get(owner)
        return pending or self._registrations()[owner[1]].get("usage_pause_id")

    def _pause_usage(self, owner: UsageOwner):
        with self.lock:
            if self.closed or self._usage_registration(self._registrations(), owner) is None:
                return
            pause_id = self._usage_pause_id(owner)
            if self._unconfirmed_resume == (owner, pause_id):
                # A later cap must survive readback of the earlier resume.
                pause_id = None
            if pause_id:
                return
            self._pending_usage_pauses[owner] = uuid4().hex
            try:
                self._save(self.data, usage_only=True)
            except OSError:
                logger.warning("Could not persist the ChatGPT usage pause")

    def resume_usage(self, *, connection_id: str, usage_pause_id: str):
        with self.lock:
            self._enabled()
            connection = self._active_connection()
            if not connection or connection["id"] != connection_id:
                raise ChatGPTError("chatgpt_target_changed", "The ChatGPT connection changed")
            owner = self._usage_owner()
            if self._usage_pause_id(owner) != usage_pause_id:
                raise ChatGPTError("chatgpt_target_changed", "The ChatGPT usage pause changed")
            registrations = dict(self._registrations())
            registration = dict(registrations[owner[1]])
            registration.pop("usage_pause_id", None)
            registrations[owner[1]] = registration
            try:
                self._save({**self.data, "registrations": registrations}, usage_only=True, resume_owner=owner)
            except OSError:
                if self._unconfirmed_digest is not None:
                    self._unconfirmed_resume = (owner, usage_pause_id)
                raise
            return {"resumed": True}

    def ensure_inference_allowed(self, source: ChatGPTModelSource):
        with self.lock:
            self._connection(source.connection_id)
            if self._usage_pause_id(self._usage_owner()):
                raise ChatGPTError(USAGE_LIMIT_PAUSED, USAGE_LIMIT_MESSAGE, status=429)

    def validate(self, source: ChatGPTModelSource):
        self.ensure_inference_allowed(source)
        if not any(item["slug"] == source.model for item in self.models(source.connection_id)):
            raise ChatGPTError("chatgpt_model_unavailable", "The selected model is absent from this ChatGPT connection")

    def ensure_active(self, source):
        with self.lock:
            self._connection(source.connection_id, dispatched=True)

    def start_request(self, source, dispatch):
        self.validate(source)
        with self.lock:
            self.ensure_inference_allowed(source)
            pause_usage = partial(self._pause_usage, self._usage_owner())
            return dispatch(self._bearer(source.connection_id), pause_usage)

    def _end_session(self, loop, client_id, token, deadline, *, connection_id=None, operation_id=None,
                     reason=None, verified_registration=None):
        grant = self.data.get("grant_pending") or {}
        if operation_id and (grant.get("id"), grant.get("client_id")) != (operation_id, client_id):
            raise ChatGPTError("chatgpt_target_changed", "ChatGPT grant operation has changed")
        if token:
            self._check_revoking(client_id)
        op = operation_id or uuid4().hex
        record = (state.grant_revocation(self.data, grant, verified_registration) if operation_id
                  else state.revocation(self.data, client_id))
        if operation_id and grant["kind"] == "exchange":
            # Discard the attempt's unused grant while preserving the committed login.
            retired = {**self.data, "connection": None, "grant_pending": None}
        else:
            retired = state.retired(self.data, reason)
        if token:
            data = {**retired, "revocations": {**retired.get("revocations", {}), op: record}}
        else:
            data = state.summarize(retired, record)
        self.models_cache = None
        storage_error = None
        try:
            self._save(data)
        except OSError as exc:
            self.error = "chatgpt_store_unavailable"
            if connection_id:
                self.disconnect_retry_id = connection_id
                raise
            if self._unconfirmed_digest is not None:
                # Preserve the known retirement if readback later proves the preceding write failed.
                # If it published the token, recovery uses that file and the token must not be revoked.
                self.data = state.summarize(retired, record)
                raise
            self.data = data
            storage_error = exc
        self.disconnect_retry_id = None
        if connection_id:
            self.error = None
        confirmed = False
        if token:
            confirmed = self._revoke_before(loop, client_id, token, deadline) and time.monotonic() < deadline
            # Another registration can finish while we wait. Only resolve this operation.
            outstanding = dict(self.data.get("revocations", {}))
            if outstanding.get(op) == record:
                del outstanding[op]
                updated = {**self.data, "revocations": outstanding}
                if not confirmed:
                    updated = state.summarize(updated, record)
                try:
                    self._commit_retirement(updated)
                except OSError:
                    logger.warning("Could not persist the ChatGPT revocation result")
        if storage_error:
            raise storage_error
        return confirmed

    async def _revoke(self, client_id, refresh_token, deadline):
        async with httpx.AsyncClient(timeout=self.http.timeout, trust_env=False, follow_redirects=False) as client:
            metadata = self._json_body(self._checked_response(await client.get(METADATA)))
            endpoint = self._metadata_endpoint(metadata, "revocation_endpoint")
            params = {
                "token": refresh_token, "token_type_hint": "refresh_token",
                "client_id": client_id,
            }
            for attempt in range(2):
                if time.monotonic() >= deadline:
                    return False
                try:
                    response = self._checked_response(await client.post(endpoint, data=params))
                    return response.status_code == 200
                except (ChatGPTError, httpx.HTTPError) as error:
                    if attempt or (isinstance(error, ChatGPTError) and error.status < 500):
                        return False
                await asyncio.sleep(0.25)

    def _revoke_before(self, loop, client_id, token, deadline):
        if loop is None or not loop.is_running() or time.monotonic() >= deadline:
            return False
        self.revoking = {key: task for key, task in self.revoking.items() if not task.done()}
        finished = Future()
        cancelled = Event()
        self.revoking[client_id] = finished
        task = None

        def complete(revocation):
            if revocation.cancelled():
                finished.set_result(False)
                return
            try:
                finished.set_result(revocation.result())
            except (asyncio.TimeoutError, ChatGPTError, httpx.HTTPError):
                finished.set_result(False)
            except Exception as exc:
                finished.set_exception(exc)

        async def revoke():
            remaining = deadline - time.monotonic()
            if cancelled.is_set() or remaining <= 0:
                return False
            return await self._revoke(client_id, token, deadline)

        def start():
            nonlocal task
            if cancelled.is_set() or time.monotonic() >= deadline:
                finished.set_result(False)
                return
            task = loop.create_task(revoke())
            task.add_done_callback(complete)

        def cancel():
            if task is not None:
                task.cancel()

        try:
            loop.call_soon_threadsafe(start)
        except RuntimeError:
            finished.set_result(False)
            return False
        try:
            self.lock.release()
            try:
                return finished.result(timeout=max(0, deadline - time.monotonic()))
            finally:
                self.lock.acquire()
        except FutureTimeout:
            cancelled.set()
            try:
                loop.call_soon_threadsafe(cancel)
            except RuntimeError:
                # The loop can no longer initiate I/O for this task.
                self.revoking.pop(client_id, None)
            return False

    def disconnect(self, loop: asyncio.AbstractEventLoop, *, connection_id=None, attempt_id=None, identity_id=None):
        deadline = time.monotonic() + DISCONNECT_TIMEOUT
        if not self.lock.acquire(timeout=min(DISCONNECT_LOCK_TIMEOUT, DISCONNECT_TIMEOUT)):
            raise ChatGPTError("chatgpt_connection_busy", "ChatGPT is busy. Try disconnecting again shortly")
        try:
            self._enabled()
            connection = self.data.get("connection")
            if connection_id is not None:
                if not connection or connection_id != connection["id"]:
                    raise ChatGPTError("chatgpt_target_changed", "The active ChatGPT connection has changed")
                confirmed = self._end_session(
                    loop, self.data["current_registration"], connection["refresh_token"], deadline,
                    connection_id=connection_id,
                )
                return {"disconnected": True, "revocation_confirmed": confirmed}
            if identity_id is not None:
                identity = self.data.get("identity") or {}
                if connection or identity.get("id") != identity_id:
                    raise ChatGPTError("chatgpt_target_changed", "The ChatGPT sign-in has changed")
                if self.pending:
                    raise ChatGPTError("chatgpt_connection_busy", "Finish or cancel the current authorization first")
                self._save({**self.data, "identity": None})
                self.error = None
                return {"disconnected": True, "revocation_confirmed": None}
            if self.pending:
                attempt = self.pending
                if attempt_id != attempt["id"] or attempt_id == (self.data.get("identity") or {}).get("id"):
                    raise ChatGPTError("chatgpt_target_changed", "The authorization attempt has changed")
                attempt["cancelled"] = True
                if attempt.get("exchanging"):
                    return {"disconnected": True, "revocation_confirmed": False}
                self.pending = None
            else:
                raise ChatGPTError("chatgpt_target_changed", "The authorization attempt has changed")
            self.error = None
            return {"disconnected": True, "revocation_confirmed": None}
        finally:
            self.lock.release()


_service = None


def start_chatgpt_service(loop: asyncio.AbstractEventLoop):
    global _service
    _service = ChatGPTOAuthService(Path.home() / "Library/Application Support/Daily Stock Analysis/chatgpt", loop)
    return _service


def stop_chatgpt_service():
    global _service
    if _service is not None:
        _service.close()
        _service = None


def get_chatgpt_service():
    if _service is None:
        raise ChatGPTError("chatgpt_unavailable", "This server does not support ChatGPT authorization")
    return _service
