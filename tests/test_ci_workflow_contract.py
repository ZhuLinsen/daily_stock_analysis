# -*- coding: utf-8 -*-
"""Contracts for selective CI gates and their cross-layer inputs."""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _workflow(relative_path: str) -> dict:
    return yaml.load(_read(relative_path), Loader=yaml.BaseLoader)


def _change_filters(ci: dict) -> tuple[dict, dict, dict]:
    changes_job = ci["jobs"]["changes"]
    filter_step = next(
        step for step in changes_job["steps"] if step.get("id") == "filter"
    )
    backend_filter_step = next(
        step for step in changes_job["steps"] if step.get("id") == "backend-filter"
    )
    return changes_job, filter_step, backend_filter_step


def test_heavy_ci_jobs_are_path_filtered_and_backend_tests_are_sharded() -> None:
    ci = _workflow(".github/workflows/ci.yml")
    changes_job, filter_step, backend_filter_step = _change_filters(ci)
    filters = str(filter_step["with"]["filters"])
    parsed_filters = yaml.load(filters, Loader=yaml.BaseLoader)
    backend_contract_paths = set(parsed_filters["backend_web_contract"])
    backend_filters = yaml.load(
        str(backend_filter_step["with"]["filters"]),
        Loader=yaml.BaseLoader,
    )

    assert changes_job["outputs"]["backend"] == (
        "${{ steps.backend-filter.outputs.backend_non_web == 'true' || "
        "steps.filter.outputs.backend_web_contract == 'true' }}"
    )
    assert changes_job["outputs"]["docker"] == "${{ steps.filter.outputs.docker }}"
    assert backend_filter_step["with"]["predicate-quantifier"] == "every"
    assert backend_filters["backend_non_web"] == ["**", "!apps/dsa-web/**"]
    assert "docker:" in filters
    assert "docker/**" in filters
    assert {
        "apps/dsa-web/public/**",
        "apps/dsa-web/src/components/settings/llmProviderTemplates.ts",
        "apps/dsa-web/src/locales/settingsHelp.ts",
    } == backend_contract_paths

    backend_tests_job = ci["jobs"]["backend-tests"]
    backend_gate_job = ci["jobs"]["backend-gate"]
    docker_job = ci["jobs"]["docker-build"]
    assert backend_tests_job["needs"] == ["changes", "ai-governance"]
    assert backend_tests_job["if"] == "needs.changes.outputs.backend == 'true'"
    assert backend_tests_job["strategy"]["fail-fast"] == "false"
    assert backend_tests_job["strategy"]["matrix"]["shard"] == ["1", "2", "3"]
    assert backend_gate_job["needs"] == [
        "changes",
        "ai-governance",
        "backend-tests",
    ]
    assert backend_gate_job["if"] == "always()"
    assert docker_job["needs"] == ["changes", "ai-governance"]
    assert docker_job["if"] == "needs.changes.outputs.docker == 'true'"

    install_step = next(
        step
        for step in backend_tests_job["steps"]
        if step["name"] == "📦 Install dependencies"
    )
    assert "python -m pip install -r .github/requirements-ci.txt" in install_step["run"]
    shard_step = next(
        step
        for step in backend_tests_job["steps"]
        if step["name"] == "✅ Offline test suite shard ${{ matrix.shard }}/3"
    )
    assert shard_step["env"] == {
        "PYTEST_SPLITS": "3",
        "PYTEST_GROUP": "${{ matrix.shard }}",
        "PYTEST_FIRST_SHARD_OVERHEAD": "20",
    }

    requirements = _read(".github/requirements-ci.txt")
    ci_gate = _read("scripts/ci_gate.sh")
    assert "pytest-xdist" not in requirements
    assert "PYTEST_WORKERS" not in ci_gate
    assert "pytest-split" not in requirements
    assert 'python scripts/ci_test_shard.py' in ci_gate
    assert '--first-shard-overhead "${PYTEST_FIRST_SHARD_OVERHEAD:-0}"' in ci_gate
    assert '.github/ci-test-durations.json' in ci_gate
    assert '--durations=30' in ci_gate


def test_backend_filter_covers_mixed_changes_and_shared_web_assets() -> None:
    """Model the complete backend output, including shared Web-owned assets."""
    ci = _workflow(".github/workflows/ci.yml")
    _, filter_step, backend_filter_step = _change_filters(ci)
    backend_web_contract = yaml.load(
        str(filter_step["with"]["filters"]),
        Loader=yaml.BaseLoader,
    )["backend_web_contract"]
    backend_filters = yaml.load(
        str(backend_filter_step["with"]["filters"]),
        Loader=yaml.BaseLoader,
    )["backend_non_web"]

    def matches_every_rule(path: str) -> bool:
        return all(
            not fnmatchcase(path, rule[1:])
            if rule.startswith("!")
            else fnmatchcase(path, rule)
            for rule in backend_filters
        )

    def backend_output(changed_paths: list[str]) -> bool:
        backend_non_web = any(matches_every_rule(path) for path in changed_paths)
        web_contract_hit = any(
            fnmatchcase(path, rule)
            for path in changed_paths
            for rule in backend_web_contract
        )
        return backend_non_web or web_contract_hit

    assert backend_filter_step["with"]["predicate-quantifier"] == "every"
    assert backend_output(["apps/dsa-web/src/App.tsx"]) is False
    assert backend_output(["apps/dsa-web/src/App.tsx", "src/config.py"]) is True
    assert backend_output(["apps/dsa-web/src/App.tsx", "docs/CHANGELOG.md"]) is True
    assert backend_output(["apps/dsa-web/public/stocks.index.json"]) is True
    assert backend_output(["apps/dsa-web/public/runtime/new-asset.json"]) is True
