from __future__ import annotations

import importlib.util
import io
import json
import logging
import urllib.error
from pathlib import Path


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
