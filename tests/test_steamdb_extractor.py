"""Tests for steamdb_extractor.py"""

import importlib.util
import json
import sys
import unittest
from unittest.mock import MagicMock, patch


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "steamdb_extractor",
        "src/steamdb_extractor.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load_module()


class TestBuildRecords(unittest.TestCase):
    """build_records transforms raw Steam API game dicts into clean records."""

    RAW_GAMES = [
        {
            "appid": 570,
            "name": "Dota 2",
            "playtime_forever": 6000,
            "img_icon_url": "abc123",
        },
        {
            "appid": 730,
            "name": "Counter-Strike 2",
            "playtime_forever": 1200,
            "img_icon_url": "def456",
        },
        {
            "appid": 400,
            "name": "Portal",
            "playtime_forever": 0,
        },
    ]

    def test_hours_calculated_correctly(self):
        records = mod.build_records(self.RAW_GAMES, "eu", fetch_prices=False)
        by_id = {r["appid"]: r for r in records}
        self.assertAlmostEqual(by_id[570]["hours_played"], 100.0)
        self.assertAlmostEqual(by_id[730]["hours_played"], 20.0)
        self.assertAlmostEqual(by_id[400]["hours_played"], 0.0)

    def test_icon_url_constructed(self):
        records = mod.build_records(self.RAW_GAMES, "eu", fetch_prices=False)
        by_id = {r["appid"]: r for r in records}
        self.assertIn("570", by_id[570]["img_icon_url"])
        self.assertIn("abc123", by_id[570]["img_icon_url"])

    def test_missing_icon_url_becomes_empty_string(self):
        records = mod.build_records(self.RAW_GAMES, "eu", fetch_prices=False)
        by_id = {r["appid"]: r for r in records}
        self.assertEqual(by_id[400]["img_icon_url"], "")

    def test_no_price_fields_when_not_requested(self):
        records = mod.build_records(self.RAW_GAMES, "eu", fetch_prices=False)
        for record in records:
            self.assertNotIn("price_final", record)

    def test_price_fields_present_when_requested(self):
        price_data = {
            "success": True,
            "data": {
                "price_overview": {
                    "initial": 999,
                    "final": 499,
                    "discount_percent": 50,
                    "currency": "EUR",
                }
            },
        }
        fake_response = {str(appid): price_data for appid in [570, 730, 400]}

        def fake_get(url, params):
            appid = params["appids"]
            return {str(appid): price_data}

        with patch.object(mod, "_get", side_effect=fake_get):
            with patch("time.sleep"):
                records = mod.build_records(self.RAW_GAMES, "eu", fetch_prices=True)

        for record in records:
            self.assertIn("price_final", record)
            self.assertIn("currency", record)

    def test_price_converted_from_cents(self):
        price_data = {
            "success": True,
            "data": {
                "price_overview": {
                    "initial": 1999,
                    "final": 1999,
                    "discount_percent": 0,
                    "currency": "EUR",
                }
            },
        }

        def fake_get(url, params):
            appid = params["appids"]
            return {str(appid): price_data}

        with patch.object(mod, "_get", side_effect=fake_get):
            with patch("time.sleep"):
                records = mod.build_records(self.RAW_GAMES[:1], "eu", fetch_prices=True)

        self.assertAlmostEqual(records[0]["price_final"], 19.99)

    def test_price_none_when_api_returns_no_data(self):
        def fake_get(url, params):
            return {str(params["appids"]): {"success": False}}

        with patch.object(mod, "_get", side_effect=fake_get):
            with patch("time.sleep"):
                records = mod.build_records(self.RAW_GAMES[:1], "eu", fetch_prices=True)

        self.assertIsNone(records[0]["price_final"])


class TestFetchOwnedGames(unittest.TestCase):
    def test_returns_game_list(self):
        fake_response = {
            "response": {
                "game_count": 2,
                "games": [
                    {"appid": 570, "name": "Dota 2", "playtime_forever": 100},
                    {"appid": 730, "name": "CS2", "playtime_forever": 50},
                ],
            }
        }
        with patch.object(mod, "_get", return_value=fake_response):
            games = mod.fetch_owned_games("76561198015238798", "fake_key")
        self.assertEqual(len(games), 2)
        self.assertEqual(games[0]["appid"], 570)

    def test_raises_on_empty_response(self):
        with patch.object(mod, "_get", return_value={"response": {}}):
            with self.assertRaises(SystemExit):
                mod.fetch_owned_games("76561198015238798", "fake_key")


class TestWriteCsv(unittest.TestCase):
    def test_csv_written_correctly(self):
        import csv
        import io
        from unittest.mock import mock_open, call

        records = [
            {"appid": 570, "name": "Dota 2", "hours_played": 100.0},
            {"appid": 730, "name": "CS2", "hours_played": 20.0},
        ]

        buf = io.StringIO()
        # Use a non-closing wrapper so the StringIO stays open after `with`
        m = MagicMock()
        m.__enter__ = MagicMock(return_value=buf)
        m.__exit__ = MagicMock(return_value=False)

        with patch("builtins.open", return_value=m):
            mod.write_csv(records, "out.csv")

        buf.seek(0)
        reader = csv.DictReader(buf)
        rows = list(reader)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["name"], "Dota 2")


if __name__ == "__main__":
    unittest.main()
