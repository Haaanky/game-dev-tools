"""Tests for local_sprite_server.py"""

import base64
import importlib
import io
import json
import sys
import types
import unittest
from http.server import HTTPServer
from unittest.mock import MagicMock, patch


def _load_module():
    """Import the sprite server module with ML packages stubbed out."""
    stubs = {
        "torch": MagicMock(),
        "diffusers": MagicMock(),
        "transformers": MagicMock(),
        "accelerate": MagicMock(),
        "safetensors": MagicMock(),
    }
    with patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location(
            "local_sprite_server",
            "src/servers/local_sprite_server.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


mod = _load_module()


class TestEnsurePackages(unittest.TestCase):
    def test_no_install_when_all_present(self):
        """Should not call pip when all packages are already importable."""
        with patch("importlib.util.find_spec", return_value=MagicMock()):
            with patch("subprocess.check_call") as mock_call:
                mod._ensure_packages()
                mock_call.assert_not_called()


class TestSpriteHandlerInputValidation(unittest.TestCase):
    """Verify that out-of-range inputs are clamped before reaching _generate."""

    def _make_request(self, body: dict) -> tuple:
        """Send a fake POST and return (status_code, response_body)."""
        raw = json.dumps(body).encode()

        request = MagicMock()
        request.makefile.return_value = io.BytesIO(b"")

        handler = mod.SpriteHandler.__new__(mod.SpriteHandler)
        handler.headers = {"Content-Length": str(len(raw))}
        handler.rfile = io.BytesIO(raw)
        handler.wfile = io.BytesIO()
        handler.server = MagicMock()

        captured = {}

        def fake_generate(prompt, width, height, steps, cfg_scale):
            captured.update(
                prompt=prompt, width=width, height=height,
                steps=steps, cfg_scale=cfg_scale,
            )
            # Return a minimal valid base64 PNG (1×1 white pixel)
            return base64.b64encode(b"\x89PNG\r\n").decode()

        with patch.object(mod, "_generate", side_effect=fake_generate):
            with patch.object(handler, "send_response"):
                with patch.object(handler, "send_header"):
                    with patch.object(handler, "end_headers"):
                        handler.do_POST()

        return captured

    def test_clamps_oversized_dimensions(self):
        result = self._make_request({"prompt": "test", "width": 9999, "height": 9999})
        self.assertLessEqual(result["width"], 1024)
        self.assertLessEqual(result["height"], 1024)

    def test_clamps_undersized_dimensions(self):
        result = self._make_request({"prompt": "test", "width": 0, "height": 0})
        self.assertGreaterEqual(result["width"], 64)
        self.assertGreaterEqual(result["height"], 64)

    def test_clamps_steps(self):
        result = self._make_request({"prompt": "test", "steps": 9999})
        self.assertLessEqual(result["steps"], 150)

    def test_truncates_long_prompt(self):
        result = self._make_request({"prompt": "x" * 1000})
        self.assertLessEqual(len(result["prompt"]), 500)

    def test_default_values_used_when_fields_missing(self):
        result = self._make_request({})
        self.assertEqual(result["width"], 256)
        self.assertEqual(result["height"], 256)
        self.assertEqual(result["steps"], 10)


class TestLoadPipelineThreadSafety(unittest.TestCase):
    def test_pipeline_loaded_only_once(self):
        """_load_pipeline should initialise the pipeline exactly once."""
        mod._pipeline = None

        fake_pipe = MagicMock()
        fake_pipe.to.return_value = fake_pipe

        mock_torch = MagicMock()
        mock_diffusers = MagicMock()
        mock_diffusers.StableDiffusionPipeline.from_pretrained.return_value = fake_pipe

        with patch.dict(sys.modules, {"torch": mock_torch, "diffusers": mock_diffusers}):
            result1 = mod._load_pipeline()
            result2 = mod._load_pipeline()

        self.assertIs(result1, result2)
        self.assertEqual(
            mock_diffusers.StableDiffusionPipeline.from_pretrained.call_count, 1
        )

        mod._pipeline = None  # reset for other tests


if __name__ == "__main__":
    unittest.main()
