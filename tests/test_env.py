import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.env import load_local_env


class LocalEnvTest(unittest.TestCase):
    def test_load_local_env_reads_simple_key_values_without_overwriting_existing_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "LOCAL_ONLY=value",
                        "EXISTING=from_file",
                        "# comment",
                        "QUOTED='hello'",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"EXISTING": "from_shell"}, clear=False):
                load_local_env(env_path)

                self.assertEqual(os.environ["LOCAL_ONLY"], "value")
                self.assertEqual(os.environ["EXISTING"], "from_shell")
                self.assertEqual(os.environ["QUOTED"], "hello")


if __name__ == "__main__":
    unittest.main()
