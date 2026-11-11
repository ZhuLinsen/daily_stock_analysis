# -*- coding: utf-8 -*-
"""
Long-report chunking for the WeCom AI Bot push transport (Issue #755 r5,
review OR-COR-7ab3e812).

`send_to_chat` is the single choke point shared by the static push channel
and the source-conversation report return path. Before r5 both sent the full
report as ONE markdown message while `notification_capabilities` declared
`max_text_bytes=4000` for the channel (never consumed by any send path) —
oversized reports were rejected wholesale by WeCom (ack errcode != 0), so the
source conversation silently lost its report with no recovery.

Contract (r5):
- content ≤4000 UTF-8 bytes → sent as-is in a single frame (no change).
- content >4000 bytes → split at paragraph/line boundaries (byte-safe: never
  splits a multibyte UTF-8 character) and sent sequentially; each chunk
  independently passes through rate limiting / the concurrency gate / quota
  accounting (more quota consumed per chunk is expected); any chunk failure →
  overall False with the sent-chunk count logged.
"""

import asyncio
import os
import sys
import threading
import time
from unittest import mock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import bot.platforms.wecom_aibot as wecom_aibot
from bot.platforms.wecom_aibot import (
    _split_wecom_aibot_text_chunks,
    _wecom_aibot_max_text_bytes,
    WecomAibotHandler,
)


def _ack_coro(errcode=0):
    return asyncio.sleep(0, result={"errcode": errcode})


