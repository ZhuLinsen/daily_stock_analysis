# -*- coding: utf-8 -*-
"""
===================================
自选股管理命令
===================================

对话式管理持久自选股列表（STOCK_LIST）：查询 / 添加 / 移除。

与 Web 端自选股 API（``api/v1/endpoints/stocks.py`` 的 ``/watchlist`` 族）
共用同一持久化入口 ``SystemConfigService.update``（STOCK_LIST 键，乐观锁
config_version），因此两侧修改互相可见，批量分析（``/batch``，读取
``config.stock_list``）在下一次 ``refresh_stock_list`` 后读到最新列表。

失败语义（issue #755 验收第 4 条）：
- 无效股票代码（stock_list_parser UNSUPPORTED，或指数形态）→ 整批拒绝；
- 保存失败（update 抛出任何异常，含版本冲突/校验失败/IO）→ 明确报失败；
- 未授权（配置了 BOT_ADMIN_USERS 且发送者不在名单）→ 修改类子命令拒绝；
以上三种情况一律不报成功，且原列表不做任何修改（写盘前完成全部校验，
update 本身在 ``ConfigManager.apply_updates`` 内原子替换 .env）。
一次性分析（AnalyzeCommand）不经过本命令，不修改持久列表（验收第 2 条）。

权限语义：``BOT_ADMIN_USERS`` 未配置时（默认部署）修改对所有用户开放，
与既有命令（analyze/batch 等）行为一致；配置了名单后仅名单内用户可修改，
查询对所有用户开放。
"""

import logging
import re
from typing import List, Optional, Tuple

from bot.commands.base import BotCommand
from bot.models import BotMessage, BotResponse
from src.services.stock_list_parser import (
    ParseStatus,
    default_index_registry,
    parse_analysis_target,
    split_stock_list,
)

logger = logging.getLogger(__name__)

# 自选股代码形态门（镜像 api/v1/endpoints/stocks.py:_STOCK_CODE_RE，与 Web 端
# watchlist API 同一值域）。stock_list_parser 对自由文本兜底按"股票名"解析
# （如 bad_code/中文代码 → stock），自选股条目必须是显式代码形态，故在 parser
# 语义校验（排除 1234567/us1/600519.BJ 等明确不支持形态并给出原因）之上再叠
# 加本形态门。大小写不敏感；`(?i)` 由 re.IGNORECASE 提供。
_STOCK_CODE_SHAPE_RE = re.compile(
    r"^(?:\d{6}"                              # A股 6 位
    r"|(?:SH|SZ|BJ)\d{6}"                     # 交易所前缀 A股
    r"|\d{6}\.(?:SH|SZ|SS|BJ)"                # 交易所后缀 A股
    r"|\d{1,5}\.HK"                           # 港股后缀
    r"|HK\d{1,5}"                             # 港股前缀
    r"|\d{5}"                                 # 裸 5 位港股
    r"|\d{4,5}\.T"                            # 日本 Yahoo 后缀
    r"|\d{6}\.(?:KS|KQ)"                      # 韩国 Yahoo 后缀
    r"|\d{4,6}\.(?:TW|TWO)"                   # 台湾 Yahoo 后缀
    r"|[A-Z]{1,5}(?:\.(?:US|[A-Z]))?"         # 美股 1-5 字母
    r")$",
    re.IGNORECASE,
)


