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
    site_filter_step = next(
        step for step in changes_job["steps"] if step.get("id") == "site-filter"
    )
    site_filters = yaml.load(
        str(site_filter_step["with"]["filters"]),
        Loader=yaml.BaseLoader,
    )

    assert changes_job["outputs"]["backend"] == (
        "${{ steps.backend-filter.outputs.backend_non_web == 'true' || "
        "steps.filter.outputs.backend_web_contract == 'true' || "
        "(github.event_name != 'pull_request' && "
        "steps.filter.outputs.backend_contract_assets == 'true') }}"
    )
    assert changes_job["outputs"]["backend_docs"] == (
        "${{ steps.filter.outputs.backend_contract_assets }}"
    )
    assert changes_job["outputs"]["docker"] == "${{ steps.filter.outputs.docker }}"
    assert changes_job["outputs"]["frontend"] == (
        "${{ steps.frontend-filter.outputs.frontend_code }}"
    )
    assert changes_job["outputs"]["frontend_runtime"] == (
        "${{ steps.frontend-filter.outputs.frontend_runtime }}"
    )
    assert filter_step["with"]["predicate-quantifier"] == "every"
    assert backend_filter_step["with"]["predicate-quantifier"] == "every"
    assert frontend_filter_step["with"]["predicate-quantifier"] == "every"
    assert site_filter_step["with"]["predicate-quantifier"] == "every"
    assert len(site_filters["site_code"]) == 1
    assert set(_expand_brace_pattern(site_filters["site_code"][0])) == {
        "apps/dsa-site/**",
        "docs/**",
        "strategies/README.md",
        ".github/workflows/ci.yml",
    }
    assert backend_filters["backend_non_web"] == [
        "**",
        "!apps/dsa-web/**",
        "!apps/dsa-site/**",
        "!docs/**",
        "!tests/fixtures/**",
        "!**/*.md",
        "!LICENSE",
    ]
    assert frontend_filters["frontend_code"] == [
        "apps/dsa-web/**",
        "!**/*.md",
    ]
    assert frontend_filters["frontend_runtime"] == [
        "apps/dsa-web/**",
        "!**/*.md",
        "!apps/dsa-web/src/**/__tests__/**",
        "!apps/dsa-web/**/*.test.ts",
        "!apps/dsa-web/**/*.test.tsx",
        "!apps/dsa-web/tests/**",
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
    docs_contract_job = ci["jobs"]["docs-contract-tests"]
    backend_gate_job = ci["jobs"]["backend-gate"]
    docker_job = ci["jobs"]["docker-build"]
    desktop_tests_job = ci["jobs"]["desktop-tests"]
    web_gate_job = ci["jobs"]["web-gate"]
    ci_gate_job = ci["jobs"]["ci-gate"]
    assert "push" in ci["on"]
    assert "pull_request" in ci["on"]
    assert "merge_group" in ci["on"]
    assert ci["permissions"]["contents"] == "read"
    assert backend_tests_job["needs"] == ["changes"]
    assert backend_tests_job["if"] == "needs.changes.outputs.backend == 'true'"
    assert backend_tests_job["strategy"]["fail-fast"] == "false"
    assert backend_tests_job["strategy"]["matrix"]["shard"] == ["1", "2", "3"]
    assert docs_contract_job["needs"] == ["changes"]
    assert docs_contract_job["if"] == (
        "needs.changes.outputs.backend != 'true' && "
        "needs.changes.outputs.backend_docs == 'true'"
    )
    docs_test_step = next(
        step
        for step in docs_contract_job["steps"]
        if step["name"] == "✅ Docs and fixture contract tests"
    )
    assert "grep -lE" in docs_test_step["run"]
    assert 'pytest -m "not network"' in docs_test_step["run"]
    assert backend_gate_job["needs"] == [
        "changes",
        "ai-governance",
        "backend-tests",
        "docs-contract-tests",
    ]
    assert backend_gate_job["if"] == "always()"
    assert docker_job["needs"] == ["changes"]
    assert docker_job["if"] == (
        "needs.changes.outputs.docker == 'true' || "
        "github.event_name != 'pull_request'"
    )
    assert desktop_tests_job["needs"] == ["changes"]
    assert desktop_tests_job["if"] == "needs.changes.outputs.desktop == 'true'"
    assert web_gate_job["needs"] == ["changes"]
    expected_runtime_if = (
        "needs.changes.outputs.frontend_runtime == 'true' || "
        "github.event_name != 'pull_request'"
    )
    for unconditional_run in ("npm run lint", "npm test"):
        step = next(s for s in web_gate_job["steps"] if s.get("run") == unconditional_run)
        assert "if" not in step
    build_step = next(s for s in web_gate_job["steps"] if s.get("run") == "npm run build")
    assert build_step["if"] == expected_runtime_if
    smoke_step = next(s for s in web_gate_job["steps"] if s.get("run") == "npm run test:smoke")
    assert smoke_step["if"] == expected_runtime_if
    fixture_step = next(
        s
        for s in web_gate_job["steps"]
        if s.get("run") == "npx playwright test --config playwright.fixture.config.ts"
    )
    assert fixture_step["if"] == expected_runtime_if
    assert any(
        step.get("uses", "").startswith("actions/cache@")
        and "~/.cache/ms-playwright" in str(step.get("with", {}).get("path", ""))
        for step in web_gate_job["steps"]
    )
    site_gate_job = ci["jobs"]["site-gate"]
    assert site_gate_job["needs"] == ["changes"]
    assert site_gate_job["if"] == "needs.changes.outputs.site == 'true'"
    assert ci_gate_job["if"] == "always()"
    assert set(ci_gate_job["needs"]) == {
        "changes",
        "ai-governance",
        "backend-gate",
        "web-gate",
        "desktop-tests",
        "site-gate",
        "docker-build",
        "desktop-futu-package-windows",
        "desktop-futu-package-macos",
    }

    install_step = next(
        step
        for step in backend_tests_job["steps"]
        if step["name"] == "📦 Install dependencies"
    )
    assert "uv pip install --system -r .github/requirements-ci.txt" in install_step["run"]
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
    frontend_filter_map = yaml.load(
        str(frontend_filter_step["with"]["filters"]),
        Loader=yaml.BaseLoader,
    )
    frontend_filters = frontend_filter_map["frontend_code"]
    frontend_runtime_filters = frontend_filter_map["frontend_runtime"]
    site_filter_step = next(
        step for step in changes_job["steps"] if step.get("id") == "site-filter"
    )
    site_filters = yaml.load(
        str(site_filter_step["with"]["filters"]),
        Loader=yaml.BaseLoader,
    )["site_code"]

    def outputs(changed_paths: list[str]) -> tuple[bool, bool, bool, bool, bool, bool]:
        backend_pr = (
            _filter_output(changed_paths, backend_filters)
            or _filter_output(changed_paths, filters["backend_web_contract"])
        )
        return (
            backend_pr,
            _filter_output(changed_paths, filters["backend_contract_assets"]),
            _filter_output(changed_paths, filters["docker"]),
            _filter_output(changed_paths, frontend_filters),
            _filter_output(changed_paths, frontend_runtime_filters),
            _filter_output(changed_paths, filters["futu_packaging"]),
        )

    assert backend_filter_step["with"]["predicate-quantifier"] == "every"
    assert outputs(["docs/CHANGELOG.md"]) == (False, True, False, False, False, False)
    assert outputs(["docs/architecture/api_spec.json"])[0] is False
    assert outputs(["docs/architecture/api_spec.json"])[1] is True
    assert outputs(["docs/alerts.md"])[1] is True
    assert outputs(["tests/fixtures/notification_reports/aggregate_report.md"])[1] is True
    assert outputs(["tests/fixtures/agent_trajectory/sample.json"]) == (
        False,
        True,
        False,
        False,
        False,
        False,
    )
    assert outputs(["THIRD_PARTY_NOTICES.md"])[1] is True
    assert outputs(["docs/CONTRIBUTING.md"]) == (False, False, False, False, False, False)
    assert outputs(["README.md"]) == (False, False, False, False, False, False)
    assert outputs(["LICENSE"]) == (False, False, False, False, False, False)
    assert outputs(["apps/dsa-web/README.md"]) == (False, False, False, False, False, False)
    assert outputs(["apps/dsa-desktop/README.md"]) == (False, False, False, False, False, False)
    assert outputs(["src/config.py"]) == (True, False, True, False, False, False)
    assert outputs(["src/services/screening/pipeline.py"]) == (True, False, True, False, False, False)
    assert outputs(["requirements.txt"]) == (True, False, True, False, False, True)
    assert outputs(["docker/Dockerfile"]) == (True, False, True, False, False, False)
    assert outputs(["apps/dsa-web/src/App.tsx"]) == (False, False, True, True, True, False)
    assert outputs(["apps/dsa-web/package-lock.json"]) == (False, False, True, True, True, False)
    assert outputs(["apps/dsa-web/src/pages/__tests__/PortfolioPage.test.tsx"]) == (
        False,
        False,
        False,
        True,
        False,
        False,
    )
    assert outputs(["apps/dsa-web/tests/ui_governance.test.ts"]) == (
        False,
        False,
        False,
        True,
        False,
        False,
    )
    assert outputs(["apps/dsa-web/e2e/fixtures/x6ai-settings.spec.ts"]) == (
        False,
        False,
        False,
        True,
        True,
        False,
    )
    assert outputs(["apps/dsa-web/src/App.tsx", "docs/CHANGELOG.md"]) == (
        False,
        True,
        True,
        True,
        True,
        False,
    )
    assert outputs(["apps/dsa-web/src/App.tsx", "src/config.py"]) == (
        True,
        False,
        True,
        True,
        True,
        False,
    )
    assert outputs(["apps/dsa-web/public/stocks.index.json"])[0] is True
    assert outputs(["apps/dsa-web/public/runtime/new-asset.json"])[0] is True
    assert _filter_output(["apps/dsa-site/src/pages/index.astro"], site_filters)
    assert _filter_output(["docs/data-center-diagnostics.md"], site_filters)
    assert _filter_output(["docs/architecture/api_spec.json"], site_filters)
    assert _filter_output(["docs/CHANGELOG.md"], site_filters)
    assert _filter_output(["strategies/README.md"], site_filters)
    assert _filter_output([".github/workflows/ci.yml"], site_filters)
    assert not _filter_output(["src/config.py"], site_filters)
    assert not _filter_output(["apps/dsa-web/src/App.tsx"], site_filters)


def test_browser_fixture_and_default_smoke_entrypoints_stay_separate() -> None:
    smoke = _read("apps/dsa-web/playwright.config.ts")
    fixture = _read("apps/dsa-web/playwright.fixture.config.ts")
    assert "testIgnore: '**/fixtures/**'" in smoke
    assert "testDir: './e2e/fixtures'" in fixture
    assert "webServer:" in fixture
    steps = _workflow(".github/workflows/ci.yml")["jobs"]["web-gate"]["steps"]
    default = next(step for step in steps if step.get("run") == "npm run test:smoke")
    assert default["env"]["DSA_WEB_SMOKE_PASSWORD"] == ""
    assert any(step.get("run") == "npx playwright test --config playwright.fixture.config.ts" for step in steps)


def test_release_workflow_unifies_atomic_publish_and_native_arm64() -> None:
    for legacy in (
        ".github/workflows/create-release.yml",
        ".github/workflows/docker-publish.yml",
        ".github/workflows/desktop-release.yml",
    ):
        assert not (REPO_ROOT / legacy).exists()

    release = _workflow(".github/workflows/release.yml")
    jobs = release["jobs"]
    docker_matrix = jobs["docker-build"]["strategy"]["matrix"]["include"]
    assert {"platform": "linux/amd64", "arch": "amd64", "runner": "ubuntu-24.04"} in docker_matrix
    assert {"platform": "linux/arm64", "arch": "arm64", "runner": "ubuntu-24.04-arm"} in docker_matrix
    assert set(jobs["docker-merge-manifest"]["needs"]) == {
        "pre-release-gate",
        "docker-build",
        "desktop-windows",
        "desktop-macos",
    }
    assert set(jobs["publish-release"]["needs"]) == {
        "pre-release-gate",
        "docker-merge-manifest",
        "desktop-windows",
        "desktop-macos",
    }
    pre_outputs = jobs["pre-release-gate"]["outputs"]
    assert "ghcr_repo" in pre_outputs
    assert "dockerhub_repo" not in pre_outputs
    assert any(
        "tr '[:upper:]' '[:lower:]'" in str(step.get("run", ""))
        for step in jobs["pre-release-gate"]["steps"]
    )
    assert any(
        "tr '[:upper:]' '[:lower:]'" in str(step.get("run", ""))
        for step in jobs["docker-build"]["steps"]
    )
    assert any(
        "tr '[:upper:]' '[:lower:]'" in str(step.get("run", ""))
        for step in jobs["docker-merge-manifest"]["steps"]
    )
    build_text = yaml.dump(jobs["docker-build"], sort_keys=False, width=4096)
    merge_text = yaml.dump(jobs["docker-merge-manifest"], sort_keys=False, width=4096)
    assert "needs.pre-release-gate.outputs.ghcr_repo" in build_text
    assert "needs.pre-release-gate.outputs.ghcr_repo" in merge_text
    assert "needs.pre-release-gate.outputs.dockerhub_repo" not in build_text
    assert "needs.pre-release-gate.outputs.dockerhub_repo" not in merge_text
    assert "${{ env.GHCR_REGISTRY }}/${{ env.GHCR_IMAGE_NAME }}" not in build_text
    assert "${{ env.GHCR_REGISTRY }}/${{ env.GHCR_IMAGE_NAME }}" not in merge_text

    merge_steps = jobs["docker-merge-manifest"]["steps"]
    step_names = [step.get("name", "") or step.get("uses", "") for step in merge_steps]
    idx_prev = step_names.index("Record previous latest digests")
    idx_stage = step_names.index("Stage immutable GHCR multi-arch manifest")
    idx_attest = next(
        i for i, step in enumerate(merge_steps)
        if str(step.get("uses", "")).startswith("actions/attest-build-provenance@")
    )
    idx_public_ghcr = step_names.index("Publish public GHCR tags")
    idx_dockerhub = step_names.index("Publish Docker Hub tags")
    assert idx_prev < idx_stage < idx_attest < idx_public_ghcr < idx_dockerhub
    stage_run = merge_steps[idx_stage]["run"]
    assert ":latest" not in stage_run
    assert "release_tag" not in stage_run
