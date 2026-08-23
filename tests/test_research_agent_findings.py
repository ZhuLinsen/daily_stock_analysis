# -*- coding: utf-8 -*-
"""Deep research must not report success when every sub-question came back empty.

Regression: sub-question agents that hit the step cap return an empty
``content``.  ``_synthesise_report`` only joins findings that *have* content, so
the synthesis prompt carried an empty "Research Findings" block, the model replied
"研究材料缺失", and the endpoint still returned ``success: true``.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.agent.research import ResearchAgent, ResearchResult


def _agent() -> ResearchAgent:
    """Build the agent without __init__ so no tool registry / LLM client is needed."""
    agent = ResearchAgent.__new__(ResearchAgent)
    agent.max_sub_questions = 3
    agent.token_budget = 100_000
    return agent


class ResearchFindingsTestCase(unittest.TestCase):
    def _run(self, findings, synth=None):
        agent = _agent()
        decomposed = {"questions": ["q1", "q2"], "tokens": 0}
        with patch.object(ResearchAgent, "_decompose_query", return_value=decomposed), \
             patch.object(ResearchAgent, "_research_sub_question", side_effect=findings), \
             patch.object(
                 ResearchAgent,
                 "_synthesise_report",
                 return_value=synth or {"content": "# 报告", "tokens": 10},
             ) as synth_mock:
            result = agent.research("AI 芯片板块最近的核心驱动是什么？")
        return result, synth_mock

    def test_all_empty_findings_fail_loudly(self) -> None:
        findings = [
            {"question": "q1", "content": "", "tokens": 900, "success": True},
            {"question": "q2", "content": "   ", "tokens": 800, "success": True},
        ]
        result, synth_mock = self._run(findings)

        self.assertIsInstance(result, ResearchResult)
        self.assertFalse(result.success, "没有任何可用发现时不能报成功")
        self.assertEqual(result.error, "no_usable_findings")
        self.assertEqual(result.findings_count, 0)
        self.assertEqual(result.report, "")
        synth_mock.assert_not_called()
        # token 消耗仍要如实上报，便于用量核账
        self.assertEqual(result.total_tokens, 1700)

    def test_partial_findings_still_synthesise(self) -> None:
        findings = [
            {"question": "q1", "content": "", "tokens": 500, "success": True},
            {"question": "q2", "content": "英伟达 Q2 数据中心收入超预期", "tokens": 700, "success": True},
        ]
        result, synth_mock = self._run(findings)

        self.assertTrue(result.success)
        self.assertEqual(result.findings_count, 1, "findings_count 应只计可用发现")
        self.assertEqual(result.report, "# 报告")
        synth_mock.assert_called_once()
        passed_findings = synth_mock.call_args.args[1]
        self.assertEqual([f["question"] for f in passed_findings], ["q2"])


if __name__ == "__main__":
    unittest.main()
