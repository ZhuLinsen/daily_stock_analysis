# -*- coding: utf-8 -*-
"""Tests for Issue #1904 P2 PR1 skill opinion sample persistence."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError

from src.agent.protocols import AgentContext, AgentOpinion
from src.agent.runtime_facts import (
    AgentRuntimeFacts,
    SkillOpinionFact,
    build_agent_runtime_facts,
)
from src.agent.skills.skill_agent import SkillAgent
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


def _skill_agent_facts(confidence) -> tuple[object, AgentRuntimeFacts]:
    ctx = AgentContext(stock_code="600519", stock_name="Test Stock")
    with patch.object(SkillAgent, "_load_skill", return_value=None):
        agent = SkillAgent(
            skill_id="alpha",
            tool_registry=MagicMock(),
            llm_adapter=MagicMock(),
        )
    opinion = agent.post_process(
        ctx,
        json.dumps(
            {
                "signal": "buy",
                "confidence": confidence,
                "reasoning": "valid test opinion",
            }
        ),
    )
    if opinion is not None:
        ctx.add_opinion(opinion)
    return opinion, build_agent_runtime_facts(ctx)


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


def test_service_retries_sqlite_locked_write_without_losing_samples(isolated_db) -> None:
    history_id = _add_history(isolated_db)
    service = SkillOpinionSampleService(db_manager=isolated_db)
    first_session = isolated_db.get_session()
    second_session = isolated_db.get_session()
    locked = OperationalError(
        "INSERT",
        None,
        sqlite3.OperationalError("database is locked"),
    )

    with patch.object(
        isolated_db,
        "get_session",
        side_effect=[first_session, second_session],
    ):
        with patch.object(first_session, "execute", side_effect=locked):
            with patch("src.storage.time.sleep") as sleep:
                created = service.persist(
                    analysis_history_id=history_id,
                    stock_code="600519",
                    opinions=(
                        SkillOpinionFact(
                            skill_id="alpha",
                            signal="buy",
                            confidence=0.8,
                        ),
                    ),
                )

    assert created == 1
    sleep.assert_called_once_with(isolated_db._sqlite_write_retry_base_delay)
    rows = SkillOpinionSampleRepository(isolated_db).list_for_history(history_id)
    assert [(row.skill_id, row.signal) for row in rows] == [("alpha", "buy")]


def test_history_deletion_retries_sqlite_locked_write(isolated_db) -> None:
    history_id = _add_history(isolated_db)
    first_session = isolated_db.get_session()
    second_session = isolated_db.get_session()
    locked = OperationalError(
        "SELECT",
        None,
        sqlite3.OperationalError("database is locked"),
    )

    with patch.object(
        isolated_db,
        "get_session",
        side_effect=[first_session, second_session],
    ):
        with patch.object(first_session, "execute", side_effect=locked):
            with patch("src.storage.time.sleep") as sleep:
                deleted = isolated_db.delete_analysis_history_records([history_id])

    assert deleted == 1
    sleep.assert_called_once_with(isolated_db._sqlite_write_retry_base_delay)
    assert isolated_db.get_analysis_history_by_id(history_id) is None


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


@pytest.mark.parametrize(
    "confidence",
    [float("nan"), float("inf"), -0.01, 1.01, 10**400, True, False],
)
def test_service_rejects_invalid_confidence_as_final_guard(
    isolated_db,
    confidence,
) -> None:
    history_id = _add_history(isolated_db)
    service = SkillOpinionSampleService(db_manager=isolated_db)

    with pytest.raises(ValueError, match="skill opinion confidence"):
        service.persist(
            analysis_history_id=history_id,
            stock_code="600519",
            opinions=(
                SkillOpinionFact(
                    skill_id="alpha",
                    signal="buy",
                    confidence=confidence,
                ),
            ),
        )

    assert SkillOpinionSampleRepository(isolated_db).list_for_history(history_id) == []


@pytest.mark.parametrize("confidence", [0, 1, 0.5])
def test_service_accepts_numeric_boundary_confidence_as_final_guard(
    isolated_db,
    confidence,
) -> None:
    history_id = _add_history(isolated_db)

    assert SkillOpinionSampleService(db_manager=isolated_db).persist(
        analysis_history_id=history_id,
        stock_code="600519",
        opinions=(
            SkillOpinionFact(
                skill_id="alpha",
                signal="buy",
                confidence=confidence,
            ),
        ),
    ) == 1

    rows = SkillOpinionSampleRepository(isolated_db).list_for_history(history_id)
    assert [(row.skill_id, row.confidence) for row in rows] == [
        ("alpha", float(confidence)),
    ]


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


def test_delayed_sample_write_after_history_deletion_creates_no_orphan(isolated_db) -> None:
    history_id = _add_history(isolated_db)
    opinion, facts = _skill_agent_facts(0.73)
    assert opinion is not None

    assert isolated_db.delete_analysis_history_records([history_id]) == 1
    assert SkillOpinionSampleService(db_manager=isolated_db).persist(
        analysis_history_id=history_id,
        stock_code="600519",
        opinions=facts.skill_opinions,
    ) == 0

    assert SkillOpinionSampleRepository(isolated_db).list_for_history(history_id) == []


def test_interleaved_sample_insert_and_history_delete_leave_no_orphan(isolated_db) -> None:
    history_id = _add_history(isolated_db)
    _, facts = _skill_agent_facts(0.73)
    service = SkillOpinionSampleService(db_manager=isolated_db)
    original_run_write_transaction = isolated_db._run_write_transaction
    insert_has_write_lock = threading.Event()
    allow_insert = threading.Event()
    delete_started = threading.Event()

    def coordinated_transaction(operation_name, write_operation):
        if operation_name == "insert skill opinion samples":

            def _pause_after_write_lock(session):
                insert_has_write_lock.set()
                assert allow_insert.wait(timeout=5)
                return write_operation(session)

            return original_run_write_transaction(operation_name, _pause_after_write_lock)
        if operation_name == "delete analysis history records":
            delete_started.set()
        return original_run_write_transaction(operation_name, write_operation)

    with patch.object(
        isolated_db,
        "_run_write_transaction",
        side_effect=coordinated_transaction,
    ):
        with ThreadPoolExecutor(max_workers=2) as executor:
            insert_future = executor.submit(
                service.persist,
                analysis_history_id=history_id,
                stock_code="600519",
                opinions=facts.skill_opinions,
            )
            assert insert_has_write_lock.wait(timeout=5)
            delete_future = executor.submit(
                isolated_db.delete_analysis_history_records,
                [history_id],
            )
            assert delete_started.wait(timeout=5)
            allow_insert.set()
            assert insert_future.result(timeout=5) == 1
            assert delete_future.result(timeout=5) == 1

    assert isolated_db.get_analysis_history_by_id(history_id) is None
    assert SkillOpinionSampleRepository(isolated_db).list_for_history(history_id) == []


@pytest.mark.parametrize("confidence", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_skill_agent_confidence_creates_no_sample(
    isolated_db,
    confidence,
) -> None:
    history_id = _add_history(isolated_db)
    opinion, facts = _skill_agent_facts(confidence)

    assert opinion is None
    assert facts.skill_opinions == ()
    assert SkillOpinionSampleService(db_manager=isolated_db).persist(
        analysis_history_id=history_id,
        stock_code="600519",
        opinions=facts.skill_opinions,
    ) == 0
    assert SkillOpinionSampleRepository(isolated_db).list_for_history(history_id) == []


@pytest.mark.parametrize("confidence", [-0.01, 1.01, 10**400, True, "0.8", None])
def test_skill_agent_rejects_out_of_range_or_non_numeric_confidence(confidence) -> None:
    opinion, facts = _skill_agent_facts(confidence)

    assert opinion is None
    assert facts.skill_opinions == ()


@pytest.mark.parametrize("confidence", [float("nan"), float("inf"), float("-inf")])
def test_runtime_facts_defensively_filter_clamped_invalid_skill_confidence(
    confidence,
) -> None:
    ctx = AgentContext()
    ctx.add_opinion(
        AgentOpinion(
            agent_name="skill_alpha",
            signal="buy",
            confidence=confidence,
        )
    )

    assert build_agent_runtime_facts(ctx).skill_opinions == ()


def test_runtime_facts_preserve_invalid_confidence_through_canonical_copy() -> None:
    from src.agent.skills.engine import StrategyEngine

    partition = StrategyEngine().partition_only(
        [
            AgentOpinion(
                agent_name="skill_alpha",
                signal="strong-buy",
                confidence=float("nan"),
            )
        ]
    )
    ctx = AgentContext(opinions=partition.valid_skill_opinions)

    assert ctx.opinions[0].signal == "strong_buy"
    assert build_agent_runtime_facts(ctx).skill_opinions == ()


def test_valid_skill_agent_confidence_persists_through_real_chain(isolated_db) -> None:
    history_id = _add_history(isolated_db)
    opinion, facts = _skill_agent_facts(0.73)

    assert opinion is not None
    assert facts.skill_opinions == (
        SkillOpinionFact(
            skill_id="alpha",
            signal="buy",
            confidence=0.73,
            observed_at=opinion.timestamp,
        ),
    )
    assert SkillOpinionSampleService(db_manager=isolated_db).persist(
        analysis_history_id=history_id,
        stock_code="600519",
        opinions=facts.skill_opinions,
    ) == 1
    rows = SkillOpinionSampleRepository(isolated_db).list_for_history(history_id)
    assert [(row.skill_id, row.confidence) for row in rows] == [("alpha", 0.73)]


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
