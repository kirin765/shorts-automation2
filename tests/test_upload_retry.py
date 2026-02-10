import unittest

import run_short


class _FakeReq:
    def __init__(self, actions):
        self._actions = list(actions)

    def next_chunk(self):
        if not self._actions:
            raise AssertionError("no more actions")
        act = self._actions.pop(0)
        if isinstance(act, BaseException):
            raise act
        return act


class TestUploadRetry(unittest.TestCase):
    def test_retries_then_succeeds(self) -> None:
        req = _FakeReq(
            [
                OSError("network down"),
                (None, None),
                (None, {"id": "vid123"}),
            ]
        )

        now = {"t": 0.0}
        sleeps: list[float] = []
        logs: list[str] = []

        def time_fn() -> float:
            return float(now["t"])

        def sleep_fn(s: float) -> None:
            sleeps.append(float(s))
            now["t"] += float(s)

        def log_fn(msg: str) -> None:
            logs.append(msg)

        resp = run_short._retry_upload_next_chunk(
            req,
            max_attempts=5,
            timeout_s=60.0,
            initial_backoff_s=1.0,
            max_backoff_s=10.0,
            is_retryable_exc=lambda e: isinstance(e, OSError),
            sleep_fn=sleep_fn,
            time_fn=time_fn,
            log_fn=log_fn,
        )
        self.assertEqual(resp["id"], "vid123")
        self.assertEqual(sleeps, [1.0])
        self.assertTrue(any(m.startswith("[upload] policy ") for m in logs), logs)
        self.assertTrue(any("next_chunk failed" in m for m in logs))

    def test_non_retryable_raises_immediately(self) -> None:
        req = _FakeReq([ValueError("bad request")])

        sleeps: list[float] = []

        with self.assertRaises(ValueError):
            run_short._retry_upload_next_chunk(
                req,
                max_attempts=5,
                timeout_s=60.0,
                initial_backoff_s=1.0,
                max_backoff_s=10.0,
                is_retryable_exc=lambda e: False,
                sleep_fn=lambda s: sleeps.append(float(s)),
                time_fn=lambda: 0.0,
                log_fn=lambda m: None,
            )
        self.assertEqual(sleeps, [])

    def test_timeout_stops_retry_loop(self) -> None:
        req = _FakeReq([OSError("flaky"), OSError("still flaky")])

        now = {"t": 0.0}
        sleeps: list[float] = []

        def time_fn() -> float:
            return float(now["t"])

        def sleep_fn(s: float) -> None:
            sleeps.append(float(s))
            now["t"] += float(s)

        with self.assertRaises(TimeoutError):
            run_short._retry_upload_next_chunk(
                req,
                max_attempts=10,
                timeout_s=3.0,
                initial_backoff_s=2.0,
                max_backoff_s=30.0,
                is_retryable_exc=lambda e: isinstance(e, OSError),
                sleep_fn=sleep_fn,
                time_fn=time_fn,
                log_fn=lambda m: None,
            )
        # First retry sleeps 2s; second retry would require 4s which exceeds timeout.
        self.assertEqual(sleeps, [2.0])


if __name__ == "__main__":
    unittest.main()
