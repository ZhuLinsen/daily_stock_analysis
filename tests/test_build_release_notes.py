from __future__ import annotations

import importlib.util
import io
import json
import logging
import urllib.error
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT_DIR / ".github" / "scripts" / "build_release_notes.py"


def _load_release_notes_module():
    spec = importlib.util.spec_from_file_location("build_release_notes", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _JsonResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self) -> io.StringIO:
        return io.StringIO(json.dumps(self._payload))

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_github_login_from_pr_returns_successful_author(monkeypatch) -> None:
    module = _load_release_notes_module()

    def fake_urlopen(request, timeout):
        return _JsonResponse({"user": {"login": "octocat"}})

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)

    assert module._github_login_from_pr("owner/repo", "token", "123") == "octocat"


def test_github_login_from_pr_expected_degrades_without_warning(caplog) -> None:
    module = _load_release_notes_module()

    with caplog.at_level(logging.WARNING, logger=module.LOGGER.name):
        assert module._github_login_from_pr("owner/repo", "", "124") is None

    assert not caplog.records


def test_github_login_from_pr_404_degrades_without_warning(monkeypatch, caplog) -> None:
    module = _load_release_notes_module()

    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            url=request.full_url,
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)

    with caplog.at_level(logging.WARNING, logger=module.LOGGER.name):
        assert module._github_login_from_pr("owner/repo", "token", "125") is None

    assert not caplog.records


def test_github_login_from_pr_http_error_warns_with_pr_and_exception_type(
    monkeypatch,
    caplog,
) -> None:
    module = _load_release_notes_module()

    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            url=request.full_url,
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)

    with caplog.at_level(logging.WARNING, logger=module.LOGGER.name):
        assert module._github_login_from_pr("owner/repo", "secret-token", "126") is None

    assert "PR #126" in caplog.text
    assert "exception_type=HTTPError" in caplog.text
    assert "status=403" in caplog.text
    assert "secret-token" not in caplog.text


def test_github_login_from_pr_network_error_warns_with_pr_and_exception_type(
    monkeypatch,
    caplog,
) -> None:
    module = _load_release_notes_module()

    def fake_urlopen(request, timeout):
        raise urllib.error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)

    with caplog.at_level(logging.WARNING, logger=module.LOGGER.name):
        assert module._github_login_from_pr("owner/repo", "secret-token", "127") is None

    assert "PR #127" in caplog.text
    assert "exception_type=URLError" in caplog.text
    assert "secret-token" not in caplog.text


def test_publish_uses_generated_notes_without_a_handwritten_version(monkeypatch, tmp_path):
    module = _load_release_notes_module()
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## [Unreleased]\n\n## [1.0.0]\n- old item\n", encoding="utf-8")
    monkeypatch.setattr(module, "CHANGELOG", changelog)
    monkeypatch.setattr(module, "_run_git", lambda *args: "v1.1.0\nv1.0.0")
    monkeypatch.setattr(module, "_contributors", lambda previous, tag: ["@octocat"])

    def generate(command, **kwargs):
        assert command[:5] == ["gh", "api", "--method", "POST", "repos/{owner}/{repo}/releases/generate-notes"]
        assert "tag_name=v1.1.0" in command and "previous_tag_name=v1.0.0" in command
        return "## What's Changed\n### Bug Fixes\n* Fixed source links (#2550)\n"

    monkeypatch.setattr(module.subprocess, "check_output", generate)
    body = module.build("v1.1.0")
    assert "Fixed source links (#2550)" in body and "@octocat" in body
    assert "old item" not in body and "See the changelog" not in body


def test_first_release_has_no_previous_tag(monkeypatch):
    module = _load_release_notes_module()
    monkeypatch.setattr(module, "_run_git", lambda *args: "v2.0.0\nv1.0.0\nv0.9.0-beta")
    assert module._previous_tag("v1.0.0") == ""


def test_archive_keeps_published_edits_and_moves_only_released_pending_items(monkeypatch, tmp_path):
    module = _load_release_notes_module()
    changelog = tmp_path / "CHANGELOG.md"
    tagged = "# Changelog\n\n## [Unreleased]\n\n- [修复] legacy\n\n## [1.0.0]\n\nOld notes.\n"
    changelog.write_text(tagged.replace("legacy", "legacy\n- [改进] later"), encoding="utf-8")
    monkeypatch.setattr(module, "CHANGELOG", changelog)
    monkeypatch.setattr(module, "_run_git", lambda *args: tagged)
    published = {"isDraft": False, "publishedAt": "2026-11-19T03:00:00Z", "body": "## v1.1.0\r\n\r\nEdited on GitHub."}
    monkeypatch.setattr(module.subprocess, "check_output", lambda *args, **kwargs: json.dumps(published))
    module.archive_release("v1.1.0")
    archived = changelog.read_text(encoding="utf-8")
    assert "## [1.1.0] - 2026-11-19" in archived
    assert module._section_for(archived, "Unreleased") == "- [改进] later"
    assert module._section_for(archived, "1.1.0") == "Edited on GitHub.\n\n### 补充说明\n\n- [修复] legacy"
    assert module._section_for(archived, "1.0.0") == "Old notes."
    monkeypatch.setattr(module.subprocess, "check_output", lambda *a, **kw: pytest.fail("archive already exists"))
    module.archive_release("v1.1.0")
    assert changelog.read_text(encoding="utf-8") == archived


def test_archive_rejects_a_draft_without_changing_the_file(monkeypatch, tmp_path):
    module = _load_release_notes_module()
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## [Unreleased]\n", encoding="utf-8")
    monkeypatch.setattr(module, "CHANGELOG", changelog)
    monkeypatch.setattr(module.subprocess, "check_output", lambda *a, **kw: json.dumps(
        {"body": "unfinished", "publishedAt": None, "isDraft": True}
    ))
    with pytest.raises(ValueError, match="published"):
        module.archive_release("v1.1.0")
    assert changelog.read_text(encoding="utf-8") == "## [Unreleased]\n"


def test_archiving_out_of_order_keeps_comparison_and_reference_links(monkeypatch, tmp_path):
    module = _load_release_notes_module()
    changelog = tmp_path / "CHANGELOG.md"
    repo = "https://github.com/owner/project"
    changelog.write_text(f"## [1.1.0] - earlier\n\nExisting.\n\n[Unreleased]: {repo}/compare/v1.1.0...HEAD\n",
                         encoding="utf-8")
    monkeypatch.setattr(module, "CHANGELOG", changelog)

    def published(command, **kwargs):
        return json.dumps({"isDraft": False, "publishedAt": "2026-11-19", "body": "notes",
                           "url": f"{repo}/releases/tag/{command[3]}"})

    monkeypatch.setattr(module.subprocess, "check_output", published)
    module.archive_release("v1.2.0")
    module.archive_release("v1.0.0")
    archived = changelog.read_text(encoding="utf-8")
    assert archived.index("## [1.2.0]") < archived.index("## [1.1.0]") < archived.index("## [1.0.0]")
    assert archived.index("## [1.0.0]") < archived.index("[Unreleased]:")
    assert f"[Unreleased]: {repo}/compare/v1.2.0...HEAD" in archived
    assert f"[1.2.0]: {repo}/releases/tag/v1.2.0" in archived
    assert f"[1.0.0]: {repo}/releases/tag/v1.0.0" in archived
