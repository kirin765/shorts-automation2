from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestQueueResultLine(unittest.TestCase):
    def test_queue_prints_result_line_at_end(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            queue_dir = root / "queue"
            done_dir = root / "done"
            failed_dir = root / "failed"
            queue_dir.mkdir(parents=True, exist_ok=True)
            (queue_dir / "bad.json").write_text("{", encoding="utf-8")

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "shorts",
                    "queue",
                    "run",
                    "--config",
                    "ENV",
                    "--queue-dir",
                    str(queue_dir),
                    "--done-dir",
                    str(done_dir),
                    "--failed-dir",
                    str(failed_dir),
                    "--retries",
                    "1",
                    "--sleep",
                    "0",
                    "--no-upload",
                ],
                cwd=repo,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(proc.returncode, 0)
            lines = [line.strip() for line in ((proc.stdout or "") + "\n" + (proc.stderr or "")).splitlines() if line.strip()]
            self.assertTrue(lines[-1].startswith("RESULT status=error"), lines[-1])