def _real_send_client(errcodes=None):
    """Client assembled for real send_to_chat execution (running loop); the
    n-th send ack resolves with errcodes[n-1] (default 0)."""
    client = wecom_aibot.WecomAibotClient.__new__(wecom_aibot.WecomAibotClient)
    client._running = True
    client._loop = asyncio.new_event_loop()
    client._sdk_client = mock.MagicMock()
    counter = {"n": 0}

    def _next_ack(chatid, body):
        index = counter["n"]
        counter["n"] += 1
        if errcodes is None:
            return asyncio.sleep(0, result={"errcode": 0})
        return asyncio.sleep(0, result={"errcode": errcodes[min(index, len(errcodes) - 1)]})

    client._sdk_client.send_message = mock.MagicMock(side_effect=_next_ack)
    client._handler = WecomAibotHandler()
    thread = threading.Thread(target=client._loop.run_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    def _shutdown():
        client._loop.call_soon_threadsafe(client._loop.stop)
        thread.join(timeout=2)
        client._loop.close()

    return client, _shutdown


def _multiline_chinese_report(line_count=24, chinese_per_line=66):
    """~24 × 198B ≈ 4752 UTF-8 bytes of Chinese lines (>4000)."""
    return "\n".join(
        f"- 贵州茅台600519 第{i}段：今日收盘价与均线系统出现趋势性背离，"
        f"量能温和放大，技术面评级为中性偏多。"
        + "酒" * chinese_per_line
        for i in range(line_count)
    )


MAX_BYTES = 4000


class TestShortReportRegression:
    def test_short_report_still_sent_in_single_frame(self):
        """≤4000 字节的报告保持原样单条发送（现路径零变化）。"""
        assert _wecom_aibot_max_text_bytes() == MAX_BYTES
        content = "- 600519 贵州茅台：技术面中性偏多，量能温和。" * 10
        assert len(content.encode("utf-8")) <= MAX_BYTES

        client, shutdown = _real_send_client()
        try:
            assert client.send_to_chat("c1", content) is True
            client._sdk_client.send_message.assert_called_once()
            body = client._sdk_client.send_message.call_args.args[1]
            assert body["markdown"]["content"] == content
        finally:
            shutdown()


class TestLongReportChunking:
    def test_multiline_report_split_into_frames_under_limit(self):
        """RED(OR-COR-7ab3e812)：>4000B 的多行中文报告必须分片发送。"""
        report = _multiline_chinese_report()
        assert len(report.encode("utf-8")) > MAX_BYTES

        client, shutdown = _real_send_client()
        try:
            assert client.send_to_chat("c1", report) is True
            calls = client._sdk_client.send_message.call_args_list
            assert len(calls) >= 2

            pieces = []
            for call in calls:
                body = call.args[1]
                piece = body["markdown"]["content"]
                encoded = piece.encode("utf-8")
                # 每片 ≤4000 字节
                assert len(encoded) <= MAX_BYTES
                # 多字节字符无损坏：每片独立合法可解码
                assert piece.encode("utf-8").decode("utf-8") == piece
                pieces.append(piece)

            # 语义还原：拼接后包含原文全部行
            joined = "\n".join(pieces)
            for line in report.split("\n"):
                if line.strip():
                    assert line in joined
        finally:
            shutdown()

    def test_single_oversized_line_cut_at_multibyte_safe_boundary(self):
        """单行超长（6000B 全中文）→ 字节安全切分，不损坏多字节字符。"""
        line = "贵州茅台" * 1500  # 6000 UTF-8 bytes, single line, no newline
        client, shutdown = _real_send_client()
        try:
            assert client.send_to_chat("c1", line) is True
            calls = client._sdk_client.send_message.call_args_list
            assert len(calls) >= 2

            pieces = []
            for call in calls:
                piece = call.args[1]["markdown"]["content"]
                encoded = piece.encode("utf-8")
                assert len(encoded) <= MAX_BYTES
                assert piece.encode("utf-8").decode("utf-8") == piece
                pieces.append(piece)

            # 字节安全：无字符丢失/损坏，拼接语义还原
            assert "".join(pieces) == line
        finally:
            shutdown()

    def test_chunk_failure_returns_false_and_logs_sent_count(self, caplog):
        """任一片失败 → 整体 False，日志记录已发送片数。"""
        import logging

        report = _multiline_chinese_report()
        client, shutdown = _real_send_client(errcodes=[0, 90001])
        try:
            with caplog.at_level(logging.ERROR):
                assert client.send_to_chat("c1", report) is False
            # 第 1 片已发送，第 2 片失败
            assert client._sdk_client.send_message.call_count == 2
            assert "已发送 1" in caplog.text or "1/2" in caplog.text
        finally:
            shutdown()


class TestSplitterUnit:
    def test_short_text_single_chunk(self):
        text = "短内容"
        assert _split_wecom_aibot_text_chunks(text) == [text]

    def test_multibyte_byte_fallback_is_lossless(self):
        """字节兜底切分不得切开多字节字符，且分片拼接无损。"""
        text = "贵州茅台600519趋势背离" * 500  # 全中文，无换行
        chunks = _split_wecom_aibot_text_chunks(text, max_bytes=5)
        assert len(chunks) >= 2
        for chunk in chunks:
            encoded = chunk.encode("utf-8")
            assert len(encoded) <= 5
            assert chunk == encoded.decode("utf-8")  # 无损坏
        assert "".join(chunks) == text  # 无损

    def test_line_boundary_preferred_when_possible(self):
        lines = [f"第{i}行内容" for i in range(50)]
        text = "\n".join(lines)
        chunks = _split_wecom_aibot_text_chunks(text, max_bytes=60)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk.encode("utf-8")) <= 60
        for line in lines:
            assert any(line in chunk for chunk in chunks)  # 不切开整行

    def test_empty_text_no_chunks(self):
        assert _split_wecom_aibot_text_chunks("") == []

    def test_declared_capability_consumed(self):
        """4000 上限消费自 notification_capabilities 声明（单一事实源）。"""
        from src.notification_capabilities import get_channel_profile

        profile = get_channel_profile("wecom_aibot")
        assert profile.max_text_bytes == _wecom_aibot_max_text_bytes()


if __name__ == "__main__":
    pytest.main([__file__])
