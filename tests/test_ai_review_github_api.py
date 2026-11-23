import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


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
    assert 'Review path filter omitted changed files' in diff
    assert 'assets/chart.png' in diff
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


def test_local_review_data_marks_filtered_paths(monkeypatch):
    monkeypatch.delenv('AI_REVIEW_SOURCE', raising=False)
    responses = iter([
        'diff --git a/setup.cfg b/setup.cfg\n+changed',
        'setup.cfg\n.dockerignore',
    ])
    monkeypatch.setattr(ai_review, 'run_git', lambda _args: next(responses))

    diff, files, truncated = ai_review.get_review_data()

    assert files == ['setup.cfg', '.dockerignore']
    assert 'Review path filter omitted changed files' in diff
    assert '.dockerignore' in diff
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


@pytest.fixture
def review_run(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    monkeypatch.setenv('AI_REVIEW_SOURCE', 'github_api')
    monkeypatch.setenv('GITHUB_REPOSITORY', 'owner/repo')
    monkeypatch.setenv('PR_NUMBER', '2051')
    monkeypatch.setenv('GITHUB_SERVER_URL', 'https://github.example')
    monkeypatch.setenv('GITHUB_RUN_ID', '101')
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '2')
    monkeypatch.setenv('GITHUB_STEP_SUMMARY', str(tmp_path / 'summary.md'))
    return tmp_path


@pytest.mark.parametrize(('changed_during', 'head', 'base_ref', 'base_sha'), [
    (None, 'original', 'main', 'base'),
    ('summary missing', 'original', 'main', 'base'),
    ('diff', 'updated', 'main', 'base'),
    ('model', 'updated', 'main', 'base'),
    ('model', 'original', 'maintenance', 'base'),
    ('model', 'original', 'main', 'new-base'),
])
def test_review_result_is_bound_to_the_diff_revision(monkeypatch, review_run, changed_during, head, base_ref, base_sha):
    original = {'number': 2051, 'head': {'sha': 'original'}, 'base': {'ref': 'main', 'sha': 'base'}}
    updated = {'number': 2051, 'head': {'sha': head}, 'base': {'ref': base_ref, 'sha': base_sha}}
    current = original

    def fake_api(path):
        nonlocal current
        if path == '/repos/owner/repo/pulls/2051':
            return current
        assert path == '/repos/owner/repo/pulls/2051/files?per_page=100&page=1'
        if changed_during == 'diff':
            current = updated
        return [{'filename': 'main.py', 'status': 'modified', 'patch': 'patch', 'additions': 2, 'deletions': 1}]

    def review(diff, files, truncated, pr):
        nonlocal current
        assert changed_during != 'diff'
        assert files == ['main.py'] and pr == original
        if changed_during == 'model':
            current = updated
        return 'review text'

    monkeypatch.setattr(ai_review, '_event_payload', lambda: {'pull_request': original})
    monkeypatch.setattr(ai_review, '_github_api_json', fake_api)
    monkeypatch.setattr(ai_review, 'ai_review', review)
    summary = review_run / 'summary.md'
    result = review_run / 'ai_review_result.txt'
    if changed_during == 'summary missing':
        monkeypatch.delenv('GITHUB_STEP_SUMMARY')
        with pytest.raises(RuntimeError, match='摘要链接'):
            ai_review.main()
        assert not result.exists()
    elif changed_during:
        with pytest.raises(RuntimeError, match='PR 版本'):
            ai_review.main()
        assert not result.exists() and not summary.exists()
    else:
        ai_review.main()
        expected = '审查版本 `original`（目标分支 `main`，基线 `base`）\n\nreview text'
        summary_text = summary.read_text(encoding='utf-8')
        assert expected in summary_text
        assert '共 1 个文件，+2 / -1' in summary_text
        assert '- `main.py` (+2/-1)' in summary_text
        assert 'https://github.example/owner/repo/actions/runs/101/attempts/2' in result.read_text(encoding='utf-8')


