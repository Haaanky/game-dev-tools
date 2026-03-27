"""Tests for local_audio_server.py"""

import importlib
import io
import json
import sys
import unittest
from unittest.mock import MagicMock, patch


def _load_module():
    """Import the audio server module with ML packages stubbed out."""
    stubs = {
        "torch": MagicMock(),
        "audiocraft": MagicMock(),
        "audiocraft.models": MagicMock(),
        "numpy": MagicMock(),
    }
    with patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location(
            "local_audio_server",
            "src/servers/local_audio_server.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


mod = _load_module()


class TestEnsurePackages(unittest.TestCase):
    def test_no_install_when_all_present(self):
        with patch("importlib.util.find_spec", return_value=MagicMock()):
            with patch("subprocess.check_call") as mock_call:
                mod._ensure_packages()
                mock_call.assert_not_called()


class TestAudioHandlerInputValidation(unittest.TestCase):
    """Verify that duration and text inputs are clamped/truncated."""

    def _make_request(self, path: str, body: dict) -> dict:
        raw = json.dumps(body).encode()

        handler = mod.AudioHandler.__new__(mod.AudioHandler)
        handler.headers = {"Content-Length": str(len(raw))}
        handler.rfile = io.BytesIO(raw)
        handler.wfile = io.BytesIO()
        handler.path = path
        handler.server = MagicMock()

        captured = {}

        def fake_generate(text, duration):
            captured.update(text=text, duration=duration)
            return b"RIFF" + b"\x00" * 36  # minimal WAV header stub

        with patch.object(mod, "_generate_audio", side_effect=fake_generate):
            with patch.object(handler, "send_response"):
                with patch.object(handler, "send_header"):
                    with patch.object(handler, "end_headers"):
                        handler.do_POST()

        return captured

    def test_duration_clamped_to_max(self):
        result = self._make_request("/generate/sfx", {"text": "boom", "duration": 9999})
        self.assertLessEqual(result["duration"], mod.MAX_DURATION)

    def test_duration_clamped_to_min(self):
        result = self._make_request("/generate/sfx", {"text": "boom", "duration": -5})
        self.assertGreaterEqual(result["duration"], 0.5)

    def test_text_truncated(self):
        result = self._make_request("/generate/sfx", {"text": "a" * 1000})
        self.assertLessEqual(len(result["text"]), 500)

    def test_sfx_default_duration(self):
        result = self._make_request("/generate/sfx", {})
        self.assertEqual(result["duration"], mod.DEFAULT_SFX_DURATION)

    def test_music_default_duration(self):
        result = self._make_request("/generate/music", {})
        self.assertEqual(result["duration"], mod.DEFAULT_MUSIC_DURATION)


class TestLoadModelThreadSafety(unittest.TestCase):
    def test_model_loaded_only_once(self):
        mod._model = None

        fake_model = MagicMock()
        mock_musicgen = MagicMock()
        mock_musicgen.MusicGen.get_pretrained.return_value = fake_model

        with patch.dict(sys.modules, {"audiocraft.models": mock_musicgen}):
            result1 = mod._load_model()
            result2 = mod._load_model()

        self.assertIs(result1, result2)
        self.assertEqual(mock_musicgen.MusicGen.get_pretrained.call_count, 1)

        mod._model = None  # reset


if __name__ == "__main__":
    unittest.main()
