# -*- coding: utf-8 -*-
"""Tests for mimetypes cold-start behaviour on Windows."""

import importlib
import mimetypes
import sys
import unittest
from unittest.mock import patch


class MimetypesWindowsInitTestCase(unittest.TestCase):
    """Cold-start: Windows skips registry; non-Windows keeps full MIME db."""

    def setUp(self):
        self._types_map_backup = dict(mimetypes.types_map)

    def tearDown(self):
        mimetypes.types_map.clear()
        mimetypes.types_map.update(self._types_map_backup)

    @staticmethod
    def _simulate_cold_start():
        mimetypes.inited = False
        mimetypes._db = None

    def test_windows_cold_import_skips_registry(self):
        """Windows cold-start must not call read_windows_registry."""
        import api.app

        self._simulate_cold_start()
        with patch("sys.platform", "win32"), \
             patch.object(mimetypes.MimeTypes, "read_windows_registry") as mock_registry:
            importlib.reload(api.app)

        mock_registry.assert_not_called()

    def test_non_windows_retains_full_mime_guessing(self):
        """Non-Windows must NOT replace the system MIME database."""
        import api.app

        self._simulate_cold_start()
        with patch("sys.platform", "linux"):
            importlib.reload(api.app)

        self.assertEqual(
            mimetypes.guess_type("index.html")[0],
            "text/html",
            "HTML must still be detected on non-Windows",
        )
        self.assertEqual(
            mimetypes.guess_type("test.pdf")[0],
            "application/pdf",
            "PDF must still be detected on non-Windows",
        )

    def test_types_map_consistent_with_db(self):
        """types_map and _db.types_map[True] must be the same object."""
        import api.app

        self._simulate_cold_start()
        with patch("sys.platform", "win32"):
            importlib.reload(api.app)

        self.assertIs(
            mimetypes.types_map,
            mimetypes._db.types_map[True],
            "types_map must reference _db internals (no split-brain)",
        )

    def test_frontend_mime_types_registered_after_init(self):
        """_register_frontend_asset_mime_types must work after cold-start init."""
        import api.app

        self._simulate_cold_start()
        with patch("sys.platform", "win32"):
            importlib.reload(api.app)

        api.app._register_frontend_asset_mime_types()

        self.assertEqual(
            mimetypes.guess_type("app.js")[0], "text/javascript"
        )
        self.assertEqual(
            mimetypes.guess_type("style.css")[0], "text/css"
        )


if __name__ == "__main__":
    unittest.main()
