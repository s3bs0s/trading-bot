import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from src.paper_service import PaperServiceConfig, apply_cli_overrides, load_config


class PaperServiceConfigTest(unittest.TestCase):
    def test_default_config_uses_recommended_two_hour_paper_preset(self):
        config = PaperServiceConfig()

        self.assertEqual(config.preset, "aggressive-eth-2h")

    def test_load_config_merges_file_values_with_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "paper.json"
            config_path.write_text(
                json.dumps({"preset": "stable-sol-4h", "sleep_seconds": 120}),
                encoding="utf-8",
            )

            config = load_config(config_path)

        self.assertEqual(config.preset, "stable-sol-4h")
        self.assertEqual(config.sleep_seconds, 120)
        self.assertEqual(config.initial_cash, 1000.0)

    def test_load_config_rejects_unknown_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "paper.json"
            config_path.write_text(json.dumps({"surprise": True}), encoding="utf-8")

            with self.assertRaises(ValueError):
                load_config(config_path)

    def test_cli_overrides_only_present_values(self):
        config = PaperServiceConfig(preset="aggressive-eth-2h", sleep_seconds=300)
        args = Namespace(preset="stable-sol-4h", sleep_seconds=None)

        updated = apply_cli_overrides(config, args)

        self.assertEqual(updated.preset, "stable-sol-4h")
        self.assertEqual(updated.sleep_seconds, 300)


if __name__ == "__main__":
    unittest.main()
