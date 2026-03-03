import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _load_run_daily_module():
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "run_daily.py"
    spec = importlib.util.spec_from_file_location("run_daily_module", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load scripts/run_daily.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestRunDailyJobNaming(unittest.TestCase):
    def test_two_runs_do_not_overwrite_same_topic_file(self) -> None:
        run_daily = _load_run_daily_module()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            queue_dir = root / "queue"
            topics_file = root / "topics.txt"
            topics_file.write_text("same topic\n", encoding="utf-8")

            argv = [
                "run_daily.py",
                "--config",
                "ENV",
                "--queue-dir",
                str(queue_dir),
                "--topics-file",
                str(topics_file),
                "--count",
                "1",
                "--run-queue",
                "scripts/run_queue.sh",
            ]

            with patch.object(run_daily.subprocess, "call", return_value=0):
                with patch.object(sys, "argv", argv):
                    rc1 = run_daily.main()
                with patch.object(sys, "argv", argv):
                    rc2 = run_daily.main()

            self.assertEqual(rc1, 0)
            self.assertEqual(rc2, 0)
            jobs = sorted(queue_dir.glob("*.json"))
            self.assertEqual(len(jobs), 2)
            self.assertNotEqual(jobs[0].name, jobs[1].name)

            payloads = [json.loads(p.read_text(encoding="utf-8")) for p in jobs]
            self.assertEqual(payloads[0]["topic"], "same topic")
            self.assertEqual(payloads[1]["topic"], "same topic")


if __name__ == "__main__":
    unittest.main()
