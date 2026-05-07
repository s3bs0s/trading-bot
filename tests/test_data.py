import json
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from src.data import fetch_binance_klines


class FakeResponse:
    def __init__(self, payload: list[list]):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class MarketDataTest(unittest.TestCase):
    def test_fetch_binance_klines_falls_back_when_primary_endpoint_is_blocked(self):
        row = [
            1704067200000,
            "100.0",
            "110.0",
            "90.0",
            "105.0",
            "123.0",
            1704070799999,
            "0",
            0,
            "0",
            "0",
            "0",
        ]
        blocked = HTTPError("https://api.binance.com", 451, "Unavailable", {}, None)

        with patch("src.data.urlopen", side_effect=[blocked, FakeResponse([row])]) as urlopen_mock:
            candles = fetch_binance_klines(symbol="ETHUSDT", interval="2h", limit=1)

        self.assertEqual(len(candles), 1)
        self.assertEqual(candles[0].close, 105.0)
        self.assertIn("api.binance.com", urlopen_mock.call_args_list[0].args[0])
        self.assertIn("api.binance.us", urlopen_mock.call_args_list[1].args[0])


if __name__ == "__main__":
    unittest.main()
