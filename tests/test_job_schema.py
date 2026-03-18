from __future__ import annotations

import unittest

from shorts.models import ReviewedPackage, RenderJob, ScriptPackage, TopicPool


class TestJobSchema(unittest.TestCase):
    def test_topic_pool_requires_candidates(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires non-empty 'candidates'"):
            TopicPool.from_dict(
                {
                    "run_id": "run1",
                    "channel_category": "테크",
                    "series_name": "AI 현상 해설",
                    "generated_at": "2026-03-18T09:00:00",
                    "candidates": [],
                }
            )

    def test_script_package_requires_three_hooks(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 3 items"):
            ScriptPackage.from_dict(
                {
                    "run_id": "run1",
                    "candidate_id": "candidate_01",
                    "series_name": "AI 현상 해설",
                    "topic": "topic",
                    "angle": "angle",
                    "target_emotion": "curiosity",
                    "hook_options": ["h1", "h2"],
                    "best_hook": "h1",
                    "script_lines": ["a", "b", "c", "d"],
                    "ending": "end",
                    "title_options": ["t1", "t2", "t3", "t4", "t5"],
                    "visual_cues": ["v1", "v2", "v3"],
                    "duration_sec": 28,
                    "retention_score": 8,
                    "novelty_score": 7,
                    "risk_flags": [],
                    "fact_check_points": [],
                    "pexels_query": "ai abstract technology motion",
                }
            )

    def test_reviewed_package_requires_selected_title(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires non-empty 'selected_title'"):
            ReviewedPackage.from_dict(
                {
                    "run_id": "run1",
                    "candidate_id": "candidate_01",
                    "series_name": "AI 현상 해설",
                    "topic": "topic",
                    "angle": "angle",
                    "target_emotion": "curiosity",
                    "hook_options": ["h1", "h2", "h3"],
                    "best_hook": "h1",
                    "script_lines": ["a", "b", "c", "d"],
                    "ending": "end",
                    "title_options": ["t1", "t2", "t3", "t4", "t5"],
                    "visual_cues": ["v1", "v2", "v3"],
                    "duration_sec": 28,
                    "retention_score": 8,
                    "novelty_score": 7,
                    "risk_flags": [],
                    "fact_check_points": [],
                    "pexels_query": "ai abstract technology motion",
                    "selected_title": "",
                    "description": "desc",
                    "hashtags": "#shorts #AI",
                    "review_notes": [],
                    "rewrite_applied": False,
                }
            )

    def test_render_job_accepts_required_fields(self) -> None:
        job = RenderJob.from_dict(
            {
                "title": "t",
                "script": "s",
                "description": "d",
                "hashtags": "#shorts",
            }
        )
        self.assertEqual(job.title, "t")
        self.assertEqual(job.hashtags, "#shorts")
