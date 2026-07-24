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


# issue #2070 regression tests: _event_payload 之前在 4 类异常下统一静默
# 返回 {},排障只能看到 'PR number is unavailable for GitHub API review',
# 无法区分 GITHUB_EVENT_PATH 未注入 / 文件不存在 / 读取失败 / JSON 非法。

def test_event_payload_warns_when_env_var_missing(monkeypatch, capsys):
    monkeypatch.delenv('GITHUB_EVENT_PATH', raising=False)

    result = ai_review._event_payload()

    assert result == {}
    captured = capsys.readouterr()
    assert 'event payload unavailable' in captured.err
    assert 'GITHUB_EVENT_PATH env var is not set' in captured.err
    # 确保没有 payload 内容泄漏到日志
    assert 'pull_request' not in captured.err


def test_event_payload_warns_when_file_does_not_exist(monkeypatch, capsys, tmp_path):
    missing_path = tmp_path / 'does-not-exist.json'
    monkeypatch.setenv('GITHUB_EVENT_PATH', str(missing_path))

    result = ai_review._event_payload()

    assert result == {}
    captured = capsys.readouterr()
    assert 'event payload unavailable' in captured.err
    assert 'file does not exist' in captured.err
    assert str(missing_path) in captured.err


def test_event_payload_warns_on_oserror(monkeypatch, capsys, tmp_path):
    # 创建一个目录作为 GITHUB_EVENT_PATH —— open() 会因为 IsADirectoryError 失败
    # (OSError 子类,多数平台 errno=21 EISDIR)。
    bad_path = tmp_path / 'is-a-dir'
    bad_path.mkdir()
    monkeypatch.setenv('GITHUB_EVENT_PATH', str(bad_path))

    result = ai_review._event_payload()

    assert result == {}
    captured = capsys.readouterr()
    assert 'event payload unavailable' in captured.err
    assert 'failed to read GITHUB_EVENT_PATH' in captured.err
    assert 'OSError' in captured.err or 'IsADirectoryError' in captured.err
    # 异常对象本身不应包含 payload 内容
    assert 'pull_request' not in captured.err


def test_event_payload_warns_on_invalid_json(monkeypatch, capsys, tmp_path):
    bad_json_path = tmp_path / 'invalid.json'
    bad_json_path.write_text('{ this is not json ', encoding='utf-8')
    monkeypatch.setenv('GITHUB_EVENT_PATH', str(bad_json_path))

    result = ai_review._event_payload()

    assert result == {}
    captured = capsys.readouterr()
    assert 'event payload unavailable' in captured.err
    assert 'failed to parse GITHUB_EVENT_PATH as JSON' in captured.err
    # JSONDecodeError 是 ValueError 子类
    assert 'json' in captured.err.lower() or 'JSONDecodeError' in captured.err
    assert 'pull_request' not in captured.err


def test_event_payload_returns_dict_on_valid_json(monkeypatch, capsys, tmp_path):
    payload_path = tmp_path / 'event.json'
    payload_path.write_text(
        '{"pull_request": {"number": 42}, "action": "opened"}',
        encoding='utf-8',
    )
    monkeypatch.setenv('GITHUB_EVENT_PATH', str(payload_path))

    result = ai_review._event_payload()

    assert result == {'pull_request': {'number': 42}, 'action': 'opened'}
    captured = capsys.readouterr()
    assert captured.err == ''  # 成功路径不应有警告


# 契约一: PR_NUMBER 已显式提供时,坏的事件文件不应阻断 GitHub API 审查流程。

def test_pull_request_number_env_override_skips_broken_event_path(monkeypatch, capsys, tmp_path):
    bad_json_path = tmp_path / 'invalid.json'
    bad_json_path.write_text('not json', encoding='utf-8')
    monkeypatch.setenv('GITHUB_EVENT_PATH', str(bad_json_path))
    monkeypatch.setenv('PR_NUMBER', '2070')

    number = ai_review._pull_request_number()

    assert number == 2070


def test_pull_request_number_env_override_handles_non_integer(monkeypatch):
    monkeypatch.setenv('PR_NUMBER', 'not-a-number')
    monkeypatch.delenv('GITHUB_EVENT_PATH', raising=False)

    try:
        ai_review._pull_request_number()
    except RuntimeError as exc:
        assert 'PR_NUMBER env var is not a valid integer' in str(exc)
        assert 'not-a-number' in str(exc)
    else:
        raise AssertionError('expected RuntimeError for non-integer PR_NUMBER')


