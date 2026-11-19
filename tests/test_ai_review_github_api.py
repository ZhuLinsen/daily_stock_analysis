import importlib.util
from pathlib import Path

import pytest


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

    assert files == ['src/example.py', 'docs/guide.md', 'assets/chart.png']
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

    assert ai_review.get_pr_context() == {'title': 'Fix review', 'body': 'Closes #2051'}


def test_review_with_no_ci_or_screenshot_cannot_claim_verification(monkeypatch):
    monkeypatch.setenv('AI_REVIEW_SOURCE', 'github_api')
    assert '尚未核验' in ai_review.get_review_evidence({})


@pytest.mark.parametrize('current_head', ['original', 'updated'])
def test_review_result_is_bound_to_the_diff_revision(monkeypatch, tmp_path, current_head):
    def revision(head):
        return {'head': {'sha': head}, 'base': {'sha': 'main'}}

    contexts = iter([revision('original'), revision(current_head)])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('AI_REVIEW_SOURCE', 'github_api')
    monkeypatch.delenv('GITHUB_STEP_SUMMARY', raising=False)
    monkeypatch.setattr(ai_review, 'get_pr_context', lambda: next(contexts))
    monkeypatch.setattr(ai_review, 'get_review_data', lambda: ('patch', ['main.py'], False))
    monkeypatch.setattr(ai_review, 'ai_review', lambda *args: 'review text')
    result = tmp_path / 'ai_review_result.txt'
    if current_head == 'updated':
        with pytest.raises(RuntimeError, match='PR 版本'):
            ai_review.main()
        assert not result.exists()
    else:
        ai_review.main()
        assert result.read_text(encoding='utf-8') == '审查版本 `original`\n\nreview text'


def test_review_includes_current_head_ci_and_distinguishes_links_from_viewed_images(monkeypatch):
    monkeypatch.setenv('AI_REVIEW_SOURCE', 'github_api')
    monkeypatch.setenv('GITHUB_REPOSITORY', 'owner/repo')
    pr = {'head': {'sha': 'abc'}, 'number': 123, 'comments': 2}
    ci = {'id': 7, 'head_sha': 'abc', 'conclusion': 'success', 'html_url': 'https://example.org/runs/7'}
    responses = {
        '/repos/owner/repo/actions/workflows/ci.yml/runs?event=pull_request&head_sha=abc&per_page=1':
            {'workflow_runs': [ci]},
        '/repos/owner/repo/actions/runs/7/artifacts?name=web-ui-evidence-abc':
            {'artifacts': [{'id': 8, 'name': 'web-ui-evidence-abc', 'expired': False}]},
        '/repos/owner/repo/issues/123/comments?per_page=100&page=1': [
            {'body': '![after](https://example.org/after.png)', 'html_url': 'https://example.org/comment/1'},
            {'body': 'Looks good', 'html_url': 'https://example.org/comment/2'},
        ],
    }
    monkeypatch.setattr(ai_review, '_github_api_json', responses.__getitem__)
    context = ai_review.get_review_evidence(pr)
    assert 'https://example.org/runs/7/artifacts/8' in context and '画面未查看' in context
    assert 'https://example.org/comment/1' in context and 'comment/2' not in context
    assert 'success' in context

    ci['head_sha'] = 'older'
    context = ai_review.get_review_evidence(pr)
    assert 'CI 运行待核实' in context and 'runs/7' not in context


def test_event_payload_missing_file_logs_warning(monkeypatch, tmp_path, capsys):
    """When GITHUB_EVENT_PATH points to a non-existent file, _event_payload()
    returns {} and prints a warning distinguishing 'file missing' from the
    other failure modes (regression for issue #2070)."""
    missing = tmp_path / 'does-not-exist.json'
    monkeypatch.setenv('GITHUB_EVENT_PATH', str(missing))

    payload = ai_review._event_payload()

    assert payload == {}
    captured = capsys.readouterr()
    assert 'GITHUB_EVENT_PATH 指向的文件不存在' in captured.out
    assert str(missing) in captured.out


