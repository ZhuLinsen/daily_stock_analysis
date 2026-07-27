# -*- coding: utf-8 -*-
"""Focused tests for concurrent strategy-skill scheduling."""

from datetime import date
import threading
import time
import unittest

from src.agent.protocols import AgentContext, AgentOpinion, StageResult, StageStatus
from src.agent.skills.scheduler import AgentSkillScheduler
from src.services.history_loader import (
    get_frozen_target_date,
    reset_frozen_target_date,
    set_frozen_target_date,
)


class _FakeSkillAgent:
    def __init__(self, agent_name):
        self.agent_name = agent_name


class TestAgentSkillScheduler(unittest.TestCase):
    def test_runs_skill_agents_concurrently_and_preserves_input_order(self):
        active = 0
        max_active = 0
        lock = threading.Lock()
        two_running = threading.Event()

        def run_stage(agent, ctx, progress_callback=None, timeout_seconds=None):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
                if active == 2:
                    two_running.set()
            two_running.wait(0.2)
            time.sleep(0.01)
            with lock:
                active -= 1
            opinion = AgentOpinion(
                agent_name=agent.agent_name,
                signal="buy",
                confidence=0.7,
                reasoning=agent.agent_name,
            )
            ctx.add_opinion(opinion)
            result = StageResult(stage_name=agent.agent_name, status=StageStatus.COMPLETED)
            result.opinion = opinion
            return result

        agents = [
            _FakeSkillAgent("skill_bull_trend"),
            _FakeSkillAgent("skill_hot_theme"),
            _FakeSkillAgent("skill_fund_flow"),
        ]
        ctx = AgentContext(query="test")
        scheduler = AgentSkillScheduler(max_concurrency=2)

        batch = scheduler.run(agents, ctx, run_stage)

        self.assertEqual(max_active, 2)
        self.assertEqual(
            [opinion.agent_name for opinion in batch.opinions],
            ["skill_bull_trend", "skill_hot_theme", "skill_fund_flow"],
        )
        self.assertEqual(ctx.opinions, [])

    def test_runs_four_selected_skills_when_concurrency_is_four(self):
        active = 0
        max_active = 0
        lock = threading.Lock()
        four_running = threading.Barrier(4, timeout=2)

        def run_stage(agent, ctx, progress_callback=None, timeout_seconds=None):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            try:
                four_running.wait()
            except threading.BrokenBarrierError:
                pass
            with lock:
                active -= 1
            opinion = AgentOpinion(
                agent_name=agent.agent_name,
                signal="buy",
                confidence=0.7,
            )
            return StageResult(
                stage_name=agent.agent_name,
                status=StageStatus.COMPLETED,
                opinion=opinion,
            )

        agents = [_FakeSkillAgent(f"skill_{index}") for index in range(4)]
        batch = AgentSkillScheduler(max_concurrency=4).run(
            agents,
            AgentContext(query="test"),
            run_stage,
        )

        self.assertEqual(max_active, 4)
        self.assertEqual(len(batch.opinions), 4)
        self.assertEqual([item.agent_name for item in batch.opinions], [
            "skill_0",
            "skill_1",
            "skill_2",
            "skill_3",
        ])

    def test_single_worker_inherits_frozen_target_date(self):
        self._assert_frozen_target_date_visible(agent_count=1, max_concurrency=1)

    def test_concurrent_workers_inherit_frozen_target_date(self):
        self._assert_frozen_target_date_visible(agent_count=2, max_concurrency=2)

    def _assert_frozen_target_date_visible(self, *, agent_count, max_concurrency):
        frozen_date = date(2026, 7, 22)
        observed = []
        all_running = threading.Barrier(agent_count, timeout=2) if agent_count > 1 else None

        def run_stage(agent, ctx, progress_callback=None, timeout_seconds=None):
            if all_running is not None:
                try:
                    all_running.wait()
                except threading.BrokenBarrierError:
                    pass
            observed.append(get_frozen_target_date())
            return StageResult(
                stage_name=agent.agent_name,
                status=StageStatus.COMPLETED,
                opinion=AgentOpinion(
                    agent_name=agent.agent_name,
                    signal="buy",
                    confidence=0.7,
                ),
            )

        token = set_frozen_target_date(frozen_date)
        try:
            AgentSkillScheduler(max_concurrency=max_concurrency).run(
                [_FakeSkillAgent(f"skill_{index}") for index in range(agent_count)],
                AgentContext(query="test"),
                run_stage,
            )
        finally:
            reset_frozen_target_date(token)

        self.assertEqual(observed, [frozen_date] * agent_count)

    def test_failed_skill_becomes_diagnostic_record(self):
        def run_stage(agent, ctx, progress_callback=None, timeout_seconds=None):
            return StageResult(
                stage_name=agent.agent_name,
                status=StageStatus.FAILED,
                error="skill timed out",
            )

        agent = _FakeSkillAgent("skill_hot_theme")
        scheduler = AgentSkillScheduler(max_concurrency=4, timeout_per_skill=30)

        batch = scheduler.run([agent], AgentContext(query="test"), run_stage)

        self.assertEqual(batch.opinions, [])
        self.assertEqual(len(batch.invalid_records), 1)
        self.assertEqual(batch.invalid_records[0]["agent_name"], "skill_hot_theme")
        self.assertEqual(batch.invalid_records[0]["reason"], "skill_timeout")
        self.assertEqual(batch.timeout_per_skill, 30)

    def test_success_without_opinion_becomes_skill_error(self):
        def run_stage(agent, ctx, progress_callback=None, timeout_seconds=None):
            return StageResult(stage_name=agent.agent_name, status=StageStatus.COMPLETED)

        agent = _FakeSkillAgent("skill_hot_theme")
        scheduler = AgentSkillScheduler(max_concurrency=1)

        batch = scheduler.run([agent], AgentContext(query="test"), run_stage)

        self.assertEqual(len(batch.invalid_records), 1)
        self.assertEqual(batch.invalid_records[0]["reason"], "skill_error")

    def test_legacy_unprefixed_specialist_name_is_scheduled(self):
        def run_stage(agent, ctx, progress_callback=None, timeout_seconds=None):
            return StageResult(
                stage_name=agent.agent_name,
                status=StageStatus.FAILED,
                error="legacy specialist failed",
            )

        agent = _FakeSkillAgent("chan_theory")
        scheduler = AgentSkillScheduler(max_concurrency=1)

        batch = scheduler.run([agent], AgentContext(query="test"), run_stage)

        self.assertEqual([result.stage_name for result in batch.stage_results], ["chan_theory"])
        self.assertEqual(len(batch.invalid_records), 1)
        self.assertEqual(batch.invalid_records[0]["agent_name"], "chan_theory")


if __name__ == "__main__":
    unittest.main()
