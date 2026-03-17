from __future__ import annotations

import json
import os
import unittest

from shorts.output import _env_truthy, _one_line, _summary_line, format_result_line


class TestOutput(unittest.TestCase):
    def test_env_truthy(self) -> None:
        old = os.environ.get("NO_UPLOAD")
        try:
            os.environ.pop("NO_UPLOAD", None)
            self.assertFalse(_env_truthy("NO_UPLOAD"))
            os.environ["NO_UPLOAD"] = "1"
            self.assertTrue(_env_truthy("NO_UPLOAD"))
            os.environ["NO_UPLOAD"] = "true"
            self.assertTrue(_env_truthy("NO_UPLOAD"))
            os.environ["NO_UPLOAD"] = "0"
            self.assertFalse(_env_truthy("NO_UPLOAD"))
        finally:
            if old is None:
                os.environ.pop("NO_UPLOAD", None)
            else:
                os.environ["NO_UPLOAD"] = old

    def test_one_line_collapses_whitespace(self) -> None:
        self.assertEqual(_one_line("a\nb\tc  d"), "a b c d")

    def test_summary_line_is_single_line_json(self) -> None:
        line = _summary_line({"status": "ok", "elapsed_s": 1.234, "video": "output/x.mp4"})
        self.assertTrue(line.startswith("SUMMARY "))
        self.assertNotIn("\n", line)
        payload = json.loads(line[len("SUMMARY ") :])
        self.assertEqual(payload["status"], "ok")

    def test_result_line_includes_video_id_when_present(self) -> None:
        line = format_result_line(
            status="ok",
            elapsed_s=1.234,
            video=None,
            video_id="abc123",
            upload_url="https://youtu.be/abc123",
            no_upload=False,
        )
        self.assertIn("RESULT ", line)
        self.assertIn("status=ok", line)
        self.assertIn("video_id=abc123", line)
        self.assertIn("upload=https://youtu.be/abc123", line)
