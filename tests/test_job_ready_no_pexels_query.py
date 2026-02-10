import unittest

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


if __name__ == "__main__":
    unittest.main()

