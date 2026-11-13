# -*- coding: utf-8 -*-
"""
Passive-reply chunking for the WeCom AI Bot (Issue #755 r6, review
OR-COR-9d6c37af).

`_reply_to_frame` (the passive aibot_respond_msg path) previously put the
full text into ONE markdown frame without consuming the declared 4000-byte
channel cap — e.g. `/watchlist list` with hundreds of stocks exceeded the
limit and the whole reply was rejected, so the user got nothing.

Contract (r6):
- reply text ≤4000 UTF-8 bytes → single respond frame (no change).
- reply text >4000 bytes → split with the SAME `_split_wecom_aibot_text_chunks`
  used by the active push path and sent as MULTIPLE aibot_respond_msg frames
  on the same req_id (SDK maintains a serialized per-req_id reply queue —
  stream replies already rely on multi-frame per req_id). Each chunk
  independently passes quota / the shared concurrency gate (chunking consumes
  more quota, expected, consistent with the active path). A synchronous chunk
  failure logs the sent-chunk count and returns False; already-sent frames
  are not rolled back.
"""

import os
import sys
import time
from unittest import mock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import bot.platforms.wecom_aibot as wecom_aibot
from bot.platforms.wecom_aibot import (
    WecomAibotHandler,
    _WECOM_AIBOT_OUTBOUND_GATE,
    _split_wecom_aibot_text_chunks,
)

MAX_BYTES = 4000


class _FakeFuture:
    """Fake scheduled-send future: completes immediately with the given ack
    (mirrors the r4-era _CompletedFakeFuture pattern, errcode configurable)."""

    def __init__(self, errcode=0):
        self._errcode = errcode

    def add_done_callback(self, cb):
        cb(self)

    def result(self, timeout=None):
        return {"errcode": self._errcode}


def _handler_with_recording_schedule(errcodes=None):
    """Handler whose _schedule_reply closes the coroutine and returns fake
    futures whose acks follow the errcodes sequence (default all 0); the
    sdk_client.reply mock records the actually dispatched frames."""
    handler = WecomAibotHandler()
    handler._loop = mock.MagicMock()
    handler._loop.is_closed.return_value = False
    handler.sdk_client = mock.MagicMock()
    counter = {"n": 0}

    def _fake_schedule(coro):
        coro.close()
        index = counter["n"]
        counter["n"] += 1
        if errcodes is None:
            return _FakeFuture(errcode=0)
        return _FakeFuture(errcode=errcodes[min(index, len(errcodes) - 1)])

    return handler, handler.sdk_client.reply, _fake_schedule


def _long_chinese_reply(line_count=50):
    """~5KB multi-line Chinese reply (>4000B)."""
    return "\n".join(
        f"{i+1}. 贵州茅台600519：收盘价与均线出现背离，量能温和放大，评级中性偏多。"
        for i in range(line_count)
    )


@pytest.fixture(autouse=True)
def _fresh_gate():
    wecom_aibot._reset_outbound_gate()
    yield
    wecom_aibot._reset_outbound_gate()


def _reply_frame(chat_id="c1"):
    return {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "req-1"},
        "body": {
            "msgtype": "text",
            "msgid": "m",
            "aibotid": "bot-abc",
            "chattype": "single",
            "text": {"content": "自选股"},
            "from": {"userid": chat_id},
        },
    }


