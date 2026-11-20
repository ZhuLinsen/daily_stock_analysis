"""Regression coverage for ChatGPT connection ownership and the Responses contract."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.endpoints import chatgpt
from src.agent.chatgpt_adapter import ChatGPTToolAdapter
from src.analyzer import GeminiAnalyzer
from src.config import Config
from src.llm.chatgpt_generation_backend import SiwcGenerationBackend
from src.llm.chatgpt_responses import ChatGPTResponse, consume_responses
from src.llm.model_source import ChatGPTModelSource
from src.services.agent_backend_status_service import evaluate_agent_backend_config
from src.services import chatgpt_oauth_service
from src.services.chatgpt_oauth_service import ChatGPTError, ChatGPTOAuthService


SOURCE = ChatGPTModelSource(provider="chatgpt_siwc", connection_id="local", model="test-model")
REGISTRATION = {"client_id": "issued", "sub": "account", "label": "Test account"}
MESSAGES = [{"role": "system", "content": "Instructions"}, {"role": "user", "content": "Question"}]
TOOLS = [{"type": "function", "function": {"name": "quote", "parameters": {"type": "object"}}}]


@pytest.fixture
def oauth(tmp_path, monkeypatch):
    monkeypatch.setattr("src.services.chatgpt_oauth_service.is_auth_enabled", lambda: True)
    service = ChatGPTOAuthService(tmp_path / "private")
    yield service
    service.close()


def token_body(scope="offline_access resource.invoke chatgpt.tokens.use.direct"):
    return {
        "token_type": "Bearer", "access_token": "access-new", "refresh_token": "refresh-new",
        "id_token": "identity", "expires_in": 3600, "scope": scope,
    }


def begin(service):
    service._save({"registration": REGISTRATION})
    attempt = {"id": "attempt", "loop": None, "registration": REGISTRATION, "expected_client_id": "issued",
               "nonce": "nonce", "verifier": "pkce", "redirect_uri": "redirect"}
    service.pending = attempt
    return attempt


def expire_connection(service):
    service._save({"registration": REGISTRATION, "connection": {
        "active": True, "id": SOURCE.connection_id, "expires_at": 0, "access_token": "access-old",
        "scopes": token_body()["scope"].split(), "refresh_token": "refresh-old",
    }})
    service.models_cache = (SOURCE.connection_id, ({"slug": SOURCE.model},))


def mock_revocation_transport(monkeypatch, handler):
    client = httpx.AsyncClient

    def make_client(**options):
        options.setdefault("transport", httpx.MockTransport(handler))
        return client(**options)

    monkeypatch.setattr(
        chatgpt_oauth_service.httpx, "AsyncClient", make_client,
    )


async def disconnect_in_worker(service, **target):
    return await asyncio.to_thread(service.disconnect, asyncio.get_running_loop(), **(target or {"connection_id": SOURCE.connection_id}))


@pytest.mark.parametrize("subject,scope,error", [
    ("different", "openid", "chatgpt_invalid_identity"),
    ("account", "openid", "chatgpt_plan_permission_required"),
])
def test_identity_binding_and_incomplete_consent(oauth, monkeypatch, subject, scope, error):
    attempt = begin(oauth)
    monkeypatch.setattr(oauth, "_grant_request", Mock(return_value=token_body(scope)))
    monkeypatch.setattr(oauth, "_revoke_before", Mock(return_value=True))
    identity = Mock(return_value={"sub": subject})
    monkeypatch.setattr(oauth, "_identity", identity)
    oauth._complete(attempt, {"code": ["code"]})
    identity.assert_called_once_with(attempt, "identity", "issued", "nonce")
    assert oauth.status()["error"] == error
    assert not oauth.status()["connected"]
    assert oauth.data["registration"]["client_id"] == "issued"


@pytest.mark.parametrize("has_refresh", [True, False])
def test_cancel_while_token_exchange_is_in_flight(oauth, monkeypatch, has_refresh):
    attempt = begin(oauth)
    started, finish = Event(), Event()

    def exchange(*args, **kwargs):
        started.set()
        assert finish.wait(5)
        body = token_body()
        if not has_refresh:
            body.pop("refresh_token")
            body["scope"] = "openid"
        return body

    monkeypatch.setattr(oauth, "_grant_request", exchange)
    revoke = Mock(return_value=True)
    monkeypatch.setattr(oauth, "_revoke_before", revoke)
    monkeypatch.setattr(oauth, "_identity", lambda *_: {"sub": "account"})
    with ThreadPoolExecutor() as executor:
        callback = executor.submit(oauth._complete, attempt, {"code": ["code"]})
        try:
            assert started.wait(5)
            asyncio.run(disconnect_in_worker(oauth, attempt_id="attempt"))
        finally:
            finish.set()
        callback.result(timeout=5)
    assert not oauth.status()["connected"]
    assert oauth.status()["revocation_unconfirmed"] is (not has_refresh)
    if has_refresh:
        assert revoke.call_args.args[1:3] == ("issued", "refresh-new")
    else:
        revoke.assert_not_called()
    assert "access-new" not in (oauth.directory / "connection.json").read_text()


@pytest.mark.parametrize("omitted,overrides,error,saved_refresh", [
    ("refresh_token", {}, None, "refresh-old"),
    (None, {"scope": "openid"}, "chatgpt_plan_permission_required", None),
    (None, {"refresh_token": {"invalid": "object"}}, "chatgpt_protocol_error", None),
], ids=["keep-refresh-token", "reject-narrowed-grant", "reject-malformed-token"])
def test_refresh_uses_existing_credentials_only_for_omitted_fields(
    oauth, monkeypatch, omitted, overrides, error, saved_refresh,
):
    expire_connection(oauth)
    body = {**token_body(), **overrides}
    if omitted:
        del body[omitted]
    monkeypatch.setattr(oauth, "_json", Mock(return_value=body))
    revoke = Mock(return_value=True)
    monkeypatch.setattr(oauth, "_revoke_before", revoke)
    dispatch = Mock(return_value="started")
    if error:
        with pytest.raises(ChatGPTError, match=error):
            oauth.start_request(SOURCE, dispatch)
        dispatch.assert_not_called()
    else:
        assert oauth.start_request(SOURCE, dispatch) == "started"
        dispatch.assert_called_once_with("access-new")
    stored = json.loads((oauth.directory / "connection.json").read_text())["connection"]
    assert (stored or {}).get("refresh_token") == saved_refresh
    if stored:
        assert stored["access_token"] == "access-new"
    if error == "chatgpt_plan_permission_required":
        assert revoke.call_args.args[1:3] == ("issued", "refresh-new")
        assert not oauth.status()["revocation_unconfirmed"]
    else:
        revoke.assert_not_called()
        assert oauth.status()["revocation_unconfirmed"] is bool(error)


def test_refresh_and_disconnect_serialize_and_reconnect_changes_reference(oauth, monkeypatch):
    expire_connection(oauth)
    refreshing, release = Event(), Event()

    def refresh(*args, **kwargs):
        refreshing.set()
        assert release.wait(5)
        body = token_body()
        del body["scope"]
        return body

    monkeypatch.setattr(oauth, "_json", refresh)

    def revoke(request):
        stored = json.loads((oauth.directory / "connection.json").read_text())
        assert stored["connection"] is None
        assert stored["registration"] == REGISTRATION
        if request.method == "GET":
            return httpx.Response(200, json={
                "issuer": chatgpt_oauth_service.ISSUER,
                "revocation_endpoint": chatgpt_oauth_service.ISSUER + "/fixture-revoke",
            })
        assert parse_qs(request.content.decode())["token"] == ["refresh-new"]
        return httpx.Response(200)

    monkeypatch.setattr(oauth, "_request", Mock(side_effect=AssertionError("Unexpected synchronous HTTP request")))
    mock_revocation_transport(monkeypatch, revoke)
    with ThreadPoolExecutor() as executor:
        dispatch = executor.submit(oauth.start_request, SOURCE, lambda bearer: bearer)
        try:
            assert refreshing.wait(5)
            disconnect = executor.submit(asyncio.run, disconnect_in_worker(oauth))
        finally:
            release.set()
        assert dispatch.result(timeout=5) == "access-new"
        assert disconnect.result(timeout=5)["revocation_confirmed"]

    attempt = begin(oauth)
    monkeypatch.setattr(oauth, "_grant_request", Mock(return_value=token_body()))
    monkeypatch.setattr(oauth, "_identity", lambda *_: {"sub": "account"})
    oauth._complete(attempt, {"code": ["code"]})
    assert oauth.status()["connection_id"] != SOURCE.connection_id
    dispatch = Mock()
    with pytest.raises(ChatGPTError, match="chatgpt_connection_inactive"):
        oauth.start_request(SOURCE, dispatch)
    dispatch.assert_not_called()


def test_disconnect_bounds_lock_wait_and_remote_revocation(oauth, monkeypatch):
    expire_connection(oauth)
    monkeypatch.setattr(chatgpt_oauth_service, "DISCONNECT_LOCK_TIMEOUT", 0.01, raising=False)
    monkeypatch.setattr(chatgpt_oauth_service, "DISCONNECT_TIMEOUT", 0.2, raising=False)
    monkeypatch.setattr(oauth, "_request", Mock(side_effect=AssertionError("Unexpected synchronous HTTP request")))
    remote_finished = Event()
    dns_started = Event()
    finish_dns = Event()

    def slow_dns_lookup():
        dns_started.set()
        assert finish_dns.wait(3)

    async def upstream(request):
        assert request.url == chatgpt_oauth_service.METADATA
        try:
            await asyncio.to_thread(slow_dns_lookup)
        finally:
            remote_finished.set()

    mock_revocation_transport(monkeypatch, upstream)
    with ThreadPoolExecutor() as executor:
        with oauth.lock:
            attempt = executor.submit(asyncio.run, disconnect_in_worker(oauth))
            with pytest.raises(ChatGPTError, match="chatgpt_connection_busy"):
                attempt.result(timeout=1)
            assert oauth.status()["connected"]
            assert not dns_started.is_set()

    async def disconnect_with_slow_dns():
        try:
            assert await asyncio.wait_for(disconnect_in_worker(oauth), timeout=1) == {
                "disconnected": True, "revocation_confirmed": False,
            }
            assert dns_started.is_set()
            assert await asyncio.to_thread(remote_finished.wait, 1)
        finally:
            finish_dns.set()

    asyncio.run(disconnect_with_slow_dns())
    assert json.loads((oauth.directory / "connection.json").read_text())["connection"] is None
    assert not oauth.status()["connected"]


def test_dynamic_registration_retry_keeps_issued_id_without_an_account(oauth, monkeypatch):
    grant = Mock(side_effect=ChatGPTError(
        "chatgpt_http_error", "fixture", status=400, upstream_code="invalid_grant",
    ))
    monkeypatch.setattr(oauth, "_grant_request", grant)
    first = oauth.connect(None)
    first_attempt = oauth.pending
    oauth._complete(first_attempt, {"code": ["expired"], "client_id": ["new-issued"]})
    first_attempt["thread"].join(2)
    assert oauth.status()["retry_id"] == first["attempt_id"]
    assert not oauth.status()["pending"] and oauth.status()["accounts"] == []

    retried = oauth.connect(None, retry_id=first["attempt_id"])
    retry_attempt = oauth.pending
    first_query = parse_qs(urlsplit(first["authorization_url"]).query)
    retry_query = parse_qs(urlsplit(retried["authorization_url"]).query)
    assert retry_query["client_id"] == ["new-issued"]
    assert retry_query["ext_agent_host_id"] == first_query["ext_agent_host_id"]
    for key in ("state", "nonce", "code_challenge"):
        assert retry_query[key] != first_query[key]
    with pytest.raises(ChatGPTError, match="chatgpt_target_changed"):
        oauth.connect(None, retry_id=first["attempt_id"])
    grant.side_effect = None
    grant.return_value = token_body()
    monkeypatch.setattr(oauth, "_identity", Mock(return_value={"sub": "verified"}))
    oauth._complete(retry_attempt, {"code": ["fresh"]})
    retry_attempt["thread"].join(2)
    assert grant.call_args.kwargs["data"]["client_id"] == "new-issued"
    assert grant.call_args.kwargs["data"]["code"] == "fresh"
    assert oauth.status()["registration_id"] == "new-issued"
    assert oauth.status()["retry_id"] is None


@pytest.mark.parametrize("restart", [False, True])
def test_ambiguous_refresh_never_confirms_revocation_of_only_old_token(oauth, monkeypatch, restart):
    expire_connection(oauth)
    revoked = Mock(return_value=True)
    oauth.http.close()
    oauth.http = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(503)), trust_env=False)
    with pytest.raises(ChatGPTError, match="HTTP 503"):
        oauth.models(SOURCE.connection_id, refresh=True)
    assert oauth.status()["connected"]
    # _load reads the same credential record a new instance would use.
    if restart:
        oauth.data = oauth._load()
    monkeypatch.setattr(oauth, "_revoke_before", revoked)
    assert oauth.disconnect(None, connection_id=SOURCE.connection_id) == {
        "disconnected": True, "revocation_confirmed": False,
    }
    revoked.assert_called_once()
    assert revoked.call_args.args[1:3] == ("issued", "refresh-old")
    assert oauth.status()["revocation_unconfirmed"]
    assert oauth.status()["revocation_account_label"] == REGISTRATION["label"]
    oauth.data = oauth._load()
    assert oauth.status()["revocation_unconfirmed"]


def test_rotated_grant_write_failure_stops_the_old_connection(oauth, monkeypatch):
    expire_connection(oauth)
    save = oauth._save
    monkeypatch.setattr(oauth, "_json", Mock(return_value=token_body()))
    monkeypatch.setattr(oauth, "_save", Mock(side_effect=OSError("fixture")))
    revoke, dispatch = Mock(return_value=True), Mock()
    monkeypatch.setattr(oauth, "_revoke_before", revoke)
    with pytest.raises(OSError):
        oauth.start_request(SOURCE, dispatch)
    assert not oauth.status()["connected"]
    assert oauth.status()["error"] == "chatgpt_store_unavailable"
    assert revoke.call_args.args[1:3] == ("issued", "refresh-new")
    save({**oauth.data, "host_id": "fixture-host"})
    with pytest.raises(ChatGPTError, match="chatgpt_connection_inactive"):
        oauth.start_request(SOURCE, dispatch)
    dispatch.assert_not_called()


def test_second_write_failure_preserves_local_disconnect_and_live_result(oauth, monkeypatch):
    expire_connection(oauth)
    original_save = oauth._save

    def save(data):
        if data["last_session_end"]["result"] == "confirmed":
            raise OSError("fixture")
        original_save(data)

    monkeypatch.setattr(oauth, "_save", save)
    monkeypatch.setattr(oauth, "_revoke_before", Mock(return_value=True))
    result = oauth.disconnect(None, connection_id=SOURCE.connection_id)
    assert result["disconnected"] and result["revocation_confirmed"]
    assert not oauth.status()["connected"] and not oauth.status()["revocation_unconfirmed"]
    oauth.data = oauth._load()
    assert not oauth.status()["connected"] and oauth.status()["revocation_unconfirmed"]


def test_same_registration_waits_for_revocation_task_exit(oauth, monkeypatch):
    expire_connection(oauth)
    monkeypatch.setattr(chatgpt_oauth_service, "DISCONNECT_TIMEOUT", 0.15)
    finishing, release = Event(), Event()

    async def revoke(*args):
        try:
            await asyncio.sleep(60)
        finally:
            finishing.set()
            while not release.is_set():
                await asyncio.sleep(0.005)

    monkeypatch.setattr(oauth, "_revoke", revoke)

    async def verify():
        loop = asyncio.get_running_loop()
        try:
            result = await disconnect_in_worker(oauth)
            assert result == {"disconnected": True, "revocation_confirmed": False}
            assert await asyncio.to_thread(finishing.wait, 1)
            with pytest.raises(ChatGPTError, match="chatgpt_connection_busy"):
                await asyncio.to_thread(oauth.connect, loop, registration_id="issued")
            different = await asyncio.to_thread(oauth.connect, loop)
            assert parse_qs(urlsplit(different["authorization_url"]).query)["client_id"] == ["dynamic_agent_client"]
            dynamic = oauth.pending
            exchange = Mock()
            monkeypatch.setattr(oauth, "_grant_request", exchange)
            await asyncio.to_thread(oauth._complete, dynamic, {"client_id": ["issued"], "code": ["code"]})
            exchange.assert_not_called()
            assert oauth.status()["error"] == "chatgpt_connection_busy"
            await asyncio.to_thread(dynamic["thread"].join, 1)
        finally:
            release.set()
        assert await asyncio.to_thread(oauth.revoking["issued"].result, 1) is False
        await asyncio.to_thread(oauth.connect, loop, registration_id="issued")
        assert oauth.status()["revocation_unconfirmed"]

    asyncio.run(verify())


def test_revoke_timeout_before_scheduling_does_not_strand_registration(oauth, monkeypatch):
    callbacks = []
    loop = Mock()
    loop.is_running.return_value = True
    loop.call_soon_threadsafe.side_effect = callbacks.append
    revoke = Mock()
    monkeypatch.setattr(oauth, "_revoke", revoke)
    assert not oauth._revoke_before(loop, "issued", "fixture", chatgpt_oauth_service.time.monotonic() + 0.02)
    with pytest.raises(ChatGPTError, match="chatgpt_connection_busy"):
        oauth._check_revoking("issued")
    for callback in callbacks:
        callback()
    revoke.assert_not_called()
    loop.create_task.assert_not_called()
    assert oauth.revoking["issued"].done()
    oauth._check_revoking("issued")


def item(text, phase=None):
    result = {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}
    if phase:
        result["phase"] = phase
    return result


def dumpable(data):
    return SimpleNamespace(model_dump=lambda **_: data)


def done(index, data):
    return SimpleNamespace(type="response.output_item.done", output_index=index, item=dumpable(data))


def completed(*items):
    return SimpleNamespace(type="response.completed", response=SimpleNamespace(
        id="resp_test", status="completed", model="test-model", usage=None,
        output=[dumpable(data) for data in items],
    ))


def test_responses_two_observed_output_shapes():
    reasoning = {"type": "reasoning", "encrypted_content": "opaque"}
    assert consume_responses([done(1, item("final")), done(0, reasoning), completed()]).items == [
        reasoning, item("final"),
    ]
    result = consume_responses([done(0, item("done event")), completed(item("terminal", "final_answer"))])
    assert result.items == [item("terminal", "final_answer")]
    assert result.final_text() == "terminal"


@pytest.mark.parametrize("events", [
    [done(0, item("no end"))],
    [SimpleNamespace(type="response.failed", response=SimpleNamespace(
        id="resp_failed", error=dumpable({"code": "subscription_sharing_usage_limit_exceeded"}),
    ))],
    [SimpleNamespace(type="response.incomplete", response=SimpleNamespace(
        id="resp_incomplete", incomplete_details=dumpable({"reason": "timeout"}),
    ))],
    [completed(item("only commentary", "commentary"))],
    [completed()],
])
def test_incomplete_or_nonfinal_output_fails(events):
    with pytest.raises(ChatGPTError):
        consume_responses(events).final_text()


def _call(call_id):
    return {
        "type": "function_call", "namespace": "dsa_market_data", "name": "quote",
        "call_id": call_id, "arguments": "{}",
    }


def test_adapter_replays_two_complete_tool_rounds(monkeypatch):
    upstream = [
        [{"type": "reasoning", "encrypted_content": "opaque"}, _call("first")],
        [_call("second")], [item("final")],
    ]
    captured = []

    def transport(service, source, *, items, **kwargs):
        captured.append(list(items))
        return ChatGPTResponse(upstream[len(captured) - 1], source.model, {})

    monkeypatch.setattr("src.agent.chatgpt_adapter.get_chatgpt_service", lambda: object())
    monkeypatch.setattr("src.agent.chatgpt_adapter.request_responses", transport)
    adapter = ChatGPTToolAdapter(SOURCE, 30)
    messages = [*MESSAGES]
    results = []
    for call_id in ("first", "second"):
        response = adapter.call_with_tools(messages, TOOLS)
        assert response.tool_calls[0].id == call_id
        messages.extend([{"role": "assistant"}, {"role": "tool", "tool_call_id": call_id, "name": "quote", "content": "1"}])
        results.append({"type": "function_call_output", "call_id": call_id, "output": "1"})
    assert adapter.call_with_tools(messages, TOOLS).content == "final"
    assert captured[2] == [MESSAGES[1], *upstream[0], results[0], *upstream[1], results[1]]


@pytest.mark.parametrize("bad", [{"name": "unknown"}, {"call_id": ""}, {"arguments": "[]"}])
def test_adapter_rejects_invalid_calls(monkeypatch, bad):
    monkeypatch.setattr("src.agent.chatgpt_adapter.get_chatgpt_service", lambda: object())
    monkeypatch.setattr("src.agent.chatgpt_adapter.request_responses", lambda *a, **kw:
                        ChatGPTResponse([{**_call("id"), **bad}], SOURCE.model, {}))
    response = ChatGPTToolAdapter(SOURCE, 30).call_with_tools(MESSAGES, TOOLS)
    assert response.provider == "error"
    assert response.tool_calls == []


def test_report_backend_and_chat_factory_without_legacy_keys(monkeypatch):
    from src.agent.factory import build_agent_chat_executor

    config = Config()
    monkeypatch.setattr("src.services.agent_backend_status_service.get_chatgpt_service",
                        lambda: SimpleNamespace(validate=lambda source: None))
    monkeypatch.setattr("src.analyzer.GeminiAnalyzer._init_litellm", Mock(side_effect=AssertionError("legacy init")))
    monkeypatch.setattr("src.agent.llm_adapter.LLMToolAdapter", Mock(side_effect=AssertionError("legacy adapter")))
    backend = SiwcGenerationBackend(SOURCE, 30)
    analyzer = GeminiAnalyzer(config=config, generation_backend=backend, generation_source=SOURCE)
    assert analyzer.is_available()
    assert analyzer.get_generation_backend_identity() == (SOURCE.provider, SOURCE.model)
    assert evaluate_agent_backend_config(config, model_source=SOURCE)["available"]
    executor = build_agent_chat_executor(config, model_source=SOURCE)
    assert executor.backend.backend_id == SOURCE.provider
    assert not executor.include_provider_trace


def test_report_failure_keeps_safe_error_and_never_retries(monkeypatch):
    config = Config(generation_fallback_backend="litellm")
    backend = SiwcGenerationBackend(SOURCE, 30)
    analyzer = GeminiAnalyzer(config=config, generation_backend=backend, generation_source=SOURCE)
    monkeypatch.setattr("src.llm.chatgpt_generation_backend.get_chatgpt_service", lambda: object())
    request = Mock(side_effect=ChatGPTError(
        "chatgpt_inference_failed", "Request failed", upstream_code="usage_limit", request_id="req_safe",
    ))
    monkeypatch.setattr("src.llm.chatgpt_generation_backend.request_responses", request)
    result = analyzer.analyze({"code": "600519", "today": {}})
    assert not result.success
    assert "usage_limit" in result.error_message and "req_safe" in result.error_message
    assert request.call_count == 1


def test_invalid_report_json_keeps_response_id(monkeypatch):
    analyzer = GeminiAnalyzer(
        config=Config(), generation_backend=SiwcGenerationBackend(SOURCE, 30), generation_source=SOURCE,
    )
    response = ChatGPTResponse([item("No report JSON")], SOURCE.model, {}, "resp_invalid_report")
    monkeypatch.setattr("src.llm.chatgpt_generation_backend.get_chatgpt_service", lambda: object())
    monkeypatch.setattr("src.llm.chatgpt_generation_backend.request_responses", lambda *args, **kwargs: response)

    report = analyzer.analyze({"code": "600519", "today": {}})

    assert not report.success
    assert "invalid_json" in report.error_message
    assert "resp_invalid_report" in report.error_message


def test_model_source_may_be_omitted_but_not_null():
    from pydantic import ValidationError
    from api.v1.endpoints.agent import ChatRequest
    from api.v1.schemas.analysis import AnalyzeRequest

    for schema, payload in ((AnalyzeRequest, {"stock_code": "600519"}), (ChatRequest, {"message": "Hello"})):
        assert schema.model_validate(payload).model_source is None
        with pytest.raises(ValidationError) as error:
            schema.model_validate({**payload, "model_source": None})
        assert error.value.errors()[0]["loc"][0] == "model_source"


def test_connection_endpoints_require_local_admin_and_same_origin(oauth, monkeypatch, tmp_path):
    from api.app import create_app
    app = create_app(tmp_path / "no-static")
    monkeypatch.setattr("api.middlewares.auth.is_auth_enabled", lambda: False)
    path = "/api/v1/chatgpt"
    app.state.chatgpt_origin = "http://127.0.0.1:8765"
    from src.auth import COOKIE_NAME
    monkeypatch.setattr("src.auth.is_auth_enabled", lambda: False)
    client = TestClient(app, base_url=app.state.chatgpt_origin)
    assert client.get(path + "/status").json()["error"] == "chatgpt_admin_auth_required"
    monkeypatch.setattr("src.auth.is_auth_enabled", lambda: True)
    monkeypatch.setattr("src.auth.verify_session", lambda cookie: cookie == "valid")
    assert client.get(path + "/status").status_code == 401
    client.cookies.set(COOKIE_NAME, "valid")
    assert client.post(path + "/disconnect", json={"connection_id": "local"}).status_code == 403
    assert client.get(path + "/status", headers={"Host": "testserver"}).status_code == 403
    def upstream(request):
        if request.url == chatgpt_oauth_service.METADATA:
            return httpx.Response(200, json={
                "issuer": chatgpt_oauth_service.ISSUER,
                "revocation_endpoint": chatgpt_oauth_service.ISSUER + "/fixture-revoke",
            })
        assert parse_qs(request.content.decode())["token"] == ["refresh-old"]
        return httpx.Response(200)

    expire_connection(oauth)
    mock_revocation_transport(monkeypatch, upstream)
    monkeypatch.setattr(chatgpt, "get_chatgpt_service", lambda: oauth)
    headers = {"Origin": app.state.chatgpt_origin}
    stale = client.post(path + "/disconnect", headers=headers, json={"connection_id": "older"})
    assert stale.status_code == 409 and oauth.status()["connected"]
    response = client.post(path + "/disconnect", headers=headers, json={"connection_id": "local"})
    assert response.json() == {"disconnected": True, "revocation_confirmed": True}
    assert not client.get(path + "/status").json()["connected"]
    expire_connection(oauth)
    error = ChatGPTError("chatgpt_http_error", "fixture", upstream_code="invalid_grant")
    monkeypatch.setattr(oauth, "_json", Mock(side_effect=error))
    response = client.get(path + "/models", params={"connection_id": SOURCE.connection_id, "refresh": True})
    assert response.status_code == 400 and response.json()["error"] == "chatgpt_reauthorization_required"
    assert not client.get(path + "/status").json()["connected"]


@pytest.mark.parametrize("cache_telemetry_enabled", [True, False], ids=["cache_enabled", "cache_disabled"])
def test_sdk_sends_only_selected_model_and_reuses_complete_done_item(monkeypatch, tmp_path, cache_telemetry_enabled):
    from src.llm.chatgpt_responses import request_responses
    from src.storage import DatabaseManager, LLMUsage

    monkeypatch.setattr(Config, "_instance", Config(llm_prompt_cache_telemetry_enabled=cache_telemetry_enabled))

    call = _call("sdk-test")
    call.update(id="fc_test", status="completed")
    events = [
        {"type": "response.output_item.done", "output_index": 0, "sequence_number": 0, "item": call},
        {"type": "response.completed", "sequence_number": 1, "response": {
            "id": "resp_test", "status": "completed", "model": SOURCE.model, "output": [],
            "usage": {
                "input_tokens": 36741, "input_tokens_details": {"cached_tokens": 34944},
                "output_tokens": 38, "output_tokens_details": {"reasoning_tokens": 0}, "total_tokens": 36779,
            },
        }},
    ]

    def upstream(request):
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.headers["authorization"] == "Bearer test-access"
        assert "openai-organization" not in request.headers and "openai-project" not in request.headers
        payload = json.loads(request.content)
        assert payload == {
            "model": SOURCE.model, "input": MESSAGES[1:], "instructions": "Instructions",
            "store": False, "stream": True, "tools": [namespace], "tool_choice": "auto",
        }
        return httpx.Response(
            200, headers={"Content-Type": "text/event-stream"},
            content="".join(f"data: {json.dumps(event)}\n\n" for event in events),
        )

    namespace = {"type": "namespace", "name": "dsa_market_data", "tools": [
        {"type": "function", **TOOLS[0]["function"], "strict": False},
    ]}
    monkeypatch.setenv("OPENAI_API_KEY", "legacy")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://legacy.invalid/v1")
    monkeypatch.setenv("OPENAI_ORG_ID", "legacy-organization")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "legacy-project")
    class MockClient(httpx.Client):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(upstream), **kwargs)

    monkeypatch.setattr("src.llm.chatgpt_responses.httpx.Client", MockClient)
    ensure_active = Mock()
    service = SimpleNamespace(start_request=lambda source, dispatch: dispatch("test-access"), ensure_active=ensure_active)
    db = DatabaseManager(f"sqlite:///{tmp_path / 'usage.db'}")
    monkeypatch.setattr(DatabaseManager, "get_instance", lambda: db)
    response = request_responses(
        service, SOURCE, call_type="agent", items=MESSAGES[1:], instructions="Instructions", timeout=5, tools=[namespace],
    )
    assert response.items == [call]
    assert response.usage["provider"] == SOURCE.provider
    assert response.usage["prompt_tokens"] == 36741
    assert response.usage["completion_tokens"] == 38
    assert response.usage["total_tokens"] == 36779
    ensure_active.assert_called_once_with(SOURCE)
    if cache_telemetry_enabled:
        assert response.usage["normalized_cache_read_tokens"] == 34944
    else:
        with db.session_scope() as session:
            row = session.query(LLMUsage).one()
            assert (row.prompt_tokens, row.completion_tokens, row.total_tokens) == (36741, 38, 36779)
            assert row.provider == SOURCE.provider
            assert row.provider_usage_json is None
            assert row.normalized_cache_read_tokens is None
            assert row.cache_observation is None


def test_analysis_accepted_source_and_skill_survive_queue_delay(monkeypatch):
    from concurrent.futures import Future
    from api.v1.endpoints import analysis
    from api.v1.schemas.analysis import AnalyzeRequest
    from src.services.task_queue import AnalysisTaskQueue
    from src.services.analysis_service import AnalysisService

    class DeferredExecutor:
        def submit(self, work, *args):
            self.run = lambda: work(*args)
            return Future()

    monkeypatch.setattr(AnalysisTaskQueue, "_instance", None)
    executor = DeferredExecutor()
    queue = AnalysisTaskQueue()
    queue._executor = executor
    config = Config(agent_mode=False, agent_skills=["all"])
    monkeypatch.setattr(analysis, "get_task_queue", lambda: queue)
    monkeypatch.setattr(analysis, "_resolve_analysis_input", lambda code: (code, None))
    validate = Mock()
    monkeypatch.setattr(analysis, "validate_chatgpt_source", validate)
    request = AnalyzeRequest(stock_code="600519", async_mode=True, notify=False, model_source=SOURCE)
    assert analysis.trigger_analysis(request, config).status_code == 202
    config.agent_mode = True
    config.agent_skills = ["changed"]
    config.litellm_model = "changed/old-model"
    service = Mock(return_value={"stock_name": "test"})
    monkeypatch.setattr(AnalysisService, "analyze_stock", service)
    executor.run()
    assert service.call_args.kwargs["model_source"] == SOURCE
    assert service.call_args.kwargs["skills"] == ["all"]
    assert service.call_args.kwargs["send_notification"] is False
    validate.assert_called_once_with(None, SOURCE)


@pytest.mark.parametrize("stream", [False, True])
def test_chat_explicit_source_uses_real_status_factory_and_persists_failure(tmp_path, monkeypatch, stream):
    from api.v1.endpoints import agent
    from src.auth import COOKIE_NAME
    from src.services.agent_chat_session_service import AgentChatSessionService
    from src.storage import DatabaseManager

    origin = "http://127.0.0.1:8765"
    app = FastAPI()
    app.state.chatgpt_origin = origin
    app.include_router(agent.router)
    db = DatabaseManager(f"sqlite:///{tmp_path / 'chat.db'}")
    app.dependency_overrides[agent.get_agent_chat_session_service] = lambda: AgentChatSessionService(db)
    monkeypatch.setattr("src.auth.is_auth_enabled", lambda: True)
    monkeypatch.setattr("src.auth.verify_session", lambda cookie: cookie == "valid")
    monkeypatch.setattr(agent, "get_config", lambda: Config())
    service = SimpleNamespace(validate=Mock())
    monkeypatch.setattr("src.services.agent_backend_status_service.get_chatgpt_service", lambda: service)
    monkeypatch.setattr("src.agent.chatgpt_adapter.get_chatgpt_service", lambda: service)
    upstream = Mock(side_effect=ChatGPTError("chatgpt_timeout", "request timed out"))
    monkeypatch.setattr("src.agent.chatgpt_adapter.request_responses", upstream)
    client = TestClient(app, base_url=origin)
    client.cookies.set(COOKIE_NAME, "valid")
    assert client.get("/status", params=SOURCE.model_dump()).json()["available"]
    endpoint = "/chat/stream" if stream else "/chat"
    response = client.post(endpoint, headers={"Origin": origin}, json={
        "message": "你好", "session_id": "siwc-failed-chat", "model_source": SOURCE.model_dump(),
    })
    assert response.status_code == 200
    assert "chatgpt_timeout" in response.text
    if stream:
        assert '"type": "accepted"' in response.text
    else:
        assert not response.json()["success"]
    upstream.assert_called_once()
    visible = db.get_visible_conversation_messages("siwc-failed-chat")
    assert [(entry["role"], entry["content"]) for entry in visible] == [
        ("user", "你好"), ("assistant", "[分析失败] chatgpt_timeout · request timed out"),
    ]


def test_newest_successful_catalog_owns_validation(oauth, monkeypatch):
    expire_connection(oauth)
    monkeypatch.setattr(oauth, "_bearer", lambda _: "fixture")
    entered, release = Event(), Event()

    def catalog(*args, **kwargs):
        slug = SOURCE.model
        if not entered.is_set():
            entered.set()
            assert release.wait(3)
            slug = "older-model"
        return {"models": [{"slug": slug, "visibility": "list"}]}

    monkeypatch.setattr(oauth, "_json", catalog)
    with ThreadPoolExecutor() as executor:
        older = executor.submit(oauth.models, SOURCE.connection_id, refresh=True)
        try:
            assert entered.wait(2)
            newest = oauth.models(SOURCE.connection_id, refresh=True)
        finally:
            release.set()
        assert older.result(timeout=2) == newest
    oauth.validate(SOURCE)


def test_switching_saved_accounts_reuses_registration_and_host(oauth, monkeypatch):
    oauth._save({"registration": REGISTRATION, "host_id": "original-host"})
    grants = [token_body("openid"), token_body(), token_body()]
    monkeypatch.setattr(oauth, "_grant_request", Mock(side_effect=grants))
    monkeypatch.setattr(oauth, "_revoke_before", Mock(return_value=True))
    monkeypatch.setattr(oauth, "_identity", lambda attempt, *args: {
        "sub": "account" if attempt["registration"] else "other", "email": "same@example.org",
    })

    def authorize(registration_id, issued):
        started = oauth.connect(None, registration_id=registration_id)
        params = parse_qs(urlsplit(started["authorization_url"]).query)
        attempt = oauth.pending
        oauth._complete(attempt, {"client_id": [issued], "code": ["fixture"]})
        attempt["thread"].join(2)
        return params

    authorize("issued", "issued")
    assert oauth.status()["error"] == "chatgpt_plan_permission_required"
    authorize(None, "other-client")
    status = oauth.status()
    assert {a["id"] for a in status["accounts"]} == {"issued", "other-client"}
    oauth.disconnect(None, connection_id=status["connection_id"])
    params = authorize("issued", "issued")
    assert params["prompt"] == ["consent"]
    assert params["client_id"] == ["issued"] and params["ext_agent_host_id"] == ["original-host"]
    assert oauth.status()["connected"] and oauth.status()["registration_id"] == "issued"


@pytest.mark.parametrize("failure", ["save", "malformed"])
def test_failed_activation_never_publishes_credentials(oauth, monkeypatch, failure):
    attempt = begin(oauth)
    body = token_body()
    if failure == "malformed":
        body["refresh_token"] = {"invalid": True}
    else:
        monkeypatch.setattr(oauth, "_save", Mock(side_effect=OSError("fixture")))
    monkeypatch.setattr(oauth, "_grant_request", Mock(return_value=body))
    monkeypatch.setattr(oauth, "_identity", lambda *_: {"sub": "account"})
    revoke = Mock(return_value=True)
    monkeypatch.setattr(oauth, "_revoke_before", revoke)
    oauth._complete(attempt, {"code": ["code"]})
    assert not oauth.status()["connected"] and oauth.pending is None
    if failure == "save":
        assert revoke.call_args.args[1:3] == ("issued", "refresh-new")
    else:
        assert oauth.status()["error"] == "chatgpt_protocol_error"
        revoke.assert_not_called()


def test_completed_calls_reach_ledger_before_local_validation(monkeypatch, tmp_path):
    from src.agent.runner import run_agent_loop
    from src.agent.tools.registry import ToolRegistry
    from src.storage import DatabaseManager, LLMUsage

    config = Config(llm_prompt_cache_telemetry_enabled=False)
    db = DatabaseManager(f"sqlite:///{tmp_path / 'completed.db'}")
    monkeypatch.setattr(Config, "_instance", config)
    monkeypatch.setattr(DatabaseManager, "get_instance", lambda: db)
    service = SimpleNamespace(start_request=lambda source, send: send("fixture"), ensure_active=Mock())
    monkeypatch.setattr("src.llm.chatgpt_generation_backend.get_chatgpt_service", lambda: service)
    monkeypatch.setattr("src.agent.chatgpt_adapter.get_chatgpt_service", lambda: service)
    completions = iter([('{"sentiment_score":50}', 13), ('{"sentiment_score":60}', 21), ("invalid", 8), ("", 34)])

    def upstream(request):
        content, tokens = next(completions)
        event = {"type": "response.completed", "sequence_number": 1, "response": {
            "id": f"fixture-{tokens}", "status": "completed", "model": SOURCE.model,
            "output": [item(content)], "usage": {"input_tokens": tokens, "output_tokens": 0, "total_tokens": tokens},
        }}
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"},
                              content=f"data: {json.dumps(event)}\n\n")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda transport, request: upstream(request))
    analyzer = GeminiAnalyzer(config=config, generation_backend=SiwcGenerationBackend(SOURCE, 5), generation_source=SOURCE)
    monkeypatch.setattr(analyzer, "_check_content_integrity", Mock(side_effect=[(False, ["analysis_summary"]), (True, [])]))
    assert analyzer.analyze({"code": "600519", "today": {}}).success
    assert not analyzer.analyze({"code": "600519", "today": {}}).success
    result = run_agent_loop(messages=MESSAGES.copy(), tool_registry=ToolRegistry(), llm_adapter=ChatGPTToolAdapter(SOURCE, 5))
    assert not result.success and result.total_tokens == 34
    with db.session_scope() as session:
        rows = session.query(LLMUsage).order_by(LLMUsage.id).all()
        assert [(r.call_type, r.stock_code, r.total_tokens) for r in rows] == [
            ("analysis", "600519", 13), ("analysis", "600519", 21), ("analysis", "600519", 8), ("agent", None, 34),
        ]
        assert all(r.cache_observation is None for r in rows)
