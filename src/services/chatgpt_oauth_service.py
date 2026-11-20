"""One user-owned Sign in with ChatGPT connection for the local DSA server."""
from __future__ import annotations

import asyncio
import base64
import hashlib
from concurrent.futures import Future, TimeoutError as FutureTimeout
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
DISCONNECT_TIMEOUT = 20
DISCONNECT_LOCK_TIMEOUT = 2
logger = logging.getLogger(__name__)


def _safe_identifier(value):
    if isinstance(value, str) and re.fullmatch(r"[\w.\[\]-]{1,120}", value, flags=re.ASCII):
        return value
    return None


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
    def upstream(cls, code, message, body, *, status=None, request_id=None):
        body = body if isinstance(body, dict) else {}
        error = body.get("error", body)
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
        self.disabled_connection_id = None
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
            connection = self.data.get("connection")
            if connection and not self._valid_refresh(connection.get("refresh_token")):
                self._save({**self.data, "connection": None, "authorization_error": "chatgpt_reauthorization_required"})
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
        # Older records stored the current registration's consent error at the top level.
        if data.get("authorization_error") == PLAN_PERMISSION_REQUIRED and data.get("registration"):
            data["registration"]["needs_consent"] = True
            del data["authorization_error"]
        return data

    def _save(self, data):
        with tempfile.NamedTemporaryFile(mode="w", dir=self.directory, delete=False) as stream:
            path = Path(stream.name)
            try:
                json.dump(data, stream)
                stream.flush()
                os.fsync(stream.fileno())
                path.replace(self.directory / "connection.json")
            finally:
                path.unlink(missing_ok=True)
        self.data = data

    def _enabled(self):
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
        self.http.close()
        self.directory_lock.close()

    def status(self):
        with self.lock:
            connection = self._active_connection() or {}
            registration = self.data.get("registration") or {}
            session_end = self.data.get("last_session_end") or {}
            revocation_unconfirmed = session_end.get("result") == "unconfirmed"
            registrations = self._registrations()
            ended_id = session_end.get("registration_id")
            ended_label = registrations.get(ended_id, {}).get("label")
            if ended_label and len(registrations) > 1:
                ended_label = f"{ended_label} ({ended_id})"
            connected = bool(connection)
            grant_error = PLAN_PERMISSION_REQUIRED if registration.get("needs_consent") else self.data.get("authorization_error")
            return {
                "available": True, "connected": connected,
                "connection_id": connection.get("id") if connected else None,
                "disconnect_retry_connection_id": self._disconnect_retry_connection_id(),
                "account_label": registration.get("label"), "plan_authorized": connected,
                "revocation_unconfirmed": revocation_unconfirmed,
                "revocation_account_label": ended_label if revocation_unconfirmed else None,
                "retry_id": self.retry_target["id"] if self.retry_target else None,
                "registration_id": registration.get("client_id"),
                "accounts": [{"id": entry["client_id"], "label": entry["label"]}
                             for entry in registrations.values()],
                "pending": self.pending is not None,
                "attempt_id": self.pending["id"] if self.pending else None,
                "cancelling": bool(self.pending and self.pending.get("cancelled")),
                "error": self.error or grant_error,
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
        registrations = dict(self.data.get("other_registrations", {}))
        current = self.data.get("registration")
        if current:
            registrations[current["client_id"]] = current
        return registrations

    def _check_revoking(self, client_id):
        task = self.revoking.get(client_id)
        if task is not None and not task.done():
            raise ChatGPTError("chatgpt_connection_busy", "ChatGPT authorization is still being revoked")

    def connect(self, loop, *, registration_id=None, retry_id=None):
        with self.lock:
            self._enabled()
            if self._disconnect_retry_connection_id():
                raise ChatGPTError("chatgpt_connection_busy", "Retry disconnecting the current ChatGPT connection first")
            retry = self.retry_target if retry_id else None
            if retry_id and (not retry or retry["id"] != retry_id):
                raise ChatGPTError("chatgpt_target_changed", "Refresh the ChatGPT authorization status")
            if self._active_connection() or self.pending:
                raise ChatGPTError("chatgpt_connection_busy", "Disconnect or cancel the current connection first")
            registration = self._registrations().get(registration_id)
            if registration_id and registration is None:
                raise ChatGPTError("chatgpt_target_changed", "Refresh the saved ChatGPT accounts")
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
            elif registration and registration.get("needs_consent"):
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
                exchange_started = True
            body = self._grant_request(attempt, "POST", TOKEN, data={
                "grant_type": "authorization_code", "client_id": client_id, "code": code,
                "code_verifier": attempt["verifier"], "redirect_uri": attempt["redirect_uri"], "resource": RESOURCE,
            })
            exchange_returned = True
            if self._valid_refresh(body.get("refresh_token")):
                unused_refresh = body["refresh_token"]
            claims = self._identity(attempt, body.get("id_token"), client_id, attempt["nonce"])
            if registration and claims["sub"] != registration["sub"]:
                raise ChatGPTError("chatgpt_invalid_identity", "OpenAI returned a different account")
            tokens = self._token_fields(body)
            complete = REQUIRED_SCOPES.issubset(tokens["scopes"]) and bool(tokens["refresh_token"])
            with self.lock:
                if not attempt.get("cancelled"):
                    self._enabled()
                    others = self._registrations()
                    saved = others.pop(client_id, None)
                    if saved and saved["sub"] != claims["sub"]:
                        raise ChatGPTError("chatgpt_invalid_identity", "The issued registration belongs to another account")
                    self._save({
                        **self.data, "other_registrations": others,
                        "registration": {
                            "client_id": client_id, "issuer": ISSUER, "sub": claims["sub"],
                            "needs_consent": not complete,
                            "label": (claims.get("email") or claims.get("name") or "ChatGPT")[:160],
                        },
                        "connection": {
                            "active": True, "id": uuid4().hex, "id_token": body["id_token"], **tokens,
                        } if complete else None,
                        "authorization_error": None,
                    })
                    if complete:
                        self.disabled_connection_id = None
                        unused_refresh = None
                        self.pending = None
        except (OSError, ValueError, ChatGPTError) as exc:
            exchange_rejected = (
                isinstance(exc, ChatGPTError) and not exchange_returned
                and exc.status is not None and 400 <= exc.status < 500
            )
            with self.lock:
                if self.pending is attempt and not attempt.get("cancelled"):
                    self.error = exc.code if isinstance(exc, ChatGPTError) else "chatgpt_authorization_failed"
                    if (
                        exchange_started and not exchange_returned and not registration
                        and isinstance(exc, ChatGPTError) and exc.upstream_code == "invalid_grant"
                    ):
                        retry_client_id = client_id
        finally:
            with self.lock:
                if self.pending is attempt:
                    try:
                        if unused_refresh or (attempt.get("cancelled") and exchange_started and not exchange_rejected):
                            self._end_session(
                                attempt["loop"], client_id, unused_refresh, time.monotonic() + DISCONNECT_TIMEOUT,
                            )
                    finally:
                        if retry_client_id and not attempt.get("cancelled"):
                            self.retry_target = {"id": attempt["id"], "client_id": retry_client_id}
                        self.pending = None

    def _active_connection(self):
        connection = self.data.get("connection")
        if connection and connection.get("active") and connection["id"] != self.disabled_connection_id:
            return connection
        return None

    def _disconnect_retry_connection_id(self):
        connection = self.data.get("connection")
        if connection and connection["id"] == self.disabled_connection_id:
            return connection["id"]
        return None

    def _connection(self, connection_id):
        self._enabled()
        connection = self._active_connection()
        if not connection or connection["id"] != connection_id:
            raise ChatGPTError("chatgpt_connection_inactive", "Connect ChatGPT and select a model again")
        return connection

    def _mark_refresh_ambiguous(self, connection):
        if connection.get("refresh_ambiguous"):
            return
        data = {**self.data, "connection": {**connection, "refresh_ambiguous": True}}
        try:
            self._save(data)
        except OSError:
            self.data = data
            logger.warning("Could not persist uncertainty about the ChatGPT refresh")

    def _bearer(self, connection_id):
        connection = self._connection(connection_id)
        if connection["expires_at"] > time.time() + 45:
            return connection["access_token"]
        client_id = self.data["registration"]["client_id"]
        deadline = time.monotonic() + DISCONNECT_TIMEOUT
        try:
            body = self._json("POST", TOKEN, data={
                "grant_type": "refresh_token", "resource": RESOURCE, "client_id": client_id,
                "refresh_token": connection["refresh_token"],
            })
        except ChatGPTError as exc:
            if exc.upstream_code in {"invalid_grant", "invalid_refresh_token", "token_expired",
                                     "refresh_token_expired", "refresh_token_invalidated", "refresh_token_reused"}:
                if connection.get("refresh_ambiguous"):
                    self._end_session(self.loop, client_id, None, deadline, connection_id=connection_id,
                                      authorization_error="chatgpt_reauthorization_required", after_refresh=True)
                else:
                    self._disable_connection("chatgpt_reauthorization_required")
                raise ChatGPTError("chatgpt_reauthorization_required", "Sign in to ChatGPT again",
                                   status=exc.status, upstream_code=exc.upstream_code, request_id=exc.request_id) from None
            if exc.status is not None and 200 <= exc.status < 300:
                self._end_session(self.loop, client_id, None, deadline, connection_id=connection_id,
                                  authorization_error="chatgpt_reauthorization_required", after_refresh=True)
            elif exc.request_may_have_arrived or (exc.status is not None and exc.status >= 500):
                self._mark_refresh_ambiguous(connection)
            raise

        if "scope" not in body:
            body["scope"] = " ".join(connection["scopes"])
        issued_refresh = body.get("refresh_token")
        body.setdefault("refresh_token", connection["refresh_token"])
        latest_refresh = body["refresh_token"] if self._valid_refresh(body["refresh_token"]) else None
        ambiguous = bool(connection.get("refresh_ambiguous") and not self._valid_refresh(issued_refresh))
        authorization_error = "chatgpt_reauthorization_required"
        needs_consent = False
        try:
            tokens = self._token_fields(body)
            if not REQUIRED_SCOPES.issubset(tokens["scopes"]):
                authorization_error = PLAN_PERMISSION_REQUIRED
                needs_consent = True
                raise ChatGPTError(PLAN_PERMISSION_REQUIRED, "ChatGPT authorization no longer grants model use")
            renewed = {**connection, **tokens}
            if not ambiguous:
                renewed.pop("refresh_ambiguous", None)
            self._save({**self.data, "connection": renewed})
        except (ChatGPTError, OSError):
            self._end_session(
                self.loop, client_id, latest_refresh, deadline, connection_id=connection_id,
                authorization_error=authorization_error, needs_consent=needs_consent,
                ambiguous=ambiguous, after_refresh=True,
            )
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

    def validate(self, source: ChatGPTModelSource):
        if not any(item["slug"] == source.model for item in self.models(source.connection_id)):
            raise ChatGPTError("chatgpt_model_unavailable", "The selected model is absent from this ChatGPT connection")

    def ensure_active(self, source):
        with self.lock:
            self._connection(source.connection_id)

    def start_request(self, source, dispatch):
        self.validate(source)
        with self.lock:
            return dispatch(self._bearer(source.connection_id))

    def _disable_connection(self, authorization_error):
        self.models_cache = None
        retired = {**self.data, "connection": None, "authorization_error": authorization_error}
        try:
            self._save(retired)
        except OSError:
            self.data = retired
            self.error = "chatgpt_store_unavailable"
            raise

    def _end_session(self, loop, client_id, token, deadline, *, connection_id=None, authorization_error=None,
                     needs_consent=False, ambiguous=False, after_refresh=False):
        """Retire the connection and publish the outcome of the same revocation."""
        if token:
            self._check_revoking(client_id)
        data = dict(self.data)
        if connection_id is not None:
            self.models_cache = None
            data.update(connection=None, authorization_error=authorization_error)
            if needs_consent:
                data["registration"] = {**data["registration"], "needs_consent": True}
        outcome = {
            "operation_id": uuid4().hex,
            "result": "unconfirmed",
            "registration_id": client_id if client_id in self._registrations() else None,
        }
        data["last_session_end"] = outcome
        storage_error = None
        try:
            self._save(data)
        except OSError as exc:
            storage_error = exc
            if connection_id is not None:
                self.error = "chatgpt_store_unavailable"
                if not after_refresh:
                    self.disabled_connection_id = connection_id
                    raise
            self.data = data
            logger.warning("Could not persist the ChatGPT connection retirement")

        confirmed = bool(token and self._revoke_before(loop, client_id, token, deadline)) and not ambiguous
        if confirmed and self.data["last_session_end"]["operation_id"] == outcome["operation_id"]:
            updated = {**self.data, "last_session_end": {**outcome, "result": "confirmed"}}
            if storage_error is None:
                try:
                    self._save(updated)
                except OSError:
                    logger.warning("Could not persist the ChatGPT revocation result")
            self.data = updated
        if storage_error is not None and connection_id is not None:
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
            return finished.result(timeout=max(0, deadline - time.monotonic()))
        except FutureTimeout:
            cancelled.set()
            try:
                loop.call_soon_threadsafe(cancel)
            except RuntimeError:
                # The loop can no longer initiate I/O for this task.
                self.revoking.pop(client_id, None)
            return False

    def disconnect(self, loop: asyncio.AbstractEventLoop, *, connection_id=None, attempt_id=None):
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
                    loop, self.data["registration"]["client_id"], connection["refresh_token"], deadline,
                    connection_id=connection_id, ambiguous=bool(connection.get("refresh_ambiguous")),
                )
                self.error = None
                return {"disconnected": True, "revocation_confirmed": confirmed}
            if self.pending:
                attempt = self.pending
                if attempt_id != attempt["id"]:
                    raise ChatGPTError("chatgpt_target_changed", "The authorization attempt has changed")
                attempt["cancelled"] = True
                if attempt.get("exchanging"):
                    return {"disconnected": True, "revocation_confirmed": False}
                self.pending = None
            elif connection:
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
