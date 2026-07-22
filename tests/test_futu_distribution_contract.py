# -*- coding: utf-8 -*-
"""Distribution contracts for the globally bundled Futu SDK."""

from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _workflow(relative_path: str) -> dict:
    return yaml.load(_read(relative_path), Loader=yaml.BaseLoader)


def _job_run_text(job: dict) -> str:
    return "\n".join(
        str(step.get("run", ""))
        for step in job.get("steps", [])
        if isinstance(step, dict)
    )


def test_futu_sdk_is_pinned_and_verified_across_linux_distributions() -> None:
    requirements = _read("requirements.txt")
    dockerfile = _read("docker/Dockerfile")
    ci = _workflow(".github/workflows/ci.yml")
    daily = _workflow(".github/workflows/00-daily-analysis.yml")
    docker_publish = _workflow(".github/workflows/docker-publish.yml")
    manual_publish = _workflow(".github/workflows/ghcr-dockerhub.yml")

    assert requirements.count("futu-api==10.8.6808") == 1
    assert 'python -c "import alphasift.dsa_adapter; import futu"' in dockerfile
    assert "import futu" in _job_run_text(ci["jobs"]["backend-gate"])
    assert "import futu" in _job_run_text(ci["jobs"]["docker-build"])
    assert "import futu" in _job_run_text(daily["jobs"]["analyze"])
    assert "import futu" in _job_run_text(docker_publish["jobs"]["build-and-push"])
    assert "import futu" in _job_run_text(manual_publish["jobs"]["build-and-push"])


def test_futu_sdk_is_collected_and_probed_in_desktop_backends() -> None:
    ci = _workflow(".github/workflows/ci.yml")
    changes_job = ci["jobs"]["changes"]
    filter_step = next(
        step for step in changes_job["steps"] if step.get("id") == "filter"
    )
    filters = str(filter_step["with"]["filters"])
    jobs = ci["jobs"]
    macos_script = _read("scripts/build-backend-macos.sh")
    windows_script = _read("scripts/build-backend.ps1")

    assert "futu_packaging:" in filters
    assert "requirements.txt" in filters
    assert "src/brokers/futu/**" in filters
    assert "scripts/build-backend-macos.sh" in filters
    assert "scripts/build-backend.ps1" in filters

    for job_name in (
        "desktop-futu-package-windows",
        "desktop-futu-package-macos",
    ):
        job = jobs[job_name]
        assert job["needs"] == ["changes", "ai-governance"]
        assert "needs.changes.outputs.futu_packaging == 'true'" in job["if"]
        assert "build-backend" in _job_run_text(job)

    assert '"${PYTHON_BIN}" -c "import futu"' in macos_script
    assert 'cmd+=("--collect-all" "futu")' in macos_script
    assert "for module in alphasift.dsa_adapter futu orjson" in macos_script

    assert 'Test-PythonCode -Python $pythonBin -Code "import futu"' in windows_script
    assert "'--collect-all', 'futu'" in windows_script
    assert "@('alphasift.dsa_adapter', 'futu', 'orjson')" in windows_script
