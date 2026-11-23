# -*- coding: utf-8 -*-
"""Text-only Zulip and Raft notification senders."""
import logging
import json
import uuid
from urllib.parse import urlsplit

import requests

from src.formatters import strip_hidden_markdown_metadata

logger = logging.getLogger(__name__)


def valid_im_url(value):
    try:
        url = (value or '').strip()
        parsed = urlsplit(url)
        if '?' in url or '#' in url:
            return False
        if not (parsed.scheme in ('http', 'https') and parsed.hostname and parsed.port != 0
                and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment):
            return False
        if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url):
            return False
        requests.Request('POST', url).prepare()
        return True
    except (ValueError, requests.RequestException):
        return False


def configured(config, prefix, fields):
    return valid_im_url(getattr(config, prefix + '_url', None)) and all(
        str(getattr(config, prefix + '_' + field, None) or '').strip() for field in fields
    )


class ZulipSender:
    def __init__(self, config):
        self._zulip_config = config

    def send_to_zulip(self, content, *, timeout_seconds=None):
        config = self._zulip_config
        if not configured(config, 'zulip', ('bot_email', 'api_key', 'stream', 'topic')):
            logger.warning('Zulip 配置不完整或地址无效')
            return False
        base_url = config.zulip_url.strip().rstrip('/')
        auth = (config.zulip_bot_email.strip(), config.zulip_api_key.strip())
        timeout = timeout_seconds or 10
        verify = getattr(config, 'webhook_verify_ssl', True)
        queue_id = None
        try:
            registration = requests.post(
                base_url + '/api/v1/register', auth=auth,
                data={'event_types': '[]', 'fetch_event_types': '["realm"]'},
                timeout=timeout, verify=verify, allow_redirects=False,
            )
            if not 200 <= registration.status_code < 300:
                logger.error('Zulip 获取消息长度限制失败: HTTP %s', registration.status_code)
                return False
            settings = registration.json()
            if not isinstance(settings, dict):
                return False
            queue_id = settings.get('queue_id')
            limit = settings.get('max_message_length')
            topic_limit = settings.get('max_topic_length')
            if (settings.get('result') != 'success' or type(limit) is not int or limit <= 0
                    or type(topic_limit) is not int or topic_limit <= 0):
                logger.error('Zulip 未返回有效的消息或主题长度限制')
                return False
            message = strip_hidden_markdown_metadata(content).strip()
            topic = config.zulip_topic.strip()
            if len(topic) > topic_limit:
                logger.error('Zulip 主题超过服务器长度限制 (%s 字符)，未发送', topic_limit)
                return False
            if len(message) > limit:
                logger.error('Zulip 消息超过服务器长度限制 (%s 字符)，未发送', limit)
                return False
            response = requests.post(
                base_url + '/api/v1/messages',
                auth=auth,
                data={'type': 'stream', 'to': json.dumps(config.zulip_stream.strip(), ensure_ascii=False),
                      'topic': topic,
                      'content': message},
                timeout=timeout, verify=verify,
                allow_redirects=False,
            )
            success = 200 <= response.status_code < 300 and response.json().get('result') == 'success'
            if not success:
                logger.error('Zulip 发送失败: HTTP %s', response.status_code)
            return success
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            logger.error('Zulip 发送失败：请求或响应异常')
            return False
        finally:
            if isinstance(queue_id, str) and queue_id:
                try:
                    requests.delete(base_url + '/api/v1/events', auth=auth, data={'queue_id': queue_id},
                                    timeout=timeout, verify=verify, allow_redirects=False)
                except requests.RequestException:
                    logger.warning('Zulip 事件队列清理失败')


class RaftSender:
    def __init__(self, config):
        self._raft_config = config

    def send_to_raft(self, content, *, timeout_seconds=None):
        config = self._raft_config
        if not configured(config, 'raft', ('agent_key', 'target')):
            logger.warning('Raft 配置不完整或地址无效')
            return False
        try:
            url = config.raft_url.strip().rstrip('/') + '/internal/agent-api/send'
            payload = {'target': config.raft_target.strip(),
                       'content': strip_hidden_markdown_metadata(content).strip(),
                       'idempotencyKey': str(uuid.uuid4())}
            def send(data):
                return requests.post(
                    url, headers={'Authorization': 'Bearer ' + config.raft_agent_key.strip()},
                    json=data, timeout=timeout_seconds or 10,
                    verify=getattr(config, 'webhook_verify_ssl', True), allow_redirects=False,
                )

            response = send(payload)
            body = response.json() if 200 <= response.status_code < 300 else {}
            if isinstance(body, dict) and body.get('ok') is True and body.get('state') == 'held':
                # A report is an independent notification; unread conversation context
                # should not indefinitely prevent delivery. Resume only this held send.
                response = send({**payload, 'continueAnyway': True})
                body = response.json() if 200 <= response.status_code < 300 else {}
            if not isinstance(body, dict):
                body = {}
            success = body.get('ok') is True and body.get('state') == 'sent' and bool(body.get('messageId'))
            if not success:
                logger.error('Raft 发送失败或未送达: HTTP %s', response.status_code)
            return success
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            logger.error('Raft 发送失败：请求或响应异常')
            return False
