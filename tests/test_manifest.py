"""Tests for src/manifest.py"""

import importlib
import json
import os
import tempfile
import unittest


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "manifest",
        os.path.join(os.path.dirname(__file__), "..", "src", "manifest.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load_module()


class TestAppendEntry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _manifest_path(self):
        return os.path.join(self.tmp, "manifest.json")

    def _read_manifest(self):
        with open(self._manifest_path()) as fh:
            return json.load(fh)

    def test_creates_manifest_on_first_call(self):
        mod.append_entry(self.tmp, "sprite", "a campfire", "openai", "sprite_campfire_1.png", _now=1000)
        self.assertTrue(os.path.exists(self._manifest_path()))

    def test_entry_fields_are_correct(self):
        mod.append_entry(self.tmp, "sfx", "sword swing", "elevenlabs", "sfx_sword_1.mp3", _now=9999)
        entries = self._read_manifest()
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["type"], "sfx")
        self.assertEqual(entry["prompt"], "sword swing")
        self.assertEqual(entry["backend"], "elevenlabs")
        self.assertEqual(entry["file"], "sfx_sword_1.mp3")
        self.assertEqual(entry["timestamp"], 9999)

    def test_appends_multiple_entries(self):
        mod.append_entry(self.tmp, "sprite", "fire", "openai", "sprite_fire_1.png", _now=1)
        mod.append_entry(self.tmp, "sfx", "fire crackle", "local", "sfx_fire_1.wav", _now=2)
        mod.append_entry(self.tmp, "music", "epic theme", "replicate", "music_epic_1.mp3", _now=3)
        entries = self._read_manifest()
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]["type"], "sprite")
        self.assertEqual(entries[1]["type"], "sfx")
        self.assertEqual(entries[2]["type"], "music")

    def test_recovers_from_corrupt_manifest(self):
        with open(self._manifest_path(), "w") as fh:
            fh.write("not valid json{{")
        mod.append_entry(self.tmp, "sprite", "test", "local", "sprite_test_1.png", _now=1)
        entries = self._read_manifest()
        self.assertEqual(len(entries), 1)

    def test_recovers_from_non_array_manifest(self):
        with open(self._manifest_path(), "w") as fh:
            json.dump({"unexpected": "object"}, fh)
        mod.append_entry(self.tmp, "sprite", "test", "local", "sprite_test_1.png", _now=1)
        entries = self._read_manifest()
        self.assertEqual(len(entries), 1)

    def test_creates_output_dir_if_missing(self):
        nested = os.path.join(self.tmp, "a", "b", "c")
        mod.append_entry(nested, "music", "calm", "local", "music_calm_1.wav", _now=1)
        self.assertTrue(os.path.exists(os.path.join(nested, "manifest.json")))

    def test_timestamp_defaults_to_current_time(self):
        import time
        before = int(time.time())
        mod.append_entry(self.tmp, "sprite", "grass tile", "openai", "sprite_grass_1.png")
        after = int(time.time())
        entries = self._read_manifest()
        self.assertGreaterEqual(entries[0]["timestamp"], before)
        self.assertLessEqual(entries[0]["timestamp"], after)


class TestCLIEntryPoint(unittest.TestCase):
    def test_main_writes_entry(self):
        import subprocess
        import sys
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    sys.executable,
                    os.path.join(os.path.dirname(__file__), "..", "src", "manifest.py"),
                    tmpdir,
                    "sprite",
                    "pixel campfire",
                    "openai",
                    "sprite_campfire_42.png",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            with open(os.path.join(tmpdir, "manifest.json")) as fh:
                entries = json.load(fh)
            self.assertEqual(entries[0]["file"], "sprite_campfire_42.png")

    def test_main_exits_nonzero_on_wrong_arg_count(self):
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(__file__), "..", "src", "manifest.py")],
            capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
