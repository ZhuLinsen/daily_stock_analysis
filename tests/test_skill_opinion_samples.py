# -*- coding: utf-8 -*-
"""Tests for Issue #1904 P2 PR1 skill opinion sample persistence."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import inspect

from src.agent.runtime_facts import AgentRuntimeFacts, SkillOpinionFact
from src.config import Config
from src.core.pipeline import StockAnalysisPipeline
from src.repositories.skill_opinion_sample_repo import SkillOpinionSampleRepository
from src.services.skill_opinion_sample_service import (
    SKILL_OPINION_SAMPLE_SCHEMA_VERSION,
    SkillOpinionSampleService,
)
from src.storage import AnalysisHistory, DatabaseManager, SkillOpinionSampleRecord


@pytest.fixture()
def isolated_db(tmp_path):
    old_database_path = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = str(tmp_path / "skill_opinion_samples.db")
    Config.reset_instance()
    DatabaseManager.reset_instance()
    db = DatabaseManager.get_instance()
    try:
        yield db
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        if old_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = old_database_path


def _add_history(db: DatabaseManager, code: str = "600519") -> int:
    with db.session_scope() as session:
        row = AnalysisHistory(query_id="sample-query", code=code, report_type="simple")
        session.add(row)
        session.flush()
        return int(row.id)


def test_service_persists_low_sensitivity_samples_idempotently(isolated_db) -> None:
    history_id = _add_history(isolated_db)
    service = SkillOpinionSampleService(db_manager=isolated_db)
    opinions = (
        SkillOpinionFact(
            skill_id="bull_trend",
            signal="buy",
            confidence=0.81,
            observed_at=1_720_000_000.0,
        ),
        SkillOpinionFact(
            skill_id="hot_theme",
            signal="hold",
            confidence=0.55,
        ),
    )

    assert service.persist(
        analysis_history_id=history_id,
        stock_code="600519",
        opinions=opinions,
        data_quality_level="usable",
    ) == 2
    assert service.persist(
        analysis_history_id=history_id,
        stock_code="600519",
        opinions=opinions,
        data_quality_level="good",
    ) == 0

    rows = SkillOpinionSampleRepository(isolated_db).list_for_history(history_id)
    assert [(row.skill_id, row.signal, row.confidence) for row in rows] == [
        ("bull_trend", "buy", 0.81),
        ("hot_theme", "hold", 0.55),
    ]
    assert rows[0].sample_schema_version == SKILL_OPINION_SAMPLE_SCHEMA_VERSION
    assert rows[0].data_quality_level == "usable"
    assert rows[0].opinion_created_at is not None
    assert rows[0].horizon is None
    assert rows[0].skill_version is None


def test_service_ignores_duplicate_key_without_rolling_back_other_samples(isolated_db) -> None:
    history_id = _add_history(isolated_db)
    service = SkillOpinionSampleService(db_manager=isolated_db)

    assert service.persist(
        analysis_history_id=history_id,
        stock_code="600519",
        opinions=(
            SkillOpinionFact(skill_id="alpha", signal="buy", confidence=0.8),
            SkillOpinionFact(skill_id="alpha", signal="sell", confidence=0.2),
            SkillOpinionFact(skill_id="beta", signal="hold", confidence=0.6),
        ),
    ) == 2

    rows = SkillOpinionSampleRepository(isolated_db).list_for_history(history_id)
    assert [(row.skill_id, row.signal, row.confidence) for row in rows] == [
        ("alpha", "buy", 0.8),
        ("beta", "hold", 0.6),
    ]


def test_sample_schema_is_idempotent_and_has_identity_constraints(isolated_db) -> None:
    from src.storage import Base

    Base.metadata.create_all(isolated_db._engine)
    inspector = inspect(isolated_db._engine)
    unique_constraints = inspector.get_unique_constraints("skill_opinion_samples")
    indexes = {item["name"] for item in inspector.get_indexes("skill_opinion_samples")}

    assert any(
        item["name"] == "uix_skill_opinion_sample_key"
        and item["column_names"]
        == ["analysis_history_id", "skill_id", "sample_schema_version"]
        for item in unique_constraints
    )
    assert "ix_skill_opinion_sample_skill_horizon_created" in indexes
    assert "ix_skill_opinion_sample_stock_created" in indexes


def test_service_rejects_invalid_identity_without_creating_samples(isolated_db) -> None:
    history_id = _add_history(isolated_db)
    service = SkillOpinionSampleService(db_manager=isolated_db)

    with pytest.raises(ValueError, match="valid skill_id and signal"):
        service.persist(
            analysis_history_id=history_id,
            stock_code="600519",
            opinions=(SkillOpinionFact(skill_id="alpha", signal="moon", confidence=0.7),),
        )

    assert SkillOpinionSampleRepository(isolated_db).list_for_history(history_id) == []


def test_history_deletion_removes_dependent_skill_samples(isolated_db) -> None:
    history_id = _add_history(isolated_db)
    SkillOpinionSampleService(db_manager=isolated_db).persist(
        analysis_history_id=history_id,
        stock_code="600519",
        opinions=(SkillOpinionFact(skill_id="alpha", signal="buy", confidence=0.7),),
    )

    assert isolated_db.delete_analysis_history_records([history_id]) == 1
    with isolated_db.get_session() as session:
        assert session.query(SkillOpinionSampleRecord).count() == 0


def test_pipeline_helper_is_noop_without_skill_opinions() -> None:
    with patch("src.services.skill_opinion_sample_service.SkillOpinionSampleService") as service:
        pipeline = object.__new__(StockAnalysisPipeline)
        pipeline.db = MagicMock()
        pipeline._persist_skill_opinion_samples_after_history_save(
            runtime_facts=AgentRuntimeFacts(),
            analysis_history_id=1,
            stock_code="600519",
            analysis_context_pack_overview=None,
        )
    service.assert_not_called()


def test_pipeline_helper_persists_quality_and_fails_open() -> None:
    facts = AgentRuntimeFacts(
        skill_opinions=(SkillOpinionFact(skill_id="alpha", signal="buy", confidence=0.7),)
    )
    service = MagicMock()
    service.persist.side_effect = RuntimeError("private database path")
    with patch(
        "src.services.skill_opinion_sample_service.SkillOpinionSampleService",
        return_value=service,
    ) as service_class:
        pipeline = object.__new__(StockAnalysisPipeline)
        pipeline.db = MagicMock()
        pipeline._persist_skill_opinion_samples_after_history_save(
            runtime_facts=facts,
            analysis_history_id=42,
            stock_code="600519",
            analysis_context_pack_overview={"data_quality": {"level": "limited"}},
        )

    service_class.assert_called_once_with(db_manager=pipeline.db)
    service.persist.assert_called_once_with(
        analysis_history_id=42,
        stock_code="600519",
        opinions=facts.skill_opinions,
        data_quality_level="limited",
    )


def test_pipeline_helper_persists_sample_in_pipeline_database(isolated_db) -> None:
    history_id = _add_history(isolated_db)
    pipeline = object.__new__(StockAnalysisPipeline)
    pipeline.db = isolated_db
    facts = AgentRuntimeFacts(
        skill_opinions=(
            SkillOpinionFact(skill_id="alpha", signal="buy", confidence=0.7),
        )
    )

    pipeline._persist_skill_opinion_samples_after_history_save(
        runtime_facts=facts,
        analysis_history_id=history_id,
        stock_code="600519",
        analysis_context_pack_overview={"data_quality": {"level": "good"}},
    )

    rows = SkillOpinionSampleRepository(isolated_db).list_for_history(history_id)
    assert [(row.analysis_history_id, row.skill_id) for row in rows] == [
        (history_id, "alpha"),
    ]
