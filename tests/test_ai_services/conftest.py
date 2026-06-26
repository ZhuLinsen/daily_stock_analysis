# -*- coding: utf-8 -*-
"""Test configuration for AI services tests.

This conftest prevents the root tests/conftest.py from being loaded,
which requires heavyweight dependencies like fastapi and anyio.
"""
