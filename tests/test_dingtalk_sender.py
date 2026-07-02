import unittest
import json
from unittest.mock import patch, MagicMock
from src.notification_sender.dingtalk_sender import DingtalkSender
from src.config import Config

class TestDingtalkSender(unittest.TestCase):
    def setUp(self):
        self.config = Config()
        self.config.dingtalk_webhook_url = "https://oapi.dingtalk.com/robot/send?access_token=test_token"
        self.config.dingtalk_secret = "test_secret"
        self.sender = DingtalkSender(self.config)

    @patch("src.notification_sender.dingtalk_sender.requests.post")
    def test_send_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {"errcode": 0, "errmsg": "ok"}
        mock_post.return_value = mock_response

        result = self.sender.send_to_dingtalk("Test content", "Test Title")
        self.assertTrue(result)
        mock_post.assert_called_once()
        
        called_url = mock_post.call_args[0][0]
        self.assertIn("timestamp=", called_url)
        self.assertIn("sign=", called_url)

    @patch("src.notification_sender.dingtalk_sender.requests.post")
    def test_send_chunked_long_chinese_message_payload_size(self, mock_post):
        """测试超过 20KB 限制的多字节中文长文本与长标题，验证实际发送的 JSON payload 字节数严格遵守限制"""
        mock_response = MagicMock()
        mock_response.json.return_value = {"errcode": 0, "errmsg": "ok"}
        mock_post.return_value = mock_response

        # 生成超长中文内容 (每个汉字 3 bytes，生成约 30,000 bytes 的文本)
        long_chinese_content = "股票复盘" * 2500 
        # 生成极端长标题
        long_title = "这是一个用来测试钉钉机器人极端边界情况的超长超长超长超长标题" * 10 

        result = self.sender.send_to_dingtalk(long_chinese_content, long_title)
        
        self.assertTrue(result)
        # 应该被切分成至少 2 个请求
        self.assertGreaterEqual(mock_post.call_count, 2)
        
        # 验证每次请求的 JSON 实际序列化字节数绝对不超过 DingTalk 的 20000 字节限制
        for call in mock_post.call_args_list:
            payload = call.kwargs['json']
            # 模拟实际网络传输时的 JSON 序列化 (无空格，UTF-8编码)
            payload_bytes = len(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
            
            # 断言：最终发送的整个 JSON 请求体 <= 20000 字节
            self.assertLessEqual(payload_bytes, 20000, f"Payload 字节数为 {payload_bytes}，超过钉钉 20KB 限制！")
            
            # 确保标题被成功截断并没有丢失分页信息
            self.assertLessEqual(len(payload['markdown']['title']), 120)

    @patch("src.notification_sender.dingtalk_sender.requests.post")
    def test_send_api_error(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {"errcode": 310000, "errmsg": "invalid token"}
        mock_post.return_value = mock_response

        result = self.sender.send_to_dingtalk("Test content")
        self.assertFalse(result)

    @patch("src.notification_sender.dingtalk_sender.requests.post")
    def test_send_exception(self, mock_post):
        mock_post.side_effect = Exception("Network Error")
        result = self.sender.send_to_dingtalk("Test content")
        self.assertFalse(result)