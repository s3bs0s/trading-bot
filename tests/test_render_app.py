import os
import unittest
from unittest.mock import patch

from src.paper_service import PaperServiceConfig
from src.render_app import apply_env_overrides


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


if __name__ == "__main__":
    unittest.main()
