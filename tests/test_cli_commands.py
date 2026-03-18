from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from shorts import cli
from shorts.models import ScriptPackage, SelectedTopic, TopicCandidate, TopicPool, TopicScores, write_script_package
from shorts.providers import ReviewFeedback


class TestCliCommands(unittest.TestCase):
    def test_topics_generate_writes_topic_pool_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "topic_pool.json"
            history_path = Path(td) / "topics_history.txt"
            topic_pool = TopicPool(
                run_id="run1",
                channel_category="테크",
                series_name="AI 현상 해설",
                generated_at="2026-03-18T09:00:00",
                candidates=[
                    TopicCandidate("candidate_01", "AI 현상 해설", "topic a", "angle", "curiosity"),
                    TopicCandidate("candidate_02", "AI 현상 해설", "topic b", "angle", "surprise"),
                ],
            )
            with mock.patch("shorts.cli.providers.generate_topic_pool", return_value=topic_pool):
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
            self.assertIn("\"candidates\"", out_path.read_text(encoding="utf-8"))

    def test_topics_evaluate_writes_selected_topics(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            pool_path = Path(td) / "topic_pool.json"
            TopicPool(
                run_id="run1",
                channel_category="테크",
                series_name="AI 현상 해설",
                generated_at="2026-03-18T09:00:00",
                candidates=[TopicCandidate("candidate_01", "AI 현상 해설", "topic a", "angle", "curiosity")],
            )
            from shorts.models import write_topic_pool

            write_topic_pool(
                pool_path,
                TopicPool(
                    run_id="run1",
                    channel_category="테크",
                    series_name="AI 현상 해설",
                    generated_at="2026-03-18T09:00:00",
                    candidates=[TopicCandidate("candidate_01", "AI 현상 해설", "topic a", "angle", "curiosity")],
                ),
            )
            selected = SelectedTopic(
                run_id="run1",
                candidate_id="candidate_01",
                rank=1,
                series_name="AI 현상 해설",
                topic="topic a",
                angle="angle",
                target_emotion="curiosity",
                scores=TopicScores(8, 8, 8, 7, 8, 3, 9),
                overall_score=7.5,
                selection_reason="good",
            )
            with mock.patch("shorts.cli.providers.evaluate_topic_pool", return_value=[selected]):
                rc = cli.main(
                    [
                        "topics",
                        "evaluate",
                        "--config",
                        "ENV",
                        "--topic-pool",
                        str(pool_path),
                        "--count",
                        "1",
                    ]
                )
            self.assertEqual(rc, 0)
            self.assertTrue((pool_path.parent / "selected_topic_01.json").exists())

    def test_scripts_generate_manual_topic_writes_script_package(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "script_package_01.json"
            selected = SelectedTopic(
                run_id="run1",
                candidate_id="manual_01",
                rank=1,
                series_name="AI 현상 해설",
                topic="manual topic",
                angle="angle",
                target_emotion="curiosity",
                scores=TopicScores(10, 10, 10, 8, 10, 1, 10),
                overall_score=9.5,
                selection_reason="manual",
            )
            script_package = ScriptPackage(
                run_id="run1",
                candidate_id="manual_01",
                series_name="AI 현상 해설",
                topic="manual topic",
                angle="angle",
                target_emotion="curiosity",
                hook_options=["h1", "h2", "h3"],
                best_hook="h1",
                script_lines=["a", "b", "c", "d"],
                ending="end",
                title_options=["t1", "t2", "t3", "t4", "t5"],
                visual_cues=["v1", "v2", "v3"],
                duration_sec=28,
                retention_score=8,
                novelty_score=7,
                risk_flags=[],
                fact_check_points=[],
                pexels_query="ai abstract technology motion",
            )
            with mock.patch("shorts.cli.providers.manual_selected_topic", return_value=selected):
                with mock.patch("shorts.cli.providers.generate_script_package", return_value=script_package):
                    rc = cli.main(
                        [
                            "scripts",
                            "generate",
                            "--config",
                            "ENV",
                            "--topic",
                            "manual topic",
                            "--out",
                            str(out_path),
                        ]
                    )
            self.assertEqual(rc, 0)
            self.assertIn("\"best_hook\": \"h1\"", out_path.read_text(encoding="utf-8"))

    def test_scripts_review_rewrites_once(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            script_path = Path(td) / "script_package_01.json"
            out_path = Path(td) / "reviewed_package_01.json"
            package = ScriptPackage(
                run_id="run1",
                candidate_id="candidate_01",
                series_name="AI 현상 해설",
                topic="topic",
                angle="angle",
                target_emotion="curiosity",
                hook_options=["h1", "h2", "h3"],
                best_hook="h1",
                script_lines=["a", "b", "c", "d"],
                ending="end",
                title_options=["t1", "t2", "t3", "t4", "t5"],
                visual_cues=["v1", "v2", "v3"],
                duration_sec=28,
                retention_score=6,
                novelty_score=5,
                risk_flags=["too vague"],
                fact_check_points=[],
                pexels_query="ai abstract technology motion",
            )
            write_script_package(script_path, package)
            pass_feedback = ReviewFeedback(
                approved=True,
                selected_title="t1",
                description="desc",
                hashtags="#shorts #AI",
                retention_score=8,
                novelty_score=7,
                risk_flags=[],
                fact_check_points=[],
                review_notes=["ok"],
                rewrite_instructions=[],
            )
            fail_feedback = ReviewFeedback(
                approved=False,
                selected_title="t1",
                description="desc",
                hashtags="#shorts #AI",
                retention_score=6,
                novelty_score=5,
                risk_flags=["too vague"],
                fact_check_points=[],
                review_notes=["tighten hook"],
                rewrite_instructions=["rewrite hook"],
            )
            rewritten = ScriptPackage(
                run_id="run1",
                candidate_id="candidate_01",
                series_name="AI 현상 해설",
                topic="topic",
                angle="angle",
                target_emotion="curiosity",
                hook_options=["h1", "h2", "h3"],
                best_hook="h2",
                script_lines=["a", "b", "c", "d"],
                ending="end",
                title_options=["t1", "t2", "t3", "t4", "t5"],
                visual_cues=["v1", "v2", "v3"],
                duration_sec=28,
                retention_score=8,
                novelty_score=7,
                risk_flags=[],
                fact_check_points=[],
                pexels_query="ai abstract technology motion",
            )
            with mock.patch("shorts.cli.providers.review_script_package", side_effect=[fail_feedback, pass_feedback]):
                with mock.patch("shorts.cli.providers.rewrite_script_package", return_value=rewritten) as rewrite_call:
                    rc = cli.main(
                        [
                            "scripts",
                            "review",
                            "--config",
                            "ENV",
                            "--script-package",
                            str(script_path),
                            "--out",
                            str(out_path),
                        ]
                    )
            self.assertEqual(rc, 0)
            rewrite_call.assert_called_once()
            self.assertTrue(out_path.exists())

    def test_pipeline_daily_runs_full_sequence(self) -> None:
        with mock.patch("shorts.cli.generate_topic_pool_to_file", return_value=Path("jobs/work/run/topic_pool.json")) as gen:
            with mock.patch("shorts.cli.evaluate_topic_pool_to_files", return_value=[Path("jobs/work/run/selected_topic_01.json")]) as eval_topics:
                with mock.patch("shorts.cli.generate_script_package_to_file", return_value=Path("jobs/work/run/script_package_01.json")) as gen_script:
                    with mock.patch("shorts.cli.review_script_package_to_file", return_value=Path("jobs/work/run/reviewed_package_01.json")) as review_script:
                        with mock.patch("shorts.cli.package_reviewed_job_to_queue", return_value=Path("jobs/queue/a.json")) as package_job:
                            with mock.patch("shorts.cli.load_reviewed_package") as load_reviewed:
                                load_reviewed.return_value.topic = "topic a"
                                with mock.patch("shorts.cli.append_topics_text") as append_history:
                                    with mock.patch("shorts.cli.run_queue", return_value=0) as run_queue:
                                        rc = cli.main(["pipeline", "daily", "--config", "ENV", "--count", "1", "--no-upload"])
        self.assertEqual(rc, 0)
        gen.assert_called_once()
        eval_topics.assert_called_once()
        gen_script.assert_called_once()
        review_script.assert_called_once()
        package_job.assert_called_once()
        append_history.assert_called_once()
        run_queue.assert_called_once()
