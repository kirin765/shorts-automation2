import unittest
from unittest.mock import patch

import run_short


class TestJobReadyNoPexelsQuery(unittest.TestCase):
    def test_no_llm_allows_missing_pexels_query(self) -> None:
        cfg = {"background_provider": "local"}
        job = run_short.Job(
            title="t",
            script="s",
            description="d",
            hashtags="#shorts",
            pexels_query=None,
        )
        out = run_short.ensure_job_ready(cfg, job, allow_llm=False)
        self.assertEqual(out.title, "t")
        self.assertIsNone(out.pexels_query)

    def test_allow_llm_regenerates_missing_fields(self) -> None:
        cfg = {"openai_api_key": "test-key"}
        job = run_short.Job(
            title="old title",
            script=None,
            description="old description",
            hashtags="#old",
            pexels_query="preset query",
            topic=None,
        )
        regenerated = run_short.Job(
            title="new title",
            script="new script",
            description="new description",
            hashtags="#shorts #new",
            pexels_query="generated query",
            topic="topic",
        )

        with patch("run_short.openai_generate_job", return_value=regenerated) as mocked:
            out = run_short.ensure_job_ready(cfg, job, allow_llm=True)

        mocked.assert_called_once()
        called_seed = mocked.call_args.args[1]
        self.assertEqual(called_seed.topic, "old title")
        self.assertEqual(out.title, "new title")
        self.assertEqual(out.script, "new script")
        self.assertEqual(out.pexels_query, "generated query")

if __name__ == "__main__":
    unittest.main()
