from __future__ import annotations

import unittest

from shorts.models import DraftJob, RenderJob


class TestJobSchema(unittest.TestCase):
    def test_draft_job_requires_topic(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires non-empty 'topic'"):
            DraftJob.from_dict({"style": "x"})

    def test_render_job_rejects_unknown_keys(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown keys"):
            RenderJob.from_dict(
                {
                    "title": "t",
                    "script": "s",
                    "description": "d",
                    "hashtags": "#shorts",
                    "bogus": 1,
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