# 契约二: PR_NUMBER 未提供时,事件载荷路径上的失败应通过 stderr 警告可定位,
# 而 _pull_request_number 抛出的 RuntimeError 也要提示去看 stderr 警告。

def test_pull_request_number_from_payload_raises_with_stderr_hint(monkeypatch, capsys):
    monkeypatch.delenv('PR_NUMBER', raising=False)
    monkeypatch.delenv('GITHUB_EVENT_PATH', raising=False)

    try:
        ai_review._pull_request_number()
    except RuntimeError as exc:
        msg = str(exc)
        assert 'PR number is unavailable' in msg
        assert 'check prior event payload warnings on stderr' in msg
    else:
        raise AssertionError('expected RuntimeError when PR number unavailable')

    captured = capsys.readouterr()
    assert 'event payload unavailable' in captured.err
    assert 'GITHUB_EVENT_PATH env var is not set' in captured.err


def test_pull_request_number_extracts_from_payload_pull_request_key(monkeypatch):
    monkeypatch.delenv('PR_NUMBER', raising=False)
    monkeypatch.setenv(
        'GITHUB_EVENT_PATH',
        '',  # 直接传入 payload 参数,跳过 _event_payload 重新读取
    )

    number = ai_review._pull_request_number(
        payload={'pull_request': {'number': 1234}}
    )

    assert number == 1234


def test_pull_request_number_extracts_from_payload_top_level_number(monkeypatch):
    # issue_comment 事件没有 pull_request 键,但 number 在顶层(指向 issue/PR 编号)。
    monkeypatch.delenv('PR_NUMBER', raising=False)

    number = ai_review._pull_request_number(payload={'number': 5678})

    assert number == 5678


def test_pull_request_number_handles_non_integer_payload_number(monkeypatch):
    """防御性测试:如果 payload 里 number 不是整数(比如被篡改成字符串 'oops'),
    _pull_request_number 应明确报错而不是让 int() 抛 TypeError/ValueError 一路冒泡。"""
    monkeypatch.delenv('PR_NUMBER', raising=False)

    try:
        ai_review._pull_request_number(payload={'number': 'oops'})
    except RuntimeError as exc:
        assert 'PR number from event payload is not a valid integer' in str(exc)
        assert "'oops'" in str(exc)
    else:
        raise AssertionError('expected RuntimeError for non-integer payload number')


# issue #2070 review 非阻断建议: payload 合法 JSON 但不是 object 时
# (例如 '[]' / 'null' / '"string"'），_pull_request_number / get_pr_context 不
# 应抛 AttributeError, 而应通过 stderr 警告可定位, 并在 PR_NUMBER override
# 或 AI_REVIEW_SOURCE=github_api 链路上不影响契约。

def test_pull_request_number_handles_array_payload_with_pr_number_override(monkeypatch, capsys):
    """契约一延伸: GITHUB_EVENT_PATH 解析成合法 JSON 但不是 object (例如 '[]')
    时, PR_NUMBER override 必须仍然能绕过, 不应在 .get 上抛 AttributeError。"""
    monkeypatch.setenv('PR_NUMBER', '2085')
    monkeypatch.delenv('GITHUB_EVENT_PATH', raising=False)

    number = ai_review._pull_request_number(payload=[])

    assert number == 2085
    # PR_NUMBER override 路径下根本没碰 payload,不应触发 _warn_event_payload。
    captured = capsys.readouterr()
    assert captured.err == ''


def test_pull_request_number_warns_on_array_payload_without_pr_number(monkeypatch, capsys):
    """契约二延伸: 无 PR_NUMBER 且 payload 是 array 时, _pull_request_number
    应通过 _warn_event_payload 输出可定位 stderr 警告, 并仍以 RuntimeError
    上抛(信息包含 stderr 提示)。"""
    monkeypatch.delenv('PR_NUMBER', raising=False)
    monkeypatch.delenv('GITHUB_EVENT_PATH', raising=False)

    try:
        ai_review._pull_request_number(payload=[])
    except RuntimeError as exc:
        assert 'PR number is unavailable' in str(exc)
        assert 'check prior event payload warnings on stderr' in str(exc)
    else:
        raise AssertionError('expected RuntimeError for array payload without PR_NUMBER')

    captured = capsys.readouterr()
    assert 'event payload parsed but is not a JSON object' in captured.err
    assert 'list' in captured.err


