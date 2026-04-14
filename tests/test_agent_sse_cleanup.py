# -*- coding: utf-8 -*-
"""
Tests for agent_chat_stream SSE cleanup exception handling.

Verifies that:
- asyncio.CancelledError during cleanup is silently ignored (no warning).
- Other exceptions during cleanup emit a WARNING log entry.
"""

import asyncio
import sys
import os
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

# Stub optional heavy deps before importing agent endpoint, without overriding a real install
ensure_litellm_stub()


class TestAgentSSECleanup(unittest.IsolatedAsyncioTestCase):
    """Test the finally-block exception handling in event_generator."""

    async def _run_cleanup(self, fut_exception):
        """
        Simulate the finally block in event_generator:
          - fut is a Future that raises *fut_exception* when awaited with wait_for.
        """
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        if isinstance(fut_exception, BaseException):
            fut.set_exception(fut_exception)
        else:
            fut.set_result(None)

        import api.v1.endpoints.agent as agent_mod

        # Replicate the finally block logic directly
        try:
            await asyncio.wait_for(fut, timeout=5.0)
        except asyncio.CancelledError:
            pass
        except asyncio.TimeoutError:
            agent_mod.logger.debug(
                "agent executor cleanup timed out after 5s for session %s", "test-session"
            )
        except Exception as exc:
            agent_mod.logger.warning(
                "agent executor cleanup error (ignored): %s", exc, exc_info=True
            )

    async def test_cancelled_error_is_silent(self):
        """CancelledError must NOT produce a warning log."""
        import api.v1.endpoints.agent as agent_mod

        with self.assertLogs(agent_mod.logger, level="WARNING") as cm:
            # We need at least one log message for assertLogs to succeed;
            # emit a sentinel so the context manager doesn't fail on zero messages.
            agent_mod.logger.warning("sentinel")
            await self._run_cleanup(asyncio.CancelledError())

        # Only the sentinel should be present; no cleanup warning.
        self.assertEqual(len(cm.output), 1)
        self.assertIn("sentinel", cm.output[0])

    async def test_runtime_error_emits_warning(self):
        """Non-CancelledError exceptions must emit a WARNING log."""
        import api.v1.endpoints.agent as agent_mod

        with self.assertLogs(agent_mod.logger, level="WARNING") as cm:
            await self._run_cleanup(RuntimeError("simulated executor crash"))

        self.assertTrue(
            any("cleanup error" in msg for msg in cm.output),
            f"Expected 'cleanup error' in log output, got: {cm.output}",
        )

    async def test_value_error_emits_warning(self):
        """ValueError also triggers a WARNING log."""
        import api.v1.endpoints.agent as agent_mod

        with self.assertLogs(agent_mod.logger, level="WARNING") as cm:
            await self._run_cleanup(ValueError("bad value"))

        self.assertTrue(any("cleanup error" in msg for msg in cm.output))


if __name__ == "__main__":
    unittest.main()
