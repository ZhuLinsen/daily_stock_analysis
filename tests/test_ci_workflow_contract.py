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


def _expand_brace_pattern(pattern: str) -> list[str]:
    """Expand the single brace group used by the CI path filters."""
    if "{" not in pattern:
        return [pattern]
    prefix, remainder = pattern.split("{", 1)
    choices, suffix = remainder.split("}", 1)
    return [f"{prefix}{choice}{suffix}" for choice in choices.split(",")]


def _matches_every_rule(path: str, rules: list[str]) -> bool:
    def matches(rule: str) -> bool:
        patterns = _expand_brace_pattern(rule.removeprefix("!"))
        matched = any(
            fnmatchcase(path, pattern)
            or (pattern.startswith("**/") and fnmatchcase(path, pattern[3:]))
            for pattern in patterns
        )
        return not matched if rule.startswith("!") else matched

    return all(matches(rule) for rule in rules)


def _filter_output(changed_paths: list[str], rules: list[str]) -> bool:
    return any(_matches_every_rule(path, rules) for path in changed_paths)


def test_heavy_ci_jobs_are_path_filtered_and_backend_tests_are_sharded() -> None:
    ci = _workflow(".github/workflows/ci.yml")
    changes_job, filter_step, backend_filter_step = _change_filters(ci)
    filters = str(filter_step["with"]["filters"])
    parsed_filters = yaml.load(filters, Loader=yaml.BaseLoader)
    backend_filters = yaml.load(
        str(backend_filter_step["with"]["filters"]),
        Loader=yaml.BaseLoader,
    )
    frontend_filter_step = next(
        step for step in changes_job["steps"] if step.get("id") == "frontend-filter"
    )
    frontend_filters = yaml.load(
        str(frontend_filter_step["with"]["filters"]),
        Loader=yaml.BaseLoader,
    )

    assert changes_job["outputs"]["backend"] == (
        "${{ steps.backend-filter.outputs.backend_non_web == 'true' || "
        "steps.filter.outputs.backend_contract_assets == 'true' || "
        "steps.filter.outputs.backend_web_contract == 'true' }}"
    )
    assert changes_job["outputs"]["docker"] == "${{ steps.filter.outputs.docker }}"
    assert changes_job["outputs"]["frontend"] == (
        "${{ steps.frontend-filter.outputs.frontend_code }}"
    )
    assert filter_step["with"]["predicate-quantifier"] == "every"
    assert backend_filter_step["with"]["predicate-quantifier"] == "every"
    assert frontend_filter_step["with"]["predicate-quantifier"] == "every"
    assert backend_filters["backend_non_web"] == [
        "**",
        "!apps/dsa-web/**",
        "!docs/**",
        "!**/*.md",
        "!LICENSE",
    ]
    assert frontend_filters["frontend_code"] == [
        "apps/dsa-web/**",
        "!**/*.md",
    ]
    assert "docker:" in filters
    assert "docker/**" in filters
    assert set(
        _expand_brace_pattern(parsed_filters["backend_web_contract"][0])
    ) == {
        "apps/dsa-web/public/**",
        "apps/dsa-web/src/components/settings/llmProviderTemplates.ts",
        "apps/dsa-web/src/locales/settingsHelp.ts",
    }
    assert parsed_filters["backend_web_contract"][1] == "!**/*.md"
    assert set(
        _expand_brace_pattern(parsed_filters["backend_contract_assets"][0])
    ) >= {
        "THIRD_PARTY_NOTICES.md",
        "docs/architecture/**",
        "docs/alerts.md",
        "docs/full-guide.md",
        "tests/fixtures/**",
    }

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
    """Model heavy-job outputs for docs-only, code, and mixed changes."""
    ci = _workflow(".github/workflows/ci.yml")
    changes_job, filter_step, backend_filter_step = _change_filters(ci)
    filters = yaml.load(
        str(filter_step["with"]["filters"]),
        Loader=yaml.BaseLoader,
    )
    backend_filters = yaml.load(
        str(backend_filter_step["with"]["filters"]),
        Loader=yaml.BaseLoader,
    )["backend_non_web"]
    frontend_filter_step = next(
        step for step in changes_job["steps"] if step.get("id") == "frontend-filter"
    )
    frontend_filters = yaml.load(
        str(frontend_filter_step["with"]["filters"]),
        Loader=yaml.BaseLoader,
    )["frontend_code"]

    def outputs(changed_paths: list[str]) -> tuple[bool, bool, bool, bool]:
        backend = (
            _filter_output(changed_paths, backend_filters)
            or _filter_output(changed_paths, filters["backend_contract_assets"])
            or _filter_output(changed_paths, filters["backend_web_contract"])
        )
        return (
            backend,
            _filter_output(changed_paths, filters["docker"]),
            _filter_output(changed_paths, frontend_filters),
            _filter_output(changed_paths, filters["futu_packaging"]),
        )

    assert backend_filter_step["with"]["predicate-quantifier"] == "every"
    assert outputs(["docs/CHANGELOG.md"]) == (True, False, False, False)
    assert outputs(["docs/architecture/api_spec.json"])[0] is True
    assert outputs(["docs/alerts.md"])[0] is True
    assert outputs(["tests/fixtures/notification_reports/aggregate_report.md"])[0] is True
    assert outputs(["THIRD_PARTY_NOTICES.md"])[0] is True
    assert outputs(["docs/CONTRIBUTING.md"]) == (False, False, False, False)
    assert outputs(["README.md"]) == (False, False, False, False)
    assert outputs(["LICENSE"]) == (False, False, False, False)
    assert outputs(["apps/dsa-web/README.md"]) == (False, False, False, False)
    assert outputs(["apps/dsa-desktop/README.md"]) == (False, False, False, False)
    assert outputs(["src/config.py"]) == (True, True, False, False)
    assert outputs(["requirements.txt"]) == (True, True, False, True)
    assert outputs(["apps/dsa-web/src/App.tsx"]) == (False, True, True, False)
    assert outputs(["apps/dsa-web/src/App.tsx", "docs/CHANGELOG.md"]) == (
        True,
        True,
        True,
        False,
    )
    assert outputs(["apps/dsa-web/src/App.tsx", "src/config.py"]) == (
        True,
        True,
        True,
        False,
    )
    assert outputs(["apps/dsa-web/public/stocks.index.json"])[0] is True
    assert outputs(["apps/dsa-web/public/runtime/new-asset.json"])[0] is True
