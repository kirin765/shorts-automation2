import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestRunQueueResultLine(unittest.TestCase):
    def test_run_queue_prints_result_line_at_end(self) -> None:
        repo = Path(__file__).resolve().parents[1]

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            q = root / "queue"
            done = root / "done"
            failed = root / "failed"
            logs = root / "logs"
            q.mkdir(parents=True, exist_ok=True)

            # Intentionally invalid JSON so run_short.py fails fast without
            # invoking ffmpeg/tts/network.
            (q / "bad.json").write_text("{", encoding="utf-8")

            proc = subprocess.run(
                [
                    "bash",
                    str(repo / "scripts" / "run_queue.sh"),
                    "--config",
                    str(repo / "config.json"),
                    "--queue-dir",
                    str(q),
                    "--done-dir",
                    str(done),
                    "--failed-dir",
                    str(failed),
                    "--log-dir",
                    str(logs),
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

            combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
            lines = [ln.strip() for ln in combined.splitlines() if ln.strip()]
            self.assertGreater(len(lines), 0)

            # The queue runner should end with a single-line summary that is easy to grep.
            self.assertTrue(lines[-1].startswith("RESULT status=error"), lines[-1])


if __name__ == "__main__":
    unittest.main()

