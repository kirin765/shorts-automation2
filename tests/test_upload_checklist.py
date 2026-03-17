from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shorts.config import load_config
from shorts.models import RenderJob
from shorts.upload import validate_upload_checklist


class TestUploadChecklist(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config("ENV")

    def _fake_video_file(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "v.mp4"
        path.write_bytes(b"x")
        return path

    def _job(self, *, title: str = "t", hashtags: str = "#shorts") -> RenderJob:
        return RenderJob(
            title=title,
            script="s",
            description="d",
            hashtags=hashtags,
        )

    def test_missing_title_fails(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "missing title"):
            validate_upload_checklist(
                self.config,
                self._job(title=""),
                self._fake_video_file(),
                ffprobe_data={"streams": [], "format": {}},
            )

    def test_missing_hashtags_fails(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "missing hashtags"):
            validate_upload_checklist(
                self.config,
                self._job(hashtags=""),
                self._fake_video_file(),
                ffprobe_data={"streams": [], "format": {}},
            )

    def test_no_audio_stream_fails(self) -> None:
        ffprobe_data = {
            "streams": [{"codec_type": "video", "width": 1080, "height": 1920}],
            "format": {"duration": "10.0"},
        }
        with self.assertRaisesRegex(RuntimeError, "no audio stream"):
            validate_upload_checklist(self.config, self._job(), self._fake_video_file(), ffprobe_data=ffprobe_data)

    def test_aspect_check_fails(self) -> None:
        ffprobe_data = {
            "streams": [
                {"codec_type": "video", "width": 1920, "height": 1080},
                {"codec_type": "audio"},
            ],
            "format": {"duration": "10.0"},
        }
        with self.assertRaisesRegex(RuntimeError, "not portrait"):
            validate_upload_checklist(self.config, self._job(), self._fake_video_file(), ffprobe_data=ffprobe_data)

    def test_too_long_fails(self) -> None:
        ffprobe_data = {
            "streams": [
                {"codec_type": "video", "width": 1080, "height": 1920},
                {"codec_type": "audio"},
            ],
            "format": {"duration": "61.001"},
        }
        with self.assertRaisesRegex(RuntimeError, "exceeds"):
            validate_upload_checklist(self.config, self._job(), self._fake_video_file(), ffprobe_data=ffprobe_data)

    def test_ok_passes(self) -> None:
        ffprobe_data = {
            "streams": [
                {"codec_type": "video", "width": 1080, "height": 1920},
                {"codec_type": "audio"},
            ],
            "format": {"duration": "28.0"},
        }
        validate_upload_checklist(self.config, self._job(), self._fake_video_file(), ffprobe_data=ffprobe_data)
