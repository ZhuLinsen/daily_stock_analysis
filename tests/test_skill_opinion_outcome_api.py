# -*- coding: utf-8 -*-
"""Admin API tests for Skill Opinion Outcome execution and read-only queries."""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

import src.auth as auth
from api.app import create_app
from src.config import Config
from src.storage import (
    AnalysisHistory,
    DatabaseManager,
    SkillOpinionOutcomeRecord,
    SkillOpinionSampleRecord,
    StockDaily,
)


def _reset_auth_globals() -> None:
    auth._auth_enabled = None
    auth._session_secret = None
    auth._password_hash_salt = None
    auth._password_hash_stored = None
    auth._rate_limit = {}


@pytest.fixture()
def client_and_db(tmp_path):
    old_env_file = os.environ.get("ENV_FILE")
    old_database_path = os.environ.get("DATABASE_PATH")
    env_path = tmp_path / ".env"
    db_path = tmp_path / "skill_opinion_outcome_api.db"
    static_dir = tmp_path / "empty-static"
    static_dir.mkdir()
    env_path.write_text(
        "\n".join(
            [
                "STOCK_LIST=600519",
                "GEMINI_API_KEY=test",
                "ADMIN_AUTH_ENABLED=false",
                f"DATABASE_PATH={db_path}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    os.environ["ENV_FILE"] = str(env_path)
    os.environ["DATABASE_PATH"] = str(db_path)
    _reset_auth_globals()
    Config.reset_instance()
    DatabaseManager.reset_instance()
    app = create_app(static_dir=Path(static_dir))
    client = TestClient(app)
    db = DatabaseManager.get_instance()
    try:
        yield client, db
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        _reset_auth_globals()
        if old_env_file is None:
            os.environ.pop("ENV_FILE", None)
        else:
            os.environ["ENV_FILE"] = old_env_file
        if old_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = old_database_path


def _add_sample(
    db: DatabaseManager,
    *,
    code: str = "600519",
    effective_date: str = "2024-01-02",
) -> int:
    with db.session_scope() as session:
        history = AnalysisHistory(
            query_id=f"outcome-api-{code}",
            code=code,
            report_type="simple",
            operation_advice="hold",
            context_snapshot=json.dumps(
                {
                    "market_phase_summary": {
                        "phase": "postmarket",
                        "effective_daily_bar_date": effective_date,
                    }
                }
            ),
            created_at=datetime(2024, 1, 2, 18, 0, 0),
        )
        session.add(history)
        session.flush()
        sample = SkillOpinionSampleRecord(
            analysis_history_id=history.id,
            stock_code=code,
            skill_id="alpha",
            signal="buy",
            confidence=0.8,
            sample_schema_version="skill-opinion-sample-v1",
        )
        session.add(sample)
        session.flush()
        return int(sample.id)


def _seed_bars(
    db: DatabaseManager,
    *,
    code: str,
    bars: list[tuple[date, float]],
) -> None:
    with db.session_scope() as session:
        for day, close in bars:
            session.add(
                StockDaily(
                    code=code,
                    date=day,
                    open=close,
                    high=close,
                    low=close,
                    close=close,
                )
            )


def test_admin_post_generates_variant_outcome_idempotently_and_get_is_read_only(
    client_and_db,
) -> None:
    client, db = client_and_db
    sample_id = _add_sample(db, code="600519.SH")
    _seed_bars(
        db,
        code="600519",
        bars=[(date(2024, 1, 2), 100.0), (date(2024, 1, 3), 105.0)],
    )

    first = client.post(
        "/api/v1/skill-opinion-outcomes/run",
        json={"sample_id": sample_id, "horizons": ["1d"]},
    )
    assert first.status_code == 200, first.text
    assert first.json()["created"] == 1
    assert first.json()["items"][0]["eval_status"] == "evaluated"
    assert first.json()["items"][0]["stock_return_pct"] == pytest.approx(5.0)

    repeated = client.post(
        "/api/v1/skill-opinion-outcomes/run",
        json={"sample_id": sample_id, "horizons": ["1d"]},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["processed_keys"] == 0

    with db.get_session() as session:
        count_before_get = session.query(SkillOpinionOutcomeRecord).count()
    response = client.get(
        "/api/v1/skill-opinion-outcomes",
        params={"sample_id": sample_id, "page": 1, "page_size": 10},
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["skill_opinion_sample_id"] == sample_id
    with db.get_session() as session:
        assert session.query(SkillOpinionOutcomeRecord).count() == count_before_get == 1


def test_admin_post_retries_pending_after_future_bar_arrives(client_and_db) -> None:
    client, db = client_and_db
    sample_id = _add_sample(db)
    _seed_bars(db, code="600519", bars=[(date(2024, 1, 2), 100.0)])

    pending = client.post(
        "/api/v1/skill-opinion-outcomes/run",
        json={"sample_id": sample_id, "horizons": ["1d"]},
    )
    assert pending.status_code == 200, pending.text
    assert pending.json()["items"][0]["eval_status"] == "pending"

    _seed_bars(db, code="600519", bars=[(date(2024, 1, 3), 105.0)])
    evaluated = client.post(
        "/api/v1/skill-opinion-outcomes/run",
        json={"sample_id": sample_id, "horizons": ["1d"]},
    )
    assert evaluated.status_code == 200, evaluated.text
    assert evaluated.json()["updated"] == 1
    assert evaluated.json()["items"][0]["eval_status"] == "evaluated"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("signal", "sell"),
        ("outcome", "hit"),
        ("engine_version", "forged"),
        ("start_price", 1.0),
        ("end_close", 2.0),
        ("direction_correct", True),
    ],
)
def test_admin_post_forbids_client_supplied_evaluation_fields(
    client_and_db,
    field,
    value,
) -> None:
    client, _db = client_and_db

    response = client.post(
        "/api/v1/skill-opinion-outcomes/run",
        json={"horizons": ["1d"], field: value},
    )

    assert response.status_code == 422


def test_admin_post_keeps_pending_when_exact_variant_start_date_is_missing(
    client_and_db,
) -> None:
    client, db = client_and_db
    sample_id = _add_sample(
        db,
        code="SH600519",
        effective_date="2024-01-03",
    )
    _seed_bars(
        db,
        code="600519",
        bars=[(date(2024, 1, 2), 100.0), (date(2024, 1, 4), 105.0)],
    )

    response = client.post(
        "/api/v1/skill-opinion-outcomes/run",
        json={"sample_id": sample_id, "horizons": ["1d"]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["eval_status"] == "pending"
    assert response.json()["items"][0]["unable_reason"] == "missing_start_bar"
