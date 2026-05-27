import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.paper_service import PaperServiceConfig
from src.render_app import (
    active_preset_names,
    apply_env_overrides,
    count_trades_closed_on,
    dashboard_summary,
    local_time_text,
    parse_paused_preset_names,
    parse_preset_names,
    report_from_saved_state,
    state_backup_payload,
)


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
            [
                "rsi-eth-2h",
                "rsi-sol-4h",
                "resilient-eth-6h",
                "aggressive-eth-30m",
                "growth-eth-4h",
                "balanced-btc-4h",
                "stable-sol-4h",
            ],
        )

    def test_parse_preset_names_accepts_comma_separated_list(self):
        names = parse_preset_names("stable-sol-4h, experimental-eth-1m")

        self.assertEqual(names, ["stable-sol-4h", "experimental-eth-1m"])

    def test_paused_presets_default_to_recent_underperformers(self):
        self.assertEqual(
            parse_paused_preset_names(None),
            ["aggressive-eth-2h", "active-eth-1h", "aggressive-eth-30m", "balanced-btc-4h", "rsi-sol-1h"],
        )

    def test_active_preset_names_filters_paused_render_presets(self):
        env = {
            "PAPER_PRESETS": "rsi-eth-2h,aggressive-eth-2h,active-eth-1h,stable-sol-4h",
        }

        with patch.dict(os.environ, env, clear=False):
            self.assertEqual(
                active_preset_names(),
                ["rsi-eth-2h", "rsi-sol-4h", "resilient-eth-6h", "growth-eth-4h", "stable-sol-4h"],
            )

    def test_active_preset_names_can_use_strict_render_override(self):
        env = {
            "PAPER_PRESETS": "rsi-eth-2h,stable-sol-4h",
            "PAPER_STRICT_PRESETS": "true",
        }

        with patch.dict(os.environ, env, clear=False):
            self.assertEqual(active_preset_names(), ["rsi-eth-2h", "stable-sol-4h"])

    def test_count_trades_closed_on_uses_colombia_day(self):
        trades = [
            {"exit_time": "2026-05-10 04:30"},
            {"exit_time": "2026-05-10 05:30"},
        ]

        self.assertEqual(count_trades_closed_on(trades, "2026-05-09"), 1)
        self.assertEqual(count_trades_closed_on(trades, "2026-05-10"), 1)

    def test_dashboard_summary_finds_best_worst_and_totals(self):
        status = {
            "last_check_at": "2026-05-10 12:00:00 UTC",
            "reports": {
                "a": {
                    "preset": "a",
                    "initial_cash": 1000.0,
                    "equity": 1010.0,
                    "trades": 2,
                    "trades_today": 1,
                    "open_position": True,
                    "last_action": "BUY - test",
                    "last_success_at": "2026-05-10 12:00:00 UTC",
                },
                "b": {
                    "preset": "b",
                    "initial_cash": 1000.0,
                    "equity": 990.0,
                    "trades": 1,
                    "trades_today": 0,
                    "open_position": False,
                    "last_action": "HOLD",
                    "last_success_at": "2026-05-10 11:00:00 UTC",
                },
            },
        }

        summary = dashboard_summary(status)

        self.assertEqual(summary["total_equity"], 2000.0)
        self.assertEqual(summary["best_preset"], "a")
        self.assertEqual(summary["worst_preset"], "b")
        self.assertEqual(summary["trades_today"], 1)
        self.assertEqual(summary["closed_trades"], 3)
        self.assertEqual(summary["open_positions"], 1)
        self.assertIn("BUY", summary["last_alert"])

    def test_report_from_saved_state_preserves_paused_loss(self):
        state = {
            "preset": "balanced-btc-4h",
            "symbol": "BTCUSDT",
            "interval": "4h",
            "initial_cash": 1000.0,
            "cash": 991.65,
            "position_qty": 0.0,
            "updated_at": "2026-05-18 15:00:00 UTC",
            "last_action": "SELL - stop loss hit",
            "trades": [{"exit_time": "2026-05-18 14:00", "pnl": -8.35}],
            "equity_curve": [{"equity": 991.65}],
        }

        report = report_from_saved_state(state)

        self.assertEqual(report["preset"], "balanced-btc-4h")
        self.assertEqual(report["equity"], 991.65)
        self.assertEqual(report["realized_pnl"], -8.35)
        self.assertIn("PAUSADA", report["last_action"])

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
