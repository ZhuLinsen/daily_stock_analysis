# -*- coding: utf-8 -*-
"""
WatchlistCommand（对话管理自选股）测试，Issue #755 Phase 2。

验收映射（issue #755 正文「### 验收要求」逐条）：
- ① 智能机器人接收消息并返回处理结果：Phase 1 已闭环 text→dispatcher→
  AnalyzeCommand；本文件 test_acc1_* 补 Phase 2 命令路径（watchlist 分发往返）。
- ② 对话指定股票一次性分析不自动修改持久自选股：test_acc2_*（真实
  AnalyzeCommand + mock 任务服务，断言 STOCK_LIST 持久层零写入）。
- ③ 对话命令查询/添加/移除自选股，修改持久化后批量分析读最新列表：
  test_acc3_*（真实 SystemConfigService + tmp ENV_FILE 全链路持久化，
  batch 命令读取语义 bot/commands/batch.py:58-60 = refresh_stock_list +
  config.stock_list）。
- ④ 无效股票/未授权/保存失败一律报失败且原列表不动：test_acc4_*。

本地 venv 不装任何新依赖；SystemConfigService 在需要处用 Fake/真 tmp .env。
错误回执约定：BotResponse.error_response 文本以 "❌" 开头（bot/models.py）。
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bot.commands.watchlist import WatchlistCommand
from bot.dispatcher import CommandDispatcher, reset_dispatcher
from bot.models import BotMessage, BotResponse, ChatType


def _msg(content: str, user_id: str = "user-1") -> BotMessage:
    return BotMessage(
        platform="test",
        message_id=f"m-{user_id}-{content}",
        user_id=user_id,
        user_name=user_id,
        chat_id=user_id,
        chat_type=ChatType.PRIVATE,
        content=content,
        raw_content=content,
        mentioned=True,
    )


class FakeSystemConfigService:
    """Mirror of the FakeSystemConfigService contract used by
    tests/test_stock_watchlist_api.py (get_config/update)."""

    def __init__(self, stock_list: str = "600519") -> None:
        self.stock_list = stock_list
        self.config_version = "cfg-v1"
        self.update_calls: list = []

    def get_config(self, include_schema: bool = False) -> dict:
        return {
            "config_version": self.config_version,
            "items": [{"key": "STOCK_LIST", "value": self.stock_list}],
        }

    def update(self, **kwargs) -> dict:
        items = kwargs["items"]
        assert kwargs.get("config_version") == self.config_version
        assert all(item["key"] == "STOCK_LIST" for item in items)
        self.stock_list = items[0]["value"]
        self.update_calls.append(self.stock_list)
        return {"success": True, "applied_count": 1}


class ExplodingUpdateService(FakeSystemConfigService):
    """get_config works, update always raises (save-failure path)."""

    def update(self, **kwargs) -> dict:
        self.update_calls.append(kwargs["items"][0]["value"])
        raise RuntimeError("disk full while writing .env")


def _watchlist_dispatcher(service, admins=None) -> CommandDispatcher:
    dispatcher = CommandDispatcher(admin_users=admins or [])
    dispatcher.register(WatchlistCommand(service_factory=lambda: service))
    return dispatcher


# ---------------------------------------------------------------------------
# Basic query/list behaviour
# ---------------------------------------------------------------------------


class TestWatchlistQuery:
    def test_list_shows_current_codes(self):
        service = FakeSystemConfigService("600519,000858")
        dispatcher = _watchlist_dispatcher(service)

        response = dispatcher.dispatch(_msg("/watchlist"))

        assert "❌" not in response.text
        assert "600519" in response.text
        assert "000858" in response.text
        assert service.update_calls == []

    def test_bare_command_without_args_lists(self):
        service = FakeSystemConfigService("600519")
        command = WatchlistCommand(service_factory=lambda: service)

        response = command.execute(_msg("/watchlist"), [])

        assert "❌" not in response.text
        assert "600519" in response.text

    def test_explicit_list_subcommand(self):
        service = FakeSystemConfigService("600519")
        command = WatchlistCommand(service_factory=lambda: service)

        response = command.execute(_msg("/watchlist list"), ["list"])

        assert "❌" not in response.text
        assert "600519" in response.text

    def test_chinese_subcommand_query(self):
        service = FakeSystemConfigService("600519")
        command = WatchlistCommand(service_factory=lambda: service)

        response = command.execute(_msg("自选股 查询"), ["查询"])

        assert "❌" not in response.text
        assert "600519" in response.text

    def test_empty_watchlist_reports_empty_not_error(self):
        service = FakeSystemConfigService("")
        command = WatchlistCommand(service_factory=lambda: service)

        response = command.execute(_msg("/watchlist"), [])

        assert "❌" not in response.text
        assert "空" in response.text

    def test_query_never_persists(self):
        service = FakeSystemConfigService("600519")
        dispatcher = _watchlist_dispatcher(service)

        dispatcher.dispatch(_msg("/watchlist"))

        assert service.update_calls == []
        assert service.stock_list == "600519"


# ---------------------------------------------------------------------------
# Add
# ---------------------------------------------------------------------------


class TestWatchlistAdd:
    def test_add_valid_code_persists_and_reports(self):
        service = FakeSystemConfigService("600519")
        command = WatchlistCommand(service_factory=lambda: service)

        response = command.execute(_msg("/watchlist add 000858"), ["add", "000858"])

        assert "❌" not in response.text
        assert "000858" in response.text
        assert service.update_calls == ["600519,000858"]
        assert service.stock_list == "600519,000858"

    def test_add_prefixed_variant_of_existing_is_noop(self):
        service = FakeSystemConfigService("00700")
        command = WatchlistCommand(service_factory=lambda: service)

        # 同一只港股的 HK 前缀变体 -> 已存在，不产生写盘。
        response = command.execute(_msg("/watchlist add hk00700"), ["add", "hk00700"])

        assert "❌" not in response.text
        assert service.update_calls == []

    def test_add_us_ticker_uppercases(self):
        service = FakeSystemConfigService("600519")
        command = WatchlistCommand(service_factory=lambda: service)

        response = command.execute(_msg("/watchlist add aapl"), ["add", "aapl"])

        assert "❌" not in response.text
        assert service.stock_list == "600519,AAPL"

    def test_add_chinese_subcommand(self):
        service = FakeSystemConfigService("")
        command = WatchlistCommand(service_factory=lambda: service)

        response = command.execute(_msg("自选股 添加 600519"), ["添加", "600519"])

        assert "❌" not in response.text
        assert service.stock_list == "600519"

    def test_add_duplicate_only_is_noop_not_error(self):
        service = FakeSystemConfigService("600519")
        command = WatchlistCommand(service_factory=lambda: service)

        response = command.execute(_msg("/watchlist add 600519"), ["add", "600519"])

        assert "❌" not in response.text
        assert service.update_calls == []
        assert service.stock_list == "600519"

    def test_add_index_code_is_rejected_with_reason(self):
        """指数是分析标的，不是自选股条目（与 Web 端 watchlist API 值域一致）。"""
        service = FakeSystemConfigService("600519")
        command = WatchlistCommand(service_factory=lambda: service)

        response = command.execute(
            _msg("/watchlist add sh000016"), ["add", "sh000016"]
        )

        assert "❌" in response.text
        assert service.update_calls == []
        assert service.stock_list == "600519"


# ---------------------------------------------------------------------------
# Remove
# ---------------------------------------------------------------------------


class TestWatchlistRemove:
    def test_remove_existing_code_persists_and_reports(self):
        service = FakeSystemConfigService("600519,000858")
        command = WatchlistCommand(service_factory=lambda: service)

        response = command.execute(
            _msg("/watchlist remove 000858"), ["remove", "000858"]
        )

        assert "❌" not in response.text
        assert "000858" in response.text
        assert service.update_calls == ["600519"]
        assert service.stock_list == "600519"

    def test_remove_chinese_subcommand(self):
        service = FakeSystemConfigService("600519,000858")
        command = WatchlistCommand(service_factory=lambda: service)

        response = command.execute(_msg("自选股 移除 000858"), ["移除", "000858"])

        assert "❌" not in response.text
        assert service.stock_list == "600519"

    def test_remove_missing_code_fails_and_list_untouched(self):
        service = FakeSystemConfigService("600519")
        command = WatchlistCommand(service_factory=lambda: service)

        response = command.execute(
            _msg("/watchlist remove 999999"), ["remove", "999999"]
        )

        assert "❌" in response.text
        assert service.update_calls == []
        assert service.stock_list == "600519"


# ---------------------------------------------------------------------------
# Acceptance ①②③④ (explicit mapping names)
# ---------------------------------------------------------------------------


class TestAcceptanceMapping:
    def test_acc1_watchlist_dispatch_round_trip(self):
        """验收①：消息进入 → 命令分派 → 处理结果返回（Phase 2 命令路径）。"""
        service = FakeSystemConfigService("600519,000858")
        dispatcher = _watchlist_dispatcher(service)

        # 中文无前缀别名（bot/models.py chinese_commands 映射 '自选股'）。
        response = dispatcher.dispatch(_msg("自选股"))
        assert "❌" not in response.text
        assert "600519" in response.text

        # 前缀命令 + add 子命令往返。
        response = dispatcher.dispatch(_msg("/watchlist add 300750"))
        assert "❌" not in response.text
        assert service.stock_list == "600519,000858,300750"

    def test_acc2_analyze_one_shot_does_not_modify_stock_list(self):
        """验收②：一次性分析不修改持久自选股列表（真实 AnalyzeCommand 路径）。"""
        from bot.commands.analyze import AnalyzeCommand

        service = FakeSystemConfigService("600519")
        dispatcher = _watchlist_dispatcher(service)
        dispatcher.register(AnalyzeCommand())

        with mock.patch("src.services.task_service.get_task_service") as m_service:
            m_service.return_value.submit_analysis.return_value = {
                "success": True,
                "task_id": "task-abc123",
            }
            response = dispatcher.dispatch(_msg("/analyze 600519"))

        assert "❌" not in response.text, response.text
        assert service.update_calls == []
        assert service.stock_list == "600519"

    def test_acc2_chinese_analyze_does_not_modify_stock_list(self):
        from bot.commands.analyze import AnalyzeCommand

        service = FakeSystemConfigService("600519")
        dispatcher = _watchlist_dispatcher(service)
        dispatcher.register(AnalyzeCommand())

        with mock.patch("src.services.task_service.get_task_service") as m_service:
            m_service.return_value.submit_analysis.return_value = {
                "success": True,
                "task_id": "task-abc123",
            }
            response = dispatcher.dispatch(_msg("分析 000858"))

        assert "❌" not in response.text, response.text
        assert service.update_calls == []
        assert service.stock_list == "600519"

    def test_acc3_add_persists_stock_list_and_batch_reads_latest(self):
        """验收③：对话添加 → 真实持久化 → 批量分析读最新列表。

        batch 命令读取语义（bot/commands/batch.py:58-60）：
            config.refresh_stock_list(); stock_list = config.stock_list
        """
        from src.config import Config
        from src.services.system_config_service import SystemConfigService

        with tempfile.TemporaryDirectory() as tmp_dir:
            env_path = Path(tmp_dir) / ".env"
            env_path.write_text("STOCK_LIST=600519\n", encoding="utf-8")

            old_env_file = os.environ.get("ENV_FILE")
            os.environ["ENV_FILE"] = str(env_path)
            Config.reset_instance()
            try:
                command = WatchlistCommand(service_factory=SystemConfigService)

                response = command.execute(
                    _msg("/watchlist add 000858"), ["add", "000858"]
                )
                assert "❌" not in response.text, response.text

                # 持久化落盘（tmp .env，非仓库 .env）。
                persisted = env_path.read_text(encoding="utf-8")
                assert "STOCK_LIST=600519,000858" in persisted

                # 批量分析读最新列表：与 BatchCommand 同语义。
                config = Config.get_instance()
                config.refresh_stock_list()
                stock_list = config.stock_list
                assert "600519" in stock_list
                assert "000858" in stock_list

                # 再走真实移除路径，回到原始列表。
                response = command.execute(
                    _msg("/watchlist remove 000858"), ["remove", "000858"]
                )
                assert "❌" not in response.text, response.text
                config.refresh_stock_list()
                assert config.stock_list == ["600519"]
            finally:
                Config.reset_instance()
                if old_env_file is None:
                    os.environ.pop("ENV_FILE", None)
                else:
                    os.environ["ENV_FILE"] = old_env_file

    def test_acc4_invalid_code_rejected_and_list_untouched(self):
        """验收④（无效股票）：报失败、原列表不动、不误报成功。"""
        service = FakeSystemConfigService("600519")
        command = WatchlistCommand(service_factory=lambda: service)

        response = command.execute(
            _msg("/watchlist add 1234567"), ["add", "1234567"]
        )

        assert "❌" in response.text
        assert "成功" not in response.text
        assert service.update_calls == []
        assert service.stock_list == "600519"

    def test_acc4_invalid_and_valid_mixed_rejects_all(self):
        """验收④：混合批次全有或全无——任一无效则整批拒绝。"""
        service = FakeSystemConfigService("600519")
        command = WatchlistCommand(service_factory=lambda: service)

        response = command.execute(
            _msg("/watchlist add 000858 bad_code"), ["add", "000858", "bad_code"]
        )

        assert "❌" in response.text
        assert service.update_calls == []
        assert service.stock_list == "600519"

    def test_acc4_save_failure_reported_and_list_untouched(self):
        """验收④（保存失败）：update 抛异常必须报失败且原列表不动。"""
        service = ExplodingUpdateService("600519")
        command = WatchlistCommand(service_factory=lambda: service)

        response = command.execute(
            _msg("/watchlist add 000858"), ["add", "000858"]
        )

        assert "❌" in response.text
        assert "成功" not in response.text
        # update 被尝试过但持久化值未变化（异常路径不落盘）。
        assert service.stock_list == "600519"

    def test_acc4_unauthorized_mutation_rejected_and_list_untouched(self):
        """验收④（未授权）：配置管理员名单后，非管理员修改一律失败。

        权限门槛读取全局 dispatcher 的 BOT_ADMIN_USERS 名单（运行时语义），
        测试以 patch bot.dispatcher.get_dispatcher 注入名单。
        """
        service = FakeSystemConfigService("600519")
        dispatcher = _watchlist_dispatcher(service)
        global_dispatcher = CommandDispatcher(admin_users=["boss-1"])

        with mock.patch(
            "bot.dispatcher.get_dispatcher", return_value=global_dispatcher
        ):
            response = dispatcher.dispatch(
                _msg("/watchlist add 000858", user_id="rand-7")
            )

        assert "❌" in response.text
        assert service.update_calls == []
        assert service.stock_list == "600519"

        # 管理员本人可以修改。
        with mock.patch(
            "bot.dispatcher.get_dispatcher", return_value=global_dispatcher
        ):
            response = dispatcher.dispatch(
                _msg("/watchlist add 000858", user_id="boss-1")
            )
        assert "❌" not in response.text
        assert service.stock_list == "600519,000858"

    def test_query_allowed_for_non_admin_even_with_admin_list(self):
        service = FakeSystemConfigService("600519")
        dispatcher = _watchlist_dispatcher(service)
        global_dispatcher = CommandDispatcher(admin_users=["boss-1"])

        with mock.patch(
            "bot.dispatcher.get_dispatcher", return_value=global_dispatcher
        ):
            response = dispatcher.dispatch(_msg("/watchlist", user_id="rand-7"))

        assert "❌" not in response.text
        assert service.update_calls == []


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestCommandRegistration:
    def test_watchlist_registered_in_all_commands(self):
        import bot.commands as commands_pkg

        assert WatchlistCommand in commands_pkg.ALL_COMMANDS

    def test_global_dispatcher_resolves_watchlist(self):
        reset_dispatcher()
        try:
            from bot.dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
            command = dispatcher.get_command("watchlist")
            assert command is not None
            assert isinstance(command, WatchlistCommand)
            assert dispatcher.get_command("wl") is command
            assert dispatcher.get_command("自选股") is command
        finally:
            reset_dispatcher()

    def test_chinese_command_map_routes_selfcmd(self):
        message = _msg("自选股 添加 600519")
        cmd, args = message.get_command_and_args("/")
        assert cmd == "watchlist"
        assert args == ["添加", "600519"]

    def test_help_lists_watchlist(self):
        reset_dispatcher()
        try:
            from bot.dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
            names = [c.name for c in dispatcher.list_commands()]
            assert "watchlist" in names
        finally:
            reset_dispatcher()


# ---------------------------------------------------------------------------
# (c) r2: match-key normalization parity with the Web watchlist API
#     (review OR-COR-e0e93ea0 / OR-COR-ba52df80)
# ---------------------------------------------------------------------------


class TestMatchKeyNormalizationParity:
    """Existing STOCK_LIST entries and command input must go through the same
    normalization (normalize_stock_code) before equivalence comparison —
    mirroring api/v1/endpoints/stocks.py:_watchlist_match_key."""

    def test_add_bare_code_matches_sh_prefixed_existing(self):
        """已有 SH600519，add 600519 → 判重复，不写盘、不重复添加。"""
        service = FakeSystemConfigService("SH600519")
        command = WatchlistCommand(service_factory=lambda: service)

        response = command.execute(_msg("/watchlist add 600519"), ["add", "600519"])

        assert "❌" not in response.text
        assert service.update_calls == []
        assert service.stock_list == "SH600519"

    def test_add_prefixed_input_matches_bare_existing(self):
        """已有 600519，add sh600519 → 判重复，不写盘。"""
        service = FakeSystemConfigService("600519")
        command = WatchlistCommand(service_factory=lambda: service)

        response = command.execute(_msg("/watchlist add sh600519"), ["add", "sh600519"])

        assert "❌" not in response.text
        assert service.update_calls == []

    def test_remove_bare_code_hits_sh_prefixed_existing(self):
        """已有 SH600519，remove 600519 → 命中并移除（r1 缺陷：报未找到）。"""
        service = FakeSystemConfigService("SH600519,000858")
        command = WatchlistCommand(service_factory=lambda: service)

        response = command.execute(_msg("/watchlist remove 600519"), ["remove", "600519"])

        assert "❌" not in response.text
        assert service.stock_list == "000858"
        assert service.update_calls == ["000858"]

    def test_remove_prefixed_input_hits_bare_existing(self):
        """已有 600519，remove SH600519 → 命中并移除。"""
        service = FakeSystemConfigService("600519,000858")
        command = WatchlistCommand(service_factory=lambda: service)

        response = command.execute(
            _msg("/watchlist remove SH600519"), ["remove", "SH600519"]
        )

        assert "❌" not in response.text
        assert service.stock_list == "000858"

    def test_hk_suffix_and_prefix_forms_are_equivalent(self):
        """已有 HK01810，add 1810.HK → 判重复；remove hk01810 → 命中。"""
        service = FakeSystemConfigService("HK01810")
        command = WatchlistCommand(service_factory=lambda: service)

        response = command.execute(_msg("/watchlist add 1810.HK"), ["add", "1810.HK"])
        assert "❌" not in response.text
        assert service.update_calls == []

        response = command.execute(_msg("/watchlist remove hk01810"), ["remove", "hk01810"])
        assert "❌" not in response.text
        assert service.stock_list == ""


if __name__ == "__main__":
    pytest.main([__file__])
