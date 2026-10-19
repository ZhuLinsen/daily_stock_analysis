# -*- coding: utf-8 -*-
"""Unit tests for structured `.env` line preservation in ConfigManager."""

import errno
import grp
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core.config_manager import ConfigManager


def _supplementary_groups() -> set:
    """Group names this process may chown a file to."""
    try:
        return {grp.getgrgid(gid).gr_name for gid in os.getgroups()}
    except (AttributeError, KeyError, OSError):  # pragma: no cover - non-POSIX
        return set()


class ConfigManagerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_path = Path(self.temp_dir.name) / ".env"
        os.environ["ENV_FILE"] = str(self.env_path)
        self.manager = ConfigManager(env_path=self.env_path)

    def tearDown(self) -> None:
        os.environ.pop("ENV_FILE", None)
        self.temp_dir.cleanup()

    def test_apply_updates_preserves_comments_blank_lines_and_raw_lines(self) -> None:
        self.env_path.write_text(
            "\n".join(
                [
                    "# Core settings",
                    "STOCK_LIST=600519,000001",
                    "",
                    "export SHOULD_STAY_UNCHANGED",
                    "# Secrets",
                    "GEMINI_API_KEY=secret-key",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        self.manager.apply_updates(
            updates=[("STOCK_LIST", "600519,300750")],
            sensitive_keys=set(),
            mask_token="******",
        )

        env_content = self.env_path.read_text(encoding="utf-8")
        self.assertIn("# Core settings\n", env_content)
        self.assertIn("\n\nexport SHOULD_STAY_UNCHANGED\n", env_content)
        self.assertIn("# Secrets\nGEMINI_API_KEY=secret-key\n", env_content)
        self.assertIn("STOCK_LIST=600519,300750\n", env_content)

    def test_apply_updates_only_rewrites_last_duplicate_assignment(self) -> None:
        self.env_path.write_text(
            "\n".join(
                [
                    "STOCK_LIST=600519",
                    "# Keep the legacy duplicate for audit history",
                    "STOCK_LIST=000001",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        self.manager.apply_updates(
            updates=[("STOCK_LIST", "300750")],
            sensitive_keys=set(),
            mask_token="******",
        )

        env_lines = self.env_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(env_lines[0], "STOCK_LIST=600519")
        self.assertEqual(env_lines[1], "# Keep the legacy duplicate for audit history")
        self.assertEqual(env_lines[2], "STOCK_LIST=300750")

    def test_apply_updates_falls_back_to_in_place_rewrite(self) -> None:
        self.env_path.write_text("STOCK_LIST=600519\n", encoding="utf-8")

        with patch("src.core.config_manager.os.replace", side_effect=OSError(errno.EXDEV, "cross-device")):
            self.manager.apply_updates(
                updates=[("STOCK_LIST", "000001")],
                sensitive_keys=set(),
                mask_token="******",
            )

        self.assertEqual(self.env_path.read_text(encoding="utf-8"), "STOCK_LIST=000001\n")

    @unittest.skipIf(os.name == "nt", "POSIX file permissions")
    def test_apply_updates_preserves_existing_env_permissions(self) -> None:
        for mode in (0o600, 0o640):
            for use_fallback in (False, True):
                with self.subTest(mode=oct(mode), fallback=use_fallback):
                    self.env_path.write_text("STOCK_LIST=600519\n", encoding="utf-8")
                    self.env_path.chmod(mode)
                    original_replace = os.replace
                    with patch(
                        "src.core.config_manager.os.replace",
                        side_effect=OSError(errno.EXDEV, "cross-device") if use_fallback else original_replace,
                    ):
                        self.manager.apply_updates(
                            updates=[("STOCK_LIST", "000001")],
                            sensitive_keys=set(), mask_token="******",
                        )
                    self.assertEqual(stat.S_IMODE(self.env_path.stat().st_mode), mode)
                    self.assertEqual(self.env_path.read_text(encoding="utf-8"), "STOCK_LIST=000001\n")
                    self.assertEqual(list(self.env_path.parent.glob("*.tmp")), [])

    @unittest.skipIf(os.name == "nt", "POSIX file permissions")
    def test_apply_updates_preserves_existing_env_group(self) -> None:
        """The atomic replace must not drop the target's group.

        chmod only copies mode bits and mkstemp creates the replacement under
        the process's primary group. A `.env` shared through a secondary group
        (owner:shared, 0640) would therefore lose that group's read access after
        a save, because the mode no longer falls back to world-read. The in-place
        fallback path keeps the inode and so keeps the group; both paths have to
        agree.
        """
        try:
            groups = sorted(
                g.gr_name for g in grp.getgrall()
                if self.env_path.parent.stat().st_gid != g.gr_gid
            )
        except (AttributeError, KeyError):  # pragma: no cover - non-POSIX
            self.skipTest("grp module unavailable")
        # Pick a group the process may chown to; without one the assertion is
        # about the warning path instead, which is covered separately.
        candidate = next(
            (name for name in groups
             if name in _supplementary_groups()),
            None,
        )
        if candidate is None:
            self.skipTest("no secondary group available to chown to")

        target_gid = grp.getgrnam(candidate).gr_gid
        self.env_path.write_text("STOCK_LIST=600519\n", encoding="utf-8")
        self.env_path.chmod(0o640)
        os.chown(self.env_path, -1, target_gid)
        before_gid = self.env_path.stat().st_gid
        original_replace = os.replace

        for use_fallback in (False, True):
            with self.subTest(fallback=use_fallback):
                with patch(
                    "src.core.config_manager.os.replace",
                    side_effect=OSError(errno.EXDEV, "cross-device") if use_fallback else original_replace,
                ):
                    self.manager.apply_updates(
                        updates=[("STOCK_LIST", "000001")],
                        sensitive_keys=set(), mask_token="******",
                    )
                after = self.env_path.stat()
                self.assertEqual(after.st_gid, before_gid)
                self.assertEqual(stat.S_IMODE(after.st_mode), 0o640)
                self.assertEqual(self.env_path.read_text(encoding="utf-8"), "STOCK_LIST=000001\n")

    @unittest.skipIf(os.name == "nt", "POSIX file permissions")
    def test_apply_updates_warns_when_group_cannot_be_preserved(self) -> None:
        """A refused chown must not fail the save, but has to be reported."""
        secondary = sorted(_supplementary_groups() - {grp.getgrgid(os.getgid()).gr_name})
        if not secondary:
            self.skipTest("no secondary group available")
        self.env_path.write_text("STOCK_LIST=600519\n", encoding="utf-8")
        self.env_path.chmod(0o640)
        # Force a group mismatch so the no-op short circuit does not apply.
        os.chown(self.env_path, -1, grp.getgrnam(secondary[0]).gr_gid)

        with patch("src.core.config_manager.os.chown",
                   side_effect=PermissionError("operation not permitted")), \
             self.assertLogs("src.core.config_manager", level="WARNING") as logs:
            self.manager.apply_updates(
                updates=[("STOCK_LIST", "000001")],
                sensitive_keys=set(), mask_token="******",
            )

        assert any("group ownership" in message for message in logs.output)
        # The write still succeeded and the mode is still correct.
        self.assertEqual(stat.S_IMODE(self.env_path.stat().st_mode), 0o640)
        self.assertEqual(self.env_path.read_text(encoding="utf-8"), "STOCK_LIST=000001\n")

    @unittest.skipIf(os.name == "nt", "POSIX file permissions")
    def test_apply_updates_creates_private_env_file(self) -> None:
        self.manager.apply_updates(
            updates=[("STOCK_LIST", "000001")],
            sensitive_keys=set(), mask_token="******",
        )
        self.assertEqual(stat.S_IMODE(self.env_path.stat().st_mode), 0o600)

    @unittest.skipIf(os.name == "nt", "POSIX file permissions")
    def test_apply_updates_creates_private_env_file_on_fallback_path(self) -> None:
        """A brand-new .env must stay private when the atomic replace is refused.

        The in-place fallback opens the target with open("w"), so without an
        explicit chmod the file is created under the process umask -- typically
        0644. That is exactly the bind-mount case the fallback exists for, and
        .env holds API keys.
        """
        self.env_path.unlink(missing_ok=True)
        original_umask = os.umask(0o022)
        try:
            with patch(
                "src.core.config_manager.os.replace",
                side_effect=OSError(errno.EBUSY, "device or resource busy"),
            ):
                self.manager.apply_updates(
                    updates=[("STOCK_LIST", "000001")],
                    sensitive_keys=set(), mask_token="******",
                )
        finally:
            os.umask(original_umask)

        self.assertEqual(stat.S_IMODE(self.env_path.stat().st_mode), 0o600)
        self.assertEqual(self.env_path.read_text(encoding="utf-8"), "STOCK_LIST=000001\n")
        self.assertEqual(list(self.env_path.parent.glob("*.tmp")), [])

    def test_custom_webhook_template_placeholders_are_escaped_for_compose(self) -> None:
        template = '{"title":$title_json,"content":$content_json,"raw":$content,"name":"$OTHER"}'

        self.manager.apply_updates(
            updates=[("CUSTOM_WEBHOOK_BODY_TEMPLATE", template)],
            sensitive_keys=set(),
            mask_token="******",
        )

        env_content = self.env_path.read_text(encoding="utf-8")
        self.assertIn(
            'CUSTOM_WEBHOOK_BODY_TEMPLATE={"title":$$title_json,"content":$$content_json,'
            '"raw":$$content,"name":"$OTHER"}',
            env_content,
        )
        self.assertEqual(
            self.manager.read_config_map()["CUSTOM_WEBHOOK_BODY_TEMPLATE"],
            template,
        )

    def test_custom_webhook_template_braced_placeholders_are_escaped_for_compose(self) -> None:
        template = '{"title":${title_json},"content":${content_json},"name":"${OTHER}"}'

        self.manager.apply_updates(
            updates=[("CUSTOM_WEBHOOK_BODY_TEMPLATE", template)],
            sensitive_keys=set(),
            mask_token="******",
        )

        env_content = self.env_path.read_text(encoding="utf-8")
        self.assertIn(
            'CUSTOM_WEBHOOK_BODY_TEMPLATE={"title":$${title_json},'
            '"content":$${content_json},"name":"${OTHER}"}',
            env_content,
        )
        self.assertEqual(
            self.manager.read_config_map()["CUSTOM_WEBHOOK_BODY_TEMPLATE"],
            template,
        )

    def test_custom_webhook_template_canonicalizes_unescaped_existing_value(self) -> None:
        self.env_path.write_text(
            'CUSTOM_WEBHOOK_BODY_TEMPLATE={"content":$content_json}\n',
            encoding="utf-8",
        )

        self.manager.apply_updates(
            updates=[("CUSTOM_WEBHOOK_BODY_TEMPLATE", '{"content":$content_json}')],
            sensitive_keys=set(),
            mask_token="******",
        )

        self.assertEqual(
            self.env_path.read_text(encoding="utf-8"),
            'CUSTOM_WEBHOOK_BODY_TEMPLATE={"content":$$content_json}\n',
        )

    def test_custom_webhook_template_does_not_double_escape_existing_value(self) -> None:
        self.env_path.write_text(
            'CUSTOM_WEBHOOK_BODY_TEMPLATE={"content":$$content_json}\n',
            encoding="utf-8",
        )

        self.manager.apply_updates(
            updates=[("CUSTOM_WEBHOOK_BODY_TEMPLATE", '{"content":$content_json}')],
            sensitive_keys=set(),
            mask_token="******",
        )

        self.assertEqual(
            self.env_path.read_text(encoding="utf-8"),
            'CUSTOM_WEBHOOK_BODY_TEMPLATE={"content":$$content_json}\n',
        )
        self.assertEqual(
            self.manager.read_config_map()["CUSTOM_WEBHOOK_BODY_TEMPLATE"],
            '{"content":$content_json}',
        )

    def test_custom_webhook_template_plain_json_is_not_changed(self) -> None:
        template = '{"content":"plain json string"}'

        self.manager.apply_updates(
            updates=[("CUSTOM_WEBHOOK_BODY_TEMPLATE", template)],
            sensitive_keys=set(),
            mask_token="******",
        )

        self.assertEqual(
            self.env_path.read_text(encoding="utf-8"),
            f"CUSTOM_WEBHOOK_BODY_TEMPLATE={template}\n",
        )

    def test_non_template_settings_keep_dotenv_interpolation_semantics(self) -> None:
        self.env_path.write_text(
            "\n".join(
                [
                    "API_PORT=8000",
                    "WEBUI_PORT=${API_PORT}",
                    'CUSTOM_WEBHOOK_BODY_TEMPLATE={"content":$${content_json}}',
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        config_map = self.manager.read_config_map()

        self.assertEqual(config_map["API_PORT"], "8000")
        self.assertEqual(config_map["WEBUI_PORT"], "8000")
        self.assertEqual(
            config_map["CUSTOM_WEBHOOK_BODY_TEMPLATE"],
            '{"content":${content_json}}',
        )

        self.manager.apply_updates(
            updates=[("WEBUI_PORT", config_map["WEBUI_PORT"])],
            sensitive_keys=set(),
            mask_token="******",
        )

        self.assertIn(
            "WEBUI_PORT=${API_PORT}\n",
            self.env_path.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
