from types import SimpleNamespace
from unittest.mock import patch

import requests

from src.notification import NotificationChannel, NotificationService
from src.notification_routing import split_notification_route_channels
from src.notification_sender.im_sender import RaftSender, ZulipSender, valid_im_url


def config():
    return SimpleNamespace(zulip_url='https://zulip.example', zulip_bot_email='bot@example.com',
                           zulip_api_key='secret', zulip_stream='stocks', zulip_topic='daily',
                           raft_url='https://raft.example', raft_agent_key='sk_agent_secret',
                           raft_target='#stocks', webhook_verify_ssl=True)


def response(body, status=200):
    result = requests.Response()
    result.status_code = status
    import json
    result._content = json.dumps(body).encode()
    return result


def test_zulip_contract_and_failure():
    registration = response({'result': 'success', 'max_message_length': 10000, 'max_topic_length': 60, 'queue_id': 'queue'})
    with patch('src.notification_sender.im_sender.requests.post', side_effect=[registration, response({'result': 'success'})]) as post, \
            patch('src.notification_sender.im_sender.requests.delete') as delete:
        assert ZulipSender(config()).send_to_zulip('hello')
        assert post.call_args.args[0] == 'https://zulip.example/api/v1/messages'
        assert post.call_args.kwargs['auth'] == ('bot@example.com', 'secret')
        assert post.call_args.kwargs['data'] == {'type': 'stream', 'to': '"stocks"', 'topic': 'daily', 'content': 'hello'}
        assert post.call_args_list[0].kwargs['data']['fetch_event_types'] == '["realm"]'
        delete.assert_called_once()
    with patch('src.notification_sender.im_sender.requests.post', side_effect=[registration, response({'result': 'error'})]), \
            patch('src.notification_sender.im_sender.requests.delete'):
        assert not ZulipSender(config()).send_to_zulip('hello')


def test_zulip_numeric_channel_is_json_string():
    settings = config()
    settings.zulip_stream = '2026'
    with patch('src.notification_sender.im_sender.requests.post', side_effect=[
        response({'result': 'success', 'max_message_length': 10, 'max_topic_length': 60}), response({'result': 'success'})
    ]) as post:
        assert ZulipSender(settings).send_to_zulip('hello')
        assert post.call_args.kwargs['data']['to'] == '"2026"'


def test_zulip_rejects_oversized_and_unknown_limit_without_sending():
    for body in ({'result': 'success', 'max_message_length': 3},
                 {'result': 'success'}, {'result': 'success', 'max_message_length': True},
                 {'result': 'error', 'max_message_length': 100}):
        with patch('src.notification_sender.im_sender.requests.post', return_value=response(body)) as post:
            assert not ZulipSender(config()).send_to_zulip('hello')
            assert post.call_count == 1
    with patch('src.notification_sender.im_sender.requests.post', side_effect=[
        response({'result': 'success', 'max_message_length': 2, 'max_topic_length': 60}), response({'result': 'success'})
    ]):
        assert ZulipSender(config()).send_to_zulip('股票')


def test_zulip_rejects_oversized_or_unknown_topic_limit_and_cleans_queue():
    settings = config()
    settings.zulip_topic = '主题测试'
    for topic_limit in (3, None, True, 0):
        with patch('src.notification_sender.im_sender.requests.post', return_value=response({
            'result': 'success', 'max_message_length': 100,
            'max_topic_length': topic_limit, 'queue_id': 'queue',
        })) as post, patch('src.notification_sender.im_sender.requests.delete') as delete:
            assert not ZulipSender(settings).send_to_zulip('hello')
            assert post.call_count == 1
            delete.assert_called_once()
    with patch('src.notification_sender.im_sender.requests.post', side_effect=[
        response({'result': 'success', 'max_message_length': 100, 'max_topic_length': 4}),
        response({'result': 'success'}),
    ]) as post:
        assert ZulipSender(settings).send_to_zulip('hello')
        assert post.call_args.kwargs['data']['topic'] == '主题测试'


def test_url_rejects_empty_query_and_fragment_delimiters():
    for base in ('https://zulip.example?', 'https://raft.example#',
                 'https://example.com/path/?', 'https://example.com/path/#'):
        assert not valid_im_url(base)
    assert valid_im_url('https://example.com/path%3Fpart')


def test_raft_contract_and_held_response():
    with patch('src.notification_sender.im_sender.requests.post', return_value=response({'ok': True, 'state': 'sent', 'messageId': '1'})) as post:
        assert RaftSender(config()).send_to_raft('hello')
        assert post.call_args.args[0] == 'https://raft.example/internal/agent-api/send'
        assert post.call_args.kwargs['headers']['Authorization'] == 'Bearer sk_agent_secret'
        assert post.call_args.kwargs['json']['target'] == '#stocks'
        assert post.call_args.kwargs['json']['idempotencyKey']
    with patch('src.notification_sender.im_sender.requests.post', side_effect=[
        response({'ok': True, 'state': 'held'}), response({'ok': True, 'state': 'sent', 'messageId': '2'})
    ]) as post:
        assert RaftSender(config()).send_to_raft('hello')
        first, second = (call.kwargs['json'] for call in post.call_args_list)
        assert second == {**first, 'continueAnyway': True}
    with patch('src.notification_sender.im_sender.requests.post', return_value=response({'ok': True, 'state': 'held'})) as post:
        assert not RaftSender(config()).send_to_raft('hello')
        assert post.call_count == 2


def test_detection_routing_and_failure_isolation():
    channels = NotificationService.detect_configured_channels(config())
    assert NotificationChannel.ZULIP in channels and NotificationChannel.RAFT in channels
    assert split_notification_route_channels(['zulip', 'raft']) == (['zulip', 'raft'], [])
    with patch('src.notification_sender.im_sender.requests.post', side_effect=requests.Timeout):
        assert not ZulipSender(config()).send_to_zulip('hello')
        assert not RaftSender(config()).send_to_raft('hello')
    assert not valid_im_url('https://user:secret@example.com')
    assert not valid_im_url('https://example.com/?token=secret')
