"""Opt-in real FRED smoke test; never runs in default pytest."""

import os

import pytest

from src.config import get_config
from src.providers.macro.fred import FREDProvider

pytestmark = pytest.mark.network


@pytest.mark.skipif(
    os.getenv("RUN_NETWORK_TESTS") != "true",
    reason="set RUN_NETWORK_TESTS=true to enable real network tests",
)
def test_fred_dgs2_real_response_has_safe_boundary_fields():
    key = get_config().fred_api_key
    if not key:
        pytest.skip("FRED_API_KEY is not configured")
    observation = FREDProvider(key).fetch_latest("treasury_2y", "DGS2")
    assert observation is not None
    assert observation.value is not None and 0 < observation.value < 30
    assert observation.unit
    assert observation.observation_date is not None
    assert observation.source_url.endswith("/DGS2")
