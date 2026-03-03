import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_short


class TestRenderVideoSubtitlePosition(unittest.TestCase):
    STYLE_KEYS = [
        "Name",
        "Fontname",
        "Fontsize",
        "PrimaryColour",
        "SecondaryColour",
        "OutlineColour",
        "BackColour",
        "Bold",
        "Italic",
        "Underline",
        "StrikeOut",
        "ScaleX",
        "ScaleY",
        "Spacing",
        "Angle",
        "BorderStyle",
        "Outline",
        "Shadow",
        "Alignment",
        "MarginL",
        "MarginR",
        "MarginV",
        "Encoding",
    ]

    def _run_render_and_get_ass_style(self, config: dict[str, object], *, title: str = "Test title") -> tuple[str, str]:
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            bg = out_dir / "bg.mp4"
            audio = out_dir / "audio.mp3"
            srt = out_dir / "subs.srt"
            out = out_dir / "out.mp4"
            bg.write_text("bg", encoding="utf-8")
            audio.write_text("audio", encoding="utf-8")
            srt.write_text("1\n00:00:00,000 --> 00:00:00,500\nHello", encoding="utf-8")

            full_config: dict[str, object] = {
                "subtitle_playres_y": 1920,
                "subtitle_font_size": 88,
                "subtitle_outline": 8,
            }
            full_config.update(config)

            with (
                patch("run_short.resolve_font_for_korean", return_value=(None, None)),
                patch("run_short.probe_duration", return_value=10.0),
                patch(
                    "run_short.resolve_bin",
                    side_effect=lambda _, key, __: "ffmpeg" if key == "ffmpeg_bin" else "ffprobe",
                ),
                patch("run_short.run") as run_mock,
            ):
                run_short.render_video(bg, audio, srt, out, full_config, title)

            cmd = run_mock.call_args[0][0]
            if "-vf" in cmd:
                vf = cmd[cmd.index("-vf") + 1]
            else:
                vf = cmd[cmd.index("-filter_complex") + 1]

            self.assertIn("ass='", vf)
            ass_path = out.with_suffix(".subs.ass")
            self.assertTrue(ass_path.exists())
            ass_text = ass_path.read_text(encoding="utf-8")
            style_line = next(line for line in ass_text.splitlines() if line.startswith("Style: Default,"))
            return vf, style_line

    def _extract_style_value(self, style_line: str, key: str) -> int:
        values = style_line[len("Style: ") :].split(",")
        style = dict(zip(self.STYLE_KEYS, values))
        self.assertIn(key, style)
        return int(style[key])

    def test_center_middle_default_margin_v_is_zero(self) -> None:
        _vf, style_line = self._run_render_and_get_ass_style({"subtitle_position": "center,middle"})
        self.assertEqual(self._extract_style_value(style_line, "Alignment"), 5)
        self.assertEqual(self._extract_style_value(style_line, "MarginV"), 0)

    def test_center_middle_margin_v_takes_precedence_over_vshift(self) -> None:
        _vf, style_line = self._run_render_and_get_ass_style(
            {"subtitle_position": "center,middle", "subtitle_margin_v": 222, "subtitle_vshift": -110}
        )
        self.assertEqual(self._extract_style_value(style_line, "MarginV"), 222)

    def test_center_middle_vshift_fallback_when_margin_v_not_set(self) -> None:
        _vf, style_line = self._run_render_and_get_ass_style(
            {"subtitle_position": "center,middle", "subtitle_vshift": -110}
        )
        self.assertEqual(self._extract_style_value(style_line, "MarginV"), -110)

    def test_subtitle_align_bottom_compat_uses_bottom_alignment_and_default_margin(self) -> None:
        _vf, style_line = self._run_render_and_get_ass_style({"subtitle_align": "bottom"})
        self.assertEqual(self._extract_style_value(style_line, "Alignment"), 2)
        self.assertEqual(self._extract_style_value(style_line, "MarginV"), 380)


if __name__ == "__main__":
    unittest.main()
