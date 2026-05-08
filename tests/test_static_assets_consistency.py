# -*- coding: utf-8 -*-
"""Tests for ``scripts/check_static_assets.py`` and the equivalent
backend startup self-check in ``api.app``.

Both code paths target the blank-page / "Preparing backend..." regression
captured in GitHub issues #1064, #1065 and #1050: vite produces a fresh
``index.html`` that references ``/assets/index-<hash>.js``, but the
packaging step copies a stale ``static/assets`` directory, so the bundle
referenced by ``index.html`` does not exist on disk.
"""

from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

check_static_assets = importlib.import_module("check_static_assets")


def _write_index(static_dir: Path, body: str) -> None:
    static_dir.mkdir(parents=True, exist_ok=True)
    (static_dir / "index.html").write_text(body, encoding="utf-8")


def _vite_index(js_name: str, css_name: str) -> str:
    return (
        "<!doctype html><html><head>"
        f'<script type="module" crossorigin src="/assets/{js_name}"></script>'
        f'<link rel="stylesheet" crossorigin href="/assets/{css_name}">'
        "</head><body><div id=\"root\"></div></body></html>"
    )


def test_check_static_dir_passes_when_assets_match(tmp_path: Path) -> None:
    static_dir = tmp_path / "static"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    (assets_dir / "index-abc.js").write_text("// js", encoding="utf-8")
    (assets_dir / "index-abc.css").write_text("/* css */", encoding="utf-8")
    _write_index(static_dir, _vite_index("index-abc.js", "index-abc.css"))

    referenced, missing = check_static_assets.check_static_dir(static_dir)

    assert sorted(referenced) == ["/assets/index-abc.css", "/assets/index-abc.js"]
    assert missing == []


def test_check_static_dir_detects_stale_bundle(tmp_path: Path) -> None:
    """index.html references new hash but assets/ holds an old hash."""
    static_dir = tmp_path / "static"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    # Stale on-disk bundle.
    (assets_dir / "index-OLD.js").write_text("// old", encoding="utf-8")
    (assets_dir / "index-OLD.css").write_text("/* old */", encoding="utf-8")
    # Fresh index.html points to a different hash.
    _write_index(static_dir, _vite_index("index-NEW.js", "index-NEW.css"))

    referenced, missing = check_static_assets.check_static_dir(static_dir)

    assert "/assets/index-NEW.js" in referenced
    assert sorted(missing) == ["/assets/index-NEW.css", "/assets/index-NEW.js"]


def test_check_static_dir_raises_when_index_missing(tmp_path: Path) -> None:
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    with pytest.raises(FileNotFoundError):
        check_static_assets.check_static_dir(static_dir)


def test_main_returns_nonzero_when_assets_missing(tmp_path: Path, capsys) -> None:
    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    _write_index(static_dir, _vite_index("index-MISSING.js", "index-MISSING.css"))

    rc = check_static_assets.main(["check_static_assets.py", str(static_dir)])

    captured = capsys.readouterr()
    assert rc == 1
    assert "ERROR" in captured.err
    assert "/assets/index-MISSING.js" in captured.err


def test_main_returns_zero_when_consistent(tmp_path: Path) -> None:
    static_dir = tmp_path / "static"
    assets = static_dir / "assets"
    assets.mkdir(parents=True)
    (assets / "main.js").write_text("// ok", encoding="utf-8")
    (assets / "main.css").write_text("/* ok */", encoding="utf-8")
    _write_index(static_dir, _vite_index("main.js", "main.css"))

    rc = check_static_assets.main(["check_static_assets.py", str(static_dir)])
    assert rc == 0


