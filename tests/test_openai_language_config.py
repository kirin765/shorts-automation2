import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_short


class _DummyResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.text = ""

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class TestOpenAILanguageConfig(unittest.TestCase):
    def test_write_srt_aligned_openai_skips_language_when_auto(self) -> None:
        captured = {}

        def fake_post(url: str, headers: dict[str, str], files: dict, data: dict, timeout: int):
            captured.update({"url": url, "headers": headers, "files": files, "data": data, "timeout": timeout})
            return _DummyResponse(
                {
                    "words": [
                        {"word": "Hello", "start": 0.0, "end": 0.2},
                        {"word": "everyone", "start": 0.2, "end": 0.6},
                        {"word": "안녕", "start": 0.6, "end": 1.0},
                        {"word": "세계", "start": 1.0, "end": 1.4},
                    ]
                }
            )

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            audio = td_path / "audio.mp3"
            srt = td_path / "out.srt"
            audio.write_bytes(b"dummy-audio")

            with patch("requests.post", side_effect=fake_post):
                run_short.write_srt_aligned_openai(
                    {
                        "openai_api_key": "test-key",
                        "openai_transcribe_language": "",
                        "subtitle_words_per_cue": 2,
                    },
                    audio_path=audio,
                    srt_path=srt,
                    prompt_text="",
                    script_text="",
                )

            self.assertNotIn("language", captured["data"])

            text = srt.read_text(encoding="utf-8")
            self.assertIn("Hello everyone", text)
            self.assertIn("안녕 세계", text)
            self.assertEqual(text.count("\n\n"), 1)

    def test_openai_generate_job_language_line_is_optional_for_empty_language(self) -> None:
        captured = {}
        response_payload = {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "title": "제목",
                                    "script": "script text",
                                    "description": "desc",
                                    "hashtags": "#shorts #k",
                                    "pexels_query": "korean video",
                                }
                            ),
                        }
                    ]
                }
            ]
        }

        def fake_post(url: str, headers: dict[str, str], json: dict, timeout: int):
            captured.update({"url": url, "headers": headers, "json": json, "timeout": timeout})
            return _DummyResponse(response_payload)

        job = run_short.Job(
            title=None,
            script=None,
            description=None,
            hashtags=None,
            pexels_query=None,
            topic="테스트 주제",
            style=None,
            tone=None,
            target_seconds=None,
        )

        with patch("requests.post", side_effect=fake_post):
            run_short.openai_generate_job(
                {
                    "openai_api_key": "test-key",
                    "openai_language": "",
                },
                job,
            )

        user_msg = next(item["content"] for item in captured["json"]["input"] if item["role"] == "user")
        self.assertNotIn("Language:", user_msg)

    def test_openai_generate_job_includes_language_when_set(self) -> None:
        captured = {}
        response_payload = {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "title": "제목",
                                    "script": "script text",
                                    "description": "desc",
                                    "hashtags": "#shorts #k",
                                    "pexels_query": "korean video",
                                }
                            ),
                        }
                    ]
                }
            ]
        }

        def fake_post(url: str, headers: dict[str, str], json: dict, timeout: int):
            captured.update({"json": json, "timeout": timeout})
            return _DummyResponse(response_payload)

        job = run_short.Job(
            title=None,
            script=None,
            description=None,
            hashtags=None,
            pexels_query=None,
            topic="테스트 주제",
            style=None,
            tone=None,
            target_seconds=None,
        )

        with patch("requests.post", side_effect=fake_post):
            run_short.openai_generate_job(
                {
                    "openai_api_key": "test-key",
                    "openai_language": "en",
                },
                job,
            )

        user_msg = next(item["content"] for item in captured["json"]["input"] if item["role"] == "user")
        self.assertIn("Language: en", user_msg)

    def test_openai_generate_job_prefers_script_model(self) -> None:
        captured = {}
        response_payload = {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "title": "제목",
                                    "script": "script text",
                                    "description": "desc",
                                    "hashtags": "#shorts #k",
                                    "pexels_query": "korean video",
                                }
                            ),
                        }
                    ]
                }
            ]
        }

        def fake_post(url: str, headers: dict[str, str], json: dict, timeout: int):
            captured.update({"json": json, "timeout": timeout})
            return _DummyResponse(response_payload)

        job = run_short.Job(
            title=None,
            script=None,
            description=None,
            hashtags=None,
            pexels_query=None,
            topic="테스트 주제",
            style=None,
            tone=None,
            target_seconds=None,
        )

        with patch("requests.post", side_effect=fake_post):
            run_short.openai_generate_job(
                {
                    "openai_api_key": "test-key",
                    "openai_model": "should-not-use",
                    "openai_script_model": "gpt-4.1-mini",
                },
                job,
            )

        self.assertEqual(captured["json"]["model"], "gpt-4.1-mini")

    def test_write_srt_aligned_openai_uses_explicit_transcribe_language(self) -> None:
        captured = {}

        def fake_post(url: str, headers: dict[str, str], files: dict, data: dict, timeout: int):
            captured.update({"data": data})
            return _DummyResponse(
                {
                    "words": [
                        {"word": "Hello", "start": 0.0, "end": 0.4},
                        {"word": "world", "start": 0.4, "end": 0.8},
                    ]
                }
            )

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            audio = td_path / "audio.mp3"
            srt = td_path / "out.srt"
            audio.write_bytes(b"dummy-audio")

            with patch("requests.post", side_effect=fake_post):
                run_short.write_srt_aligned_openai(
                    {
                        "openai_api_key": "test-key",
                        "openai_transcribe_language": "en",
                    },
                    audio_path=audio,
                    srt_path=srt,
                    prompt_text="",
                    script_text="",
                )

        self.assertEqual(captured["data"].get("language"), "en")


if __name__ == "__main__":
    unittest.main()
