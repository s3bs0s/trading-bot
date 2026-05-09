import unittest

from src.state_store import build_equity_record, build_trade_record, parse_market_time, trade_id_for


class StateStoreTest(unittest.TestCase):
    def test_parse_market_time_treats_naive_market_time_as_utc(self):
        parsed = parse_market_time("2026-05-09 17:00")

        self.assertEqual(parsed.isoformat(), "2026-05-09T17:00:00+00:00")

    def test_trade_id_is_stable_for_same_trade(self):
        state = {"preset": "active-eth-1h", "symbol": "ETHUSDT", "interval": "1h"}
        trade = {
            "entry_time": "2026-05-09 17:00",
            "exit_time": "2026-05-09 18:00",
            "entry_price": 2300.0,
            "exit_price": 2320.0,
            "quantity": 0.1,
        }

        self.assertEqual(trade_id_for(state, trade), trade_id_for(state, trade))

    def test_trade_record_contains_analysis_columns(self):
        state = {"preset": "active-eth-1h", "symbol": "ETHUSDT", "interval": "1h"}
        trade = {
            "entry_time": "2026-05-09 17:00",
            "exit_time": "2026-05-09 18:00",
            "entry_price": 2300.0,
            "exit_price": 2320.0,
            "quantity": 0.1,
            "entry_reason": "buy reason",
            "exit_reason": "sell reason",
            "pnl": 1.5,
            "return_pct": 0.015,
        }

        record = build_trade_record(state, trade)

        self.assertEqual(record[1], "active-eth-1h")
        self.assertEqual(record[8], 2300.0)
        self.assertEqual(record[13], 1.5)

    def test_equity_record_contains_candle_and_capital_data(self):
        state = {"preset": "stable-sol-4h", "symbol": "SOLUSDT", "interval": "4h"}
        point = {
            "date": "2026-05-09 16:00",
            "close": 92.5,
            "equity": 1010.0,
            "cash": 700.0,
            "position_value": 310.0,
            "drawdown_pct": 0.01,
        }

        record = build_equity_record(state, point)

        self.assertEqual(record[0], "stable-sol-4h")
        self.assertEqual(record[5], 92.5)
        self.assertEqual(record[6], 1010.0)


if __name__ == "__main__":
    unittest.main()
