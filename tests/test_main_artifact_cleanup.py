import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_short


class TestMainArtifactCleanup(unittest.TestCase):
    def _write_job(self, td: str) -> Path:
        job = {
            "title": "Cleanup title",
            "script": "짧은 샘플 대본입니다.",
            "description": "Cleanup description",
            "hashtags": "#test",
        }
        p = Path(td) / "job.json"
        p.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        return p

    def _write_config(self, td: str, extra: dict[str, object] | None = None) -> Path:
        output_dir = Path(td) / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        cfg = {
            "output_dir": str(output_dir),
            "subtitle_align_openai": False,
            "elevenlabs_api_key": "api-key",
            "elevenlabs_voice_id": "voice-1",
        }
        if extra:
            cfg.update(extra)
        p = Path(td) / "config.json"
        p.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        return p

    def test_main_leaves_only_mp4_when_run_success(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            job_path = self._write_job(td)
            cfg_path = self._write_config(td)
            output_dir = Path(td) / "output"

            def fake_tts(
                text: str,
                out_mp3: Path,
                *,
                voice_id: str,
                api_key: str,
                model_id: str,
                timeout_s: float,
            ) -> None:
                out_mp3.write_bytes(b"mp3-data")

            def fake_background(config: dict, job: run_short.Job, *, duration_s: float, out_path: Path):
                out_path.write_bytes(b"bg")
                return out_path, None

            def fake_render(
                bg: Path,
                audio: Path,
                srt: Path,
                out_video: Path,
                config: dict,
                title_text: str,
            ) -> None:
                out_video.write_bytes(b"video-data")
                out_video.with_suffix(".title.txt").write_text("title", encoding="utf-8")
                out_video.with_suffix(".subs.ass").write_text("ass", encoding="utf-8")

            with patch.object(
                sys,
                "argv",
                [
                    "run_short.py",
                    "--config",
                    str(cfg_path),
                    "--job",
                    str(job_path),
                    "--no-upload",
                ],
            ):
                with (
                    patch("run_short.probe_duration", return_value=10.0),
                    patch("run_short.ensure_background_for_job", side_effect=fake_background),
                    patch("run_short.render_video", side_effect=fake_render),
                    patch("run_short.tts_with_retries", side_effect=lambda fn, **_: fn()),
                    patch("run_short.tts_elevenlabs", side_effect=fake_tts),
                    patch("run_short._apply_srt_timing_guard", return_value=True),
                    patch("sys.stdout", new=io.StringIO()),
                ):
                    rc = run_short.main()

            self.assertEqual(rc, 0)
            files = sorted([p for p in output_dir.glob("*") if p.is_file()])
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].suffix, ".mp4")
            self.assertFalse(any(p.suffix == ".mp3" for p in output_dir.glob("*")))
            self.assertFalse(any(p.suffix == ".srt" for p in output_dir.glob("*")))
            self.assertFalse(any(str(p).endswith(".bg.mp4") for p in output_dir.glob("*")))
            self.assertFalse(any(str(p).endswith(".title.txt") for p in output_dir.glob("*")))
            self.assertFalse(any(str(p).endswith(".subs.ass") for p in output_dir.glob("*")))
            self.assertFalse(any(str(p).endswith(".credits.txt") for p in output_dir.glob("*")))

    def test_main_keeps_external_audio(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            job_path = self._write_job(td)
            cfg_path = self._write_config(td)
            output_dir = Path(td) / "output"
            external_audio = Path(td) / "seed.mp3"
            external_audio.write_bytes(b"seed-audio")

            def fake_background(config: dict, job: run_short.Job, *, duration_s: float, out_path: Path):
                out_path.write_bytes(b"bg")
                return out_path, None

            def fake_render(
                bg: Path,
                audio: Path,
                srt: Path,
                out_video: Path,
                config: dict,
                title_text: str,
            ) -> None:
                out_video.write_bytes(b"video-data")
                out_video.with_suffix(".title.txt").write_text("title", encoding="utf-8")
                out_video.with_suffix(".subs.ass").write_text("ass", encoding="utf-8")

            with patch.object(
                sys,
                "argv",
                [
                    "run_short.py",
                    "--config",
                    str(cfg_path),
                    "--job",
                    str(job_path),
                    "--no-upload",
                    "--audio",
                    str(external_audio),
                ],
            ):
                with (
                    patch("run_short.probe_duration", return_value=10.0),
                    patch("run_short.ensure_background_for_job", side_effect=fake_background),
                    patch("run_short.render_video", side_effect=fake_render),
                    patch("run_short._apply_srt_timing_guard", return_value=True),
                    patch("sys.stdout", new=io.StringIO()),
                ):
                    rc = run_short.main()

            self.assertEqual(rc, 0)
            self.assertTrue(external_audio.exists())
            files = sorted([p for p in output_dir.glob("*") if p.is_file()])
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].suffix, ".mp4")

    def test_main_keep_intermediate_artifacts_preserves_subs_ass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            job_path = self._write_job(td)
            cfg_path = self._write_config(td, extra={"keep_intermediate_artifacts": True})
            output_dir = Path(td) / "output"

            def fake_tts(
                text: str,
                out_mp3: Path,
                *,
                voice_id: str,
                api_key: str,
                model_id: str,
                timeout_s: float,
            ) -> None:
                out_mp3.write_bytes(b"mp3-data")

            def fake_background(config: dict, job: run_short.Job, *, duration_s: float, out_path: Path):
                out_path.write_bytes(b"bg")
                return out_path, None

            def fake_render(
                bg: Path,
                audio: Path,
                srt: Path,
                out_video: Path,
                config: dict,
                title_text: str,
            ) -> None:
                out_video.write_bytes(b"video-data")
                out_video.with_suffix(".title.txt").write_text("title", encoding="utf-8")
                out_video.with_suffix(".subs.ass").write_text("ass", encoding="utf-8")

            with patch.object(
                sys,
                "argv",
                [
                    "run_short.py",
                    "--config",
                    str(cfg_path),
                    "--job",
                    str(job_path),
                    "--no-upload",
                ],
            ):
                with (
                    patch("run_short.probe_duration", return_value=10.0),
                    patch("run_short.ensure_background_for_job", side_effect=fake_background),
                    patch("run_short.render_video", side_effect=fake_render),
                    patch("run_short.tts_with_retries", side_effect=lambda fn, **_: fn()),
                    patch("run_short.tts_elevenlabs", side_effect=fake_tts),
                    patch("run_short._apply_srt_timing_guard", return_value=True),
                    patch("sys.stdout", new=io.StringIO()),
                ):
                    rc = run_short.main()

            self.assertEqual(rc, 0)
            self.assertTrue(any(str(p).endswith(".subs.ass") for p in output_dir.glob("*")))

    def test_main_cleanup_all_artifacts_removes_video_and_intermediates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            job_path = self._write_job(td)
            cfg_path = self._write_config(td)
            output_dir = Path(td) / "output"

            def fake_tts(
                text: str,
                out_mp3: Path,
                *,
                voice_id: str,
                api_key: str,
                model_id: str,
                timeout_s: float,
            ) -> None:
                out_mp3.write_bytes(b"mp3-data")

            def fake_background(config: dict, job: run_short.Job, *, duration_s: float, out_path: Path):
                out_path.write_bytes(b"bg")
                return out_path, None

            def fake_render(
                bg: Path,
                audio: Path,
                srt: Path,
                out_video: Path,
                config: dict,
                title_text: str,
            ) -> None:
                out_video.write_bytes(b"video-data")
                out_video.with_suffix(".title.txt").write_text("title", encoding="utf-8")
                out_video.with_suffix(".subs.ass").write_text("ass", encoding="utf-8")

            with patch.object(
                sys,
                "argv",
                [
                    "run_short.py",
                    "--config",
                    str(cfg_path),
                    "--job",
                    str(job_path),
                    "--no-upload",
                    "--cleanup-all-artifacts",
                ],
            ):
                with (
                    patch("run_short.probe_duration", return_value=10.0),
                    patch("run_short.ensure_background_for_job", side_effect=fake_background),
                    patch("run_short.render_video", side_effect=fake_render),
                    patch("run_short.tts_with_retries", side_effect=lambda fn, **_: fn()),
                    patch("run_short.tts_elevenlabs", side_effect=fake_tts),
                    patch("run_short._apply_srt_timing_guard", return_value=True),
                    patch("sys.stdout", new=io.StringIO()),
                ):
                    rc = run_short.main()

            self.assertEqual(rc, 0)
            self.assertEqual(len(list(output_dir.glob("*"))), 0)


if __name__ == "__main__":
    unittest.main()