@pytest.mark.parametrize('existing', [False, True])
def test_workflow_comment_links_to_review_without_mixing_it_with_live_files(monkeypatch, review_run, existing):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required to run the GitHub Script step locally')

    path = ROOT / '.github' / 'workflows' / 'pr-review.yml'
    steps = yaml.safe_load(path.read_text(encoding='utf-8'))['jobs']['comment']['steps']
    script = next(step['with']['script'] for step in steps if step.get('uses', '').startswith('actions/github-script@'))
    pr = {'number': 2051, 'head': {'sha': 'original'}, 'base': {'ref': 'main', 'sha': 'base'}}
    monkeypatch.setattr(ai_review, 'get_pr_context', lambda: pr)
    monkeypatch.setattr(ai_review, 'MAX_DIFF_LENGTH', 40)
    monkeypatch.setattr(ai_review, '_fetch_pull_files', lambda: [
        {'filename': 'original.py', 'status': 'modified', 'patch': 'original patch', 'additions': 2, 'deletions': 1},
    ])
    monkeypatch.setattr(ai_review, 'ai_review', lambda *args: 'CI: success')
    ai_review.main()

    # The PR changes after the review artifact has been generated.
    harness = """
const fs = require('fs');
const { script, existing } = JSON.parse(fs.readFileSync(0, 'utf8'));
const events = [];
const github = {
  paginate: async (method) => {
    if (method === github.rest.pulls.listFiles) {
      return [{filename: 'updated.py', additions: 3, deletions: 4}];
    }
    if (method === github.rest.issues.listComments) {
      return existing ? [{id: 1, user: {type: 'Bot'}, body: '## 🤖 自动审查报告'}] : [];
    }
    throw new Error('Unexpected GitHub request');
  },
  rest: {
    pulls: {listFiles() {}},
    issues: {
      listComments() {},
      createComment: async ({body}) => events.push(['create', body]),
      updateComment: async ({body}) => events.push(['update', body]),
    },
  },
};
const run = new (Object.getPrototypeOf(async function() {}).constructor)('github', 'context', 'core', 'require', script);
run(github, {repo: {owner: 'owner', repo: 'repo'}}, {setFailed: message => events.push(['failed', message])}, require)
  .then(() => console.log(JSON.stringify(events)))
  .catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(
        [node, '-e', harness], input=json.dumps({'script': script, 'existing': existing}),
        cwd=review_run, capture_output=True, text=True, encoding='utf-8', timeout=15, check=True,
    )
    (action, comment), = json.loads(result.stdout)
    assert action == ('update' if existing else 'create')
    assert '[运行摘要](https://github.example/owner/repo/actions/runs/101/attempts/2)' in comment
    assert '审查版本 `original`（目标分支 `main`，基线 `base`）' in comment
    assert '下方文件统计取自生成评论时的 PR' in comment and '`updated.py` (+3/-4)' in comment
    assert 'CI: success' not in comment and 'original.py' not in comment
    summary = (review_run / 'summary.md').read_text(encoding='utf-8')
    assert 'CI: success' in summary and '`original.py` (+2/-1)' in summary
    assert '文本 diff 已截断至 40 字符' in summary
    assert 'updated.py' not in summary


def test_review_includes_current_head_ci_and_distinguishes_links_from_viewed_images(monkeypatch):
    monkeypatch.setenv('AI_REVIEW_SOURCE', 'github_api')
    monkeypatch.setenv('GITHUB_REPOSITORY', 'owner/repo')
    monkeypatch.setattr(ai_review, 'GITHUB_API_PAGE_SIZE', 2)
    pr = {'head': {'sha': 'abc'}, 'number': 123, 'base': {'ref': 'main', 'sha': 'base'},
          'comments': 1, 'mergeable': False, 'mergeable_state': 'dirty'}
    pull = {'number': 123, 'head': pr['head'], 'base': pr['base']}
    ci = {'id': 7, 'head_sha': 'abc', 'conclusion': 'success', 'html_url': 'https://example.org/runs/7',
          'pull_requests': [pull]}
    runs_path = '/repos/owner/repo/actions/workflows/ci.yml/runs?event=pull_request&head_sha=abc&per_page=2'
    responses = {
        f'{runs_path}&page=1': {'workflow_runs': [
            {**ci, 'id': 9, 'pull_requests': [{**pull, 'number': 124}]},
            {**ci, 'id': 10, 'pull_requests': [{**pull, 'base': {'ref': 'main', 'sha': 'previous-base'}}]},
        ]},
        f'{runs_path}&page=2': {'workflow_runs': [ci]},
        '/repos/owner/repo/actions/runs/7/jobs?per_page=100':
            {'jobs': [{'name': 'docker-build', 'conclusion': 'skipped', 'status': 'completed'}]},
        '/repos/owner/repo/actions/runs/7/artifacts?name=web-ui-evidence-abc':
            {'artifacts': [{'id': 8, 'name': 'web-ui-evidence-abc', 'expired': False}]},
        '/repos/owner/repo/issues/123/comments?per_page=2&page=1': [
            {'body': '![after](https://example.org/after.png)', 'html_url': 'https://example.org/comment/1'},
            {'body': 'Looks good', 'html_url': 'https://example.org/comment/2'},
        ],
    }
    monkeypatch.setattr(ai_review, '_github_api_json', responses.__getitem__)
    context = ai_review.get_review_evidence(pr)
    assert 'https://example.org/runs/7/artifacts/8' in context and '画面未查看' in context
    assert 'https://example.org/comment/1' in context and 'comment/2' not in context
    assert 'success' in context
    assert 'docker-build: skipped' in context and '存在合并冲突' in context
    assert 'GitHub 合并状态: dirty' in context

    ci['head_sha'] = 'older'
    context = ai_review.get_review_evidence(pr)
    assert 'CI 运行待核实' in context and 'runs/7' not in context


@pytest.mark.parametrize('pull_requests', [
    [],
    [{'number': 123, 'base': {'ref': 'main', 'sha': 'shared-base'}}],
    [{'number': 124, 'base': {'ref': 'main', 'sha': 'shared-base'}}],
    [{'number': 124, 'base': {'ref': 'maintenance', 'sha': 'older-base'}}],
    [{'number': 124, 'base': {'ref': 'maintenance', 'sha': 'shared-base'}, 'head': {'sha': 'older-head'}}],
    [
        {'number': 123, 'base': {'ref': 'main', 'sha': 'shared-base'}},
        {'number': 124, 'base': {'ref': 'maintenance', 'sha': 'shared-base'}},
    ],
])
def test_ci_is_unverified_without_a_matching_pr_and_base(monkeypatch, pull_requests):
    monkeypatch.setenv('AI_REVIEW_SOURCE', 'github_api')
    monkeypatch.setenv('GITHUB_REPOSITORY', 'owner/repo')
    pr = {'number': 124, 'head': {'sha': 'shared-head'}, 'base': {'ref': 'maintenance', 'sha': 'shared-base'}}
    ci = {'id': 7, 'head_sha': 'shared-head', 'conclusion': 'success', 'html_url': 'https://example.org/runs/7',
          'pull_requests': [{'head': pr['head'], **pull} for pull in pull_requests]}

    def fake_api(path):
        assert path.endswith('/ci.yml/runs?event=pull_request&head_sha=shared-head&per_page=100&page=1')
        return {'workflow_runs': [ci]}

    monkeypatch.setattr(ai_review, '_github_api_json', fake_api)
    evidence = ai_review.get_review_evidence(pr)
    assert 'CI 运行待核实' in evidence and 'runs/7' not in evidence


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


def test_build_prompt_forbids_whole_pr_merge_verdict_when_truncated():
    prompt = ai_review.build_prompt(
        'diff --git a/foo.py b/foo.py\n+x = 1',
        ['foo.py', 'bar.py'],
        True,
        'chore: test',
        'body',
        'evidence',
    )
    assert '不得对整个 PR 给出“可合入”结论' in prompt


def test_build_prompt_forbids_whole_pr_merge_verdict_for_filtered_path():
    prompt = ai_review.build_prompt(
        '@@ Review path filter omitted changed files; coverage is incomplete: .dockerignore @@',
        ['.dockerignore', 'setup.cfg'],
        False,
        'chore: test',
        'body',
        'evidence',
    )
    assert '不得对整个 PR 给出“可合入”结论' in prompt
    assert '覆盖不完整' in prompt


def test_load_review_guidance_falls_back_when_skill_missing_in_legacy_checkout(tmp_path):
    guidance = ai_review._load_review_guidance(tmp_path)
    assert guidance == ai_review._FALLBACK_REVIEW_GUIDANCE


def test_review_guidance_uses_compact_automation_excerpt():
    guidance = ai_review._load_review_guidance(ROOT)

    assert len(guidance) <= ai_review.MAX_GUIDANCE_LENGTH
    assert 'gh pr view' not in guidance
    assert '14 维' in guidance


def test_build_prompt_marks_truncated_file_list_as_incomplete():
    prompt = ai_review.build_prompt(
        'diff --git a/foo.py b/foo.py\n+x = 1',
        ['file.py'] * (ai_review.MAX_PROMPT_FILES_LENGTH // len('file.py, ') + 10),
        False,
        'chore: test',
        'body',
        'evidence',
    )

    assert '文件清单已截断' in prompt
    assert '不得对整个 PR 给出“可合入”结论' in prompt

