import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.paper_service import PaperServiceConfig
from src.render_app import apply_env_overrides, local_time_text, parse_preset_names, state_backup_payload


class RenderAppTest(unittest.TestCase):
    def test_local_time_text_shows_colombia_time(self):
        self.assertEqual(local_time_text("2026-05-08 14:00:00 UTC"), "2026-05-08 09:00:00 AM Colombia")

    def test_apply_env_overrides_updates_public_paper_settings(self):
        config = PaperServiceConfig()
        env = {
            "PAPER_PRESET": "stable-sol-4h",
            "PAPER_INITIAL_CASH": "250",
            "PAPER_SLEEP_SECONDS": "120",
        }

        with patch.dict(os.environ, env, clear=False):
            updated = apply_env_overrides(config)

        self.assertEqual(updated.preset, "stable-sol-4h")
        self.assertEqual(updated.initial_cash, 250.0)
        self.assertEqual(updated.sleep_seconds, 120)

    def test_parse_preset_names_defaults_to_base_and_active_reports(self):
        self.assertEqual(
            parse_preset_names(None),
            ["aggressive-eth-2h", "active-eth-1h", "aggressive-eth-30m", "growth-eth-4h", "stable-sol-4h"],
        )

    def test_parse_preset_names_accepts_comma_separated_list(self):
        names = parse_preset_names("stable-sol-4h, experimental-eth-1m")

        self.assertEqual(names, ["stable-sol-4h", "experimental-eth-1m"])

    def test_state_backup_payload_includes_local_state_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / "paper_state"
            state_dir.mkdir()
            (state_dir / "paper_test.json").write_text('{"preset":"test","cash":1000}', encoding="utf-8")

            current_dir = os.getcwd()
            os.chdir(temp_dir)
            try:
                payload = state_backup_payload()
            finally:
                os.chdir(current_dir)

        self.assertIn("paper_test.json", payload["states"])
        self.assertEqual(payload["states"]["paper_test.json"]["cash"], 1000)


if __name__ == "__main__":
    unittest.main()
