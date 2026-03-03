import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

import run_short


class FakeResponse:
    def __init__(self, status_code: int = 200, *, content: bytes = b"", text: str = "", content_type: str = "audio/mpeg") -> None:
        self.status_code = int(status_code)
        self.content = content
        self.text = text
        self.headers = {"content-type": content_type}


class TestTTSFunctions(unittest.TestCase):
    def test_tts_elevenlabs_success_stores_audio_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out.mp3"
            with patch("requests.post") as post:
                post.return_value = FakeResponse(
                    status_code=200,
                    content=b"mp3-bytes",
                    text="ok",
                    content_type="audio/mpeg",
                )
                run_short.tts_elevenlabs("hello world", out, voice_id="voice-1", api_key="k", timeout_s=3.0)

            self.assertTrue(out.exists())
            self.assertEqual(out.read_bytes(), b"mp3-bytes")
            self.assertEqual(post.call_count, 1)

    def test_tts_elevenlabs_transient_retry_then_success(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out.mp3"
            with patch("requests.post") as post:
                post.side_effect = [
                    FakeResponse(status_code=500, text="throttle"),
                    FakeResponse(status_code=200, content=b"ok", content_type="audio/mpeg"),
                ]

                sleeps: list[float] = []
                logs: list[str] = []
                run_short.tts_with_retries(
                    lambda: run_short.tts_elevenlabs("hello", out, voice_id="voice-1", api_key="k", timeout_s=3.0),
                    label="tts",
                    max_attempts=3,
                    initial_backoff_s=1.25,
                    max_backoff_s=4.0,
                    sleep_fn=lambda s: sleeps.append(float(s)),
                    log_fn=logs.append,
                )

            self.assertEqual(post.call_count, 2)
            self.assertEqual(sleeps, [1.25])
            self.assertTrue(any("attempt 1/3" in m for m in logs))
            self.assertEqual(out.read_bytes(), b"ok")

    def test_tts_elevenlabs_client_error_is_not_retried(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out.mp3"
            with patch("requests.post") as post:
                post.return_value = FakeResponse(status_code=400, text="bad request", content_type="application/json")
                sleeps: list[float] = []

                with self.assertRaisesRegex(RuntimeError, "client failure"):
                    run_short.tts_with_retries(
                        lambda: run_short.tts_elevenlabs("hello", out, voice_id="voice-1", api_key="k", timeout_s=3.0),
                        label="tts",
                        max_attempts=3,
                        initial_backoff_s=1.0,
                        max_backoff_s=2.0,
                        sleep_fn=lambda s: sleeps.append(float(s)),
                    )

                self.assertEqual(post.call_count, 1)
                self.assertEqual(sleeps, [])

    def test_tts_elevenlabs_timeout_retried_then_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out.mp3"
            with patch("requests.post") as post:
                post.side_effect = [requests.Timeout("timed out"), requests.Timeout("timed out")]
                sleeps: list[float] = []

                with self.assertRaisesRegex(RuntimeError, "elevenlabs_tts timeout after 3.0s"):
                    run_short.tts_with_retries(
                        lambda: run_short.tts_elevenlabs("hello", out, voice_id="voice-1", api_key="k", timeout_s=3.0),
                        label="tts",
                        max_attempts=2,
                        initial_backoff_s=1.0,
                        max_backoff_s=2.0,
                        sleep_fn=lambda s: sleeps.append(float(s)),
                    )

                self.assertEqual(post.call_count, 2)
                self.assertEqual(sleeps, [1.0])

    def test_tts_elevenlabs_network_error_retried_then_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out.mp3"
            with patch("requests.post") as post:
                post.side_effect = [requests.RequestException("network"), requests.RequestException("network")]
                sleeps: list[float] = []

                with self.assertRaisesRegex(RuntimeError, "elevenlabs_tts network error"):
                    run_short.tts_with_retries(
                        lambda: run_short.tts_elevenlabs("hello", out, voice_id="voice-1", api_key="k", timeout_s=3.0),
                        label="tts",
                        max_attempts=2,
                        initial_backoff_s=1.0,
                        max_backoff_s=2.0,
                        sleep_fn=lambda s: sleeps.append(float(s)),
                    )

                self.assertEqual(post.call_count, 2)
                self.assertEqual(sleeps, [1.0])


if __name__ == "__main__":
    unittest.main()
