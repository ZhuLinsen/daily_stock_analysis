# -*- coding: utf-8 -*-
"""Web 意图层 SSE 流集成回归测试。

覆盖两类行为约束：
- 规则无解时意图解析会同步调用 LLM（8s 超时 + 一次重试），必须移出事件
  循环线程，不能阻塞 SSE 首包；
- 确认分支必须保持 accepted 提交边界（accepted 为首事件），否则 Web
  store 会把澄清场景判成协议错误。

终态契约回归：
- 确认分支失败（api/v1/endpoints/agent.py 会话历史写入异常、
  src/agent/web_intent_resolver.py 构建器异常）时，流只以唯一终态
  error（error_code=confirmation_failed）收尾，绝不再发 done ——
  前端统一消费策略按"读到终态事件（done/error）即收尾"工作，
  本文件显式锁定"确认失败仅 error 终态、不走 done"的行为。
"""

import asyncio
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.agent.conversation import ConversationSession
from src.agent.web_intent_resolver import (
    WebIntent, WebIntentResolution, WebIntentResolver,
)
from src.config import Config
from src.services.agent_chat_session_service import AgentChatSessionService
from src.services.name_to_code_resolver import Stock
from src.storage import DatabaseManager

import api.v1.endpoints.agent as agent_endpoint


@pytest.fixture(autouse=True)
def _restore_resolver_state():
    """快照/还原 name_to_code_resolver 模块级可变状态，防止本文件集成用例
    触发真实 AkShare 扩展（extend_AkShare 合并全局 stockDB 并置位
    _akshare_merged）后泄漏给同进程内后续运行的测试文件。"""
    from src.services import name_to_code_resolver as resolver_mod

    db = dict(resolver_mod.stockDB)
    cache = resolver_mod._akshare_cache
    merged = resolver_mod._akshare_merged
    yield
    resolver_mod.stockDB.clear()
    resolver_mod.stockDB.update(db)
    resolver_mod._akshare_cache = cache
    resolver_mod._akshare_merged = merged
    # stockDB 原地增删，按对象身份缓存的名称/拼音列表可能已陈旧，强制重建
    resolver_mod._database_names_cache[:] = [None, None, None]


def setup_function() -> None:
    DatabaseManager.reset_instance()
    Config.reset_instance()


def teardown_function() -> None:
    DatabaseManager.reset_instance()
    Config.reset_instance()


