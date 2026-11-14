# -*- coding: utf-8 -*-
"""LiteLLM per-chunk streaming logging must stay disabled.

LiteLLM submits an ``asyncio.run()`` logging task for every streamed chunk.
On Windows each one builds a Proactor event loop plus a loopback socketpair;
thousands per report wedged the global pool in ``accept()`` and kept the CLI
process alive after "程序执行完成".
"""

import unittest

import litellm


class LiteLLMStreamingLoggingTestCase(unittest.TestCase):
    def test_llm_adapter_import_disables_streaming_logging(self):
        import src.agent.llm_adapter  # noqa: F401

        self.assertTrue(litellm.disable_streaming_logging)

    def test_analyzer_import_path_disables_streaming_logging(self):
        import src.analyzer  # noqa: F401

        self.assertTrue(litellm.disable_streaming_logging)


if __name__ == "__main__":
    unittest.main()
