from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


class TestRenderFailFast(unittest.TestCase):
    def test_missing_job_exits_nonzero_without_traceback(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "shorts",
                "render",
                "--job",
                "no_such_job.json",
                "--no-upload",
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
                "-m",
                "shorts",
                "render",
                "--job",
                "no_such_job.json",
                "--no-upload",
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
