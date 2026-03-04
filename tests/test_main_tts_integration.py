import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_short
import requests


class TestMainTTSIntegration(unittest.TestCase):
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
        cfg = {"output_dir": td, "subtitle_align_openai": False}
        if extra:
            cfg.update(extra)
        p = Path(td) / "config.json"
        p.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        return p

    def test_main_without_credentials_fails_fast(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            job_path = self._write_job(td)
            cfg_path = self._write_config(td)

            with (
                patch.object(sys, "argv", ["run_short.py", "--config", str(cfg_path), "--job", str(job_path), "--no-upload"]),
                patch(
                    "run_short.openai_generate_job",
                    return_value=run_short.Job(
                        title="title", script="script", description="description", hashtags="#shorts", topic="topic"
                    ),
                ),
            ):
                buf = io.StringIO()
                with patch("sys.stdout", buf):
                    rc = run_short.main()

            out = buf.getvalue()
            self.assertEqual(rc, 1)
            self.assertIn("Missing ElevenLabs config", out)
            self.assertIn("elevenlabs_api_key", out)

    def test_main_elevenlabs_forced_when_edge_provider_set(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            job_path = self._write_job(td)
            cfg_path = self._write_config(
                td,
                {
                    "tts_provider": "edge",
                    "elevenlabs_api_key": "api-key",
                    "elevenlabs_voice_id": "voice-1",
                    "keep_intermediate_artifacts": True,
                },
            )

            audio_paths: list[Path] = []

            def fake_tts(
                text: str,
                out_mp3: Path,
                *,
                voice_id: str,
                api_key: str,
                model_id: str,
                timeout_s: float,
            ) -> None:
                audio_paths.append(out_mp3)
                out_mp3.write_bytes(b"mp3-data")

            def fake_background(
                config: dict,
                job: run_short.Job,
                *,
                duration_s: float,
                out_path: Path,
            ) -> tuple[Path, str | None]:
                out_path.write_text("background", encoding="utf-8")
                return out_path, None

            def fake_render(
                bg: Path, audio: Path, srt: Path, out_video: Path, config: dict, title_text: str
            ) -> None:
                out_video.write_bytes(b"video-data")

            with patch.object(sys, "argv", ["run_short.py", "--config", str(cfg_path), "--job", str(job_path), "--no-upload"]):
                with (
                    patch("run_short.probe_duration", return_value=30.0),
                    patch("run_short.ensure_background_for_job", side_effect=fake_background),
                    patch("run_short.render_video", side_effect=fake_render),
                    patch("run_short.tts_elevenlabs", side_effect=fake_tts),
                    patch("run_short._apply_srt_timing_guard", return_value=True),
                    patch(
                        "run_short.openai_generate_job",
                        return_value=run_short.Job(
                            title="title", script="script", description="description", hashtags="#shorts", topic="topic"
                        ),
                    ),
                    patch("sys.stdout", new=io.StringIO()) as stdout_buf,
                ):
                    rc = run_short.main()

            out = stdout_buf.getvalue()
            self.assertEqual(rc, 0)
            self.assertIn("is not supported. Forcing ElevenLabs-only mode.", out)
            self.assertEqual(len(audio_paths), 1)
            self.assertTrue(audio_paths[0].exists())
            self.assertEqual(audio_paths[0].read_bytes(), b"mp3-data")

    def test_main_tts_failure_reports_wrapped_message_after_retries(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            job_path = self._write_job(td)
            cfg_path = self._write_config(
                td,
                {
                    "tts_provider": "elevenlabs",
                    "elevenlabs_api_key": "api-key",
                    "elevenlabs_voice_id": "voice-1",
                    "elevenlabs_tts_attempts": 2,
                    "elevenlabs_tts_initial_backoff_s": 0.0,
                    "elevenlabs_tts_max_backoff_s": 0.0,
                },
            )

            with (
                patch.object(
                    sys,
                    "argv",
                    ["run_short.py", "--config", str(cfg_path), "--job", str(job_path), "--no-upload"],
                ),
                patch(
                    "run_short.tts_elevenlabs",
                    side_effect=RuntimeError("elevenlabs_tts timeout after 40.0s: timed out"),
                ),
                patch(
                    "run_short.openai_generate_job",
                    return_value=run_short.Job(
                        title="title", script="script", description="description", hashtags="#shorts", topic="topic"
                    ),
                ),
                patch("sys.stdout", new=io.StringIO()) as stdout_buf,
            ):
                rc = run_short.main()

            out = stdout_buf.getvalue()
            self.assertEqual(rc, 1)
            self.assertIn("TTS failed after 2 attempts", out)
            self.assertIn("elevenlabs_tts timeout after", out)

    def test_main_subtitle_position_center_middle_logged_or_rendered_as_align_5(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            job_path = self._write_job(td)
            cfg_path = self._write_config(
                td,
                {
                    "subtitle_position": "center,middle",
                    "subtitle_align": "bottom",
                    "elevenlabs_api_key": "api-key",
                    "elevenlabs_voice_id": "voice-1",
                },
            )

            captured: dict[str, object] = {}

            def fake_tts(_text: str, out_mp3: Path, **_kwargs: object) -> None:
                out_mp3.write_bytes(b"mp3")

            def fake_background(config: dict, job: run_short.Job, *, duration_s: float, out_path: Path) -> tuple[Path, str | None]:
                return Path(td) / "bg.mp4", None

            def fake_render(bg: Path, audio: Path, srt: Path, out_video: Path, config: dict, title_text: str) -> None:
                captured["subtitle_position"] = config.get("subtitle_position")
                captured["subtitle_alignment"] = run_short._align_from_position(run_short._normalize_subtitle_position(config.get("subtitle_position")))

            Path(Path(td) / "bg.mp4").write_text("bg", encoding="utf-8")
            Path(Path(td) / "audio.mp3").write_text("audio", encoding="utf-8")

            with (
                patch.object(sys, "argv", ["run_short.py", "--config", str(cfg_path), "--job", str(job_path), "--no-upload", "--no-llm"]),
                patch("run_short.probe_duration", return_value=10.0),
                patch("run_short.tts_elevenlabs", side_effect=fake_tts),
                patch("run_short.tts_with_retries", side_effect=lambda fn, **_: fn()),
                patch("run_short.ensure_background_for_job", side_effect=fake_background),
                patch("run_short.render_video", side_effect=fake_render),
            ):
                rc = run_short.main()

        self.assertEqual(rc, 0)
        self.assertEqual(captured.get("subtitle_position"), "center,middle")
        self.assertEqual(captured.get("subtitle_alignment"), 5)


if __name__ == "__main__":
    unittest.main()
