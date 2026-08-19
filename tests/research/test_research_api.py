# -*- coding: utf-8 -*-
"""API tests for the read-only research job endpoints."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.endpoints import research as research_endpoint
from src.agent.research_jobs import ResearchJobService
from src.agent.research_orchestrator import ResearchOrchestrator
from tests.research.mock_provider import MockResearchProvider


def _client() -> TestClient:
    app = FastAPI()
    app.state.research_job_service = ResearchJobService(
        ResearchOrchestrator([MockResearchProvider()])
    )
    app.include_router(research_endpoint.router, prefix="/api/v1/research")
    return TestClient(app)


class TestResearchAPI:
    def test_create_query_and_no_order_fields(self) -> None:
        client = _client()
        created = client.post(
            "/api/v1/research/jobs",
            json={"subject": "TEST", "market": "cn", "as_of": "2026-07-01"},
        )
        assert created.status_code == 200
        body = created.json()
        assert body["status"] == "succeeded"
        assert body["decision"]["short_term"]["stance"]
        assert body["decision"]["medium_term"]["stance"]
        assert body["decision"]["long_term"]["stance"]
        assert "conflicts" in body["decision"]
        assert "order" not in body
        assert "broker" not in body
        assert "quantity" not in body
        dumped = created.text
        assert "place_order" not in dumped

        fetched = client.get(f"/api/v1/research/jobs/{body['job_id']}")
        assert fetched.status_code == 200
        assert fetched.json()["job_id"] == body["job_id"]

    def test_idempotent_create(self) -> None:
        client = _client()
        payload = {"subject": "TEST", "as_of": "2026-07-01", "idempotency_key": "api-dup"}
        first = client.post("/api/v1/research/jobs", json=payload).json()
        second = client.post("/api/v1/research/jobs", json=payload).json()
        assert first["job_id"] == second["job_id"]

    def test_cancel_unknown_job(self) -> None:
        client = _client()
        response = client.post("/api/v1/research/jobs/missing/cancel")
        assert response.status_code == 404

    def test_unknown_horizon_rejected(self) -> None:
        client = _client()
        response = client.post(
            "/api/v1/research/jobs",
            json={"subject": "TEST", "horizons": ["intraday"]},
        )
        assert response.status_code == 400
