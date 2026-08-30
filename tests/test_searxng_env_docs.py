from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def test_env_example_documents_searxng_actions_variable_mapping() -> None:
    env_example = (ROOT_DIR / ".env.example").read_text(encoding="utf-8")

    start = env_example.index("# SearXNG 实例地址")
    end = env_example.index("SEARXNG_PUBLIC_INSTANCES_ENABLED=", start)
    searxng_block = env_example[start:end]

    assert "GitHub Actions" in searxng_block
    assert "Variables 优先" in searxng_block
    assert "Secrets" in searxng_block
    assert "需配置为 Secret" not in searxng_block


def test_env_example_defaults_public_searxng_instances_off() -> None:
    """公共实例发现默认关闭：公共实例普遍限流或不返回 JSON，
    默认开启会让未配置搜索 key 的用户每次分析白等 30~60 秒且拿到空新闻面。"""
    env_example = (ROOT_DIR / ".env.example").read_text(encoding="utf-8")

    assert "SEARXNG_PUBLIC_INSTANCES_ENABLED=false" in env_example
    assert "SEARXNG_PUBLIC_INSTANCES_ENABLED=true" not in env_example


def test_searxng_timeout_env_contract() -> None:
    from src.config import parse_env_int

    env_example = (ROOT_DIR / ".env.example").read_text(encoding="utf-8")
    assert "SEARXNG_TIMEOUT_SECONDS=10" in env_example
    assert parse_env_int(None, 10, field_name="SEARXNG_TIMEOUT_SECONDS", minimum=1) == 10
    assert parse_env_int("25", 10, field_name="SEARXNG_TIMEOUT_SECONDS", minimum=1) == 25
    assert parse_env_int("0", 10, field_name="SEARXNG_TIMEOUT_SECONDS", minimum=1) == 1


def test_daily_analysis_workflow_matches_documented_searxng_variable_mapping() -> None:
    workflow = (
        ROOT_DIR / ".github" / "workflows" / "00-daily-analysis.yml"
    ).read_text(encoding="utf-8")

    assert (
        "SEARXNG_BASE_URLS: ${{ vars.SEARXNG_BASE_URLS || secrets.SEARXNG_BASE_URLS }}"
        in workflow
    )
    assert "SEARXNG_BASE_URLS: ${{ secrets.SEARXNG_BASE_URLS }}" not in workflow


def test_changelog_mentions_searxng_actions_variable_mapping() -> None:
    changelog = (ROOT_DIR / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")

    assert (
        "- [修复] GitHub Actions 每日分析工作流读取 SearXNG 自建实例地址时"
        "支持 Variables 优先、Secrets 回退，修复仅配置 Variables 时 URL 不生效的问题。"
    ) in changelog


def test_runtime_default_disables_public_searxng_instances(monkeypatch) -> None:
    """未设置环境变量时，运行时必须解析为关闭。

    这是本项改动真正生效的地方：只改 .env.example 只影响复制了新模板的用户，
    已有安装和 GitHub Actions（未配置 Variable/Secret 时变量为空）仍会
    走公共实例发现，继续承受 30~60 秒的失败重试。
    """
    from src.config import parse_env_bool

    monkeypatch.delenv("SEARXNG_PUBLIC_INSTANCES_ENABLED", raising=False)
    import os

    assert (
        parse_env_bool(os.getenv("SEARXNG_PUBLIC_INSTANCES_ENABLED"), default=False)
        is False
    )


def test_config_constructor_defaults_public_searxng_instances_off() -> None:
    """直接构造 Config 时也必须遵循公共实例发现默认关闭的契约。"""
    from src.config import Config

    assert Config().searxng_public_instances_enabled is False


def test_config_module_uses_false_as_runtime_default() -> None:
    """锁住 config.py 里的默认值，防止后续改动悄悄回退。"""
    src = (ROOT_DIR / "src" / "config.py").read_text(encoding="utf-8")
    idx = src.index("SEARXNG_PUBLIC_INSTANCES_ENABLED")
    window = src[idx : idx + 200]

    assert "default=False" in window
    assert "default=True" not in window


def test_workflow_reports_disabled_when_variable_unset() -> None:
    """工作流诊断不得把「未设置」显示成已开启，否则与运行时行为不一致。"""
    workflow = (
        ROOT_DIR / ".github" / "workflows" / "00-daily-analysis.yml"
    ).read_text(encoding="utf-8")

    assert "默认开启" not in workflow
    assert "默认关闭" in workflow


def test_docs_describe_public_searxng_discovery_as_opt_in() -> None:
    chinese_docs = [
        ROOT_DIR / "docs" / "full-guide.md",
        ROOT_DIR / "docs" / "DEPLOY.md",
        ROOT_DIR / "docs" / "docker" / "zeabur-deployment.md",
    ]
    for path in chinese_docs:
        content = path.read_text(encoding="utf-8")
        base_url_lines = [
            line for line in content.splitlines() if "`SEARXNG_BASE_URLS`" in line
        ]
        public_toggle_lines = [
            line
            for line in content.splitlines()
            if "`SEARXNG_PUBLIC_INSTANCES_ENABLED`" in line
        ]
        assert base_url_lines
        assert public_toggle_lines
        assert all("留空时默认自动发现公共实例" not in line for line in base_url_lines)
        assert all("默认 `false`" in line for line in public_toggle_lines)

    english_guide = (ROOT_DIR / "docs" / "full-guide_EN.md").read_text(
        encoding="utf-8"
    )
    english_base_url_lines = [
        line for line in english_guide.splitlines() if "`SEARXNG_BASE_URLS`" in line
    ]
    english_public_toggle_lines = [
        line
        for line in english_guide.splitlines()
        if "`SEARXNG_PUBLIC_INSTANCES_ENABLED`" in line
    ]
    assert english_base_url_lines
    assert english_public_toggle_lines
    assert all(
        "when empty the app auto-discovers public instances" not in line
        for line in english_base_url_lines
    )
    assert all("default `false`" in line for line in english_public_toggle_lines)


def test_constructor_kwargs_carry_searxng_timeout_for_subprocess_rebuild() -> None:
    """bounded 题材搜索在子进程中重建 SearchService 时必须带上超时配置（PR #2249 blocker）。"""
    from src.search_service import SearchService

    service = SearchService(
        searxng_base_urls=["http://searxng.local:8080"],
        searxng_timeout_seconds=25,
    )
    kwargs = service._constructor_kwargs
    assert kwargs["searxng_timeout_seconds"] == 25
    assert kwargs["searxng_base_urls"] == ["http://searxng.local:8080"]

    # 子进程按同一 kwargs 重建后,provider 应拿到相同超时
    rebuilt = SearchService(**kwargs)
    searxng = next(p for p in rebuilt._providers if p.name == "SearXNG")
    assert searxng._self_hosted_timeout_seconds == 25


def test_daily_analysis_workflow_maps_searxng_timeout_variable() -> None:
    workflow = (
        ROOT_DIR / ".github" / "workflows" / "00-daily-analysis.yml"
    ).read_text(encoding="utf-8")
    assert (
        "SEARXNG_TIMEOUT_SECONDS: ${{ vars.SEARXNG_TIMEOUT_SECONDS || secrets.SEARXNG_TIMEOUT_SECONDS }}"
        in workflow
    )
