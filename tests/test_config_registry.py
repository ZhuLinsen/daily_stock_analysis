# -*- coding: utf-8 -*-
"""Tests for config_registry field definitions and schema building.

Ensures every notification channel that has a sender implementation also
has its config keys registered in _FIELD_DEFINITIONS so the Web settings
page and /api/v1/system/config/schema can expose them.
"""
import unittest

from src.core.config_registry import (
    build_schema_response,
    get_field_definition,
)


class TestSlackFieldsRegistered(unittest.TestCase):
    """Slack config keys must be present in the registry."""

    _SLACK_KEYS = ("SLACK_BOT_TOKEN", "SLACK_CHANNEL_ID", "SLACK_WEBHOOK_URL")

    def test_field_definitions_exist(self):
        for key in self._SLACK_KEYS:
            field = get_field_definition(key)
            self.assertEqual(field["category"], "notification", f"{key} category")
            self.assertNotEqual(
                field["display_order"], 9000,
                f"{key} should be explicitly registered, not inferred",
            )

    def test_bot_token_is_sensitive(self):
        field = get_field_definition("SLACK_BOT_TOKEN")
        self.assertTrue(field["is_sensitive"])
        self.assertEqual(field["ui_control"], "password")

    def test_webhook_url_is_sensitive(self):
        field = get_field_definition("SLACK_WEBHOOK_URL")
        self.assertTrue(field["is_sensitive"])
        self.assertEqual(field["ui_control"], "password")

    def test_channel_id_not_sensitive(self):
        field = get_field_definition("SLACK_CHANNEL_ID")
        self.assertFalse(field["is_sensitive"])

    def test_schema_response_includes_slack(self):
        schema = build_schema_response()
        notification_cat = next(
            (c for c in schema["categories"] if c["category"] == "notification"),
            None,
        )
        self.assertIsNotNone(notification_cat, "notification category missing")
        field_keys = {f["key"] for f in notification_cat["fields"]}
        for key in self._SLACK_KEYS:
            self.assertIn(key, field_keys, f"{key} missing from schema response")

    def test_display_order_between_discord_and_pushover(self):
        discord = get_field_definition("DISCORD_MAIN_CHANNEL_ID")
        pushover = get_field_definition("PUSHOVER_USER_KEY")
        for key in self._SLACK_KEYS:
            order = get_field_definition(key)["display_order"]
            self.assertGreater(order, discord["display_order"],
                               f"{key} should appear after Discord")
            self.assertLess(order, pushover["display_order"],
                            f"{key} should appear before Pushover")


class TestFeishuWebhookFieldsRegistered(unittest.TestCase):
    """Feishu webhook security fields must be registered for the settings UI."""

    _FEISHU_KEYS = (
        "FEISHU_WEBHOOK_URL",
        "FEISHU_WEBHOOK_SECRET",
        "FEISHU_WEBHOOK_KEYWORD",
    )

    def test_field_definitions_exist(self):
        for key in self._FEISHU_KEYS:
            field = get_field_definition(key)
            self.assertEqual(field["category"], "notification", f"{key} category")
            self.assertNotEqual(
                field["display_order"], 9000,
                f"{key} should be explicitly registered, not inferred",
            )

    def test_secret_is_sensitive(self):
        field = get_field_definition("FEISHU_WEBHOOK_SECRET")
        self.assertTrue(field["is_sensitive"])
        self.assertEqual(field["ui_control"], "password")

    def test_keyword_is_not_sensitive(self):
        field = get_field_definition("FEISHU_WEBHOOK_KEYWORD")
        self.assertFalse(field["is_sensitive"])
        self.assertEqual(field["ui_control"], "text")

    def test_webhook_url_uses_url_validation(self):
        field = get_field_definition("FEISHU_WEBHOOK_URL")
        self.assertEqual(field["validation"]["item_type"], "url")
        self.assertIn("https", field["validation"]["allowed_schemes"])

    def test_schema_response_includes_feishu_webhook_fields(self):
        schema = build_schema_response()
        notification_cat = next(
            (c for c in schema["categories"] if c["category"] == "notification"),
            None,
        )
        self.assertIsNotNone(notification_cat, "notification category missing")
        field_keys = {f["key"] for f in notification_cat["fields"]}
        for key in self._FEISHU_KEYS:
            self.assertIn(key, field_keys, f"{key} missing from schema response")


class TestSensitiveFieldsUsePasswordControl(unittest.TestCase):
    """Every is_sensitive field must use ui_control='password' to avoid
    leaking secrets in the Web settings page."""

    def test_all_sensitive_fields_use_password(self):
        schema = build_schema_response()
        violations = []
        for cat in schema["categories"]:
            for field in cat["fields"]:
                if field.get("is_sensitive") and field.get("ui_control") != "password":
                    violations.append(field["key"])
        self.assertEqual(violations, [],
                         f"Sensitive fields with non-password ui_control: {violations}")


class TestDiscordInteractionPublicKeyField(unittest.TestCase):
    def test_field_definition_exists(self):
        field = get_field_definition("DISCORD_INTERACTIONS_PUBLIC_KEY")
        self.assertEqual(field["category"], "notification")
        self.assertFalse(field["is_sensitive"])
        self.assertEqual(field["ui_control"], "text")

    def test_schema_response_includes_public_key_field(self):
        schema = build_schema_response()
        notification_cat = next(
            (c for c in schema["categories"] if c["category"] == "notification"),
            None,
        )
        self.assertIsNotNone(notification_cat, "notification category missing")
        field_keys = {f["key"] for f in notification_cat["fields"]}
        self.assertIn("DISCORD_INTERACTIONS_PUBLIC_KEY", field_keys)


if __name__ == "__main__":
    unittest.main()
