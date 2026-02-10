import json
import unittest

import run_short


class TestSummaryLine(unittest.TestCase):
    def test_env_truthy(self) -> None:
        import os

        old = os.environ.get("NO_UPLOAD")
        try:
            os.environ.pop("NO_UPLOAD", None)
            self.assertFalse(run_short._env_truthy("NO_UPLOAD"))
            os.environ["NO_UPLOAD"] = "1"
            self.assertTrue(run_short._env_truthy("NO_UPLOAD"))
            os.environ["NO_UPLOAD"] = "true"
            self.assertTrue(run_short._env_truthy("NO_UPLOAD"))
            os.environ["NO_UPLOAD"] = "0"
            self.assertFalse(run_short._env_truthy("NO_UPLOAD"))
        finally:
            if old is None:
                os.environ.pop("NO_UPLOAD", None)
            else:
                os.environ["NO_UPLOAD"] = old

    def test_one_line_collapses_whitespace(self) -> None:
        s = "a\nb\tc  d"
        out = run_short._one_line(s)
        self.assertEqual(out, "a b c d")
        self.assertNotIn("\n", out)

    def test_summary_line_is_single_line_json(self) -> None:
        line = run_short._summary_line({"status": "ok", "elapsed_s": 1.234, "video": "output/x.mp4"})
        self.assertTrue(line.startswith("SUMMARY "))
        self.assertNotIn("\n", line)
        payload = line[len("SUMMARY ") :]
        obj = json.loads(payload)
        self.assertEqual(obj["status"], "ok")

    def test_result_line_includes_video_id_when_present(self) -> None:
        line = run_short.format_result_line(
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


if __name__ == "__main__":
    unittest.main()
