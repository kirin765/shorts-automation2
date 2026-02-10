import subprocess
import sys
import unittest
from pathlib import Path


class TestFailFast(unittest.TestCase):
    def test_missing_job_exits_nonzero_without_traceback(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        proc = subprocess.run(
            [
                sys.executable,
                str(repo / "run_short.py"),
                "--job",
                "no_such_job.json",
                "--no-upload",
                "--no-llm",
            ],
            cwd=repo,
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        self.assertIn("RESULT status=error", combined)
        self.assertNotIn("Traceback (most recent call last)", combined)

    def test_traceback_flag_prints_traceback(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        proc = subprocess.run(
            [
                sys.executable,
                str(repo / "run_short.py"),
                "--job",
                "no_such_job.json",
                "--no-upload",
                "--no-llm",
                "--traceback",
            ],
            cwd=repo,
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        self.assertIn("RESULT status=error", combined)
        self.assertIn("Traceback (most recent call last)", combined)


if __name__ == "__main__":
    unittest.main()

