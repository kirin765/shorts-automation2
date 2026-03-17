from __future__ import annotations

import unittest

from shorts.upload import _retry_upload_next_chunk


class _FakeReq:
    def __init__(self, actions):
        self._actions = list(actions)

    def next_chunk(self):
        if not self._actions:
            raise AssertionError("no more actions")
        action = self._actions.pop(0)
        if isinstance(action, BaseException):
            raise action
        return action


class TestUploadRetry(unittest.TestCase):
    def test_retries_then_succeeds(self) -> None:
        req = _FakeReq([OSError("network down"), (None, None), (None, {"id": "vid123"})])
        now = {"t": 0.0}
        sleeps = []
        logs = []

        def time_fn() -> float:
            return float(now["t"])

        def sleep_fn(value: float) -> None:
            sleeps.append(float(value))
            now["t"] += float(value)

        def log_fn(message: str) -> None:
            logs.append(message)

        response = _retry_upload_next_chunk(
            req,
            max_attempts=5,
            timeout_s=60.0,
            initial_backoff_s=1.0,
            max_backoff_s=10.0,
            is_retryable_exc=lambda exc: isinstance(exc, OSError),
            sleep_fn=sleep_fn,
            time_fn=time_fn,
            log_fn=log_fn,
        )
        self.assertEqual(response["id"], "vid123")
        self.assertEqual(sleeps, [1.0])
        self.assertTrue(any(message.startswith("[upload] policy ") for message in logs))
        self.assertTrue(any("next_chunk failed" in message for message in logs))

    def test_non_retryable_raises_immediately(self) -> None:
        req = _FakeReq([ValueError("bad request")])
        with self.assertRaises(ValueError):
            _retry_upload_next_chunk(
                req,
                max_attempts=5,
                timeout_s=60.0,
                initial_backoff_s=1.0,
                max_backoff_s=10.0,
                is_retryable_exc=lambda exc: False,
                sleep_fn=lambda _value: None,
                time_fn=lambda: 0.0,
                log_fn=lambda _message: None,
            )

    def test_timeout_stops_retry_loop(self) -> None:
        req = _FakeReq([OSError("flaky"), OSError("still flaky")])
        now = {"t": 0.0}
        sleeps = []

        def time_fn() -> float:
            return float(now["t"])

        def sleep_fn(value: float) -> None:
            sleeps.append(float(value))
            now["t"] += float(value)

        with self.assertRaises(TimeoutError):
            _retry_upload_next_chunk(
                req,
                max_attempts=10,
                timeout_s=3.0,
                initial_backoff_s=2.0,
                max_backoff_s=30.0,
                is_retryable_exc=lambda exc: isinstance(exc, OSError),
                sleep_fn=sleep_fn,
                time_fn=time_fn,
                log_fn=lambda _message: None,
            )
        self.assertEqual(sleeps, [2.0])
