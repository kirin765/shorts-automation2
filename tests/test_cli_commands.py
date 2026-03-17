from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from shorts import cli
from shorts.models import RenderJob


class TestCliCommands(unittest.TestCase):
    def test_topics_generate_writes_file_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "topics.txt"
            history_path = Path(td) / "topics_history.txt"
            with mock.patch("shorts.cli.providers.generate_topics", return_value=["topic a", "topic b"]):
                rc = cli.main(
                    [
                        "topics",
                        "generate",
                        "--config",
                        "ENV",
                        "--out",
                        str(out_path),
                        "--history",
                        str(history_path),
                        "--count",
                        "2",
                    ]
                )
            self.assertEqual(rc, 0)
            self.assertEqual(out_path.read_text(encoding="utf-8"), "topic a\ntopic b\n")
            self.assertEqual(history_path.read_text(encoding="utf-8"), "topic a\ntopic b\n")

    def test_jobs_draft_writes_render_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            queue_dir = Path(td) / "queue"
            with mock.patch(
                "shorts.cli.providers.generate_render_job",
                return_value=RenderJob(
                    title="t",
                    script="s",
                    description="d",
                    hashtags="#shorts",
                ),
            ):
                rc = cli.main(
                    [
                        "jobs",
                        "draft",
                        "--config",
                        "ENV",
                        "--queue-dir",
                        str(queue_dir),
                        "--topic",
                        "AI.com이 다시 뜨는 이유",
                    ]
                )
            self.assertEqual(rc, 0)
            files = sorted(queue_dir.glob("*.json"))
            self.assertEqual(len(files), 1)
            self.assertIn("\"title\": \"t\"", files[0].read_text(encoding="utf-8"))

    def test_pipeline_daily_runs_generate_draft_queue_sequence(self) -> None:
        with mock.patch("shorts.cli.generate_topics_to_file", return_value=["topic a"]) as generate_topics:
            with mock.patch("shorts.cli.draft_jobs_to_queue", return_value=[Path("jobs/queue/a.json")]) as draft_jobs:
                with mock.patch("shorts.cli.run_queue", return_value=0) as run_queue:
                    rc = cli.main(["pipeline", "daily", "--config", "ENV", "--count", "1", "--no-upload"])
        self.assertEqual(rc, 0)
        generate_topics.assert_called_once()
        draft_jobs.assert_called_once()
        run_queue.assert_called_once()
