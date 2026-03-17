from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from shorts.config import load_config


class TestConfig(unittest.TestCase):
    def test_env_overrides_apply(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {
                "APP__DEFAULT_LANGUAGE": "en",
                "RENDER__SUBTITLE_FONT_SIZE": "99",
                "OPENAI_API_KEY": "abc123",
            },
            clear=False,
        ):
            config = load_config("ENV")
        self.assertEqual(config.app.default_language, "en")
        self.assertEqual(config.render.subtitle_font_size, 99)
        self.assertEqual(config.content.openai_api_key, "abc123")

    def test_unknown_key_in_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.json"
            path.write_text(json.dumps({"app": {"bogus": 1}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown config key"):
                load_config(str(path))

    def test_nested_file_overrides_apply(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "app": {"output_dir": "custom-output"},
                        "tts": {"provider": "gtts"},
                        "youtube": {"privacy_status": "unlisted"},
                    }
                ),
                encoding="utf-8",
            )
            config = load_config(str(path))
        self.assertEqual(config.app.output_dir, "custom-output")
        self.assertEqual(config.tts.provider, "gtts")
        self.assertEqual(config.youtube.privacy_status, "unlisted")