def _intent_config(**overrides):
    values = {
        "agent_backend": "auto",
        "is_agent_available": lambda: True,
        "report_language": "zh",
        "agent_web_intent_enabled": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _result(*, backend: str = "litellm", success: bool = True):
    return SimpleNamespace(
        success=success,
        content="ok" if success else "",
        error=None,
        total_steps=1,
        backend=backend,
        error_code=None,
    )


def _executor(result=None) -> MagicMock:
    executor = MagicMock()
    executor.prepare_turn.return_value = object()
    executor.execute_turn.return_value = result or _result()
    return executor


def _ambiguous_resolution() -> WebIntentResolution:
    """多候选股票（hk 09988 / us BABA）→ 需要用户确认。"""
    return WebIntentResolution(
        intent=WebIntent.STOCK_RESEARCH,
        confidence=0.85,
        source="rule",
        candidates=[
            Stock("09988", "阿里巴巴", "hk"),
            Stock("BABA", "阿里巴巴", "us"),
        ],
        needs_confirmation=True,
        reason="ambiguous_stock_name",
        pending_action={
            "action": "confirm_stock",
            "candidates": [
                {"code": "09988", "name": "阿里巴巴", "market": "hk"},
                {"code": "BABA", "name": "阿里巴巴", "market": "us"},
            ],
        },
    )


def _simple_resolution() -> WebIntentResolution:
    """唯一已解析股票（600519）→ 无需确认。"""
    return WebIntentResolution(
        intent=WebIntent.STOCK_RESEARCH,
        confidence=0.9,
        source="rule",
        stocks=[Stock("600519", "贵州茅台", "a")],
        reason="explicit_stock",
    )


async def _immediate_to_thread(func, /, *args, **kwargs):
    """测试替身：把 to_thread 变成同步直调，避免真实线程池。"""
    return func(*args, **kwargs)


async def _collect_stream_events(request: "agent_endpoint.ChatRequest") -> list[dict]:
    response = await agent_endpoint.agent_chat_stream(
        request,
        session_service=AgentChatSessionService(),
    )
    return [
        json.loads(chunk.removeprefix("data: ").strip())
        async for chunk in response.body_iterator
    ]


def test_confirmation_branch_keeps_accepted_commit_boundary() -> None:
    """确认分支必须保持 accepted 提交边界。

    Web store 要求第一条事件必须是 accepted（否则抛协议错误），因此确认分支
    的事件序列必须是 accepted → intent_resolved → action_required → done。
    """
    executor = _executor(_result())
    config = _intent_config()
    captured: dict = {}

    async def exercise() -> None:
        with patch("api.v1.endpoints.agent.get_config", return_value=config), \
             patch("api.v1.endpoints.agent.asyncio.to_thread", side_effect=_immediate_to_thread), \
             patch("src.agent.conversation.conversation_manager") as cm, \
             patch("src.agent.web_intent_resolver.WebIntentResolver") as resolver_cls, \
             patch("api.v1.endpoints.agent._build_executor", return_value=executor):
            session = ConversationSession(session_id="confirm-session")
            cm.get_or_create.return_value = session
            resolver_cls.return_value.resolve.return_value = _ambiguous_resolution()
            captured["events"] = await _collect_stream_events(
                agent_endpoint.ChatRequest(
                    message="阿里巴巴",
                    session_id="confirm-session",
                )
            )
            captured["cm"] = cm

    asyncio.run(exercise())
    events = captured["events"]
    cm = captured["cm"]
    assert [event["type"] for event in events] == [
        "accepted",
        "intent_resolved",
        "action_required",
        "done",
    ]
    assert events[0]["backend"] == "litellm"
    assert events[1]["intent"] == "stock_research"
    assert events[2]["action"] == "confirm_stock"
    assert "阿里巴巴" in events[3]["content"]
    assert events[3]["success"] is True
    # 确认分支短路：不进入 Agent 编排
    executor.prepare_turn.assert_not_called()
    executor.execute_turn.assert_not_called()
    # 会话历史写入 user 消息 + 澄清回复
    cm.add_message.assert_any_call("confirm-session", "user", "阿里巴巴")
    cm.add_message.assert_any_call("confirm-session", "assistant", events[3]["content"])


def _assert_confirmation_failure_terminal(events: list[dict], executor: MagicMock) -> None:
    """确认失败终态契约：accepted → error，绝无 done，且不进入 Agent 编排。

    前端统一消费策略按事件类型分发、读到终态事件（done/error）即收尾：
    确认失败后流必须以唯一终态 error 结束，绝不追加 done —— 否则前端会
    把 done 当"分析成功"消费，歧义请求被静默放行；也不得退回 Agent 执行
    未确认的歧义请求，否则绕过"未确认不执行"安全门。
    """
    types = [event["type"] for event in events]
    assert types == ["accepted", "error"]
    assert "done" not in types
    assert not any(event["type"] == "intent_resolved" for event in events)
    assert not any(event["type"] == "action_required" for event in events)
    terminal = events[-1]
    assert terminal["type"] == "error"
    assert terminal["error_code"] == "confirmation_failed"
    assert terminal["message"] == "无法完成该请求的确认流程，请稍后重试"
    assert terminal["backend"] == "litellm"
    # 确认失败仍保持短路：绝不执行未确认的歧义请求
    executor.prepare_turn.assert_not_called()
    executor.execute_turn.assert_not_called()


def test_confirmation_failure_sends_only_error_terminal_no_done() -> None:
    """确认分支失败（agent.py 异常路径：会话历史写入抛错）仅发 error 终态。

    模拟 conversation_manager.add_message 写入 SQLite 失败：确认分支的
    except 必须保持短路，流事件序列为 accepted → error（唯一终态），
    绝不追加 done、绝不退回 Agent 编排执行未确认的歧义请求。
    """
    config = _intent_config()
    executor = _executor(_result())

    async def exercise() -> list[dict]:
        with patch("api.v1.endpoints.agent.get_config", return_value=config), \
             patch("api.v1.endpoints.agent.asyncio.to_thread", side_effect=_immediate_to_thread), \
             patch("src.agent.conversation.conversation_manager") as cm, \
             patch("src.agent.web_intent_resolver.WebIntentResolver") as resolver_cls, \
             patch("api.v1.endpoints.agent._build_executor", return_value=executor):
            cm.get_or_create.return_value = ConversationSession(session_id="confirm-fail-session")
            cm.add_message.side_effect = RuntimeError("session history write failed")
            resolver_cls.return_value.resolve.return_value = _ambiguous_resolution()
            return await _collect_stream_events(
                agent_endpoint.ChatRequest(
                    message="阿里巴巴",
                    session_id="confirm-fail-session",
                )
            )

    events = asyncio.run(exercise())
    _assert_confirmation_failure_terminal(events, executor)


def test_confirmation_failure_via_intent_builder_only_error_terminal() -> None:
    """确认分支失败（web_intent_resolver.py 异常路径：澄清构建器抛错）仅发 error 终态。

    build_clarification_message 属于 web_intent_resolver.py 的构建函数，
    是确认分支内最先被调用的模块函数：它抛错时同样必须保持短路终态契约
    （accepted → error，无 done），与会话历史写入失败的路径行为一致，
    保证前端统一消费策略对"确认失败"只有一种终态可收。
    """
    config = _intent_config()
    executor = _executor(_result())

    async def exercise() -> list[dict]:
        # build_clarification_message 在 agent_chat_stream 函数内延迟 import，
        # 需在源模块 src.agent.web_intent_resolver 上打补丁才能影响确认分支
        # （patch 窗口内函数体的 from ... import 会绑定被替换的属性）
        with patch("api.v1.endpoints.agent.get_config", return_value=config), \
             patch("api.v1.endpoints.agent.asyncio.to_thread", side_effect=_immediate_to_thread), \
             patch("src.agent.conversation.conversation_manager") as cm, \
             patch("src.agent.web_intent_resolver.WebIntentResolver") as resolver_cls, \
             patch("src.agent.web_intent_resolver.build_clarification_message",
                   side_effect=RuntimeError("clarification build failed")), \
             patch("api.v1.endpoints.agent._build_executor", return_value=executor):
            cm.get_or_create.return_value = ConversationSession(session_id="clarify-fail-session")
            resolver_cls.return_value.resolve.return_value = _ambiguous_resolution()
            return await _collect_stream_events(
                agent_endpoint.ChatRequest(
                    message="阿里巴巴",
                    session_id="clarify-fail-session",
                )
            )

    events = asyncio.run(exercise())
    _assert_confirmation_failure_terminal(events, executor)


def test_confirmed_compare_turn_reaches_prepare_turn_with_compare_scope() -> None:
    """确认消费轮的多股比较必须把比较对带入 prepare_turn（OR-COR-1f4c2d7a）。

    "对比阿里巴巴和腾讯控股" 触发歧义确认（阿里 09988/BABA）后，用户回复
    "港股"：确认轮的 primary_stock_code 为空串，若端点只转发该单码字段，
    prepare_turn 只能看到裸确认回复（"港股"），既无比较股票也无原始请求，
    工具调用不再受比较对约束。端点必须把已解析比较对 + 原始请求注入
    请求上下文。
    """
    config = _intent_config()
    executor = _executor(_result())
    confirmed_resolution = WebIntentResolution(
        intent=WebIntent.STOCK_RESEARCH,
        confidence=0.95,
        source="confirmation",
        stocks=[
            Stock("09988", "阿里巴巴", "hk"),
            Stock("00700", "腾讯控股", "hk"),
        ],
        reason="confirmed_stock",
        original_request="对比阿里巴巴和腾讯控股",
    )

    async def exercise() -> list[dict]:
        with patch("api.v1.endpoints.agent.get_config", return_value=config), \
             patch("api.v1.endpoints.agent.asyncio.to_thread", side_effect=_immediate_to_thread), \
             patch("src.agent.conversation.conversation_manager") as cm, \
             patch("src.agent.web_intent_resolver.WebIntentResolver") as resolver_cls, \
             patch("api.v1.endpoints.agent._build_executor", return_value=executor):
            cm.get_or_create.return_value = ConversationSession(
                session_id="confirm-compare-session"
            )
            resolver_cls.return_value.resolve.return_value = confirmed_resolution
            return await _collect_stream_events(
                agent_endpoint.ChatRequest(
                    message="港股",
                    session_id="confirm-compare-session",
                )
            )

    events = asyncio.run(exercise())
    assert [event["type"] for event in events] == ["accepted", "intent_resolved", "done"]
    executor.execute_turn.assert_called_once()
    kwargs = executor.prepare_turn.call_args.kwargs
    # 历史保真：本轮用户消息仍是确认回复本身，不被改写
    assert kwargs["message"] == "港股"
    # 已解析比较对与原始请求进入本轮上下文，prepare_agent_chat 才能构建
    # 比较作用域（否则工具调用不受比较对约束）
    assert kwargs["context"]["resolved_stock_codes"] == ["09988", "00700"]
    assert kwargs["context"]["web_intent_original_request"] == "对比阿里巴巴和腾讯控股"
    # 多股比较轮绝不锁定单一主股票
    assert not kwargs["context"].get("stock_code")


def test_confirmation_failure_clears_stale_pending_actions() -> None:
    """确认分支失败必须清空会话 pending_actions。

    修复前：apply_resolution_to_session 先写入 pending_actions，随后会话历史
    写入抛错，except 只发 error 终态、不清会话状态；下一轮 resolve() 会把
    用户的新消息（如"港股"）误当成上一轮失败确认流程的回复直接确认
    （source="confirmation"，股票 09988）。
    修复后：失败路径同步清空 pending_actions，下一轮按新消息重新分类。
    """
    config = _intent_config()
    executor = _executor(_result())
    captured: dict = {}

    async def exercise() -> list[dict]:
        with patch("api.v1.endpoints.agent.get_config", return_value=config), \
             patch("api.v1.endpoints.agent.asyncio.to_thread", side_effect=_immediate_to_thread), \
             patch("src.agent.conversation.conversation_manager") as cm, \
             patch("src.agent.web_intent_resolver.WebIntentResolver") as resolver_cls, \
             patch("api.v1.endpoints.agent._build_executor", return_value=executor):
            session = ConversationSession(session_id="confirm-fail-state-session")
            cm.get_or_create.return_value = session
            cm.add_message.side_effect = RuntimeError("session history write failed")
            resolver_cls.return_value.resolve.return_value = _ambiguous_resolution()
            events = await _collect_stream_events(
                agent_endpoint.ChatRequest(
                    message="阿里巴巴",
                    session_id="confirm-fail-state-session",
                )
            )
            captured["session"] = session
            return events

    events = asyncio.run(exercise())
    _assert_confirmation_failure_terminal(events, executor)

    # 会话中不得残留待确认动作
    session: ConversationSession = captured["session"]
    assert session.context.get("pending_actions") == []

    # 复核反馈反例：失败后同会话的下一轮消息不得被误消费为确认回复
    follow_up = WebIntentResolver(None).resolve(
        "港股",
        session_context=session.context,
        request_context={},
    )
    assert follow_up.source != "confirmation"
    assert not follow_up.needs_confirmation


def test_prepare_turn_failure_keeps_session_context_unchanged() -> None:
    """prepare_turn 失败时，意图层不得提前污染会话上下文。

    意图解析器在 prepare_turn 之前已完成分类（例如"分析一下贵州茅台" →
    600519 / stock_research），但 prepare_turn 失败时端点只发送
    request_not_accepted 终态；该请求不应被视作已接受的会话边界，因此
    recent_stocks / last_intent 必须保持解析前的状态；上一轮遗留的
    pending_actions 则会被清空（本用例预置为空，所以整体快照仍不变），
    否则下一轮追问（如"它还能涨吗"）会继承一个被拒绝请求的股票上下文。
    """
    config = _intent_config()
    executor = _executor(_result())
    executor.prepare_turn.side_effect = RuntimeError("prepare_turn failed")
    session = ConversationSession(session_id="prepare-fail-intent-session")
    session.update_context("recent_stocks", ["000001"])
    session.update_context("last_intent", WebIntent.GENERAL_CHAT)
    session.update_context("pending_actions", [])
    context_before = dict(session.context)

    async def exercise() -> list[dict]:
        with patch("api.v1.endpoints.agent.get_config", return_value=config), \
             patch("api.v1.endpoints.agent.asyncio.to_thread", side_effect=_immediate_to_thread), \
             patch("src.agent.conversation.conversation_manager") as cm, \
             patch("src.agent.web_intent_resolver.WebIntentResolver") as resolver_cls, \
             patch("api.v1.endpoints.agent._build_executor", return_value=executor):
            cm.get_or_create.return_value = session
            resolver_cls.return_value.resolve.return_value = _simple_resolution()
            return await _collect_stream_events(
                agent_endpoint.ChatRequest(
                    message="分析一下贵州茅台",
                    session_id=session.session_id,
                )
            )

    events = asyncio.run(exercise())

    assert [event["type"] for event in events] == ["accepted", "error"]
    terminal = events[-1]
    assert terminal["type"] == "error"
    assert terminal["error_code"] == "request_not_accepted"
    executor.execute_turn.assert_not_called()
    # 意图解析确实发生在 prepare_turn 之前（stock_code 已注入请求上下文）
    assert executor.prepare_turn.call_args.kwargs["context"]["stock_code"] == "600519"
    # 但会话上下文必须保持解析前的快照：被拒绝的请求不得成为后续追问的上下文
    assert session.context == context_before


def test_prepare_turn_failure_clears_stale_confirm_pending() -> None:
    """prepare_turn 失败且本轮为新请求时，必须清空上一轮遗留 pending_actions。

    复现：第 1 轮歧义请求写入 confirm_stock 待确认动作；第 2 轮新请求
    （如"分析一下贵州茅台"）被意图层判定为显式股票，但 prepare_turn 抛错
    走到 request_not_accepted。若不清空 pending_actions，第 3 轮无关消息
    会被 _consume_pending_action 误当成第 1 轮的确认回复，执行旧的歧义股票。
    """
    config = _intent_config()
    executor = _executor(_result())
    executor.prepare_turn.side_effect = RuntimeError("prepare_turn failed")
    session = ConversationSession(session_id="prepare-fail-stale-pending-session")
    session.update_context("recent_stocks", ["000001"])
    session.update_context("last_intent", WebIntent.GENERAL_CHAT)
    stale_pending = _ambiguous_resolution().pending_action
    session.update_context("pending_actions", [stale_pending])

    async def exercise() -> list[dict]:
        with patch("api.v1.endpoints.agent.get_config", return_value=config), \
             patch("api.v1.endpoints.agent.asyncio.to_thread", side_effect=_immediate_to_thread), \
             patch("src.agent.conversation.conversation_manager") as cm, \
             patch("src.agent.web_intent_resolver.WebIntentResolver") as resolver_cls, \
             patch("api.v1.endpoints.agent._build_executor", return_value=executor):
            cm.get_or_create.return_value = session
            resolver_cls.return_value.resolve.return_value = _simple_resolution()
            return await _collect_stream_events(
                agent_endpoint.ChatRequest(
                    message="分析一下贵州茅台",
                    session_id=session.session_id,
                )
            )

    events = asyncio.run(exercise())

    assert [event["type"] for event in events] == ["accepted", "error"]
    terminal = events[-1]
    assert terminal["type"] == "error"
    assert terminal["error_code"] == "request_not_accepted"
    executor.execute_turn.assert_not_called()
    # 意图解析确实发生在 prepare_turn 之前（stock_code 已注入请求上下文）
    assert executor.prepare_turn.call_args.kwargs["context"]["stock_code"] == "600519"
    # 被拒的新请求不污染 recent_stocks / last_intent
    assert session.context["recent_stocks"] == ["000001"]
    assert session.context["last_intent"] == WebIntent.GENERAL_CHAT
    # 但上一轮遗留的确认窗口必须关闭
    assert session.context["pending_actions"] == []

    # 复核反馈反例：后续无关消息不再被消费为确认回复
    follow_up = WebIntentResolver(None).resolve(
        "港股",
        session_context=session.context,
        request_context={},
    )
    assert follow_up.source != "confirmation"
    assert not follow_up.needs_confirmation


def test_prepare_turn_success_commits_intent_context() -> None:
    """prepare_turn 成功后才提交意图上下文，保证成功路径不回退。

    修复将 apply_resolution_to_session 从意图解析线程挪到 prepare_turn
    成功之后；本用例锁定成功路径仍会写入 recent_stocks / last_intent。
    """
    config = _intent_config()
    executor = _executor(_result())
    session = ConversationSession(session_id="prepare-ok-intent-session")

    async def exercise() -> list[dict]:
        with patch("api.v1.endpoints.agent.get_config", return_value=config), \
             patch("api.v1.endpoints.agent.asyncio.to_thread", side_effect=_immediate_to_thread), \
             patch("src.agent.conversation.conversation_manager") as cm, \
             patch("src.agent.web_intent_resolver.WebIntentResolver") as resolver_cls, \
             patch("api.v1.endpoints.agent._build_executor", return_value=executor):
            cm.get_or_create.return_value = session
            resolver_cls.return_value.resolve.return_value = _simple_resolution()
            return await _collect_stream_events(
                agent_endpoint.ChatRequest(
                    message="分析一下贵州茅台",
                    session_id=session.session_id,
                )
            )

    events = asyncio.run(exercise())

    assert [event["type"] for event in events] == [
        "accepted",
        "intent_resolved",
        "done",
    ]
    assert session.context == {
        "recent_stocks": ["600519"],
        "last_intent": WebIntent.STOCK_RESEARCH,
        "pending_actions": [],
    }


def test_intent_llm_fallback_does_not_block_event_loop() -> None:
    """规则无解 + LLM 兜底（同步阻塞调用）不得阻塞 SSE 事件循环。

    slow_resolve 模拟同步 LLM 调用阻塞 0.5s；断言 heartbeat 协程在 resolve 的
    阻塞窗口内仍能 tick。修复前 resolve 在事件循环线程内同步执行，阻塞期间
    事件循环无法调度任何协程，窗口内没有 heartbeat；修复后 resolve 走
    asyncio.to_thread，事件循环空闲，窗口内正常 tick。
    """
    config = _intent_config()
    executor = _executor(_result())
    heartbeats: list = []
    observed: dict = {}

    def slow_resolve(self, message, *, session_context=None, request_context=None):
        # 模拟规则无解时的同步 LLM 兜底调用（最多 8s 超时 + 一次重试）
        observed["resolve_start"] = time.monotonic()
        time.sleep(0.5)
        observed["resolve_end"] = time.monotonic()
        return _simple_resolution()

    async def exercise() -> list[dict]:
        with patch("api.v1.endpoints.agent.get_config", return_value=config), \
             patch("src.agent.conversation.conversation_manager") as cm, \
             patch.object(WebIntentResolver, "resolve", slow_resolve), \
             patch("api.v1.endpoints.agent._build_executor", return_value=executor):
            cm.get_or_create.return_value = ConversationSession(session_id="hb-session")

            async def heartbeat() -> None:
                for _ in range(20):
                    await asyncio.sleep(0.05)
                    heartbeats.append(time.monotonic())

            hb_task = asyncio.create_task(heartbeat())
            events = await _collect_stream_events(
                agent_endpoint.ChatRequest(
                    message="分析一下你好股份",
                    session_id="hb-session",
                )
            )
            await hb_task
            return events

    events = asyncio.run(exercise())
    # heartbeat 必须在 resolve 的同步阻塞窗口内完成至少一次，才能证明事件循环
    # 未被 LLM 兜底调用卡住（旧行为下窗口内无 tick，此断言会失败）
    within_window = any(
        observed["resolve_start"] <= tick <= observed["resolve_end"]
        for tick in heartbeats
    )
    assert within_window, "event loop was blocked during intent LLM fallback"
    assert [event["type"] for event in events] == [
        "accepted",
        "intent_resolved",
        "done",
    ]
    assert events[1]["intent"] == "stock_research"


def test_intent_resolution_runs_off_event_loop_thread() -> None:
    """意图解析（含 LLM 兜底与 AkShare 扩展）在工作线程执行，不在事件循环线程。"""
    config = _intent_config()
    executor = _executor(_result())
    main_thread_id = threading.get_ident()
    observed: dict = {}

    def fake_resolve(self, message, *, session_context=None, request_context=None):
        observed["thread_id"] = threading.get_ident()
        observed["message"] = message
        return _simple_resolution()

    async def exercise() -> list[dict]:
        with patch("api.v1.endpoints.agent.get_config", return_value=config), \
             patch("src.agent.conversation.conversation_manager") as cm, \
             patch.object(WebIntentResolver, "resolve", fake_resolve), \
             patch("api.v1.endpoints.agent._build_executor", return_value=executor):
            cm.get_or_create.return_value = ConversationSession(session_id="thread-session")
            return await _collect_stream_events(
                agent_endpoint.ChatRequest(
                    message="分析一下你好股份",
                    session_id="thread-session",
                )
            )

    events = asyncio.run(exercise())
    assert observed["thread_id"] != main_thread_id
    assert observed["message"] == "分析一下你好股份"
    assert [event["type"] for event in events] == [
        "accepted",
        "intent_resolved",
        "done",
    ]


def test_accepted_first_event_does_not_wait_for_intent_resolution() -> None:
    """accepted 首事件不得等待意图解析完成（用户气泡即时渲染回归）。

    修复前 accepted 在意图解析之后才发出：解析触发 LLM 兜底（8s 超时 + 一次
    重试）或 AkShare 扩展下载时，Web store 收不到 accepted，用户输入（如
    "分析三花"）的气泡要等解析完成后才显示。修复后 accepted 立即送达，
    解析仍阻塞在工作线程时前端就能渲染用户消息。
    """
    config = _intent_config()
    executor = _executor(_result())
    release = threading.Event()
    resolve_started = threading.Event()
    resolve_finished = threading.Event()

    def blocking_resolve(self, message, *, session_context=None, request_context=None):
        resolve_started.set()
        release.wait(timeout=5)
        resolve_finished.set()
        return _simple_resolution()

    captured: dict = {}

    async def exercise() -> None:
        with patch("api.v1.endpoints.agent.get_config", return_value=config), \
             patch("src.agent.conversation.conversation_manager") as cm, \
             patch.object(WebIntentResolver, "resolve", blocking_resolve), \
             patch("api.v1.endpoints.agent._build_executor", return_value=executor):
            cm.get_or_create.return_value = ConversationSession(session_id="early-accept-session")
            response = await agent_endpoint.agent_chat_stream(
                agent_endpoint.ChatRequest(
                    message="分析三花",
                    session_id="early-accept-session",
                ),
                session_service=AgentChatSessionService(),
            )
            iterator = response.body_iterator
            # 解析仍在阻塞时必须能读到首事件；若 accepted 等解析完成才发，
            # 此 anext 会阻塞直到 wait_for 超时。
            captured["first"] = json.loads(
                (await asyncio.wait_for(anext(iterator), timeout=5)).removeprefix("data: ").strip()
            )
            captured["resolved_before_first"] = resolve_finished.is_set()
            release.set()
            captured["rest"] = [
                json.loads(chunk.removeprefix("data: ").strip())
                async for chunk in iterator
            ]

    async def main() -> None:
        task = asyncio.create_task(exercise())
        deadline = time.monotonic() + 5
        while not resolve_started.is_set() and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        assert resolve_started.is_set(), "intent resolution never started"
        await task

    asyncio.run(main())
    first = captured["first"]
    rest = captured["rest"]
    assert first["type"] == "accepted"
    assert not captured["resolved_before_first"], (
        "accepted was emitted only after intent resolution finished"
    )
    assert [event["type"] for event in rest] == ["intent_resolved", "done"]
    assert rest[0]["intent"] == "stock_research"


def test_intent_layer_default_off_keeps_legacy_stream() -> None:
    """未声明 agent_web_intent_enabled 的临时 Config 走原路径（无意图事件）。"""
    config = SimpleNamespace(
        agent_backend="auto",
        is_agent_available=lambda: True,
        report_language="zh",
    )
    executor = _executor(_result())

    async def exercise() -> list[dict]:
        with patch("api.v1.endpoints.agent.get_config", return_value=config), \
             patch("api.v1.endpoints.agent.asyncio.to_thread", side_effect=_immediate_to_thread), \
             patch("api.v1.endpoints.agent._build_executor", return_value=executor):
            return await _collect_stream_events(
                agent_endpoint.ChatRequest(
                    message="分析 600519",
                    session_id="legacy-session",
                )
            )

    events = asyncio.run(exercise())
    assert [event["type"] for event in events] == ["accepted", "done"]
