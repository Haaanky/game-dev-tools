"""Tests for psn_extractor.py"""

import importlib.util
import unittest
from unittest.mock import MagicMock, patch


def _load_module():
    import sys
    spec = importlib.util.spec_from_file_location(
        "psn_extractor",
        "src/psn_extractor.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["psn_extractor"] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load_module()


# ---------------------------------------------------------------------------
# build_records
# ---------------------------------------------------------------------------

class TestBuildRecords(unittest.TestCase):
    RAW_TITLES = [
        {
            "npCommunicationId": "NPWR12345_00",
            "trophyTitleName": "God of War",
            "trophyTitlePlatform": "PS5",
            "hasTrophyGroups": False,
            "earnedTrophies": {"bronze": 20, "silver": 8, "gold": 3, "platinum": 1},
            "definedTrophies": {"bronze": 20, "silver": 8, "gold": 3, "platinum": 1},
            "lastUpdatedDateTime": "2024-01-15T10:30:00Z",
        },
        {
            "npCommunicationId": "NPWR99999_00",
            "trophyTitleName": "Astro's Playroom",
            "trophyTitlePlatform": "PS5",
            "hasTrophyGroups": True,
            "earnedTrophies": {"bronze": 10, "silver": 4, "gold": 1, "platinum": 0},
            "definedTrophies": {"bronze": 20, "silver": 8, "gold": 3, "platinum": 1},
            "lastUpdatedDateTime": "2023-11-01T08:00:00Z",
        },
    ]

    def test_returns_one_record_per_title(self):
        records = mod.build_records(self.RAW_TITLES)
        self.assertEqual(len(records), 2)

    def test_full_completion_is_100(self):
        records = mod.build_records(self.RAW_TITLES)
        by_id = {r["np_communication_id"]: r for r in records}
        self.assertEqual(by_id["NPWR12345_00"]["completion_percent"], 100.0)

    def test_partial_completion_calculated_correctly(self):
        # earned: 10+4+1+0=15, defined: 20+8+3+1=32 → 15/32 * 100 = 46.9
        records = mod.build_records(self.RAW_TITLES)
        by_id = {r["np_communication_id"]: r for r in records}
        expected = round(15 / 32 * 100, 1)
        self.assertAlmostEqual(by_id["NPWR99999_00"]["completion_percent"], expected)

    def test_fields_mapped_correctly(self):
        records = mod.build_records(self.RAW_TITLES[:1])
        r = records[0]
        self.assertEqual(r["name"], "God of War")
        self.assertEqual(r["platform"], "PS5")
        self.assertEqual(r["trophies_earned_platinum"], 1)
        self.assertEqual(r["trophies_defined_bronze"], 20)
        self.assertEqual(r["last_updated"], "2024-01-15T10:30:00Z")

    def test_zero_defined_trophies_yields_zero_completion(self):
        title = {
            "npCommunicationId": "NPWR00000_00",
            "trophyTitleName": "Empty",
            "trophyTitlePlatform": "PS4",
            "hasTrophyGroups": False,
            "earnedTrophies": {"bronze": 0, "silver": 0, "gold": 0, "platinum": 0},
            "definedTrophies": {"bronze": 0, "silver": 0, "gold": 0, "platinum": 0},
            "lastUpdatedDateTime": "",
        }
        records = mod.build_records([title])
        self.assertEqual(records[0]["completion_percent"], 0.0)

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(mod.build_records([]), [])


# ---------------------------------------------------------------------------
# fetch_trophy_titles (pagination)
# ---------------------------------------------------------------------------

class TestFetchTrophyTitlesPagination(unittest.TestCase):
    def _make_page(self, titles, total):
        return {"trophyTitles": titles, "totalItemCount": total}

    def test_single_page_returned(self):
        page = self._make_page([{"npCommunicationId": "A"}], total=1)
        with patch.object(mod, "_get", return_value=page):
            result = mod.fetch_trophy_titles("me", "tok", limit=None)
        self.assertEqual(len(result), 1)

    def test_multi_page_fetched_until_total(self):
        titles_p1 = [{"npCommunicationId": f"T{i}"} for i in range(100)]
        titles_p2 = [{"npCommunicationId": "T100"}]

        pages = [
            {"trophyTitles": titles_p1, "totalItemCount": 101},
            {"trophyTitles": titles_p2, "totalItemCount": 101},
        ]
        call_count = {"n": 0}

        def fake_get(url, headers, params):
            idx = call_count["n"]
            call_count["n"] += 1
            return pages[idx]

        with patch.object(mod, "_get", side_effect=fake_get):
            result = mod.fetch_trophy_titles("me", "tok", limit=None)

        self.assertEqual(len(result), 101)

    def test_limit_respected(self):
        titles = [{"npCommunicationId": f"T{i}"} for i in range(100)]
        page = {"trophyTitles": titles, "totalItemCount": 500}
        with patch.object(mod, "_get", return_value=page):
            result = mod.fetch_trophy_titles("me", "tok", limit=50)
        self.assertEqual(len(result), 50)


# ---------------------------------------------------------------------------
# exchange_npsso_for_code
# ---------------------------------------------------------------------------

class TestExchangeNpssoForCode(unittest.TestCase):
    def test_extracts_code_from_redirect_url(self):
        from urllib.error import HTTPError
        import io

        fake_exc = HTTPError(
            url="https://example.com",
            code=302,
            msg="Found",
            hdrs={"Location": "com.playstation.PlayStationApp://redirect?code=ABC123&state=x"},  # type: ignore[arg-type]
            fp=io.BytesIO(b""),
        )
        with patch("psn_extractor.urlopen", side_effect=fake_exc):
            code = mod.exchange_npsso_for_code("my_npsso_token")
        self.assertEqual(code, "ABC123")

    def test_raises_on_missing_code_param(self):
        from urllib.error import HTTPError
        import io

        fake_exc = HTTPError(
            url="https://example.com",
            code=302,
            msg="Found",
            hdrs={"Location": "com.playstation.PlayStationApp://redirect?state=x"},  # type: ignore[arg-type]
            fp=io.BytesIO(b""),
        )
        with patch("psn_extractor.urlopen", side_effect=fake_exc):
            with self.assertRaises(SystemExit):
                mod.exchange_npsso_for_code("bad_npsso")


# ---------------------------------------------------------------------------
# write_csv
# ---------------------------------------------------------------------------

class TestWriteCsv(unittest.TestCase):
    def test_csv_rows_written(self):
        import io

        records = [
            {"name": "God of War", "platform": "PS5", "completion_percent": 100.0},
            {"name": "Astro's Playroom", "platform": "PS5", "completion_percent": 46.9},
        ]

        buf = io.StringIO()
        m = MagicMock()
        m.__enter__ = MagicMock(return_value=buf)
        m.__exit__ = MagicMock(return_value=False)

        with patch("builtins.open", return_value=m):
            mod.write_csv(records, "out.csv")

        import csv
        buf.seek(0)
        rows = list(csv.DictReader(buf))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["name"], "God of War")

    def test_empty_records_no_file_written(self):
        with patch("builtins.open") as mock_open:
            mod.write_csv([], "out.csv")
            mock_open.assert_not_called()


if __name__ == "__main__":
    unittest.main()
