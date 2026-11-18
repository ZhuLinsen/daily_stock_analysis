"""One user-owned Sign in with ChatGPT connection for the local DSA server."""
from __future__ import annotations

import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile
from threading import RLock, Thread
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
DYNAMIC_CLIENT = "dynamic_agent_client"
CALLBACK_PATH = "/auth/callback"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
REQUIRED_SCOPES = {"resource.invoke", "chatgpt.tokens.use.direct", "offline_access"}
APP_NAME = "Daily Stock Analysis"


def _safe_identifier(value):
    if isinstance(value, str) and re.fullmatch(r"[\w.\[\]-]{1,120}", value, flags=re.ASCII):
        return value
    return None


class ChatGPTError(Exception):
    """Safe error information shared by the OAuth and inference paths."""

    def __init__(self, code, message, *, status=None, upstream_code=None, param=None, request_id=None):
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
    def __init__(self, directory: Path):
        import fcntl

        self.directory = directory
        self.lock = RLock()
        self.pending = None
        self.error = None
        self.models_cache = None
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
            return json.load(stream)

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
            self._cancel_pending()
            self.http.close()
            self.directory_lock.close()

    def status(self):
        with self.lock:
            connection = self.data.get("connection") or {}
            registration = self.data.get("registration") or {}
            connected = bool(connection.get("active"))
            return {
                "available": True, "connected": connected,
                "connection_id": connection.get("id") if connected else None,
                "account_label": registration.get("label"), "plan_authorized": connected,
                "pending": self.pending is not None,
                "error": self.error or self.data.get("authorization_error"),
            }

    def _request(self, method, url, **kwargs):
        try:
            response = self.http.request(method, url, **kwargs)
        except httpx.HTTPError:
            raise ChatGPTError("chatgpt_network_error", "Could not reach OpenAI") from None
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
        try:
            body = self._request(method, url, **kwargs).json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise ChatGPTError("chatgpt_protocol_error", "OpenAI returned an invalid JSON object")
        return body

    def _metadata(self):
        metadata = self._json("GET", ISSUER + "/.well-known/openid-configuration")
        if metadata.get("issuer") != ISSUER:
            raise ChatGPTError("chatgpt_protocol_error", "Unexpected OpenAI issuer")
        return metadata

    def _metadata_endpoint(self, field):
        endpoint = self._metadata().get(field)
        if not isinstance(endpoint, str) or not endpoint.startswith(ISSUER + "/"):
            raise ChatGPTError("chatgpt_protocol_error", "Unexpected OpenAI metadata endpoint")
        return endpoint

    def _identity(self, encoded, client_id, nonce):
        keys = self._json("GET", self._metadata_endpoint("jwks_uri")).get("keys", [])
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
    def _token_fields(body):
        if (
            str(body.get("token_type", "")).lower() != "bearer"
            or not isinstance(body.get("access_token"), str) or not body["access_token"]
            or not isinstance(body.get("expires_in"), int) or body["expires_in"] <= 0
            or not isinstance(body.get("scope"), str)
        ):
            raise ChatGPTError("chatgpt_protocol_error", "OpenAI returned an incomplete token response")
        return {
            "access_token": body["access_token"], "refresh_token": body.get("refresh_token"),
            "expires_at": time.time() + body["expires_in"], "scopes": body["scope"].split(),
        }

    def connect(self, *, new_account=False, reconsent=False):
        with self.lock:
            self._enabled()
            if (self.data.get("connection") or {}).get("active") or self.pending:
                raise ChatGPTError("chatgpt_connection_busy", "Disconnect or cancel the current connection first")
            if not self.data.get("host_id"):
                self._save({**self.data, "host_id": f"urn:uuid:{uuid4()}"})
            registration = None if new_account else self.data.get("registration")
            attempt = {
                "id": uuid4().hex, "state": secrets.token_urlsafe(32), "nonce": secrets.token_urlsafe(32),
                "verifier": secrets.token_urlsafe(64), "registration": registration,
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
                "client_id": registration["client_id"] if registration else DYNAMIC_CLIENT,
                "ext_agent_host_id": self.data["host_id"], "redirect_uri": attempt["redirect_uri"],
                "response_type": "code", "scope": SCOPES, "resource": RESOURCE,
                "state": attempt["state"], "nonce": attempt["nonce"],
                "code_challenge": base64.urlsafe_b64encode(
                    hashlib.sha256(attempt["verifier"].encode()).digest()
                ).decode().rstrip("="),
                "code_challenge_method": "S256",
            }
            if not registration:
                query["agent_name_hint"] = APP_NAME
            elif reconsent:
                query["prompt"] = "consent"
            self.pending = attempt
            self.error = None
            Thread(target=self._listen, args=(attempt,), daemon=True).start()
            return {
                "attempt_id": attempt["id"],
                "authorization_url": ISSUER + "/api/accounts/authorize?" + urlencode(query),
            }

    def _listen(self, attempt):
        with attempt["listener"] as listener:
            deadline = time.monotonic() + 600
            while self.pending is attempt and time.monotonic() < deadline:
                listener.handle_request()
            with self.lock:
                if self.pending is attempt:
                    self.pending = None
                    self.error = "chatgpt_authorization_timeout"

    def _cancel_pending(self):
        # The listener exits at its short next poll. An exchange already in
        # flight can finish, but it can no longer publish the connection.
        self.pending = None

    def _complete(self, attempt, fields):
        with self.lock:
            if self.pending is not attempt:
                return
        try:
            if "error" in fields:
                raise ChatGPTError("chatgpt_consent_declined", "ChatGPT authorization was declined")
            registration = attempt["registration"]
            existing_id = registration["client_id"] if registration else None
            client_id, = fields.get("client_id", [existing_id])
            code, = fields.get("code", [None])
            if not code or not client_id or client_id == DYNAMIC_CLIENT or (existing_id and client_id != existing_id):
                raise ChatGPTError("chatgpt_invalid_callback", "OpenAI callback did not match the selected registration")
            body = self._json("POST", TOKEN, data={
                "grant_type": "authorization_code", "client_id": client_id, "code": code,
                "code_verifier": attempt["verifier"], "redirect_uri": attempt["redirect_uri"], "resource": RESOURCE,
            })
            claims = self._identity(body.get("id_token"), client_id, attempt["nonce"])
            if registration and claims["sub"] != registration["sub"]:
                raise ChatGPTError("chatgpt_invalid_identity", "OpenAI returned a different account")
            tokens = self._token_fields(body)
            complete = REQUIRED_SCOPES.issubset(tokens["scopes"]) and bool(tokens["refresh_token"])
            with self.lock:
                if self.pending is attempt:
                    self._enabled()
                    self._save({
                        **self.data,
                        "registration": {
                            "client_id": client_id, "issuer": ISSUER, "sub": claims["sub"],
                            "label": (claims.get("email") or claims.get("name") or "ChatGPT")[:160],
                        },
                        "connection": {
                            "active": True, "id": uuid4().hex, "id_token": body["id_token"], **tokens,
                        } if complete else None,
                        "authorization_error": None if complete else "chatgpt_plan_permission_required",
                    })
        except (OSError, ValueError, ChatGPTError) as exc:
            with self.lock:
                if self.pending is attempt:
                    self.error = exc.code if isinstance(exc, ChatGPTError) else "chatgpt_authorization_failed"
        finally:
            with self.lock:
                if self.pending is attempt:
                    self.pending = None

    def _connection(self, connection_id):
        self._enabled()
        connection = self.data.get("connection") or {}
        if not connection.get("active") or connection["id"] != connection_id:
            raise ChatGPTError("chatgpt_connection_inactive", "Connect ChatGPT and select a model again")
        return connection

    def _bearer(self, connection_id):
        connection = self._connection(connection_id)
        if connection["expires_at"] > time.time() + 45:
            return connection["access_token"]
        try:
            body = self._json("POST", TOKEN, data={
                "grant_type": "refresh_token", "resource": RESOURCE,
                "client_id": self.data["registration"]["client_id"],
                "refresh_token": connection["refresh_token"],
            })
        except ChatGPTError as exc:
            if exc.upstream_code in {"invalid_grant", "invalid_refresh_token", "token_expired",
                                     "refresh_token_expired", "refresh_token_invalidated", "refresh_token_reused"}:
                self._save({**self.data, "connection": None, "authorization_error": "chatgpt_reauthorization_required"})
                self.models_cache = None
                raise ChatGPTError("chatgpt_reauthorization_required", "Sign in to ChatGPT again",
                                   status=exc.status, upstream_code=exc.upstream_code, request_id=exc.request_id) from None
            raise
        tokens = self._token_fields(body)
        if not REQUIRED_SCOPES.issubset(tokens["scopes"]) or not tokens["refresh_token"]:
            self._save({**self.data, "connection": None, "authorization_error": "chatgpt_plan_permission_required"})
            self.models_cache = None
            raise ChatGPTError("chatgpt_plan_permission_required", "ChatGPT authorization no longer grants model use")
        self._save({**self.data, "connection": {**connection, **tokens}})
        return tokens["access_token"]

    def models(self, connection_id, *, refresh=False):
        with self.lock:
            self._connection(connection_id)
            if not refresh and self.models_cache and self.models_cache[0] == connection_id:
                return self.models_cache[1]
            bearer = self._bearer(connection_id)
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

    def disconnect(self):
        with self.lock:
            self._enabled()
            self._cancel_pending()
            connection = self.data.get("connection") or {}
            self.models_cache = None
            self.error = None
            if not connection:
                return {"disconnected": True, "revocation_confirmed": None}
            # Keep the revocation token only in memory once the user disconnects.
            self._save({**self.data, "connection": None, "authorization_error": None})
            confirmed = False
            try:
                endpoint = self._metadata_endpoint("revocation_endpoint")
                params = {
                    "token": connection["refresh_token"], "token_type_hint": "refresh_token",
                    "client_id": self.data["registration"]["client_id"],
                }
                for attempt in range(2):
                    try:
                        confirmed = self._request("POST", endpoint, data=params).status_code == 200
                        break
                    except ChatGPTError as exc:
                        if attempt or (exc.status is not None and exc.status < 500):
                            break
                        time.sleep(0.25)
            except ChatGPTError:
                pass
            return {"disconnected": True, "revocation_confirmed": confirmed}


_service = None


def start_chatgpt_service():
    global _service
    _service = ChatGPTOAuthService(Path.home() / "Library/Application Support/Daily Stock Analysis/chatgpt")
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
