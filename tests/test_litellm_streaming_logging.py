# -*- coding: utf-8 -*-
"""LiteLLM per-chunk streaming logging must stay disabled.

LiteLLM submits an ``asyncio.run()`` logging task for every streamed chunk.
On Windows each one builds a Proactor event loop plus a loopback socketpair;
thousands per report wedged the global pool in ``accept()`` and kept the CLI
process alive after "程序执行完成".

Other tests may swap ``sys.modules["litellm"]`` for a lightweight stub, so the
assertions read the litellm module object that ``llm_adapter`` itself holds.
"""

import sys
import unittest


class LiteLLMStreamingLoggingTestCase(unittest.TestCase):
    def test_llm_adapter_disables_streaming_logging(self):
        from src.agent import llm_adapter

        self.assertIs(getattr(llm_adapter.litellm, "disable_streaming_logging", None), True)

    def test_analyzer_import_loads_llm_adapter(self):
        import src.analyzer  # noqa: F401

        self.assertIn("src.agent.llm_adapter", sys.modules)
        adapter = sys.modules["src.agent.llm_adapter"]
        self.assertIs(getattr(adapter.litellm, "disable_streaming_logging", None), True)


if __name__ == "__main__":
    unittest.main()
