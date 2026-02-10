import json
import tempfile
import unittest
from pathlib import Path

import run_short


class TestUploadIdempotency(unittest.TestCase):
    def test_lookup_returns_last_record_for_job_key(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "uploads.jsonl"
            key = "/abs/path/to/job.json"

            p.write_text(
                "\n".join(
                    [
                        '{"job_key": "/other", "video_id": "x"}',
                        "not json",
                        json.dumps({"job_key": key, "video_id": "old", "upload_url": "https://youtu.be/old"}),
                        json.dumps({"job_key": key, "video_id": "new", "upload_url": "https://youtu.be/new"}),
                        "",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            rec = run_short._lookup_uploaded_record(p, key)
            self.assertIsNotNone(rec)
            assert rec is not None
            self.assertEqual(rec["video_id"], "new")
            self.assertEqual(rec["upload_url"], "https://youtu.be/new")

    def test_append_jsonl_writes_single_line_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "uploads.jsonl"
            run_short._append_jsonl(p, {"job_key": "k", "video_id": "v"})
            txt = p.read_text(encoding="utf-8")
            lines = [ln for ln in txt.splitlines() if ln.strip()]
            self.assertEqual(len(lines), 1)
            obj = json.loads(lines[0])
            self.assertEqual(obj["job_key"], "k")
            self.assertEqual(obj["video_id"], "v")


if __name__ == "__main__":
    unittest.main()

