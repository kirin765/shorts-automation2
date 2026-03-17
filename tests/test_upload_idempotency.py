from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from shorts.upload import _append_jsonl, _lookup_uploaded_record


class TestUploadIdempotency(unittest.TestCase):
    def test_lookup_returns_last_record_for_job_key(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "uploads.jsonl"
            key = "/abs/path/to/job.json"
            path.write_text(
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
            rec = _lookup_uploaded_record(path, key)
            self.assertIsNotNone(rec)
            assert rec is not None
            self.assertEqual(rec["video_id"], "new")
            self.assertEqual(rec["upload_url"], "https://youtu.be/new")

    def test_append_jsonl_writes_single_line_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "uploads.jsonl"
            _append_jsonl(path, {"job_key": "k", "video_id": "v"})
            text = path.read_text(encoding="utf-8")
            lines = [line for line in text.splitlines() if line.strip()]
            self.assertEqual(len(lines), 1)
            payload = json.loads(lines[0])
            self.assertEqual(payload["job_key"], "k")
            self.assertEqual(payload["video_id"], "v")
