import unittest
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
        # Mock a successful API response
        mock_response = MagicMock()
        mock_response.json.return_value = {"errcode": 0, "errmsg": "ok"}
        mock_post.return_value = mock_response

        result = self.sender.send_to_dingtalk("Test content", "Test Title")
        self.assertTrue(result)
        mock_post.assert_called_once()
        
        # Verify the signature and timestamp were added to the URL
        called_url = mock_post.call_args[0][0]
        self.assertIn("timestamp=", called_url)
        self.assertIn("sign=", called_url)

    @patch("src.notification_sender.dingtalk_sender.requests.post")
    def test_send_api_error(self, mock_post):
        # Mock a DingTalk API error
        mock_response = MagicMock()
        mock_response.json.return_value = {"errcode": 310000, "errmsg": "invalid token"}
        mock_post.return_value = mock_response

        result = self.sender.send_to_dingtalk("Test content")
        self.assertFalse(result)

    @patch("src.notification_sender.dingtalk_sender.requests.post")
    def test_send_exception(self, mock_post):
        # Mock a network timeout
        mock_post.side_effect = Exception("Network Error")
        result = self.sender.send_to_dingtalk("Test content")
        self.assertFalse(result)