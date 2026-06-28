from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def test_env_example_documents_searxng_actions_variable_mapping() -> None:
    env_example = (ROOT_DIR / ".env.example").read_text(encoding="utf-8")

    start = env_example.index("# SearXNG 实例地址")
    end = env_example.index("SEARXNG_PUBLIC_INSTANCES_ENABLED=true", start)
    searxng_block = env_example[start:end]

    assert "GitHub Actions" in searxng_block
    assert "Variables 优先" in searxng_block
    assert "Secrets" in searxng_block
    assert "需配置为 Secret" not in searxng_block


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