class TestReplyChunking:
    def test_short_reply_single_frame_regression(self):
        reply = "当前自选股（2 只）：600519, 000858"
        assert len(reply.encode("utf-8")) <= MAX_BYTES
        handler, reply_mock, fake_schedule = _handler_with_recording_schedule()
        with mock.patch.object(handler, "_schedule_reply", side_effect=fake_schedule):
            assert handler._reply_to_frame(_reply_frame(), reply) is True
        reply_mock.assert_called_once()
        body = reply_mock.call_args.args[1]
        assert body["markdown"]["content"] == reply

    def test_oversized_reply_splits_into_multiple_frames(self):
        """RED(OR-COR-9d6c37af)：>4000B 回复按共享切分器多帧发送。"""
        reply = _long_chinese_reply()
        assert len(reply.encode("utf-8")) > MAX_BYTES
        handler, reply_mock, fake_schedule = _handler_with_recording_schedule()
        with mock.patch.object(handler, "_schedule_reply", side_effect=fake_schedule):
            assert handler._reply_to_frame(_reply_frame(), reply) is True

        calls = reply_mock.call_args_list
        assert len(calls) >= 2

        pieces = []
        for call in calls:
            body = call.args[1]
            assert body["msgtype"] == "markdown"
            piece = body["markdown"]["content"]
            encoded = piece.encode("utf-8")
            # 每帧 ≤4000B（同一上限同源）
            assert len(encoded) <= MAX_BYTES
            # 多字节字符无损坏：逐帧合法解码
            assert piece == encoded.decode("utf-8")
            pieces.append(piece)

        # 语义还原：拼接包含原文全部行
        joined = "\n".join(pieces)
        for line in reply.split("\n"):
            assert line in joined

        # 逐帧配额记账：3 帧消耗 3 条分钟配额
        chunk_total = len(calls)
        assert (
            handler._outbound_minute_limiter.get_remaining("c1")
            == 30 - chunk_total
        )

    def test_single_oversized_line_reply_cut_multibyte_safe(self):
        """单行超长回复（6000B 全中文）→ 字节安全切分、拼接无损。"""
        reply = "贵州茅台" * 1500
        handler, reply_mock, fake_schedule = _handler_with_recording_schedule()
        with mock.patch.object(handler, "_schedule_reply", side_effect=fake_schedule):
            assert handler._reply_to_frame(_reply_frame(), reply) is True

        calls = reply_mock.call_args_list
        assert len(calls) >= 2
        pieces = [
            call.args[1]["markdown"]["content"] for call in calls
        ]
        for piece in pieces:
            assert len(piece.encode("utf-8")) <= MAX_BYTES
        assert "".join(pieces) == reply

    def test_chunk_failure_logs_sent_count_and_returns_false(self, caplog):
        """同步分片失败（调度异常）→ 部分交付可观测、整体 False。"""
        import logging

        reply = _long_chinese_reply()
        handler, reply_mock, fake_schedule = _handler_with_recording_schedule()

        real_schedule = fake_schedule
        state = {"n": 0, "closed_undispatched": 0}

        def _failing_schedule(coro):
            state["n"] += 1
            if state["n"] == 2:
                # 第 2 帧构造已完成（reply mock 已记录），调度被拒：
                # 协程关闭、不再派发。
                coro.close()
                state["closed_undispatched"] += 1
                raise RuntimeError("loop gone mid-chunks")
            return real_schedule(coro)

        with mock.patch.object(
            handler, "_schedule_reply", side_effect=_failing_schedule
        ), caplog.at_level(logging.ERROR):
            assert handler._reply_to_frame(_reply_frame(), reply) is False

        # 两帧均进入构造；第 2 帧在调度层失败（协程关闭、未派发）
        assert reply_mock.call_count == 2
        assert state["closed_undispatched"] == 1
        assert "已发送 1" in caplog.text or "1/2" in caplog.text

    def test_gate_full_rejects_oversized_reply_with_quota_refund(self):
        """闸满（≤3 在途被占）→ 超限回复首片即拒、配额退还、零发送。"""
        reply = _long_chinese_reply()
        handler, reply_mock, fake_schedule = _handler_with_recording_schedule()
        slots = [_WECOM_AIBOT_OUTBOUND_GATE.try_acquire("c1") for _ in range(3)]
        assert all(slot is not None for slot in slots)

        with mock.patch.object(handler, "_schedule_reply", side_effect=fake_schedule):
            assert handler._reply_to_frame(_reply_frame(), reply) is False

        reply_mock.assert_not_called()
        assert handler._outbound_minute_limiter.get_remaining("c1") == 30
        assert _WECOM_AIBOT_OUTBOUND_GATE.in_flight("c1") == 3

        slots[0].release()
        with mock.patch.object(handler, "_schedule_reply", side_effect=fake_schedule):
            assert handler._reply_to_frame(_reply_frame(), reply) is True


class TestSerialChunkCompletion:
    """RED(OR-COR-82e5ad71)：分片必须串行等回执完成再发下一片。

    _LatentFuture 不立即完成（真实语义 stub）：调度后并发闸槽位真实在途
    （≤3 闸约束生效），result() 经短暂延迟返回 ack 0。旧行为（调度后立即
    调度下一片）会在第 4 片被自身并发闸截断（12008B→4 片只发出 3 片）。
    """

    def _build_four_chunk_reply(self):
        reply = ""
        while len(_split_wecom_aibot_text_chunks(reply)) < 4:
            reply += "贵州茅台600519：收盘价与均线出现背离，量能温和放大，评级中性偏多。\n"
        chunks = _split_wecom_aibot_text_chunks(reply)
        assert len(chunks) == 4
        return reply

    def test_all_chunks_sent_with_serial_wait(self):
        reply = self._build_four_chunk_reply()
        handler, reply_mock, _ = _handler_with_recording_schedule()

        snapshots = []

        class _LatentFuture:
            """真实语义 stub：挂起、不立即完成；result 消耗短暂异步时延。"""

            def __init__(self, errcode=0):
                self._errcode = errcode
                self._callbacks = []

            def add_done_callback(self, cb):
                self._callbacks.append(cb)  # 注册但不立即触发（真实异步占用）

            def result(self, timeout=None):
                # 在途快照：本片等待期间闸内应只有本片（前片已完成释放）
                snapshots.append(_WECOM_AIBOT_OUTBOUND_GATE.in_flight("c1"))
                time.sleep(0.05)
                return {"errcode": self._errcode}

        def _schedule(coro):
            coro.close()
            return _LatentFuture(0)

        import time as _time
        with mock.patch.object(handler, "_schedule_reply", side_effect=_schedule),                 mock.patch.object(handler, "_REPLY_ACK_TIMEOUT_SECONDS", 5.0, create=True):
            assert handler._reply_to_frame(_reply_frame(), reply) is True

        # 4 片全部发出（旧行为：第 4 片被自身并发闸截断，只发出 3 片）
        assert reply_mock.call_count == 4
        assert len(snapshots) == 4
        # 串行：每片等待期间在途恒为 1（前片已完成并释放槽位）
        assert snapshots == [1, 1, 1, 1]
        # 全部完成后闸清空
        assert _WECOM_AIBOT_OUTBOUND_GATE.in_flight("c1") == 0
        # 逐片配额记账：4 片消耗 4 条分钟配额
        assert handler._outbound_minute_limiter.get_remaining("c1") == 26


if __name__ == "__main__":
    pytest.main([__file__])
