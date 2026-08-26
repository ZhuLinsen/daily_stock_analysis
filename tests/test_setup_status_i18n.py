# -*- coding: utf-8 -*-
"""Regression coverage for localized first-run setup status copy."""

from __future__ import annotations

import re
import unittest

from src.setup_status_i18n import SETUP_CHECK_TEXT, localize_setup_checks


class SetupStatusI18nTestCase(unittest.TestCase):
    @staticmethod
    def _check(message: str, *, key: str = "llm_primary", next_step: str | None = None) -> dict:
        return {
            "key": key,
            "title": "legacy title",
            "category": "ai_model",
            "required": True,
            "status": "needs_action",
            "message": message,
            "next_step": next_step,
        }

    def test_all_static_setup_messages_have_korean_copy(self) -> None:
        checks = [self._check(message) for message in SETUP_CHECK_TEXT]

        localized = localize_setup_checks(checks, "ko")

        self.assertEqual(len(localized), len(checks))
        for check in localized:
            self.assertNotRegex(check["title"], re.compile(r"[\u4e00-\u9fff]"))
            self.assertNotRegex(check["message"], re.compile(r"[\u4e00-\u9fff]"))

    def test_dynamic_setup_messages_have_korean_copy(self) -> None:
        checks = [
            self._check("已启用 Codex CLI 本地生成 Backend（experimental/limited）。"),
            self._check("已选择 claude_code_cli，但未找到 claude 可执行文件。"),
            self._check("已检测到 LLM 渠道: openai/gpt-5.5"),
            self._check("Agent 工具调用暂不支持 codex_cli text-only backend。", key="llm_agent"),
            self._check("普通分析使用 Codex CLI；Agent 工具调用仍使用 LiteLLM 主模型: openai/gpt-5.5", key="llm_agent"),
            self._check("Agent 主模型 hermes-agent 只有 Hermes deployment，Phase 3 不支持 Agent 工具调用。", key="llm_agent"),
            self._check("已配置 Agent 主模型: openai/gpt-5.5", key="llm_agent"),
            self._check("Agent 主模型 openai/gpt-5.5 缺少可用渠道或匹配的 API Key。", key="llm_agent"),
            self._check("已配置 4 只股票。", key="stock_list"),
            self._check("数据库路径父目录不可用: /tmp/missing", key="storage"),
            self._check("数据库上级目录可创建: /tmp/new-data", key="storage"),
            self._check("数据库路径可用: data/stock_analysis.db", key="storage"),
            self._check("数据库路径上级目录不可写: /var/lib/dsa", key="storage"),
        ]

        localized = localize_setup_checks(checks, "ko")

        for check in localized:
            self.assertNotRegex(check["title"], re.compile(r"[\u4e00-\u9fff]"))
            self.assertNotRegex(check["message"], re.compile(r"[\u4e00-\u9fff]"))

        self.assertEqual(localized[0]["message"], "Codex CLI 로컬 생성 백엔드가 활성화되어 있습니다(실험적/제한적).")
        self.assertEqual(localized[8]["message"], "종목 4개가 구성되었습니다.")
        self.assertEqual(localized[11]["message"], "데이터베이스 경로를 사용할 수 있습니다: data/stock_analysis.db")

    def test_legacy_request_without_language_keeps_chinese_copy(self) -> None:
        checks = [self._check("已配置 4 只股票。", key="stock_list")]

        self.assertEqual(localize_setup_checks(checks, None), checks)


if __name__ == "__main__":
    unittest.main()
