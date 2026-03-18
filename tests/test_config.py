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
                "APP__WORK_DIR": "jobs/custom-work",
                "RENDER__SUBTITLE_FONT_SIZE": "99",
                "CONTENT__SERIES_CONSTRAINTS": "[\"짧게 쓴다\", \"첫 문장은 훅\"]",
                "OPENAI_API_KEY": "abc123",
            },
            clear=False,
        ):
            config = load_config("ENV")
        self.assertEqual(config.app.work_dir, "jobs/custom-work")
        self.assertEqual(config.render.subtitle_font_size, 99)
        self.assertEqual(config.content.series_constraints, ["짧게 쓴다", "첫 문장은 훅"])
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
                        "app": {"work_dir": "jobs/custom-work"},
                        "content": {"series_name": "새 시리즈", "topic_pool_size": 12},
                        "youtube": {"privacy_status": "unlisted"},
                    }
                ),
                encoding="utf-8",
            )
            config = load_config(str(path))
        self.assertEqual(config.app.work_dir, "jobs/custom-work")
        self.assertEqual(config.content.series_name, "새 시리즈")
        self.assertEqual(config.content.topic_pool_size, 12)
        self.assertEqual(config.youtube.privacy_status, "unlisted")