def test_event_payload_unreadable_file_logs_oserror(monkeypatch, tmp_path, capsys):
    """When the event payload file exists but cannot be read, _event_payload()
    preserves the empty-payload degradation but logs the OSError-derived
    exception class and the source path (regression for issue #2070)."""
    # Make a file and strip read permissions so open() raises PermissionError
    # (a subclass of OSError). Skip on platforms where chmod is a no-op for
    # the current user.
    unreadable = tmp_path / 'event.json'
    unreadable.write_text('{"pull_request": {"number": 1}}', encoding='utf-8')
    unreadable.chmod(0o000)

    monkeypatch.setenv('GITHUB_EVENT_PATH', str(unreadable))

    try:
        payload = ai_review._event_payload()
    finally:
        unreadable.chmod(0o600)

    # If the test runner is root (chmod is a no-op), skip the assertion:
    # the file may actually be readable on such hosts. Either way it must
    # not raise.
    if payload == {}:
        captured = capsys.readouterr()
        assert '事件载荷读取失败' in captured.out
        assert str(unreadable) in captured.out


def test_event_payload_invalid_json_logs_parse_error(monkeypatch, tmp_path, capsys):
    """When the event payload file contains invalid JSON, _event_payload()
    preserves the empty-payload degradation but logs the JSONDecodeError-
    derived exception class and the source path (regression for issue #2070).
    """
    bad = tmp_path / 'event.json'
    bad.write_text('not-json-at-all', encoding='utf-8')
    monkeypatch.setenv('GITHUB_EVENT_PATH', str(bad))

    payload = ai_review._event_payload()

    assert payload == {}
    captured = capsys.readouterr()
    assert '事件载荷 JSON 解析失败' in captured.out
    assert str(bad) in captured.out


def test_event_payload_valid_json_returns_payload_no_warning(monkeypatch, tmp_path, capsys):
    """The happy path: a readable, valid JSON file yields the payload and
    prints no warning. Guards against the warnings accidentally firing on
    the success path (regression for issue #2070)."""
    good = tmp_path / 'event.json'
    good.write_text('{"pull_request": {"number": 4242}}', encoding='utf-8')
    monkeypatch.setenv('GITHUB_EVENT_PATH', str(good))

    payload = ai_review._event_payload()

    assert payload == {'pull_request': {'number': 4242}}
    captured = capsys.readouterr()
    assert captured.out == ''


def test_event_payload_non_utf8_logs_unicode_error(monkeypatch, tmp_path, capsys):
    """When the event payload file is readable but contains non-UTF-8 bytes,
    _event_payload() preserves the empty-payload degradation and logs the
    UnicodeDecodeError-derived exception class plus the source path.

    Regression for the codex P2 review point on PR #2096: the previous
    `except (OSError, ValueError)` bucket implicitly caught UnicodeDecodeError
    (a ValueError subclass); splitting the handler into OSError + JSONDecodeError
    left UnicodeDecodeError uncaught, which would terminate the review instead
    of degrading. The dedicated UnicodeDecodeError branch restores parity.
    """
    bad = tmp_path / 'event.json'
    # 写入非法 UTF-8 字节序列 (0xff 0xfe 不构成合法 UTF-8 起始)
    bad.write_bytes(b'\xff\xfe\x00\x00not-utf8')
    monkeypatch.setenv('GITHUB_EVENT_PATH', str(bad))

    payload = ai_review._event_payload()

    assert payload == {}
    captured = capsys.readouterr()
    assert '事件载荷非 UTF-8' in captured.out
    assert 'UnicodeDecodeError' in captured.out
    assert str(bad) in captured.out


def test_pull_request_number_failure_after_bad_event_payload(monkeypatch, tmp_path, capsys):
    """When PR_NUMBER is unset and the event payload is unreadable, the
    chain must surface a clearly-named RuntimeError instead of silently
    treating the run as success (regression for issue #2070). The warning
    is printed first so logs distinguish 'bad payload' from 'no PR number'.
    """
    bad = tmp_path / 'event.json'
    bad.write_text('{invalid json', encoding='utf-8')
    monkeypatch.setenv('GITHUB_EVENT_PATH', str(bad))
    monkeypatch.delenv('PR_NUMBER', raising=False)

    raised = False
    try:
        ai_review._pull_request_number()
    except RuntimeError as exc:
        raised = True
        assert 'PR number is unavailable' in str(exc)

    assert raised, 'Expected RuntimeError when PR number cannot be derived'
    captured = capsys.readouterr()
    assert '事件载荷 JSON 解析失败' in captured.out
