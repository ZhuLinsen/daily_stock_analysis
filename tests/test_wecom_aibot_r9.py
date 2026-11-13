# -*- coding: utf-8 -*-
"""
r9 fixes for the WeCom AI Bot lazy-start path (Issue #755, reviews on PR
#2494 @3d70c410):

- OR-COR-f398a721: the lazy start only checked `wecom_aibot_notify_enabled`;
  with WECOM_AIBOT_ENABLED=false but credentials/notify config retained, the
  lazy start still pulled up the long connection (which also receives
  commands). The master switch must gate the lazy start: disabled → refuse
  without starting and return False.

- OR-COR-c48c90ae: start_background's "check alive → create thread → assign
  state" sequence had no mutual exclusion (the singleton lock only protects
  instance acquisition) — two concurrent first-time lazy starts could both
  pass the alive check and create two supervision threads (two connections).
  start_background now holds an instance-level `_start_lock` for the whole
  critical section; the second caller observes the live thread and returns
  False (idempotent).
"""

import os
import sys
import threading
import time
from unittest import mock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import bot.platforms.wecom_aibot as wecom_aibot
from bot.platforms.wecom_aibot import WecomAibotClient
from src.notification_sender.wecom_aibot_sender import WecomAibotSender


def _full_config(wecom_aibot_enabled):
    """Credentials + notify config retained; only the master switch varies."""
    from src.config import Config

    return Config(
        stock_list=[],
        wecom_aibot_enabled=wecom_aibot_enabled,
        wecom_aibot_bot_id="bot-abc",
        wecom_aibot_secret="secret-xyz",
        wecom_aibot_notify_enabled=True,
        wecom_aibot_notify_chatid="c1",
    )


def _not_running_client():
    client = mock.MagicMock()
    client.is_running = False
    client.start_background = mock.MagicMock(return_value=True)
    client.wait_for_ready = mock.MagicMock(return_value=True)
    client.send_to_chat = mock.MagicMock(return_value=True)
    return client


class TestLazyStartRespectsMasterSwitch:
    def test_master_switch_disabled_refuses_lazy_start(self):
        """RED(OR-COR-f398a721)：WECOM_AIBOT_ENABLED=false 且凭据/通知配置
        齐全 → 惰性启动不得拉起长连接（不启动、不等待、不发送）。"""
        sender = WecomAibotSender(_full_config(wecom_aibot_enabled=False))
        client = _not_running_client()

        with mock.patch(
            "bot.platforms.wecom_aibot.get_wecom_aibot_client", return_value=client
        ):
            assert sender.send_to_wecom_aibot("report") is False

        client.start_background.assert_not_called()
        client.wait_for_ready.assert_not_called()
        client.send_to_chat.assert_not_called()

    def test_master_switch_enabled_lazy_start_still_works(self):
        """对照：主开关开启时惰性启动路径不受影响。"""
        sender = WecomAibotSender(_full_config(wecom_aibot_enabled=True))
        client = _not_running_client()

        with mock.patch(
            "bot.platforms.wecom_aibot.get_wecom_aibot_client", return_value=client
        ):
            assert sender.send_to_wecom_aibot("report") is True

        client.start_background.assert_called_once()
        client.wait_for_ready.assert_called_once()
        client.send_to_chat.assert_called_once()


class TestConcurrentStartBackground:
    def test_concurrent_start_creates_single_supervisor_thread(self):
        """RED(OR-COR-c48c90ae)：两线程并发 start_background → 监督线程恰 1、
        结果一真一幂等（False）。慢 Thread 拉大「查存活→建线程」窗口以
        确定性复现无锁竞态。"""
        run_invocations = []
        hold = threading.Event()

        def _blocking_run_background(client_self):
            run_invocations.append(1)
            hold.wait(5)

        real_thread_cls = threading.Thread

        class _SlowThread(real_thread_cls):
            """在建线程构造期睡眠，拉大存活检查→赋值的无锁窗口。"""

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                time.sleep(0.05)

        # 全部补丁必须覆盖到并发 start_background 调用点（含 SDK 可用标志）
        with mock.patch.object(
            wecom_aibot, "get_config", return_value=mock.MagicMock(
                wecom_aibot_enabled=True,
                wecom_aibot_bot_id="bot-abc",
                wecom_aibot_secret="secret-xyz",
                wecom_aibot_reply_stream=False,
            )
        ), mock.patch.object(
            wecom_aibot, "WECOM_AIBOT_SDK_AVAILABLE", True
        ), mock.patch.object(wecom_aibot, "aibot", create=True):
            client = WecomAibotClient()

            with mock.patch.object(
                WecomAibotClient, "_run_background", _blocking_run_background
            ), mock.patch.object(wecom_aibot.threading, "Thread", _SlowThread):
                results = {}
                barrier = threading.Barrier(2)

                def _caller(tag):
                    barrier.wait(2)
                    results[tag] = client.start_background()

                callers = [
                    threading.Thread(target=_caller, args=(tag,), daemon=True)
                    for tag in ("a", "b")
                ]
                for t in callers:
                    t.start()
                for t in callers:
                    t.join(5)
                # start() 返回 ≠ 目标已起跑：等待监督线程真正进入运行体
                deadline = time.time() + 2
                while len(run_invocations) < 1 and time.time() < deadline:
                    time.sleep(0.02)

        assert sorted(results.values()) == [False, True]
        assert len(run_invocations) == 1
        assert client._background_thread is not None

        # cleanup: release the blocking supervisor and stop the client
        hold.set()
        time.sleep(0.1)
        client.stop()


if __name__ == "__main__":
    pytest.main([__file__])
