import io
import json
import unittest
import subprocess
import tempfile
import sys
from pathlib import Path
from unittest.mock import patch

import run_short
from config_loader import load_config

class TestOpenclawConfigDefaults(unittest.TestCase):
    def test_example_voice_id_updated(self) -> None:
        cfg = load_config("ENV")
        self.assertEqual(cfg.get("elevenlabs_voice_id"), "uyVNoMrnUku1dZyVEXwD")
        self.assertEqual(cfg.get("openclaw_notify_enabled"), False)


class TestOpenclawNotifyFlow(unittest.TestCase):
    def _write_job(self, td: str) -> Path:
        job = {
            "title": "Test title",
            "script": "This is a short sample script.",
            "description": "This is a short description.",
            "hashtags": "#shorts",
        }
        p = Path(td) / "job.json"
        p.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        return p

    def _write_config(self, td: str, extra: dict[str, object] | None = None) -> Path:
        cfg = {
            "output_dir": td,
            "subtitle_align_openai": False,
            "elevenlabs_api_key": "api-key",
            "elevenlabs_voice_id": "configured-voice",
            "elevenlabs_tts_attempts": 1,
            "elevenlabs_tts_initial_backoff_s": 0.0,
            "elevenlabs_tts_max_backoff_s": 0.0,
            "openclaw_notify_enabled": True,
            "openclaw_error_log_path": str(Path(td) / "errors.jsonl"),
            "openclaw_notify_timeout_s": 12.0,
        }
        if extra:
            cfg.update(extra)
        p = Path(td) / "config.json"
        p.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        return p

    def test_error_is_logged_and_openclaw_notified_once(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            job_path = self._write_job(td)
            cfg_path = self._write_config(td)

            with (
                patch.object(
                    sys,
                    "argv",
                    ["run_short.py", "--config", str(cfg_path), "--job", str(job_path), "--no-upload", "--no-llm"],
                ),
                patch("run_short.tts_elevenlabs", side_effect=RuntimeError("elevenlabs down")),
                patch("run_short.openai_generate_job", return_value=run_short.Job(title="title", script="script", description="", hashtags="#shorts", topic="topic")),
                patch("run_short._notify_openclaw") as notify_mock,
                patch("sys.stdout", new=io.StringIO()),
            ):
                rc = run_short.main()

            self.assertEqual(rc, 1)
            notify_mock.assert_called_once()
            log_file = Path(td) / "errors.jsonl"
            self.assertTrue(log_file.exists())
            logs = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertTrue(any(item.get("status") == "error" for item in logs))

    def test_notify_command_handles_message_placeholder(self) -> None:
        with patch("run_short.subprocess.run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            run_short._notify_openclaw(
                "hello world",
                config={
                    "openclaw_notify_enabled": True,
                    "openclaw_notify_cmd": "openclaw telegram send --text {message}",
                    "openclaw_notify_timeout_s": 12.0,
                },
            )
            run_mock.assert_called_once()
            args, _ = run_mock.call_args
            self.assertEqual(args[0][0], "openclaw")


if __name__ == "__main__":
    unittest.main()
