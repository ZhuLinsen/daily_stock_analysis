# -*- coding: utf-8 -*-
"""Thread-safety regression tests for ConversationManager."""

import threading
import unittest
from unittest.mock import patch

from src.agent.conversation import ConversationManager


class ConversationManagerThreadSafetyTestCase(unittest.TestCase):
    def test_add_message_is_safe_under_parallel_session_creation(self):
        manager = ConversationManager()
        errors = []
        start = threading.Event()

        def _worker(worker_id: int) -> None:
            start.wait()
            try:
                for message_id in range(1000):
                    manager.add_message(f"session-{worker_id}-{message_id}", "user", "hello")
            except Exception as exc:  # pragma: no cover - failures are asserted below
                errors.append(exc)

        threads = [
            threading.Thread(target=_worker, args=(idx,), daemon=True)
            for idx in range(6)
        ]

        with patch("src.agent.conversation.ConversationSession.add_message", autospec=True):
            for thread in threads:
                thread.start()
            start.set()
            for thread in threads:
                thread.join()

        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
