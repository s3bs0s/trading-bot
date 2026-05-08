import os
import unittest
from unittest.mock import patch

from src.paper_service import PaperServiceConfig
from src.render_app import apply_env_overrides, parse_preset_names


class RenderAppTest(unittest.TestCase):
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
            ["aggressive-eth-2h", "active-eth-1h", "aggressive-eth-30m", "stable-sol-4h"],
        )

    def test_parse_preset_names_accepts_comma_separated_list(self):
        names = parse_preset_names("stable-sol-4h, experimental-eth-1m")

        self.assertEqual(names, ["stable-sol-4h", "experimental-eth-1m"])


if __name__ == "__main__":
    unittest.main()
