import tempfile
import unittest
from pathlib import Path

import run_short


class TestUploadChecklist(unittest.TestCase):
    def _fake_video_file(self) -> Path:
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        p = Path(d.name) / "v.mp4"
        p.write_bytes(b"x")
        return p

    def _job(self, *, title: str = "t", hashtags: str = "#shorts") -> run_short.Job:
        return run_short.Job(
            title=title,
            script="s",
            description="d",
            hashtags=hashtags,
            pexels_query=None,
            topic=None,
            style=None,
            tone=None,
            target_seconds=28,
        )

    def test_missing_title_fails(self) -> None:
        p = self._fake_video_file()
        with self.assertRaisesRegex(RuntimeError, "missing title"):
            run_short.validate_upload_checklist({}, self._job(title=""), p, ffprobe_data={"streams": [], "format": {}})

    def test_missing_hashtags_fails(self) -> None:
        p = self._fake_video_file()
        with self.assertRaisesRegex(RuntimeError, "missing hashtags"):
            run_short.validate_upload_checklist({}, self._job(hashtags=""), p, ffprobe_data={"streams": [], "format": {}})

    def test_no_audio_stream_fails(self) -> None:
        p = self._fake_video_file()
        ff = {
            "streams": [
                {"codec_type": "video", "width": 1080, "height": 1920},
            ],
            "format": {"duration": "10.0"},
        }
        with self.assertRaisesRegex(RuntimeError, "no audio stream"):
            run_short.validate_upload_checklist({}, self._job(), p, ffprobe_data=ff)

    def test_aspect_check_fails(self) -> None:
        p = self._fake_video_file()
        ff = {
            "streams": [
                {"codec_type": "video", "width": 1920, "height": 1080},
                {"codec_type": "audio"},
            ],
            "format": {"duration": "10.0"},
        }
        with self.assertRaisesRegex(RuntimeError, "not portrait"):
            run_short.validate_upload_checklist(
                {"youtube": {"min_width": 1, "min_height": 1}},
                self._job(),
                p,
                ffprobe_data=ff,
            )

    def test_too_long_fails(self) -> None:
        p = self._fake_video_file()
        ff = {
            "streams": [
                {"codec_type": "video", "width": 1080, "height": 1920},
                {"codec_type": "audio"},
            ],
            "format": {"duration": "61.001"},
        }
        with self.assertRaisesRegex(RuntimeError, "exceeds"):
            run_short.validate_upload_checklist({"youtube": {"max_duration_s": 60}}, self._job(), p, ffprobe_data=ff)

    def test_ok_passes(self) -> None:
        p = self._fake_video_file()
        ff = {
            "streams": [
                {"codec_type": "video", "width": 1080, "height": 1920},
                {"codec_type": "audio"},
            ],
            "format": {"duration": "28.0"},
        }
        run_short.validate_upload_checklist({}, self._job(), p, ffprobe_data=ff)


if __name__ == "__main__":
    unittest.main()