class WatchlistCommand(BotCommand):
    """
    自选股管理命令

    用法：
        /watchlist                 - 查询当前自选股
        /watchlist list            - 同上
        /watchlist add 600519      - 添加（可多只：/watchlist add 600519 AAPL）
        /watchlist remove 600519   - 移除
        自选股 添加 600519          - 中文子命令等价（添加/移除/查询/帮助）
    """

    # 子命令别名（首参数；英文大小写不敏感）
    _SUB_ALIASES = {
        "list": "list",
        "查询": "list",
        "查看": "list",
        "列出": "list",
        "show": "list",
        "ls": "list",
        "add": "add",
        "添加": "add",
        "新增": "add",
        "remove": "remove",
        "rm": "remove",
        "移除": "remove",
        "删除": "remove",
        "help": "help",
        "帮助": "help",
    }

    def __init__(self, service_factory=None):
        """
        Args:
            service_factory: 可注入的 SystemConfigService 工厂（测试用）；
                默认惰性实例化 ``SystemConfigService()``。
        """
        self._service_factory = service_factory

    @property
    def name(self) -> str:
        return "watchlist"

    @property
    def aliases(self) -> List[str]:
        return ["wl", "自选股", "自选"]

    @property
    def description(self) -> str:
        return "查询/添加/移除自选股（修改持久 STOCK_LIST）"

    @property
    def usage(self) -> str:
        return "/watchlist [list|add|remove] [代码...]"

    # ------------------------------------------------------------------ #
    #  入口                                                                #
    # ------------------------------------------------------------------ #

    def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
        if not args:
            return self._list_codes()

        sub = self._SUB_ALIASES.get(args[0].strip().lower())
        if sub == "list":
            return self._list_codes()
        if sub == "help":
            return BotResponse.markdown_response(self.get_help_text())

        if sub in ("add", "remove"):
            codes = [c for c in (a.strip() for a in args[1:]) if c]
            if not codes:
                return BotResponse.error_response(f"请提供股票代码\n用法: `{self.usage}`")

            denied = self._mutation_denial_response(message)
            if denied is not None:
                return denied

            if sub == "add":
                return self._add(codes)
            return self._remove(codes)

        return BotResponse.error_response(
            f"未知子命令: {args[0]}\n用法: `{self.usage}`"
        )

    # ------------------------------------------------------------------ #
    #  权限                                                                #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _mutation_denial_response(message: BotMessage) -> Optional[BotResponse]:
        """修改类子命令的管理员门槛（仅当配置了 BOT_ADMIN_USERS 时生效）。"""
        try:
            from bot.dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
        except Exception:  # pragma: no cover - 防御分支
            return None
        if dispatcher.admin_users and not dispatcher.is_admin(message.user_id):
            logger.warning(
                "[WatchlistCommand] 非管理员修改自选股被拒绝: user=%s",
                message.user_id,
            )
            return BotResponse.error_response(
                "修改自选股需要管理员权限（BOT_ADMIN_USERS）"
            )
        return None

    # ------------------------------------------------------------------ #
    #  持久化读写（与 Web 端 /watchlist API 同一入口）                      #
    # ------------------------------------------------------------------ #

    def _get_service(self):
        if self._service_factory is not None:
            return self._service_factory()
        from src.services.system_config_service import SystemConfigService

        return SystemConfigService()

    @staticmethod
    def _read_codes(service) -> Tuple[str, List[str]]:
        """读取 (config_version, STOCK_LIST codes)。"""
        config_data = service.get_config(include_schema=False)
        stock_list_str = ""
        for item in config_data.get("items", []):
            if item.get("key") == "STOCK_LIST":
                stock_list_str = str(item.get("value", ""))
                break
        return str(config_data.get("config_version", "")), split_stock_list(stock_list_str)

    @staticmethod
    def _save_codes(service, config_version: str, codes: List[str]) -> None:
        """持久化 STOCK_LIST（与 api/v1/endpoints/stocks.py 同参数契约）。

        任何异常向上抛出（update 在 apply_updates 内原子替换 .env，
        失败时原文件不变），由调用方转为失败回执。
        """
        service.update(
            config_version=config_version,
            items=[{"key": "STOCK_LIST", "value": ",".join(codes)}],
            mask_token="******",
            reload_now=True,
        )

    # ------------------------------------------------------------------ #
    #  校验与匹配                                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _validate_token(token: str, registry) -> Tuple[Optional[str], Optional[str]]:
        """校验单只股票代码，返回 (storage_code, error_message)。

        校验两层：
        1. stock_list_parser 语义校验（与 AnalyzeCommand 同一解析内核）——
           UNSUPPORTED 即无效代码（给出 parser 原因）；指数形态明确拒绝
           （指数是分析标的而非自选股条目，与 Web 端 watchlist API 值域一致）；
        2. 代码形态门（镜像 api/v1/endpoints/stocks.py:_STOCK_CODE_RE）——
           parser 对自由文本兜底按股票名解析，自选股条目必须是显式代码形态。
        """
        target = parse_analysis_target(token, registry=registry)
        if target.asset_type == ParseStatus.UNSUPPORTED:
            reason = target.unsupported_reason or f"无法识别股票: {token}"
            return None, f"`{token}` 不是有效的股票代码（{reason}）"
        if target.asset_type == ParseStatus.INDEX:
            return None, (
                f"`{token}` 是指数代码，自选股仅支持股票（指数分析请用 /analyze）"
            )
        if not _STOCK_CODE_SHAPE_RE.match(token.strip()):
            return None, (
                f"`{token}` 不是有效的股票代码格式"
                "（A股6位 / 交易所前缀或后缀 / 港股 / 美股1-5字母）"
            )

        from data_provider.base import normalize_stock_code

        storage_code = normalize_stock_code(token.strip()).upper()
        if not storage_code:
            return None, f"`{token}` 不是有效的股票代码"
        return storage_code, None

    @staticmethod
    def _match_key(code: str) -> str:
        """自选股条目等价键（镜像 api/v1/endpoints/stocks.py:_watchlist_match_key）。

        既有 STOCK_LIST 条目与命令输入统一走 normalize_stock_code（r2 修复
        OR-COR-e0e93ea0：仅大写比较会让 SH600519/600519、1810.HK/HK01810
        判不了等价），再按裸 5 位数字加 HK 前缀形态、其余大写比较。
        """
        from data_provider.base import normalize_stock_code

        normalized = normalize_stock_code(code.strip()).upper()
        if re.fullmatch(r"\d{5}", normalized):
            return f"HK{normalized}"
        return normalized

    # ------------------------------------------------------------------ #
    #  子命令实现                                                          #
    # ------------------------------------------------------------------ #

    def _list_codes(self) -> BotResponse:
        try:
            _, codes = self._read_codes(self._get_service())
        except Exception as exc:
            logger.error("[WatchlistCommand] 读取自选股失败: %s", exc)
            return BotResponse.error_response(f"读取自选股失败: {str(exc)[:100]}")

        if not codes:
            return BotResponse.markdown_response(
                "📋 当前自选股为空。\n发送 `/watchlist add <代码>` 添加。"
            )
        return BotResponse.markdown_response(
            f"📋 当前自选股（{len(codes)} 只）：\n{', '.join(codes)}"
        )

    def _add(self, codes: List[str]) -> BotResponse:
        service = self._get_service()
        registry = default_index_registry()

        try:
            config_version, existing = self._read_codes(service)
        except Exception as exc:
            logger.error("[WatchlistCommand] 读取自选股失败: %s", exc)
            return BotResponse.error_response(f"读取自选股失败: {str(exc)[:100]}")

        # 写盘前完成全部校验（全有或全无，原列表不动）。
        existing_keys = {self._match_key(c) for c in existing}
        added: List[str] = []
        duplicates: List[str] = []
        for token in codes:
            storage_code, error = self._validate_token(token, registry)
            if error is not None:
                return BotResponse.error_response(
                    f"添加失败：{error}（原列表未修改）"
                )
            key = self._match_key(storage_code)
            if key in existing_keys:
                duplicates.append(storage_code)
                continue
            existing_keys.add(key)
            added.append(storage_code)

        if not added:
            return BotResponse.markdown_response(
                "ℹ️ 以下代码已在自选股中，未做修改：\n" + ", ".join(duplicates)
            )

        new_list = existing + added
        try:
            self._save_codes(service, config_version, new_list)
        except Exception as exc:
            logger.error("[WatchlistCommand] 保存自选股失败: %s", exc)
            return BotResponse.error_response(
                f"保存自选股失败: {str(exc)[:100]}（原列表未修改）"
            )

        lines = [f"✅ 已添加 {len(added)} 只：{', '.join(added)}"]
        if duplicates:
            lines.append(f"（已存在跳过：{', '.join(duplicates)}）")
        lines.append(f"自选股共 {len(new_list)} 只：{', '.join(new_list)}")
        return BotResponse.markdown_response("\n".join(lines))

    def _remove(self, codes: List[str]) -> BotResponse:
        service = self._get_service()
        registry = default_index_registry()

        try:
            config_version, existing = self._read_codes(service)
        except Exception as exc:
            logger.error("[WatchlistCommand] 读取自选股失败: %s", exc)
            return BotResponse.error_response(f"读取自选股失败: {str(exc)[:100]}")

        requested = []  # (原始 token, 匹配键)
        for token in codes:
            storage_code, error = self._validate_token(token, registry)
            if error is not None:
                return BotResponse.error_response(
                    f"移除失败：{error}（原列表未修改）"
                )
            requested.append((token, self._match_key(storage_code)))

        requested_keys = {key for _, key in requested}
        existing_keys = {self._match_key(c) for c in existing}
        missing = [token for token, key in requested if key not in existing_keys]

        if len(missing) == len(codes):
            # 全部未命中：不写盘，原列表不动。
            return BotResponse.error_response(
                f"未在自选股中找到：{', '.join(missing)}（原列表未修改）"
            )

        remaining = [c for c in existing if self._match_key(c) not in requested_keys]
        removed = [c for c in existing if self._match_key(c) in requested_keys]
        try:
            self._save_codes(service, config_version, remaining)
        except Exception as exc:
            logger.error("[WatchlistCommand] 保存自选股失败: %s", exc)
            return BotResponse.error_response(
                f"保存自选股失败: {str(exc)[:100]}（原列表未修改）"
            )

        lines = [f"✅ 已移除 {len(removed)} 只：{', '.join(removed)}"]
        if missing:
            lines.append(f"（未在列表中，跳过：{', '.join(missing)}）")
        if remaining:
            lines.append(f"自选股共 {len(remaining)} 只：{', '.join(remaining)}")
        else:
            lines.append("自选股已清空。")
        return BotResponse.markdown_response("\n".join(lines))
