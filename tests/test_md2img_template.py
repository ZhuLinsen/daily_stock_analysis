# -*- coding: utf-8 -*-

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.config import Config
from src.md2img import (
    _markdown_to_image_m2f,
    _markdown_to_image_playwright,
    _markdown_to_image_wkhtml,
    markdown_to_image,
)
from src.share_image import ShareImageBranding


TEST_BRANDING = ShareImageBranding(
    xiaohongshu_url="https://example.com/xhs",
    xiaohongshu_handle="@示例账号",
    xiaohongshu_id="123456",
    xiaohongshu_qr_path=str(
        Path(__file__).parents[1] / "src" / "assets" / "share_image" / "xiaohongshu_qr.jpg"
    ),
)


def test_wkhtml_renderer_uses_share_poster_dimensions_and_qr_template():
    with patch("imgkit.from_string", return_value=b"png") as render:
        assert _markdown_to_image_wkhtml(
            "# 大盘复盘\n\n## 结论\n\n震荡",
            branding=TEST_BRANDING,
        ) == b"png"

    html, output = render.call_args.args
    options = render.call_args.kwargs["options"]
    assert output is False
    assert 'class="poster market"' in html
    assert "项目主页二维码" not in html
    assert "ZhuLinsen/daily_stock_analysis" in html
    assert "@示例账号" in html
    assert options["width"] == 1080
    assert options["disable-smart-width"] == ""


def test_markdown_to_file_renderer_receives_the_same_share_poster(tmp_path, monkeypatch):
    captured = {}
    resolved_m2f = str(tmp_path / "m2f.CMD")

    def fake_run(args, **_kwargs):
        captured["command"] = args[0]
        captured["html"] = Path(args[1]).read_text(encoding="utf-8")
        (tmp_path / "report.png").write_bytes(b"png")
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr("src.md2img.shutil.which", lambda _name: resolved_m2f)
    monkeypatch.setattr("src.md2img.tempfile.mkdtemp", lambda: str(tmp_path))
    monkeypatch.setattr("src.md2img.subprocess.run", fake_run)
    monkeypatch.setattr("src.md2img.shutil.rmtree", lambda _path: None)

    assert _markdown_to_image_m2f(
        "# 贵州茅台 600519\n\n## 结论\n\n偏多",
        branding=TEST_BRANDING,
    ) == b"png"
    assert captured["command"] == resolved_m2f
    assert 'class="poster stock"' in captured["html"]
    assert "项目主页二维码" not in captured["html"]
    assert "ZhuLinsen/daily_stock_analysis" in captured["html"]
    assert "@示例账号" in captured["html"]


def test_playwright_renderer_receives_the_same_share_poster(tmp_path, monkeypatch):
    captured = {}
    resolved_playwright = str(tmp_path / "playwright.CMD")

    def fake_run(args, **_kwargs):
        captured["args"] = args
        captured["html"] = (tmp_path / "report.html").read_text(encoding="utf-8")
        Path(args[-1]).write_bytes(b"png")
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr("src.md2img._resolve_playwright_command", lambda: resolved_playwright)
    monkeypatch.setattr("src.md2img.tempfile.mkdtemp", lambda: str(tmp_path))
    monkeypatch.setattr("src.md2img.subprocess.run", fake_run)
    monkeypatch.setattr("src.md2img.shutil.rmtree", lambda _path: None)

    assert _markdown_to_image_playwright(
        "# 贵州茅台 600519\n\n## 结论\n\n偏多",
        branding=TEST_BRANDING,
    ) == b"png"
    assert captured["args"][0] == resolved_playwright
    assert captured["args"][1:6] == [
        "screenshot",
        "--browser",
        "chromium",
        "--viewport-size",
        "1080,720",
    ]
    assert "--full-page" in captured["args"]
    assert 'class="poster stock"' in captured["html"]
    assert "ZhuLinsen/daily_stock_analysis" in captured["html"]


def test_config_accepts_playwright_image_engine():
    assert Config._parse_md2img_engine("playwright") == "playwright"


def test_markdown_to_image_forwards_social_branding_from_config():
    config = SimpleNamespace(
        md2img_engine="wkhtmltoimage",
        share_image_xiaohongshu_url="https://example.com/xhs",
        share_image_xiaohongshu_handle="@自定义账号",
        share_image_xiaohongshu_id="987654",
        share_image_xiaohongshu_qr_path="custom-qr.png",
    )
    with (
        patch("src.config.get_config", return_value=config),
        patch("src.md2img._markdown_to_image_wkhtml", return_value=b"png") as render,
    ):
        assert markdown_to_image("# 大盘复盘") == b"png"

    branding = render.call_args.args[2]
    assert branding == ShareImageBranding(
        xiaohongshu_url="https://example.com/xhs",
        xiaohongshu_handle="@自定义账号",
        xiaohongshu_id="987654",
        xiaohongshu_qr_path="custom-qr.png",
    )


def test_wkhtml_renderer_forwards_structured_analysis_payload():
    payload = {
        "name": "中钨高新",
        "code": "000657",
        "operation_advice": "观望",
        "sentiment_score": 40,
        "dashboard": {"core_conclusion": {"one_sentence": "等待企稳"}},
    }
    with patch("imgkit.from_string", return_value=b"png") as render:
        assert _markdown_to_image_wkhtml(
            "# 占位名称 000657\n\n## 核心结论\n\n占位文本",
            structured_payload=payload,
        ) == b"png"

    html = render.call_args.args[0]
    assert "中钨高新" in html
    assert "等待企稳" in html


def test_wkhtml_renderer_returns_none_when_share_poster_build_fails():
    with patch("src.md2img.build_share_image_html", side_effect=FileNotFoundError("missing qr")):
        assert _markdown_to_image_wkhtml("# 大盘复盘") is None


def test_markdown_to_file_renderer_returns_none_when_share_poster_build_fails(monkeypatch):
    monkeypatch.setattr("src.md2img.shutil.which", lambda _name: "m2f")

    with patch("src.md2img.build_share_image_html", side_effect=FileNotFoundError("missing qr")):
        assert _markdown_to_image_m2f("# 贵州茅台 600519") is None