def test_backend_startup_check_logs_when_bundle_inconsistent(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from api import app as app_module

    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    _write_index(static_dir, _vite_index("index-NEW.js", "index-NEW.css"))

    with caplog.at_level(logging.ERROR, logger="api.app"):
        missing = app_module._check_frontend_assets_consistency(static_dir)

    assert sorted(missing) == ["/assets/index-NEW.css", "/assets/index-NEW.js"]
    assert any(
        "Frontend bundle is inconsistent" in record.getMessage()
        for record in caplog.records
    )


def test_backend_startup_check_silent_when_bundle_consistent(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from api import app as app_module

    static_dir = tmp_path / "static"
    assets = static_dir / "assets"
    assets.mkdir(parents=True)
    (assets / "index-abc.js").write_text("// js", encoding="utf-8")
    (assets / "index-abc.css").write_text("/* css */", encoding="utf-8")
    _write_index(static_dir, _vite_index("index-abc.js", "index-abc.css"))

    with caplog.at_level(logging.ERROR, logger="api.app"):
        missing = app_module._check_frontend_assets_consistency(static_dir)

    assert missing == []
    assert not any(
        "Frontend bundle is inconsistent" in record.getMessage()
        for record in caplog.records
    )


def test_missing_asset_returns_safe_404_content_types(tmp_path: Path) -> None:
    from api.app import create_app

    static_dir = tmp_path / "static"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    (assets_dir / "index-abc.js").write_text("// ok", encoding="utf-8")
    (assets_dir / "index-abc.css").write_text("/* ok */", encoding="utf-8")
    _write_index(static_dir, _vite_index("index-abc.js", "index-abc.css"))

    client = TestClient(create_app(static_dir=static_dir))

    js_response = client.get("/assets/index-missing.js")
    css_response = client.get("/assets/index-missing.css")
    html_response = client.get("/assets/%3Cscript%3Ealert(1)%3C/script%3E.html")

    assert js_response.status_code == 404
    assert js_response.text == "asset not found"
    assert js_response.headers["content-type"].startswith("text/javascript")

    assert css_response.status_code == 404
    assert css_response.text == "asset not found"
    assert css_response.headers["content-type"].startswith("text/css")

    assert html_response.status_code == 404
    assert html_response.text == "asset not found"
    assert html_response.headers["content-type"].startswith("text/plain")


def test_existing_asset_is_served_from_explicit_assets_route(tmp_path: Path) -> None:
    from api.app import create_app

    static_dir = tmp_path / "static"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    js_file = assets_dir / "index-abc.js"
    css_file = assets_dir / "index-abc.css"
    js_file.write_text("console.log('ok')", encoding="utf-8")
    css_file.write_text("body{color:#fff}", encoding="utf-8")
    _write_index(static_dir, _vite_index("index-abc.js", "index-abc.css"))

    client = TestClient(create_app(static_dir=static_dir))

    js_response = client.get("/assets/index-abc.js")
    css_response = client.get("/assets/index-abc.css")

    assert js_response.status_code == 200
    assert js_response.text == "console.log('ok')"
    assert js_response.headers["content-type"].startswith("text/javascript")

    assert css_response.status_code == 200
    assert css_response.text == "body{color:#fff}"
    assert css_response.headers["content-type"].startswith("text/css")


def test_existing_asset_supports_head_and_conditional_requests(tmp_path: Path) -> None:
    from api.app import create_app

    static_dir = tmp_path / "static"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    js_file = assets_dir / "index-abc.js"
    js_file.write_text("console.log('ok')", encoding="utf-8")
    (assets_dir / "index-abc.css").write_text("body{color:#fff}", encoding="utf-8")
    _write_index(static_dir, _vite_index("index-abc.js", "index-abc.css"))

    client = TestClient(create_app(static_dir=static_dir))

    get_response = client.get("/assets/index-abc.js")
    etag = get_response.headers["etag"]

    head_response = client.head("/assets/index-abc.js")
    cached_response = client.get(
        "/assets/index-abc.js",
        headers={"if-none-match": etag},
    )

    assert get_response.status_code == 200
    assert head_response.status_code == 200
    assert head_response.content == b""
    assert head_response.headers["etag"] == etag
    assert head_response.headers["content-type"].startswith("text/javascript")

    assert cached_response.status_code == 304
    assert cached_response.content == b""
    assert cached_response.headers["etag"] == etag


@pytest.mark.parametrize(
    "request_path",
    [
        "/assets/..%5C..%5Csecret.txt",
        "/assets/C:%5Csecret.txt",
        "/assets/%5Cwindows%5Csystem32%5Cconfig",
        "/assets/%2e%2e/%2e%2e/secret.txt",
        "/assets/%2500.js",
    ],
)
def test_asset_traversal_attempts_are_rejected(
    tmp_path: Path,
    request_path: str,
) -> None:
    from api.app import create_app

    static_dir = tmp_path / "static"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    (assets_dir / "index-abc.js").write_text("// ok", encoding="utf-8")
    (assets_dir / "index-abc.css").write_text("/* ok */", encoding="utf-8")
    _write_index(static_dir, _vite_index("index-abc.js", "index-abc.css"))
    outside_secret = tmp_path / "secret.txt"
    outside_secret.write_text("top secret", encoding="utf-8")

    client = TestClient(create_app(static_dir=static_dir))
    response = client.get(request_path)

    assert response.status_code == 404
    assert response.text == "not found"
    assert "top secret" not in response.text
