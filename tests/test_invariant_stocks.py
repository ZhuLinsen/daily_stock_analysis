import pytest
import sys
import os
from fastapi.testclient import TestClient

# Add the project root to sys.path to import the actual module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from api.v1.endpoints.stocks import router
from fastapi import FastAPI

app = FastAPI()
app.include_router(router)
client = TestClient(app)

@pytest.mark.parametrize("payload", [
    # Exact exploit case: extremely large text field
    {"text": "A" * 10_000_000},
    # Boundary case: just above typical reasonable limit
    {"text": "X" * 100_001},
    # Valid input
    {"text": "AAPL,100,2023-01-01"},
    # Adversarial content: injection attempt
    {"text": "'; DROP TABLE stocks; --"},
    # Empty string (edge case)
    {"text": ""},
])
def test_stocks_parse_import_text_field_security(payload):
    """Invariant: The endpoint must enforce reasonable size limits and not crash or hang on adversarial text input."""
    
    response = client.post(
        "/api/v1/stocks/parse-import",
        json=payload,
        headers={"Content-Type": "application/json"}
    )
    
    # Security property: must not crash (5xx) or hang (timeout handled by test framework)
    # The endpoint must either:
    # 1. Accept with valid input (2xx)
    # 2. Reject with proper error (4xx)
    # But never crash with 5xx or hang indefinitely
    assert response.status_code != 500, f"Server crashed on payload: {payload}"
    assert response.status_code != 502, f"Bad gateway error on payload: {payload}"
    assert response.status_code != 503, f"Service unavailable on payload: {payload}"
    assert response.status_code != 504, f"Gateway timeout on payload: {payload}"
    
    # Additional invariant: response must be JSON (if it's a 4xx/2xx from our API)
    if response.status_code in (200, 400):
        assert response.headers.get("content-type") == "application/json"