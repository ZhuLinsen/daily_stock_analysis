# -*- coding: utf-8 -*-
"""Tests for FastAPI app CORS configuration."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.middleware.cors import CORSMiddleware

from api.app import create_app


class AppCorsConfigTestCase(unittest.TestCase):
    """CORS configuration should stay browser-compatible."""

    def _build_app(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        return create_app(static_dir=Path(temp_dir.name))

    def test_allow_all_disables_credentials(self):
        with patch.dict(os.environ, {"CORS_ALLOW_ALL": "true"}, clear=False):
            app = self._build_app()

        cors = next(m for m in app.user_middleware if m.cls is CORSMiddleware)
        self.assertEqual(cors.kwargs["allow_origins"], ["*"])
        self.assertFalse(cors.kwargs["allow_credentials"])

    def test_explicit_origin_list_keeps_credentials_enabled(self):
        with patch.dict(os.environ, {"CORS_ALLOW_ALL": "false"}, clear=False):
            app = self._build_app()

        cors = next(m for m in app.user_middleware if m.cls is CORSMiddleware)
        self.assertIn("http://localhost:5173", cors.kwargs["allow_origins"])
        self.assertTrue(cors.kwargs["allow_credentials"])


if __name__ == "__main__":
    unittest.main()
