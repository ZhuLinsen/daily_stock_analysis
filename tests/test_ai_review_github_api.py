import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / '.github' / 'scripts' / 'ai_review.py'
SPEC = importlib.util.spec_from_file_location('ai_review_script', SCRIPT_PATH)
assert SPEC and SPEC.loader
ai_review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ai_review)


def test_github_api_review_data_treats_patch_as_data(monkeypatch):
    pull_files = [
        {
            'filename': 'src/example.py',
            'status': 'modified',
            'patch': '@@ -1 +1 @@\n-old\n+new',
        },
        {
            'filename': 'docs/guide.md',
            'status': 'added',
            'patch': '@@ -0,0 +1 @@\n+# Guide',
        },
        {
            'filename': 'assets/chart.png',
            'status': 'added',
            'patch': None,
        },
    ]
    monkeypatch.setenv('AI_REVIEW_SOURCE', 'github_api')
    monkeypatch.setattr(ai_review, '_fetch_pull_files', lambda: pull_files)
    monkeypatch.setattr(
        ai_review,
        'run_git',
        lambda _args: (_ for _ in ()).throw(AssertionError('git must not run')),
    )

    diff, files, truncated = ai_review.get_review_data()

    assert files == ['src/example.py', 'docs/guide.md']
    assert 'diff --git a/src/example.py b/src/example.py' in diff
    assert '--- /dev/null\n+++ b/docs/guide.md' in diff
    assert 'assets/chart.png' not in diff
    assert truncated is False


def test_github_api_review_data_marks_missing_text_patch(monkeypatch):
    monkeypatch.setenv('AI_REVIEW_SOURCE', 'github_api')
    monkeypatch.setattr(
        ai_review,
        '_fetch_pull_files',
        lambda: [{'filename': 'README.md', 'status': 'modified'}],
    )

    diff, files, truncated = ai_review.get_review_data()

    assert files == ['README.md']
    assert 'Patch unavailable from GitHub API' in diff
    assert truncated is False


def test_pull_file_api_is_paginated(monkeypatch):
    paths = []

    def fake_api(path):
        paths.append(path)
        if 'page=1' in path:
            return [{'filename': 'one.py'}, {'filename': 'two.py'}]
        return [{'filename': 'three.py'}]

    monkeypatch.setenv('GITHUB_REPOSITORY', 'owner/repo')
    monkeypatch.setenv('PR_NUMBER', '2051')
    monkeypatch.setattr(ai_review, 'GITHUB_API_PAGE_SIZE', 2)
    monkeypatch.setattr(ai_review, '_github_api_json', fake_api)

    files = ai_review._fetch_pull_files()

    assert [item['filename'] for item in files] == ['one.py', 'two.py', 'three.py']
    assert paths == [
        '/repos/owner/repo/pulls/2051/files?per_page=2&page=1',
        '/repos/owner/repo/pulls/2051/files?per_page=2&page=2',
    ]


def test_manual_dispatch_context_comes_from_github_api(monkeypatch):
    monkeypatch.setenv('AI_REVIEW_SOURCE', 'github_api')
    monkeypatch.setenv('GITHUB_REPOSITORY', 'owner/repo')
    monkeypatch.setenv('PR_NUMBER', '2051')
    monkeypatch.delenv('GITHUB_EVENT_PATH', raising=False)
    monkeypatch.setattr(
        ai_review,
        '_github_api_json',
        lambda path: {'title': 'Fix review', 'body': 'Closes #2051'}
        if path == '/repos/owner/repo/pulls/2051'
        else None,
    )

    assert ai_review.get_pr_context() == ('Fix review', 'Closes #2051')


def test_delegated_ci_context_does_not_claim_success(monkeypatch):
    monkeypatch.setenv('CI_DELEGATED_TO_PULL_REQUEST', 'true')

    context = ai_review._build_ci_context()

    assert 'backend-gate' in context
    assert '不假设并行 CI 已通过' in context