def test_pull_request_number_warns_on_non_dict_pull_request_field(monkeypatch, capsys):
    """payload 是 dict, 但 pull_request 字段是 list/string 等非 dict 类型时,
    应记 stderr 警告(避免 pr.get 提前 AttributeError)。"""
    monkeypatch.delenv('PR_NUMBER', raising=False)

    try:
        ai_review._pull_request_number(
            payload={'pull_request': ['not', 'a', 'dict']}
        )
    except RuntimeError as exc:
        assert 'PR number is unavailable' in str(exc)
        assert 'check prior event payload warnings on stderr' in str(exc)
    else:
        raise AssertionError('expected RuntimeError for non-dict pull_request field')

    captured = capsys.readouterr()
    assert "event payload 'pull_request' field is not a JSON object" in captured.err
    assert 'list' in captured.err


def test_pull_request_number_handles_none_payload_with_pr_number_override(monkeypatch):
    """contract: payload=None (GITHUB_EVENT_PATH 缺失 → {}) + PR_NUMBER override 时
    应跳过事件文件读取,直接返回 PR_NUMBER。"""
    monkeypatch.setenv('PR_NUMBER', '2085')
    monkeypatch.delenv('GITHUB_EVENT_PATH', raising=False)

    # payload=None 触发 _event_payload 路径,但因为 PR_NUMBER 优先,函数提前 return。
    number = ai_review._pull_request_number(payload=None)

    assert number == 2085


def test_get_pr_context_warns_on_array_payload(monkeypatch, capsys):
    """get_pr_context 入口同样应防御非 dict payload, 通过 stderr 警告可定位,
    而不是抛 AttributeError 让脚本崩溃。"""
    monkeypatch.delenv('GITHUB_EVENT_PATH', raising=False)
    monkeypatch.delenv('AI_REVIEW_SOURCE', raising=False)

    # 直接 monkeypatch _event_payload 返回 list,模拟合法 JSON 但不是 object。
    monkeypatch.setattr(ai_review, '_event_payload', lambda: [])

    title, body = ai_review.get_pr_context()

    assert title == ''
    assert body == ''
    captured = capsys.readouterr()
    assert 'event payload parsed but is not a JSON object' in captured.err
    assert 'list' in captured.err


def test_get_pr_context_warns_on_non_dict_pull_request_field(monkeypatch, capsys):
    """get_pr_context 中 pr 字段不是 dict 时也应记 stderr 警告并降级返回 ('','')."""
    monkeypatch.delenv('GITHUB_EVENT_PATH', raising=False)
    monkeypatch.delenv('AI_REVIEW_SOURCE', raising=False)
    monkeypatch.setattr(
        ai_review,
        '_event_payload',
        lambda: {'pull_request': 'not-a-dict'},
    )

    title, body = ai_review.get_pr_context()

    assert title == ''
    assert body == ''
    captured = capsys.readouterr()
    assert "event payload 'pull_request' field is not a JSON object" in captured.err
    assert 'str' in captured.err


def test_get_pr_context_goes_through_github_api_when_payload_is_array(monkeypatch, capsys):
    """end-to-end: payload 是 array + AI_REVIEW_SOURCE=github_api + PR_NUMBER override
    时, get_pr_context 应不抛 AttributeError, 而是走 GitHub API fallback 取回 title/body。"""
    monkeypatch.setenv('AI_REVIEW_SOURCE', 'github_api')
    monkeypatch.setenv('GITHUB_REPOSITORY', 'owner/repo')
    monkeypatch.setenv('PR_NUMBER', '2085')
    monkeypatch.delenv('GITHUB_EVENT_PATH', raising=False)
    monkeypatch.setattr(ai_review, '_event_payload', lambda: [])

    monkeypatch.setattr(
        ai_review,
        '_github_api_json',
        lambda path: {'title': 'Fix review', 'body': 'Closes #2085'}
        if path == '/repos/owner/repo/pulls/2085'
        else None,
    )

    title, body = ai_review.get_pr_context()

    assert title == 'Fix review'
    assert body == 'Closes #2085'
