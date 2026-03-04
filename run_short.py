from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import textwrap
import traceback
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Literal
from urllib.parse import quote_plus

from config_loader import ENV_SENTINEL, load_config

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


@dataclass
class Job:
    title: str | None
    script: str | None
    description: str | None
    hashtags: str | None
    pexels_query: str | None = None
    topic: str | None = None
    style: str | None = None
    tone: str | None = None
    target_seconds: int | None = None
    subtopic: str | None = None


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr}")


def resolve_bin(config: dict, key: str, default: str) -> str:
    """Resolve an external binary path.

    Prefer explicit config (e.g. ffmpeg_bin), otherwise fall back to PATH lookup.
    """
    explicit = (config.get(key) or "").strip()
    if explicit:
        return explicit
    found = shutil.which(default)
    if found:
        return found
    if default == "ffmpeg":
        for alt in (
            "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
            "/usr/local/opt/ffmpeg-full/bin/ffmpeg",
            shutil.which("ffmpeg-full"),
        ):
            if alt and Path(alt).exists():
                return str(alt)
    elif default == "ffprobe":
        for alt in (
            "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe",
            "/usr/local/opt/ffmpeg-full/bin/ffprobe",
            shutil.which("ffprobe-full"),
        ):
            if alt and Path(alt).exists():
                return str(alt)
    raise RuntimeError(
        f"Required binary not found: {default}. "
        f"Install it or set `{key}` via env/config to an absolute path."
    )


def probe_duration(path: Path, *, ffprobe: str = "ffprobe") -> float:
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def split_for_captions(text: str) -> list[str]:
    clean = re.sub(r"\s+", " ", text).strip()
    chunks = re.split(r"(?<=[.!?])\s+", clean)
    out: list[str] = []
    for c in chunks:
        c = c.strip()
        if not c:
            continue
        if len(c) > 28:
            out.extend(textwrap.wrap(c, width=26, break_long_words=False))
        else:
            out.append(c)
    return out


def split_for_captions_dense(text: str, *, max_chars: int = 22) -> list[str]:
    """More aggressive caption splitting for fast Shorts pacing.

    Notes:
    - Favor splitting on natural pause points (sentence end, commas, connectors).
    - Keep each line short (<= max_chars) for readability on mobile.
    """
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return []

    # Split on sentence-ish boundaries, then on softer pauses.
    chunks = re.split(r"(?<=[.!?…])\s+|[,:;，：；]\s*", clean)
    out: list[str] = []
    for c in chunks:
        c = c.strip()
        if not c:
            continue
        # Extra split on common Korean connectors if the chunk is still long.
        if len(c) > max_chars + 6:
            # Keep the connector token at the beginning of the next line.
            for conn in (
                " 그리고 ",
                " 그래서 ",
                " 하지만 ",
                " 그런데 ",
                " 즉 ",
                " 다시 말해 ",
                " 예를 들어 ",
                " 왜냐하면 ",
                " 왜냐면 ",
                " 반대로 ",
                " 대신 ",
                " 다시 ",
            ):
                c = c.replace(conn, conn.rstrip() + "\n")
            parts = [p.strip() for p in c.split("\n") if p.strip()]
        else:
            parts = [c]

        for p in parts:
            # Handle common bullet-like separators in scripts.
            p = re.sub(r"\s*[-/|]\s*", " ", p).strip()
            if len(p) > max_chars:
                out.extend(textwrap.wrap(p, width=max_chars, break_long_words=False))
            else:
                out.append(p)
    return out


def fmt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def _coerce_int(value, *, default: int, key: str | None = None, min_value: int = 0) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        if key is not None:
            print(f"[-] Invalid numeric config '{key}'={value!r}; using default {default}.")
        return default

    if n < min_value:
        if key is not None:
            print(f"[-] Config '{key}'={n} is below minimum ({min_value}); using default {default}.")
        return default

    return n


def _coerce_float(value, *, default: float, key: str | None = None) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        if key is not None:
            print(f"[-] Invalid numeric config '{key}'={value!r}; using default {default}.")
        return default


def _coerce_bool(value, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _resolve_openai_language(value: object) -> str:
    """Normalize optional OpenAI language settings.

    Returns an empty string for unset/blank/auto/none values so callers can
    rely on API-side language auto-detection.
    """
    raw = "" if value is None else str(value).strip()
    if not raw:
        return ""
    if raw.lower() in {"auto", "none"}:
        return ""
    return raw


def _cleanup_paths(paths: Iterable[Path], *, preserve: set[Path] | None = None) -> None:
    preserved = preserve or set()
    for path in set(paths):
        if path in preserved:
            continue
        try:
            path.unlink(missing_ok=True)
        except Exception as e:
            print(f"[-] Failed to remove temporary artifact {path}: {_one_line(str(e))}")


def _is_sample_output_dir(path: Path) -> bool:
    lowered = str(path).replace("\\", "/").lower()
    return "tmp_sample" in lowered and "run" in lowered


def _normalize_subtitle_position(value) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        print("[-] subtitle_position is empty. Falling back to center,middle.")
        return "center,middle"

    parts = [p.strip() for p in normalized.split(",")]
    if len(parts) != 2:
        print(f"[-] Invalid subtitle_position '{normalized}'. Falling back to center,middle.")
        return "center,middle"

    horizontal, vertical = parts
    if horizontal not in {"left", "center", "right"}:
        print(f"[-] Invalid subtitle horizontal position '{horizontal}'. Falling back to center,middle.")
        return "center,middle"

    if vertical not in {"top", "middle", "bottom"}:
        print(f"[-] Invalid subtitle vertical position '{vertical}'. Falling back to center,middle.")
        return "center,middle"

    return f"{horizontal},{vertical}"


def _align_from_position(position: str) -> int:
    horizontal, vertical = _normalize_subtitle_position(position).split(",")

    return {
        "top": {"left": 7, "center": 8, "right": 9},
        "middle": {"left": 4, "center": 5, "right": 6},
        "bottom": {"left": 1, "center": 2, "right": 3},
    }[vertical][horizontal]


def _font_name_from_path(fontfile: str) -> str:
    stem = Path(fontfile).stem
    name = stem.replace("_", " ").replace("-", " ")
    name = re.sub(r"(?<=[a-zA-Z])(?=[A-Z])", " ", name)
    return " ".join(name.split())


def _coerce_font_name(family: str | None, fontfile: str | None = None) -> str:
    if family:
        return ",".join(part.strip() for part in family.split(",") if part.strip()) or "Noto Sans CJK KR"
    if fontfile:
        return _font_name_from_path(fontfile)
    return "Noto Sans CJK KR"


def _parse_srt_timestamp_to_seconds(value: str) -> float:
    h, m, rest = value.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def _read_srt_timing_lines(path: Path) -> list[tuple[int, float, float]]:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    if not raw.strip():
        raise ValueError("subtitle file is empty")

    lines = raw.splitlines()
    timing_pattern = re.compile(r"^(?P<start>\d\d:\d\d:\d\d,\d\d\d)\s*-->\s*(?P<end>\d\d:\d\d:\d\d,\d\d\d)\s*$")
    out: list[tuple[int, float, float]] = []
    for i, line in enumerate(lines):
        if "-->" not in line:
            continue
        match = timing_pattern.match(line.strip())
        if not match:
            raise ValueError(f"invalid timing format at line {i + 1}: {line!r}")
        start = _parse_srt_timestamp_to_seconds(match.group("start"))
        end = _parse_srt_timestamp_to_seconds(match.group("end"))
        out.append((i, start, end))

    if not out:
        raise ValueError("subtitle file has no timing lines")
    return out


def _format_ass_timestamp(seconds: float) -> str:
    total_cs = max(0, int(round(float(seconds) * 100.0)))
    h = total_cs // 360000
    m = (total_cs % 360000) // 6000
    s = (total_cs % 6000) // 100
    cs = total_cs % 100
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def _escape_ass_text(text: str) -> str:
    escaped = text.replace("\\", r"\\")
    escaped = escaped.replace("{", r"\{").replace("}", r"\}")
    escaped = escaped.replace("\r\n", "\n").replace("\r", "\n")
    return escaped.replace("\n", r"\N")


def _read_srt_cues_for_ass(path: Path) -> list[tuple[float, float, str]]:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    if not raw.strip():
        raise ValueError("subtitle file is empty")

    blocks = re.split(r"\n\s*\n", raw.replace("\r\n", "\n").replace("\r", "\n").strip())
    timing_pattern = re.compile(r"^(?P<start>\d\d:\d\d:\d\d,\d\d\d)\s*-->\s*(?P<end>\d\d:\d\d:\d\d,\d\d\d)\s*$")
    cues: list[tuple[float, float, str]] = []

    for block in blocks:
        lines = [line.rstrip() for line in block.split("\n")]
        if not lines:
            continue

        idx = 0
        if re.fullmatch(r"\d+", lines[0].strip()):
            idx = 1
        if idx >= len(lines):
            continue

        match = timing_pattern.match(lines[idx].strip())
        if not match:
            raise ValueError(f"invalid timing line in subtitle block: {lines[idx]!r}")

        start = _parse_srt_timestamp_to_seconds(match.group("start"))
        end = _parse_srt_timestamp_to_seconds(match.group("end"))
        text_lines = [line.strip() for line in lines[idx + 1 :] if line.strip()]
        if not text_lines:
            continue
        cues.append((start, end, "\n".join(text_lines)))

    if not cues:
        raise ValueError("subtitle file has no usable cues")
    return cues


def _write_ass_from_srt(
    srt_path: Path,
    ass_path: Path,
    *,
    playres_y: int,
    font_name: str,
    font_size: int,
    outline: int,
    alignment: int,
    margin_v: int,
) -> None:
    cues = _read_srt_cues_for_ass(srt_path)
    ass_font_name = (font_name.split(",")[0].strip() if font_name else "") or "Noto Sans CJK KR"

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "PlayResX: 1080",
        f"PlayResY: {max(1, int(playres_y))}",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        (
            "Style: Default,"
            f"{ass_font_name},{int(font_size)},"
            "&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,"
            f"0,0,0,0,100,100,0,0,1,{int(outline)},0,{int(alignment)},20,20,{int(margin_v)},1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    for start, end, text in cues:
        if end <= start:
            end = start + 0.05
        lines.append(
            f"Dialogue: 0,{_format_ass_timestamp(start)},{_format_ass_timestamp(end)},Default,,0,0,0,,{_escape_ass_text(text)}"
        )

    ass_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_last_srt_end_time(path: Path) -> float:
    return _read_srt_timing_lines(path)[-1][2]


def _repair_srt_timing(
    path: Path,
    audio_duration: float,
    *,
    enabled: bool = True,
    max_drift: float = 0.5,
    max_scale_delta: float = 0.12,
    label: str = "srt",
) -> bool:
    if not enabled:
        print(f"[subtitles] repair disabled for {label}; using raw timing.")
        return _validate_srt_timing(path, audio_duration, max_drift=max_drift)

    try:
        entries = _read_srt_timing_lines(path)
        raw = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception as e:
        print(f"[-] subtitle repair parse failed ({label}): {e}")
        return False

    if not entries:
        print(f"[-] subtitle repair failed ({label}): no timing entries found")
        return False

    starts = [start for _, start, _ in entries]
    ends = [end for _, _, end in entries]
    first_start = starts[0]
    last_end = ends[-1]
    initial_drift = abs(last_end - audio_duration)
    applied_shift = 0.0
    applied_scale = 1.0
    should_apply = False

    if first_start > 0 and first_start <= max_drift:
        # remove leading silence by shifting all cue timings backward
        shift = -first_start
        entries = [
            (i, max(0.0, start + shift), max(0.0, end + shift))
            for (i, start, end) in entries
        ]
        first_start = 0.0
        last_end = entries[-1][2]
        applied_shift = shift
        should_apply = True

    drift_after_shift = abs(last_end - audio_duration)
    if drift_after_shift > max_drift and audio_duration > 0 and entries:
        target_scale = audio_duration / last_end
        target_scale = max(1.0 - max_scale_delta, min(1.0 + max_scale_delta, target_scale))
        if abs(target_scale - 1.0) > 1e-9:
            entries = [
                (i, start * target_scale, end * target_scale)
                for (i, start, end) in entries
            ]
            last_end = entries[-1][2]
            applied_scale = target_scale
            should_apply = True

    if not should_apply:
        print(
            f"[subtitles] {label} timing repair skipped: first_start={first_start:.3f}s, "
            f"initial_drift={initial_drift:.2f}s"
        )
        return True

    fixed_lines = raw[:]
    for idx, start, end in entries:
        fixed_lines[idx] = f"{fmt_time(start)} --> {fmt_time(end)}"

    try:
        path.write_text("\n".join(fixed_lines), encoding="utf-8")
    except Exception as e:
        print(f"[-] Failed to write repaired subtitles ({label}): {e}")
        return False

    final_drift = abs(last_end - audio_duration)
    print(
        f"[subtitles] repair label={label} applied_shift={applied_shift:.3f}s "
        f"applied_scale={applied_scale:.6f} initial_drift={initial_drift:.2f}s final_drift={final_drift:.2f}s "
        f"file={path}"
    )
    return True


def _validate_srt_timing(path: Path, audio_duration: float, *, max_drift: float = 0.5) -> bool:
    try:
        last_end = _read_last_srt_end_time(path)
    except Exception as e:
        print(f"[-] Invalid subtitle timing ({e}); file={path}")
        return False

    if last_end <= 0:
        print(f"[-] Subtitle timing invalid: last_end={last_end:.2f} (file={path})")
        return False

    drift = abs(last_end - audio_duration)
    if drift > max_drift:
        print(f"[-] Subtitle timing drift={drift:.2f}s exceeded threshold ({max_drift}s). file={path}, audio={audio_duration:.2f}, last_end={last_end:.2f}")
        return False

    return True


def _apply_srt_timing_guard(
    path: Path,
    audio_duration: float,
    *,
    enabled: bool,
    repair_max_drift: float,
    max_scale_delta: float,
    validate_max_drift: float,
    label: str,
) -> bool:
    if enabled:
        if not _repair_srt_timing(
            path,
            audio_duration,
            max_drift=repair_max_drift,
            max_scale_delta=max_scale_delta,
            label=label,
        ):
            print(f"[-] {label} subtitle repair failed; moving to fallback.")
            return False

    return _validate_srt_timing(path, audio_duration, max_drift=validate_max_drift)


def write_srt(lines: list[str], duration: float, srt_path: Path) -> None:
    if not lines:
        lines = ["..."]
    chunk = duration / len(lines)
    cursor = 0.0
    blocks = []
    for i, line in enumerate(lines, start=1):
        start = cursor
        end = duration if i == len(lines) else cursor + chunk
        blocks.append(f"{i}\n{fmt_time(start)} --> {fmt_time(end)}\n{line}\n")
        cursor = end
    srt_path.write_text("\n".join(blocks), encoding="utf-8")


def write_srt_aligned_openai(
    config: dict,
    *,
    audio_path: Path,
    srt_path: Path,
    prompt_text: str,
    script_text: str,
) -> None:
    """Generate SRT using OpenAI transcription timestamps.

    Falls back to segment-level timing if word timing is unavailable.
    """
    import requests

    api_key = _openai_api_key(config)
    base_url = (config.get("openai_base_url") or "https://api.openai.com/v1").rstrip("/")
    model = (config.get("openai_transcribe_model") or "whisper-1").strip()
    timeout_s = int(config.get("openai_transcribe_timeout_s", 60))
    transcribe_lang = _resolve_openai_language(config.get("openai_transcribe_language"))

    files = {"file": (audio_path.name, audio_path.read_bytes(), "audio/mpeg")}
    data = {
        "model": model,
        "response_format": "verbose_json",
        "prompt": (prompt_text or "")[:4000],
    }
    if transcribe_lang:
        # API expects ISO language codes like "ko", "en".
        data["language"] = transcribe_lang
    # Ask for word-level timestamps when supported.
    # The API accepts repeated timestamp_granularities[] keys in multipart form.
    data["timestamp_granularities[]"] = ["word", "segment"]

    r = requests.post(
        f"{base_url}/audio/transcriptions",
        headers={"Authorization": f"Bearer {api_key}"},
        files=files,
        data=data,
        timeout=timeout_s,
    )
    r.raise_for_status()
    obj = r.json()

    max_chars = int(config.get("subtitle_max_chars", 26))
    min_cue = float(config.get("subtitle_min_cue_s", 0.45))
    max_cue = float(config.get("subtitle_max_cue_s", 3.5))
    max_words = int(config.get("subtitle_words_per_cue", 10))

    blocks: list[str] = []
    windows: list[tuple[float, float]] = []
    transcript_lines: list[str] = []

    def add_window(start: float, end: float) -> None:
        # Enforce sane durations.
        if end <= start:
            end = start + min_cue
        dur = end - start
        if dur < min_cue:
            end = start + min_cue
        elif dur > max_cue:
            end = start + max_cue
        windows.append((start, end))

    def add_block(i: int, start: float, end: float, text: str) -> None:
        if not text.strip():
            return
        blocks.append(f"{i}\n{fmt_time(start)} --> {fmt_time(end)}\n{text.strip()}\n")

    words = obj.get("words") or []
    if isinstance(words, list) and words:
        cue_words: list[dict] = []
        cue_text = ""
        for w in words:
            if not isinstance(w, dict):
                continue
            wt = str(w.get("word") or "").strip()
            if not wt:
                continue
            # Build display text with spaces when transcription returns word tokens.
            next_text = (cue_text + (" " if cue_text else "") + wt).strip()
            cue_words.append(w)
            cue_text = next_text
            if len(cue_words) >= max_words or len(cue_text) >= max_chars or wt.endswith((".", "!", "?", "…")):
                start = float(cue_words[0].get("start") or 0.0)
                end = float(cue_words[-1].get("end") or start)
                add_window(start, end)
                transcript_lines.append(cue_text.strip())
                cue_words = []
                cue_text = ""
        if cue_words:
            start = float(cue_words[0].get("start") or 0.0)
            end = float(cue_words[-1].get("end") or start)
            add_window(start, end)
            transcript_lines.append(cue_text.strip())
    else:
        # Segment-level fallback.
        segs = obj.get("segments") or []
        if not isinstance(segs, list) or not segs:
            raise RuntimeError("transcription returned no segments/words")

        for seg in segs:
            if not isinstance(seg, dict):
                continue
            text = str(seg.get("text") or "").strip()
            if not text:
                continue
            start = float(seg.get("start") or 0.0)
            end = float(seg.get("end") or start)
            parts = textwrap.wrap(text, width=max_chars, break_long_words=False) or [text]
            if len(parts) == 1:
                add_window(start, end)
                transcript_lines.append(parts[0].strip())
                continue
            total = sum(max(1, len(p)) for p in parts)
            cur = start
            for p in parts:
                share = (max(1, len(p)) / total) * max(0.01, end - start)
                add_window(cur, cur + share)
                transcript_lines.append(p.strip())
                cur += share

    # Decide subtitle text source.
    text_source = (config.get("subtitle_text_source") or "transcript").strip().lower()
    if text_source not in ("transcript", "script"):
        text_source = "transcript"

    if text_source == "script":
        # Use original script for on-screen text, but keep Whisper timing windows.
        # Split more aggressively for a "Shorts" pacing.
        lines = split_for_captions_dense(script_text or "", max_chars=max_chars) or split_for_captions(script_text or "")
        if not windows:
            raise RuntimeError("no timing windows produced")

        def resample_windows(src: list[tuple[float, float]], target_n: int) -> list[tuple[float, float]]:
            if target_n <= len(src):
                return src[:target_n]
            out = list(src)
            # Split the longest window until we have enough.
            while len(out) < target_n:
                idx = max(range(len(out)), key=lambda i: (out[i][1] - out[i][0]))
                s, e = out[idx]
                if e - s <= (min_cue * 2.05):
                    break
                mid = (s + e) / 2.0
                out[idx : idx + 1] = [(s, mid), (mid, e)]
            # If still short, append tiny windows at end (rare; keeps code from crashing).
            while len(out) < target_n:
                s, e = out[-1]
                out.append((e, e + min_cue))
            return out

        # Match the number of timing windows to the desired number of script lines.
        win = resample_windows(windows, len(lines))

        for i, ((start, end), text) in enumerate(zip(win, lines), start=1):
            add_block(i, start, end, text)
        srt_path.write_text("\n".join(blocks), encoding="utf-8")
        return

    # Default: use transcript text.
    for i, ((start, end), text) in enumerate(zip(windows, transcript_lines), start=1):
        add_block(i, start, end, text)
    srt_path.write_text("\n".join(blocks), encoding="utf-8")
    return


def tts_elevenlabs(
    text: str,
    out_mp3: Path,
    *,
    voice_id: str,
    api_key: str,
    model_id: str = "eleven_multilingual_v2",
    timeout_s: float = 40.0,
) -> None:
    """ElevenLabs TTS for more natural speech.

    This function only performs one request attempt and returns a focused error
    when API/network behavior is not successful.
    """
    if not text.strip():
        raise RuntimeError("elevenlabs_tts empty text")

    import requests

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "accept": "audio/mpeg",
        "content-type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": 0.45,
            "similarity_boost": 0.80,
            "style": 0.25,
            "use_speaker_boost": True,
        },
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=float(timeout_s))
    except requests.Timeout as e:
        raise RuntimeError(f"elevenlabs_tts timeout after {float(timeout_s):.1f}s: {e}") from e
    except requests.RequestException as e:
        raise RuntimeError(f"elevenlabs_tts network error: {e}") from e

    status = int(r.status_code)
    if status == 429 or status >= 500:
        body = _one_line((r.text or "").strip())[:240]
        raise RuntimeError(f"elevenlabs_tts transient failure: status={status}, body={body}")
    if 400 <= status < 500:
        body = _one_line((r.text or "").strip())[:240]
        raise RuntimeError(f"elevenlabs_tts client failure: status={status}, body={body}")
    if status not in (200, 201):
        body = _one_line((r.text or "").strip())[:240]
        raise RuntimeError(f"elevenlabs_tts unexpected status={status}: body={body}")

    if not r.content:
        raise RuntimeError("elevenlabs_tts returned empty audio payload")

    ctype = (r.headers.get("content-type") or "").lower()
    if "audio/mpeg" not in ctype and "audio/mp3" not in ctype:
        raise RuntimeError(
            f"elevenlabs_tts returned non-audio content-type: {r.headers.get('content-type')!r}"
        )

    out_mp3.write_bytes(r.content)


def _is_retryable_tts_error(err: BaseException) -> bool:
    msg = (str(err) or "").lower()
    if "timeout" in msg:
        return True
    if "network error" in msg:
        return True
    if "transient" in msg:
        return True
    if "status=429" in msg:
        return True
    if "status=500" in msg:
        return True
    if "status=502" in msg:
        return True
    if "status=503" in msg:
        return True
    if "status=504" in msg:
        return True
    return False


def tts_with_retries(
    fn: Callable[[], None],
    *,
    label: str,
    max_attempts: int,
    initial_backoff_s: float,
    max_backoff_s: float,
    log_fn: Callable[[str], None] = print,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> None:
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    delay = max(0.0, float(initial_backoff_s))
    max_delay = max(0.0, float(max_backoff_s))

    for attempt in range(1, max_attempts + 1):
        try:
            fn()
            return
        except Exception as e:
            if (not _is_retryable_tts_error(e)) or attempt >= max_attempts:
                raise

            log_fn(f"[{label}] attempt {attempt}/{max_attempts} failed: {_one_line(str(e))}")
            log_fn(f"[{label}] retrying in {delay:.1f}s")
            if delay > 0:
                sleep_fn(delay)
            delay = min(max_delay, max(1.0, delay * 2.0)) if max_delay > 0 else 0.0


def densify_srt_inplace(srt_path: Path, *, max_chars: int = 26) -> None:
    """Split long SRT cues into shorter ones without changing overall timing."""

    def parse_time(t: str) -> float:
        # "HH:MM:SS,mmm"
        h, m, rest = t.split(":")
        s, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

    def fmt_sec(sec: float) -> str:
        return fmt_time(max(0.0, sec))

    raw = srt_path.read_text(encoding="utf-8", errors="ignore")
    blocks = re.split(r"\n\s*\n", raw.strip(), flags=re.M)
    out_blocks: list[str] = []
    idx = 1
    for b in blocks:
        lines = [ln.rstrip("\r") for ln in b.splitlines() if ln.strip() != ""]
        if len(lines) < 3:
            continue
        # Best-effort: first line is index, second is timing.
        timing = lines[1] if "-->" in lines[1] else lines[0]
        m = re.match(r"(\d\d:\d\d:\d\d,\d\d\d)\s*-->\s*(\d\d:\d\d:\d\d,\d\d\d)", timing)
        if not m:
            continue
        start = parse_time(m.group(1))
        end = parse_time(m.group(2))
        text = " ".join(lines[2:]).strip()
        if not text:
            continue

        parts = split_for_captions_dense(text, max_chars=max_chars) or [text]
        if len(parts) == 1:
            out_blocks.append(f"{idx}\n{fmt_sec(start)} --> {fmt_sec(end)}\n{parts[0]}\n")
            idx += 1
            continue

        total = sum(max(1, len(p)) for p in parts)
        cur = start
        dur = max(0.01, end - start)
        for p in parts:
            share = (max(1, len(p)) / total) * dur
            out_blocks.append(f"{idx}\n{fmt_sec(cur)} --> {fmt_sec(cur + share)}\n{p}\n")
            idx += 1
            cur += share

    srt_path.write_text("\n".join(out_blocks).strip() + "\n", encoding="utf-8")


def _openai_api_key(config: dict) -> str:
    key = (config.get("openai_api_key") or os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError(
            "?蹂??먮룞 ?앹꽦(OpenAI)???곕젮硫?API ?ㅺ? ?꾩슂?⑸땲?? "
            "?섍꼍蹂??`OPENAI_API_KEY`瑜??ㅼ젙?섏꽭?? (?먮뒗 config??`openai_api_key`)"
        )
    return key


def openai_generate_job(config: dict, job: Job) -> Job:
    """Generate job fields (title/script/description/hashtags/pexels_query) via OpenAI Responses API."""
    import requests

    api_key = _openai_api_key(config)
    base_url = (config.get("openai_base_url") or "https://api.openai.com/v1").rstrip("/")
    model = (config.get("openai_script_model") or config.get("openai_model") or "gpt-4o-mini").strip()
    timeout_s = int(config.get("openai_timeout_s", 40))
    temperature = float(config.get("openai_temperature", 0.7))
    max_tokens = int(config.get("openai_max_output_tokens", 650))

    language = _resolve_openai_language(config.get("openai_script_language"))
    if not language:
        language = _resolve_openai_language(config.get("openai_language"))
    if not language:
        language = str(config.get("default_language", "")).strip() or ""
    target_seconds = int(job.target_seconds or config.get("shorts_target_seconds", 28))

    topic = (job.topic or job.title or "").strip()
    if not topic:
        topic = "shorts topic"
    subtopic = (job.subtopic or "").strip()

    # Avoid hallucinated hard facts; keep it general unless user supplies facts in the topic.
    system = (
        "You write high-retention YouTube Shorts scripts. "
        "Do not invent precise statistics, dates, prices, quotes, or named sources. "
        "If you need numbers, use vague ranges (e.g., 'around 10~20%', '일부 사용자 10~20%') or omit them. "
        "Use natural Korean sentence style in the output. "
        "Keep sentences short and punchy. Output must be valid JSON matching the provided schema."
    )
    user_parts = [
        f"Topic: {topic}",
    ]
    if subtopic:
        user_parts.append(f"Subtopic: {subtopic}")
    user_parts.extend(
        [
        f"Style: {job.style or 'tech news / explain like I am busy'}",
        f"Tone: {job.tone or 'confident, concise'}",
        f"Target duration: about {target_seconds} seconds of narration.",
        "Use topic/subtopic phrasing as context, then write one clear title and script."
    ])
    if language:
        user_parts.insert(0, f"Language: {language}")
    user = (
        "\n".join(user_parts)
        + "\n"
        + "\n".join(
            [
                "Output rules:",
                "- title: <= 28 chars, curiosity-driven, no clickbait lies.",
                "- script: 5-7 sentences total. First sentence must be the hook.",
                "- script: avoid long clauses; prefer short lines that are easy to subtitle.",
                "- description: 1-2 sentences summary.",
                "- hashtags: 3-5 tags including #shorts.",
                "- pexels_query: 4-8 English words, no brand names.",
                "Structure:",
                "1) Hook",
                "2) 3-5 beats (each beat 1 sentence)",
                "3) Wrap-up + subtle CTA (e.g., '???뚭퀬 ?띠쑝硫????)",
            ]
        )
    )

    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string"},
            "script": {"type": "string"},
            "description": {"type": "string"},
            "hashtags": {"type": "string"},
            "pexels_query": {"type": "string"},
        },
        "required": ["title", "script", "description", "hashtags", "pexels_query"],
    }

    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_output_tokens": max_tokens,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "shorts_job",
                "schema": schema,
                "strict": True,
            }
        },
        "store": False,
    }

    r = requests.post(
        f"{base_url}/responses",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=timeout_s,
    )
    r.raise_for_status()
    data = r.json()

    text_out = None
    for item in data.get("output", []) or []:
        for c in item.get("content", []) or []:
            if c.get("type") in ("output_text", "text") and isinstance(c.get("text"), str):
                text_out = c["text"]
                break
        if text_out:
            break
    if not text_out:
        raise RuntimeError("OpenAI ?묐떟?먯꽌 ?띿뒪?몃? 李얠? 紐삵뻽?듬땲??")

    obj = json.loads(text_out)
    title = (obj.get("title") or "").strip()
    script = (obj.get("script") or "").strip()
    description = (obj.get("description") or "").strip()
    hashtags = (obj.get("hashtags") or "").strip()
    pexels_query = (obj.get("pexels_query") or "").strip()
    if not (title and script and description and hashtags and pexels_query):
        raise RuntimeError("OpenAI returned incomplete job fields. expected title/script/description/hashtags/pexels_query")

    return Job(
        title=title,
        script=script,
        description=description,
        hashtags=hashtags,
        pexels_query=pexels_query,
        topic=job.topic,
        style=job.style,
        tone=job.tone,
        target_seconds=job.target_seconds,
        subtopic=job.subtopic,
    )


def ensure_background(config: dict) -> Path:
    raise RuntimeError("deprecated: use ensure_background_for_job()")


def _slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.strip().lower()).strip("-")
    return s or "bg"


def guess_pexels_query(job: Job) -> str:
    # Prefer explicit per-job query when provided.
    if (job.pexels_query or "").strip():
        return (job.pexels_query or "").strip()

    t = f"{job.subtopic or ''} {job.topic or ''} {job.title or ''} {job.script or ''}".lower()
    # Cheap topic heuristics: Pexels search works best with English keywords.
    if "ai.com" in t or "ai" in t or "인공지능" in t:
        return "artificial intelligence abstract technology"
    if "주식" in t or "stock" in t:
        return "stock market abstract"
    if "부동산" in t or "real estate" in t:
        return "city skyline"
    return "abstract background"


def pexels_video_search(
    *,
    api_key: str,
    query: str,
    orientation: str = "portrait",
    per_page: int = 10,
    min_height: int = 1920,
    timeout_s: int = 20,
) -> dict:
    """Search videos via Pexels API and pick a portrait-ish mp4.

    Pexels API docs: https://www.pexels.com/api/documentation/ (video endpoints use /videos/).
    """
    import requests

    url = (
        "https://api.pexels.com/videos/search"
        f"?query={quote_plus(query)}&per_page={per_page}&orientation={quote_plus(orientation)}"
    )
    r = requests.get(url, headers={"Authorization": api_key}, timeout=timeout_s)
    r.raise_for_status()
    data = r.json()

    best: dict | None = None
    best_file: dict | None = None

    for v in data.get("videos", []) or []:
        w = int(v.get("width") or 0)
        h = int(v.get("height") or 0)
        if h <= 0 or w <= 0:
            continue
        # Filter to portrait-ish results.
        if h < w:
            continue

        for f in v.get("video_files", []) or []:
            if (f.get("file_type") or "").lower() != "video/mp4":
                continue
            fw = int(f.get("width") or 0)
            fh = int(f.get("height") or 0)
            if fh < fw:
                continue
            if fh < min_height:
                continue

            # Prefer larger height then width.
            score = fh * 10000 + fw
            if not best_file or score > (int(best_file.get("_score", 0))):
                f = dict(f)
                f["_score"] = score
                best = v
                best_file = f

    if not best or not best_file:
        raise RuntimeError(f"No suitable Pexels portrait mp4 found for query={query!r}")

    # Return minimal metadata needed for download/credit.
    return {
        "video_id": best.get("id"),
        "page_url": best.get("url"),
        "user_name": (best.get("user") or {}).get("name"),
        "user_url": (best.get("user") or {}).get("url"),
        "download_url": best_file.get("link"),
        "width": best_file.get("width"),
        "height": best_file.get("height"),
        "duration": best.get("duration"),
        "query": query,
        "orientation": orientation,
    }


def pexels_video_search_many(
    *,
    api_key: str,
    query: str,
    orientation: str = "portrait",
    per_page: int = 15,
    min_height: int = 1600,
    k: int = 3,
    timeout_s: int = 20,
) -> list[dict]:
    """Return up to k best unique videos (mp4 portrait-ish)."""
    import requests

    url = (
        "https://api.pexels.com/videos/search"
        f"?query={quote_plus(query)}&per_page={per_page}&orientation={quote_plus(orientation)}"
    )
    r = requests.get(url, headers={"Authorization": api_key}, timeout=timeout_s)
    r.raise_for_status()
    data = r.json()

    scored: list[tuple[int, dict, dict]] = []
    for v in data.get("videos", []) or []:
        w = int(v.get("width") or 0)
        h = int(v.get("height") or 0)
        if h <= 0 or w <= 0 or h < w:
            continue
        vid = v.get("id")
        if not vid:
            continue

        for f in v.get("video_files", []) or []:
            if (f.get("file_type") or "").lower() != "video/mp4":
                continue
            fw = int(f.get("width") or 0)
            fh = int(f.get("height") or 0)
            if fh < fw or fh < min_height:
                continue
            score = fh * 10000 + fw
            scored.append((score, v, f))

    scored.sort(key=lambda t: t[0], reverse=True)
    out: list[dict] = []
    seen: set[int] = set()
    for _, v, f in scored:
        vid = int(v.get("id"))
        if vid in seen:
            continue
        seen.add(vid)
        out.append(
            {
                "video_id": v.get("id"),
                "page_url": v.get("url"),
                "user_name": (v.get("user") or {}).get("name"),
                "user_url": (v.get("user") or {}).get("url"),
                "download_url": f.get("link"),
                "width": f.get("width"),
                "height": f.get("height"),
                "duration": v.get("duration"),
                "query": query,
                "orientation": orientation,
            }
        )
        if len(out) >= k:
            break

    if not out:
        raise RuntimeError(f"No suitable Pexels portrait mp4 found for query={query!r}")
    return out


def download_file(url: str, out_path: Path, *, timeout_s: int = 60) -> None:
    import requests

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".part")

    with requests.get(url, stream=True, timeout=timeout_s) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                f.write(chunk)
    tmp.replace(out_path)


def _pick_pexels_offset(meta: dict, seg_s: float) -> float:
    try:
        dur = float(meta.get("duration") or 0.0)
    except Exception:
        dur = 0.0
    avail = max(0.0, dur - seg_s - 0.1)
    if avail <= 0.0:
        return 0.0
    # deterministic pseudo-random offset based on video_id
    try:
        vid = int(meta.get("video_id") or 0)
    except Exception:
        vid = 0
    return float((vid * 2654435761) % int(avail * 1000)) / 1000.0


def build_background_video_from_clips(
    config: dict,
    metas: list[dict],
    out_path: Path,
    *,
    duration_s: float,
) -> tuple[Path, str]:
    """Download/cut multiple clips and concat them into a single portrait bg video."""
    ffmpeg = resolve_bin(config, "ffmpeg_bin", "ffmpeg")

    cache_dir = Path(config.get("pexels_cache_dir") or "assets/pexels_cache")
    clip_count = int(config.get("pexels_clip_count", 3))
    clip_count = max(1, min(clip_count, len(metas)))
    metas = metas[:clip_count]

    # Download to cache.
    clip_paths: list[Path] = []
    credit_lines: list[str] = []
    for meta in metas:
        out_name = f"pexels_{_slug(meta['query'])}_{meta['video_id']}_{meta['width']}x{meta['height']}.mp4"
        p = cache_dir / out_name
        if not p.exists():
            download_file(meta["download_url"], p, timeout_s=int(config.get("pexels_download_timeout_s", 120)))
        clip_paths.append(p)
        credit_lines.append(f"- {meta.get('page_url')} (by {meta.get('user_name')})")

    credit = "Background videos (Pexels):\n" + "\n".join(credit_lines)

    if clip_count == 1:
        return clip_paths[0], credit

    # Concat for exact narration duration.
    seg = duration_s / clip_count
    # Build input args with per-clip -ss/-t to avoid processing full files.
    cmd: list[str] = [ffmpeg, "-y"]
    for meta, p in zip(metas, clip_paths):
        off = _pick_pexels_offset(meta, seg)
        cmd += ["-ss", f"{off:.3f}", "-t", f"{(seg + 0.25):.3f}", "-i", str(p)]

    # Normalize each clip to 1080x1920 and concat.
    parts = []
    for i in range(clip_count):
        parts.append(
            f"[{i}:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,setsar=1,setpts=PTS-STARTPTS[v{i}]"
        )
    concat_in = "".join(f"[v{i}]" for i in range(clip_count))
    fc = ";".join(parts) + f";{concat_in}concat=n={clip_count}:v=1:a=0[v]"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd += [
        "-filter_complex",
        fc,
        "-map",
        "[v]",
        "-t",
        f"{duration_s:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        str(out_path),
    ]
    run(cmd)
    return out_path, credit


def ensure_background_for_job(config: dict, job: Job, *, duration_s: float, out_path: Path) -> tuple[Path, str | None]:
    """Return (background_path, credit_line_or_none)."""
    provider = (config.get("background_provider") or "local").strip().lower()

    # Backward compat: if user sets background_video to something other than default and doesn't enable pexels.
    if provider != "pexels":
        bg = Path(config.get("background_video") or "assets/background.mp4")
        regenerate = bool(config.get("regenerate_background", False))
        if bg.exists() and not regenerate:
            return bg, None

        ffmpeg = resolve_bin(config, "ffmpeg_bin", "ffmpeg")
        bg.parent.mkdir(parents=True, exist_ok=True)
        # fallback: dynamic abstract motion background
        run([
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "nullsrc=s=1080x1920:d=40",
            "-vf",
            "geq=r='42+18*sin(2*PI*(X/W+T/9))':g='56+18*sin(2*PI*(Y/H+T/8))':b='78+22*sin(2*PI*((X+Y)/(W+H)+T/10))',gblur=sigma=28,eq=saturation=0.72:contrast=1.06:brightness=-0.03,noise=alls=4:allf=t,drawgrid=w=140:h=140:t=1:c=white@0.025,drawbox=x=0:y=0:w=1080:h=1920:color=black@0.08:t=fill",
            "-t",
            "40",
            "-pix_fmt",
            "yuv420p",
            str(bg),
        ])
        return bg, None

    # Pexels flow.
    api_key = (config.get("pexels_api_key") or os.environ.get("PEXELS_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError(
            "background_provider=pexels ?몃뜲 Pexels API key媛 ?놁뒿?덈떎. "
            "?섍꼍蹂??`PEXELS_API_KEY`瑜??ㅼ젙?섏꽭?? (?먮뒗 config??`pexels_api_key`)"
        )

    query = (config.get("pexels_query") or "").strip() or guess_pexels_query(job)
    if not ((config.get("pexels_query") or "").strip()) and not ((job.pexels_query or "").strip()):
        # Keep this visible because it affects background relevance.
        print(f"[bg] pexels_query not set; guessed query={query!r}")
    orientation = (config.get("pexels_orientation") or "portrait").strip().lower()
    per_page = int(config.get("pexels_per_page", 10))
    min_h = int(config.get("pexels_min_height", 1600))

    clip_count = int(config.get("pexels_clip_count", 3))
    if clip_count <= 1:
        meta = pexels_video_search(
            api_key=api_key,
            query=query,
            orientation=orientation,
            per_page=per_page,
            min_height=min_h,
            timeout_s=int(config.get("pexels_timeout_s", 20)),
        )
        cache_dir = Path(config.get("pexels_cache_dir") or "assets/pexels_cache")
        name = f"pexels_{_slug(meta['query'])}_{meta['video_id']}_{meta['width']}x{meta['height']}.mp4"
        p = cache_dir / name
        if not p.exists():
            download_file(meta["download_url"], p, timeout_s=int(config.get("pexels_download_timeout_s", 120)))
        credit = f"Background video: {meta.get('page_url')} (by {meta.get('user_name')})"
        return p, credit

    metas = pexels_video_search_many(
        api_key=api_key,
        query=query,
        orientation=orientation,
        per_page=max(per_page, 15),
        min_height=min_h,
        k=clip_count,
        timeout_s=int(config.get("pexels_timeout_s", 20)),
    )
    return build_background_video_from_clips(config, metas, out_path, duration_s=duration_s)


def _ffmpeg_escape(text: str) -> str:
    return (
        text.replace("\\", r"\\")
        .replace(":", r"\:")
        .replace("'", r"\'")
        .replace(",", r"\,")
        .replace("%", r"\%")
    )


def resolve_font_for_korean(config: dict) -> tuple[str | None, str | None]:
    """Return (fontfile, fontname) best-effort for Korean rendering.

    `drawtext` shows tofu squares when a glyph isn't available in the chosen font.
    In WSL, Korean fonts are often available only on the Windows side.
    """
    def _fc_match_font(query: str) -> tuple[str | None, str | None]:
        # Ask fontconfig for an installed fallback that supports the language.
        try:
            result = subprocess.run(
                ["fc-match", "-f", "%{file}\\n%{family}\\n", query],
                capture_output=True,
                text=True,
                check=False,
                timeout=2,
            )
            if result.returncode != 0:
                return None, None
            lines = (result.stdout or "").splitlines()
            if not lines:
                return None, None
            fontfile = lines[0].strip()
            fontname = lines[1].strip() if len(lines) > 1 else None
            if fontfile and Path(fontfile).exists():
                return fontfile, fontname
        except Exception:
            pass
        return None, None

    raw = (config.get("font_file") or "").strip()
    if raw:
        p = Path(raw)
        if p.exists():
            fontfile = str(p)
            print(f"[font] resolved title/subtitle font from config: path={fontfile}")
            return fontfile, _coerce_font_name(None, fontfile)

    # WSL: use Windows font files if present.
    candidates: list[tuple[str, str]] = [
        ("/System/Library/Fonts/AppleSDGothicNeo.ttc", "Apple SD Gothic Neo"),
        ("/System/Library/Fonts/Supplemental/AppleGothic.ttf", "Apple Gothic"),
        ("/System/Library/Fonts/NotoSansCJK.ttc", "Noto Sans CJK KR"),
        ("/System/Library/Fonts/Supplemental/NanumGothic.ttc", "Nanum Gothic"),
        ("/mnt/c/Windows/Fonts/malgunbd.ttf", "Malgun Gothic"),
        ("/mnt/c/Windows/Fonts/malgun.ttf", "Malgun Gothic"),
        ("/mnt/c/Windows/Fonts/NanumGothicBold.ttf", "NanumGothic"),
        ("/mnt/c/Windows/Fonts/NanumGothic.ttf", "NanumGothic"),
    ]
    for path, name in candidates:
        if Path(path).exists():
            print(f"[font] resolved title/subtitle font from fallback path: path={path}")
            return path, name

    # Last resort: fontconfig (Linux). Might still resolve to a non-Korean font if CJK isn't installed.
    for query in (
        "Noto Sans CJK KR:style=Bold",
        "Noto Sans CJK KR",
        "Noto Sans KR:style=Bold",
        "Apple SD Gothic Neo:style=Bold",
        ":lang=ko",
    ):
        fontfile, fontname = _fc_match_font(query)
        if fontfile:
            family = _coerce_font_name(fontname, fontfile)
            print(f"[font] resolved title/subtitle font via fc-match query={query!r}: path={fontfile}, family={family}")
            return fontfile, family

    print("[font] no Korean-capable font detected. Falling back to ffmpeg/fontconfig default.")
    return None, None


def format_title_for_titlefile(title: str) -> tuple[str, int]:
    """Return (text_with_newlines, fontsize) for `drawtext=textfile=...`.

    Using `textfile` avoids fragile escaping issues with Korean, punctuation and newlines.
    """
    clean = re.sub(r"\s+", " ", title).strip()
    if not clean:
        return "", 72

    def visual_len(s: str) -> float:
        # Rough: ASCII chars are narrower than Hangul/CJK on typical sans fonts.
        n = 0.0
        for ch in s:
            if ch.isspace():
                n += 0.3
            elif ord(ch) < 128:
                n += 0.6
            else:
                n += 1.0
        return n

    # Auto-fit rule:
    # - Prefer a single line if we can keep it big enough without clipping.
    # - Otherwise wrap to 2 lines at a word boundary and fit again.
    #
    # We only have a heuristic estimate for text width. This keeps output stable and avoids
    # hard-coded per-title tweaks.
    target_px = 980  # keep some padding inside 1080, including stroke
    unit_px = 0.92   # 1.0 visual_len ~= ~0.92 * fontsize pixels for CJK-ish glyphs

    def fit_fontsize(v: float, cap: int) -> int:
        if v <= 0:
            return min(72, cap)
        return max(52, min(cap, int(target_px / (v * unit_px))))

    vlen = visual_len(clean)
    one = fit_fontsize(vlen, 92)
    if one >= 74:
        return clean, one

    tokens = [t for t in clean.split(" ") if t]
    if len(tokens) < 2:
        return clean, one

    # Wrap (2 lines). Choose the split that minimizes the max line length.
    best: tuple[float, str, str] | None = None  # (max_vlen, left, right)
    for i in range(1, len(tokens)):
        left = " ".join(tokens[:i]).strip()
        right = " ".join(tokens[i:]).strip()
        m = max(visual_len(left), visual_len(right))
        if best is None or m < best[0]:
            best = (m, left, right)

    if not best:
        return clean, one

    max_line, left, right = best
    two = fit_fontsize(max_line, 88)
    return f"{left}\n{right}", two


def render_video(bg: Path, audio: Path, srt: Path, out_video: Path, config: dict, title_text: str) -> None:
    """Render a Shorts-style 3-zone layout:
    - Top: solid black bar + fixed title
    - Middle: moving background + subtitles
    - Bottom: solid black bar (safe area)
    """
    ffmpeg = resolve_bin(config, "ffmpeg_bin", "ffmpeg")
    ffprobe = resolve_bin(config, "ffprobe_bin", "ffprobe")

    duration = probe_duration(audio, ffprobe=ffprobe)
    top_h = int(config.get("top_bar_height", 260))
    bottom_h = int(config.get("bottom_bar_height", 260))

    # Use a Korean-capable font for the title; otherwise `drawtext` renders squares.
    font_opt = ""
    subs_font_name = "Noto Sans CJK KR"
    fontfile, fontname = resolve_font_for_korean(config)
    if fontfile:
        font_opt = f":fontfile={_ffmpeg_escape(str(fontfile))}"
        if fontname:
            subs_font_name = fontname

    subtitle_fontfile = fontfile or ""
    subtitle_font_name = _coerce_font_name(subs_font_name, subtitle_fontfile)
    subs_font_name = subtitle_font_name

    # libass (used by ffmpeg subtitles filter) needs the font to be discoverable via fontconfig or fontsdir.
    # In WSL, Korean fonts commonly live in Windows fonts directory which fontconfig may not scan by default.
    # Use a deterministic fontsdir that contains the selected fontfile when possible.
    fontsdir_opt = ""
    fontsdir: str | None = None
    if fontfile:
        fontsdir = str(Path(fontfile).parent)
    else:
        win_fonts = Path("/mnt/c/Windows/Fonts")
        if win_fonts.exists():
            fontsdir = str(win_fonts)
    # Allow explicit override via config (string path).
    cfg_fontsdir = (config.get("subtitle_fontsdir") or "").strip() if isinstance(config.get("subtitle_fontsdir"), str) else ""
    if cfg_fontsdir:
        fontsdir = cfg_fontsdir
    if fontsdir:
        fontsdir_opt = f":fontsdir='{_ffmpeg_escape(fontsdir)}'"

    # Use a title text file for reliable newline / unicode behavior with ffmpeg drawtext.
    title_content, title_fontsize = format_title_for_titlefile(title_text)
    title_txt = out_video.with_suffix(".title.txt")
    title_txt.write_text(title_content + "\n", encoding="utf-8")
    title_txt_safe = _ffmpeg_escape(str(title_txt))

    # libass SRT default script uses PlayResY=288, so force_style values are expressed in that coordinate space
    # then scaled to the video. Our layout values are in pixels for a 1080x1920 canvas, so convert them.
    playres_y = int(config.get("subtitle_playres_y", 288))
    def px_to_ass(v_px: int, *, min_v: int = 1) -> int:
        return max(min_v, int(round(v_px * (playres_y / 1920.0))))

    # Subtitles: configurable position and styling for readability on mobile.
    subtitle_position_raw = config.get("subtitle_position")
    if isinstance(subtitle_position_raw, str) and subtitle_position_raw.strip():
        subtitle_position = _normalize_subtitle_position(subtitle_position_raw)
    else:
        # Backward compatibility for existing configs that still use subtitle_align.
        subtitle_align = (config.get("subtitle_align") or "").strip().lower()
        align_to_position = {
            "bottom": "center,bottom",
            "bottom_center": "center,bottom",
            "middle": "center,middle",
            "center": "center,middle",
            "center_center": "center,middle",
            "top": "center,top",
        }
        subtitle_position = align_to_position.get(subtitle_align, "center,middle")

    _, vertical_sub_pos = subtitle_position.split(",")
    subtitle_alignment = _align_from_position(subtitle_position)

    subs_fontsize_px = _coerce_int(
        config.get("subtitle_font_size"),
        default=88,
        key="subtitle_font_size",
        min_value=30,
    )
    subs_outline_px = _coerce_int(
        config.get("subtitle_outline"),
        default=8,
        key="subtitle_outline",
        min_value=0,
    )

    # Keep legacy default for legacy top/bottom-style setups.
    # For center/middle, explicit subtitle_margin_v / subtitle_vshift are handled separately.
    subs_margin_default = _coerce_int(
        config.get("subtitle_margin_v"),
        default=bottom_h + 120,
        key="subtitle_margin_v",
        min_value=0,
    )
    subs_margin_top = _coerce_int(
        config.get("subtitle_margin_top_v"),
        default=subs_margin_default,
        key="subtitle_margin_top_v",
        min_value=0,
    )
    subs_margin_bottom = _coerce_int(
        config.get("subtitle_margin_bottom_v"),
        default=subs_margin_default,
        key="subtitle_margin_bottom_v",
        min_value=0,
    )
    if vertical_sub_pos == "top":
        subs_margin_px = subs_margin_top
    elif vertical_sub_pos == "bottom":
        subs_margin_px = subs_margin_bottom
    else:
        # Center/middle: align to visual center unless explicitly overridden.
        if "subtitle_margin_v" in config:
            subs_margin_px = _coerce_int(
                config.get("subtitle_margin_v"),
                default=0,
                key="subtitle_margin_v",
                min_value=0,
            )
        elif "subtitle_vshift" in config:
            # Backward-compatible override for legacy users that tuned by shift value.
            subtitle_vshift = _coerce_int(
                config.get("subtitle_vshift"),
                default=0,
                key="subtitle_vshift",
                min_value=-1920,
            )
            subs_margin_px = subtitle_vshift
        else:
            subs_margin_px = 0

    print(
        f"[subtitles] position={subtitle_position} align={subtitle_alignment} "
        f"font={subs_font_name} fontfile={subtitle_fontfile or 'default'} "
        f"font_size={subs_fontsize_px} outline={subs_outline_px} margin_v={subs_margin_px}"
    )

    margin_min = -300 if vertical_sub_pos == "middle" else 0
    ass_margin_v = px_to_ass(subs_margin_px, min_v=margin_min)
    ass_path = out_video.with_suffix(".subs.ass")
    try:
        _write_ass_from_srt(
            srt,
            ass_path,
            playres_y=playres_y,
            font_name=subs_font_name,
            font_size=px_to_ass(subs_fontsize_px),
            outline=px_to_ass(subs_outline_px),
            alignment=subtitle_alignment,
            margin_v=ass_margin_v,
        )
    except Exception as e:
        raise RuntimeError(f"subtitle ASS conversion failed: {_one_line(str(e))}") from e

    print(
        f"[subtitles] render_mode=ass align={subtitle_alignment} "
        f"margin_v={ass_margin_v} ass={ass_path}"
    )

    # Title y position inside top bar
    # Keep some breathing room under the top bar for 1-2 lines.
    title_y = max(34, int(top_h * 0.16))
    ass_safe = _ffmpeg_escape(str(ass_path))

    vf = (
        "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        "eq=saturation=0.90:contrast=1.04,"
        f"drawbox=x=0:y=0:w=1080:h={top_h}:color=black@1.0:t=fill,"
        f"drawbox=x=0:y={1920 - bottom_h}:w=1080:h={bottom_h}:color=black@1.0:t=fill,"
        f"drawtext=textfile='{title_txt_safe}'{font_opt}:reload=0:x=(w-text_w)/2:y={title_y}:fontsize={title_fontsize}:fontcolor=white:borderw=8:bordercolor=black:line_spacing=10:text_align=C:fix_bounds=1,"
        f"ass='{ass_safe}'{fontsdir_opt},"
        f"drawbox=x=0:y=1892:w='1080*t/{duration:.3f}':h=10:color=0x00E5FF@0.9:t=fill"
    )

    cmd = [
        ffmpeg,
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        str(bg),
        "-i",
        str(audio),
    ]

    bgm_file = Path(config.get("bgm_file", "")) if config.get("bgm_file") else None
    use_bgm = bool(bgm_file and bgm_file.exists())

    if use_bgm:
        cmd += ["-stream_loop", "-1", "-i", str(bgm_file)]
        cmd += [
            "-t",
            f"{duration:.3f}",
            "-filter_complex",
            f"[0:v]{vf}[v];[1:a]volume=1.0[a1];[2:a]volume=0.08[a2];[a1][a2]amix=inputs=2:duration=first[a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
        ]
    else:
        cmd += [
            "-t",
            f"{duration:.3f}",
            "-vf",
            vf,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
        ]

    video_preset = str(config.get("video_preset", "medium")).strip() or "medium"
    video_crf = int(config.get("video_crf", 21))
    video_bitrate = str(config.get("video_bitrate", "")).strip()
    audio_bitrate = str(config.get("audio_bitrate", "192k")).strip() or "192k"
    bitrate_args = []
    if video_bitrate:
        bitrate_args = ["-b:v", video_bitrate]

    cmd += [
        "-c:v",
        "libx264",
        "-preset",
        video_preset,
        "-crf",
        str(video_crf),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        audio_bitrate,
        *bitrate_args,
        "-shortest",
        "-movflags",
        "+faststart",
        str(out_video),
    ]

    run(cmd)


def get_youtube_client(client_secret_file: Path, token_file: Path):
    # Lazy import so `--no-upload` can run without Google deps installed.
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_file), SCOPES)
            creds = flow.run_local_server(port=0)
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds)


def _retry_upload_next_chunk(
    req: Any,
    *,
    max_attempts: int,
    timeout_s: float | None,
    initial_backoff_s: float,
    max_backoff_s: float,
    is_retryable_exc: Callable[[BaseException], bool],
    sleep_fn: Callable[[float], None] = time.sleep,
    time_fn: Callable[[], float] = time.monotonic,
    log_fn: Callable[[str], None] = print,
) -> dict[str, Any]:
    """
    Drive resumable upload `req.next_chunk()` with retries/backoff.

    googleapiclient's resumable upload returns (status, response) where response
    stays None until the final chunk completes.
    """
    max_attempts = int(max_attempts)
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    started = time_fn()
    attempt = 0
    backoff_s = float(initial_backoff_s)
    timeout_s = float(timeout_s) if timeout_s is not None else None

    # Make retry behavior explicit in logs so production runs are debuggable.
    log_fn(
        "[upload] policy "
        f"max_attempts={max_attempts} "
        f"timeout_s={(timeout_s if timeout_s is not None else 'none')} "
        f"initial_backoff_s={float(initial_backoff_s)} "
        f"max_backoff_s={float(max_backoff_s)}"
    )

    while True:
        if timeout_s is not None and (time_fn() - started) > timeout_s:
            raise TimeoutError(f"upload timed out after {timeout_s:.1f}s")

        attempt += 1
        try:
            _, response = req.next_chunk()
            if response is not None:
                if not isinstance(response, dict):
                    raise RuntimeError(f"unexpected upload response type: {type(response).__name__}")
                return response
        except Exception as e:
            if (attempt >= max_attempts) or (not is_retryable_exc(e)):
                raise

            # Avoid sleeping past the deadline; surface a concrete timeout error.
            if timeout_s is not None:
                elapsed = time_fn() - started
                if elapsed + backoff_s > timeout_s:
                    raise TimeoutError(f"upload timed out after {timeout_s:.1f}s") from e

            log_fn(f"[upload] next_chunk failed (attempt {attempt}/{max_attempts}): {type(e).__name__}: {_one_line(str(e))}")
            log_fn(f"[upload] retrying in {backoff_s:.1f}s")
            sleep_fn(backoff_s)
            backoff_s = min(backoff_s * 2.0, float(max_backoff_s))


def upload_video(config: dict, job: Job, video_path: Path, *, credit_line: str | None = None):
    # Lazy import so `--no-upload` can run without Google deps installed.
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError

    yt_cfg = config["youtube"]
    client = get_youtube_client(Path(yt_cfg["client_secret_file"]), Path(yt_cfg["token_file"]))

    if not job.title or not job.script:
        raise RuntimeError("upload_video(): job.title/job.script is missing")
    description = f"{job.description or ''}\n\n{job.hashtags or ''}".strip()
    if credit_line and bool(config.get("append_credit_to_description", True)):
        description = f"{description}\n\n{credit_line}".strip()

    body = {
        "snippet": {
            "title": (job.title or "")[:100],
            "description": description[:5000],
            "categoryId": yt_cfg.get("category_id", "28"),
            "defaultLanguage": config.get("default_language", "ko"),
            "defaultAudioLanguage": config.get("default_language", "ko"),
        },
        "status": {
            "privacyStatus": yt_cfg.get("privacy_status", "private"),
            "selfDeclaredMadeForKids": False,
        },
    }

    req = client.videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(str(video_path), chunksize=-1, resumable=True),
    )

    # Retry/backoff policy (override in config.json under `youtube`):
    # - upload_max_attempts: int (default 5)
    # - upload_timeout_s: seconds (default 900)
    # - upload_initial_backoff_s: seconds (default 2)
    # - upload_max_backoff_s: seconds (default 30)
    max_attempts = int(yt_cfg.get("upload_max_attempts", 5))
    timeout_s = yt_cfg.get("upload_timeout_s", 900)
    initial_backoff_s = float(yt_cfg.get("upload_initial_backoff_s", 2.0))
    max_backoff_s = float(yt_cfg.get("upload_max_backoff_s", 30.0))

    def is_retryable_exc(e: BaseException) -> bool:
        if isinstance(e, TimeoutError):
            return True
        if isinstance(e, OSError):
            return True
        if isinstance(e, HttpError):
            status = getattr(getattr(e, "resp", None), "status", None)
            return status in {408, 429, 500, 502, 503, 504}
        return False

    response = _retry_upload_next_chunk(
        req,
        max_attempts=max_attempts,
        timeout_s=(float(timeout_s) if timeout_s is not None else None),
        initial_backoff_s=initial_backoff_s,
        max_backoff_s=max_backoff_s,
        is_retryable_exc=is_retryable_exc,
    )

    return response.get("id")


def load_job(path: Path) -> Job:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Job(
        title=data.get("title"),
        script=data.get("script"),
        description=data.get("description"),
        hashtags=data.get("hashtags"),
        pexels_query=data.get("pexels_query"),
        topic=data.get("topic"),
        subtopic=data.get("subtopic"),
        style=data.get("style"),
        tone=data.get("tone"),
        target_seconds=data.get("target_seconds"),
    )


def ensure_job_ready(config: dict, job: Job, *, allow_llm: bool) -> Job:
    # When OpenAI is enabled, refresh title/script/etc every run.
    needs = []
    if not (job.title or "").strip():
        needs.append("title")
    if not (job.script or "").strip():
        needs.append("script")
    if not (job.description or "").strip():
        needs.append("description")
    if not (job.hashtags or "").strip():
        needs.append("hashtags")

    if not allow_llm:
        if needs:
            raise RuntimeError(f"Missing required fields from job: {', '.join(needs)}. Use --no-llm to allow this.")
        return job

    if not needs:
        return job

    print(f"[0/4] Regenerating title/script via OpenAI")
    seed_topic = (job.topic or "").strip() or (job.title or "").strip() or (job.script or "").strip() or "shorts topic"
    if job.subtopic:
        seed_topic = f"{seed_topic}: {job.subtopic.strip()}"
    if len(seed_topic) > 80:
        seed_topic = seed_topic[:80].strip()

    seed_job = Job(
        title=None,
        script=None,
        description=None,
        hashtags=None,
        pexels_query=job.pexels_query,
        topic=seed_topic,
        subtopic=job.subtopic,
        style=job.style,
        tone=job.tone,
        target_seconds=job.target_seconds,
    )
    job2 = openai_generate_job(config, seed_job)
    if not (job2.title and job2.script):
        raise RuntimeError("OpenAI ?앹꽦 寃곌낵媛 鍮꾩뼱?덉뒿?덈떎(title/script).")
    return job2


def _one_line(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _job_idempotency_key(job_path: Path) -> str:
    # Treat the job file as the unit of work. This is pragmatic for queue reruns:
    # if the same job file already uploaded once, we should not upload again.
    try:
        return str(job_path.resolve())
    except Exception:
        return str(job_path)


def _read_jsonl_last_by_key(path: Path, *, key_field: str) -> dict[str, dict[str, Any]]:
    """
    Read a JSONL file and keep the last object per key_field value.
    Malformed lines are ignored (best-effort persistence).
    """
    out: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return out
    try:
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                ln = raw.strip()
                if not ln:
                    continue
                try:
                    obj = json.loads(ln)
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue
                k = obj.get(key_field)
                if not isinstance(k, str) or not k:
                    continue
                out[k] = obj
    except OSError:
        # If the state file cannot be read, treat as empty; don't block rendering.
        return {}
    return out


def _lookup_uploaded_record(state_path: Path, job_key: str) -> dict[str, Any] | None:
    rec = _read_jsonl_last_by_key(state_path, key_field="job_key").get(job_key)
    if not rec:
        return None
    if rec.get("video_id") or rec.get("upload_url"):
        return rec
    return None


def _append_jsonl(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


def _env_truthy(name: str) -> bool:
    v = (os.environ.get(name) or "").strip().lower()
    return v in {"1", "true", "yes", "y", "on"}


def _summary_line(summary: dict[str, Any]) -> str:
    payload = json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
    return f"SUMMARY {payload}"


def _coerce_openclaw_notify_flag(config: dict[str, Any], *, env_key: str, config_key: str, default: bool = False) -> bool:
    if env_key in os.environ:
        return _env_truthy(env_key)
    return _coerce_bool(config.get(config_key), default=default)


def _openclaw_log_path(config: dict[str, Any]) -> Path:
    raw = (config.get("openclaw_error_log_path") or os.environ.get("OPENCLAW_ERROR_LOG_PATH") or "").strip()
    if raw:
        return Path(raw)
    return Path("logs") / "errors.jsonl"


def _read_tail_lines(path: Path, max_lines: int = 20) -> list[str]:
    if max_lines <= 0 or not path.exists():
        return []
    lines: list[str] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                lines.append(line.rstrip("\n"))
    except Exception:
        return []

    return lines[-max_lines:]


def _log_error_event(config: dict[str, Any], payload: dict[str, Any]) -> None:
    path = _openclaw_log_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        **payload,
    }
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[-] Failed to write error log {path}: {_one_line(str(e))}")


def _format_openclaw_message(*, status: str, job: str, error_type: str, error: str, result_line: str | None, log_file: Path | None) -> str:
    base = [
        "[shorts-automation2]",
        f"status={status}",
        f"job={job}",
        f"error_type={error_type}",
        f"error={error}",
        f"result={result_line}" if result_line else "",
        f"log={log_file}" if log_file else "",
    ]
    return " | ".join(part for part in base if part)


def _notify_openclaw(message: str, *, config: dict[str, Any]) -> None:
    notify_enabled = _coerce_openclaw_notify_flag(
        config,
        env_key="OPENCLAW_NOTIFY_ENABLED",
        config_key="openclaw_notify_enabled",
        default=False,
    )
    if not notify_enabled:
        return

    cmd_raw = str(config.get("openclaw_notify_cmd") or os.environ.get("OPENCLAW_NOTIFY_CMD") or "").strip()
    if not cmd_raw:
        print("[-] openclaw notify is enabled but openclaw_notify_cmd is empty.")
        return

    timeout_s = _coerce_float(config.get("openclaw_notify_timeout_s"), default=12.0, key="openclaw_notify_timeout_s")

    quoted_message = shlex.quote(message)
    if "{message}" in cmd_raw:
        cmd_raw = cmd_raw.replace("{message}", quoted_message)
    else:
        cmd_raw = f"{cmd_raw} {quoted_message}"

    try:
        cmd = shlex.split(cmd_raw)
    except Exception as e:
        print(f"[-] openclaw notify command parse failed: {_one_line(str(e))}")
        return

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=float(timeout_s))
    except Exception as e:
        print(f"[-] openclaw notify command failed: {_one_line(str(e))}")
        return

    if result.returncode != 0:
        err = _one_line(result.stderr or result.stdout or "")
        print(f"[-] openclaw notify command returned non-zero ({result.returncode}): {err}")



def _run_ffprobe_json(ffprobe_bin: str, path: Path) -> dict[str, Any]:
    """
    Run ffprobe and return parsed JSON.

    Kept as a small helper so upload validation can be unit-tested by injecting
    pre-canned ffprobe JSON without requiring ffprobe in CI.
    """
    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    p = subprocess.run(cmd, text=True, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed (code {p.returncode}): {_one_line(p.stderr or p.stdout or '')}")
    try:
        return json.loads(p.stdout or "{}")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"ffprobe output is not valid JSON: {e}") from e


def _as_float(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        s = str(v).strip()
        if not s:
            return None
        return float(s)
    except Exception:
        return None


def validate_upload_checklist(
    config: dict[str, Any],
    job: Job,
    video_path: Path,
    *,
    ffprobe_data: dict[str, Any] | None = None,
) -> None:
    """
    Upload guardrails: fail-fast before attempting YouTube upload.

    Checks (defaults can be overridden in config.json under `youtube`):
    - title present
    - hashtags present
    - video file exists and non-empty
    - duration <= youtube.max_duration_s (default 60)
    - has video+audio streams
    - portrait and (optionally) ~9:16 aspect ratio
    - minimum resolution
    """
    yt_cfg = config.get("youtube") or {}

    title = (job.title or "").strip()
    hashtags = (job.hashtags or "").strip()
    if not title:
        raise RuntimeError("upload checklist failed: missing title")
    if not hashtags:
        raise RuntimeError("upload checklist failed: missing hashtags")

    if not video_path.exists():
        raise RuntimeError(f"upload checklist failed: video not found: {video_path}")
    try:
        if video_path.stat().st_size <= 0:
            raise RuntimeError(f"upload checklist failed: video is empty: {video_path}")
    except OSError as e:
        raise RuntimeError(f"upload checklist failed: cannot stat video: {video_path}: {e}") from e

    if ffprobe_data is None:
        ffprobe_bin = resolve_bin(config, "ffprobe_bin", "ffprobe")
        ffprobe_data = _run_ffprobe_json(ffprobe_bin, video_path)

    streams = list(ffprobe_data.get("streams") or [])
    fmt = dict(ffprobe_data.get("format") or {})

    video_stream = next((s for s in streams if (s or {}).get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if (s or {}).get("codec_type") == "audio"), None)
    if not video_stream:
        raise RuntimeError("upload checklist failed: no video stream")
    if not audio_stream:
        raise RuntimeError("upload checklist failed: no audio stream")

    dur_s = _as_float(fmt.get("duration"))
    max_duration_s = float(yt_cfg.get("max_duration_s", 60.0))
    if dur_s is not None and dur_s > max_duration_s + 1e-6:
        raise RuntimeError(f"upload checklist failed: duration {dur_s:.3f}s exceeds {max_duration_s:.1f}s")

    w = _as_float(video_stream.get("width"))
    h = _as_float(video_stream.get("height"))
    if w is None or h is None or w <= 0 or h <= 0:
        raise RuntimeError("upload checklist failed: invalid video resolution")

    min_w = int(yt_cfg.get("min_width", 720))
    min_h = int(yt_cfg.get("min_height", 1280))
    if int(w) < min_w or int(h) < min_h:
        raise RuntimeError(f"upload checklist failed: resolution {int(w)}x{int(h)} below {min_w}x{min_h}")

    require_portrait = bool(yt_cfg.get("require_portrait", True))
    if require_portrait and not (h > w):
        raise RuntimeError(f"upload checklist failed: not portrait (got {int(w)}x{int(h)})")

    require_aspect_9_16 = bool(yt_cfg.get("require_aspect_9_16", True))
    if require_aspect_9_16:
        tol = float(yt_cfg.get("aspect_tolerance", 0.07))
        aspect = float(w) / float(h)
        target = 9.0 / 16.0
        if abs(aspect - target) > tol:
            raise RuntimeError(f"upload checklist failed: aspect {aspect:.4f} not ~9:16 (tol {tol:.3f})")


def format_result_line(
    *,
    status: Literal["ok", "error"],
    elapsed_s: float,
    video: Path | None,
    video_id: str | None,
    upload_url: str | None,
    no_upload: bool,
    error: str | None = None,
) -> str:
    parts: list[str] = [
        "RESULT",
        f"status={status}",
        f"elapsed_s={elapsed_s:.3f}",
    ]
    if video is not None:
        parts.append(f"video={video}")
    if video_id:
        parts.append(f"video_id={video_id}")
    if no_upload:
        parts.append("upload=SKIPPED")
    elif upload_url:
        parts.append(f"upload={upload_url}")
    if error:
        parts.append(f"error={_one_line(error)}")
    return " ".join(parts)


def _print_summary(summary: dict[str, Any]) -> None:
    print(_summary_line(summary), flush=True)


def main() -> int:
    started = time.monotonic()
    parser = argparse.ArgumentParser(description="YouTube Shorts auto render + upload")
    # ENV means: don't require config.json; load defaults + env overrides instead.
    parser.add_argument("--config", default=ENV_SENTINEL)
    parser.add_argument("--job", required=True, help="job json path")
    parser.add_argument("--no-upload", action="store_true", help="Skip upload (or set NO_UPLOAD=1)")
    parser.add_argument("--force-upload", action="store_true", help="Upload even if this job was already uploaded")
    parser.add_argument("--no-llm", action="store_true", help="Disable OpenAI job/script generation")
    parser.add_argument(
        "--traceback",
        action="store_true",
        help="Print full traceback on failure (default: one-line reason only).",
    )
    parser.add_argument(
        "--audio",
        help="Use an existing audio file (mp3/wav). If set, TTS generation is skipped.",
    )
    parser.add_argument(
        "--cleanup-all-artifacts",
        action="store_true",
        help="Delete all generated files after run, including final video outputs.",
    )
    args = parser.parse_args()
    no_upload = bool(args.no_upload) or _env_truthy("NO_UPLOAD")

    job_path = Path(args.job)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    audio: Path | None = None
    srt: Path | None = None
    video: Path | None = None
    credit_path: Path | None = None
    duration: float | None = None
    video_id: str | None = None
    upload_url: str | None = None
    idempotency_hit: bool = False
    idempotency_key: str | None = None
    idempotency_state_file: str | None = None
    generated_artifacts: list[Path] = []
    preserved_artifacts: set[Path] = set()
    keep_intermediate_artifacts: bool = False
    cleanup_all_artifacts: bool = False
    out_dir: Path | None = None
    config: dict[str, Any] = {}
    trace_lines: list[str] = []

    try:
        config = load_config(args.config)
        job = ensure_job_ready(config, load_job(job_path), allow_llm=(not args.no_llm))

        out_dir = Path(config.get("output_dir", "output"))
        out_dir.mkdir(parents=True, exist_ok=True)
        if _is_sample_output_dir(out_dir):
            print(f"[i] output_dir looks like a sample path ({out_dir}). run_short does not rename output folders itself.")

        keep_intermediate_artifacts = _coerce_bool(
            config.get("keep_intermediate_artifacts"), default=False
        )
        cleanup_all_artifacts = bool(args.cleanup_all_artifacts) or _env_truthy("CLEANUP_ALL_ARTIFACTS")
        if not cleanup_all_artifacts:
            cleanup_all_artifacts = _coerce_bool(config.get("cleanup_all_artifacts"), default=False)

        external_audio = bool(args.audio)
        audio = Path(args.audio) if external_audio else (out_dir / f"{stamp}.mp3")
        srt = out_dir / f"{stamp}.srt"
        video = out_dir / f"{stamp}.mp4"
        bg_out = out_dir / f"{stamp}.bg.mp4"
        if not cleanup_all_artifacts:
            preserved_artifacts.add(video)
        generated_artifacts.append(srt)
        if external_audio:
            preserved_artifacts.add(audio)
        else:
            generated_artifacts.append(audio)

        if external_audio:
            if not audio.exists():
                raise FileNotFoundError(f"--audio not found: {audio}")
            print("[1/3] TTS ?ㅽ궢 (--audio)")
        else:
            print("[1/4] TTS ?앹꽦")
            tts_provider = (config.get("tts_provider") or "elevenlabs").lower()
            if tts_provider != "elevenlabs":
                print(f"[-] tts_provider={tts_provider!r} is not supported. Forcing ElevenLabs-only mode.")

            api_key = config.get("elevenlabs_api_key") or os.environ.get("ELEVENLABS_API_KEY")
            voice_id = config.get("elevenlabs_voice_id") or os.environ.get("ELEVENLABS_VOICE_ID")
            model_id = config.get("elevenlabs_model_id") or os.environ.get("ELEVENLABS_MODEL_ID") or "eleven_multilingual_v2"
            if not api_key or not voice_id:
                raise RuntimeError(
                    "Missing ElevenLabs config: set elevenlabs_api_key / elevenlabs_voice_id (or ELEVENLABS_API_KEY / ELEVENLABS_VOICE_ID)."
                )

            tts_attempts = _coerce_int(
                config.get("elevenlabs_tts_attempts"),
                default=3,
                key="elevenlabs_tts_attempts",
                min_value=1,
            )
            tts_initial_backoff_s = _coerce_float(
                config.get("elevenlabs_tts_initial_backoff_s"),
                default=1.0,
                key="elevenlabs_tts_initial_backoff_s",
            )
            tts_max_backoff_s = _coerce_float(
                config.get("elevenlabs_tts_max_backoff_s"),
                default=6.0,
                key="elevenlabs_tts_max_backoff_s",
            )
            if tts_max_backoff_s < tts_initial_backoff_s:
                print(
                    "[-] elevenlabs_tts_max_backoff_s is less than elevenlabs_tts_initial_backoff_s; using initial value."
                )
                tts_max_backoff_s = tts_initial_backoff_s

            tts_timeout_s = _coerce_float(config.get("elevenlabs_tts_timeout_s"), default=40.0, key="elevenlabs_tts_timeout_s")
            try:
                tts_with_retries(
                    lambda: tts_elevenlabs(
                        job.script or "",
                        audio,
                        voice_id=voice_id,
                        api_key=api_key,
                        model_id=model_id,
                        timeout_s=tts_timeout_s,
                    ),
                    label="tts",
                    max_attempts=tts_attempts,
                    initial_backoff_s=tts_initial_backoff_s,
                    max_backoff_s=tts_max_backoff_s,
                )
            except Exception as e:
                raise RuntimeError(f"TTS failed after {tts_attempts} attempts: {_one_line(str(e))}") from e

        print("[2/3] ?먮쭑 ?앹꽦" if external_audio else "[2/4] ?먮쭑 ?앹꽦")
        duration = probe_duration(audio, ffprobe=resolve_bin(config, "ffprobe_bin", "ffprobe"))
        subtitle_sync_tolerance = _coerce_float(
            config.get("subtitle_sync_drift_tolerance"),
            default=0.5,
            key="subtitle_sync_drift_tolerance",
        )
        subtitle_sync_repair = _coerce_bool(config.get("subtitle_sync_repair"), default=True)
        subtitle_sync_repair_max_drift = _coerce_float(
            config.get("subtitle_sync_repair_max_drift"),
            default=subtitle_sync_tolerance,
            key="subtitle_sync_repair_max_drift",
        )
        subtitle_sync_max_scale_delta = _coerce_float(
            config.get("subtitle_sync_max_scale_delta"),
            default=0.12,
            key="subtitle_sync_max_scale_delta",
        )
        if subtitle_sync_max_scale_delta < 0:
            print("[-] subtitle_sync_max_scale_delta is negative; using 0.12")
            subtitle_sync_max_scale_delta = 0.12
        if subtitle_sync_max_scale_delta > 1:
            print("[-] subtitle_sync_max_scale_delta is too large; clamping to 1.0")
            subtitle_sync_max_scale_delta = 1.0

        subtitle_ok = False
        subtitle_method = "none"

        # 1) OpenAI alignment (best sync)
        if (not external_audio) and bool(config.get("subtitle_align_openai", True)):
            try:
                print("[2-1/4] OpenAI ?먮쭑 ?뺣젹 ?쒕룄")
                write_srt_aligned_openai(
                    config,
                    audio_path=audio,
                    srt_path=srt,
                    prompt_text=job.script or "",
                    script_text=job.script or "",
                )
                if _apply_srt_timing_guard(
                    srt,
                    duration,
                    enabled=subtitle_sync_repair,
                    repair_max_drift=subtitle_sync_repair_max_drift,
                    max_scale_delta=subtitle_sync_max_scale_delta,
                    validate_max_drift=subtitle_sync_tolerance,
                    label="openai",
                ):
                    subtitle_ok = True
                    subtitle_method = "openai"
                else:
                    print(
                        f"[-] OpenAI ?먮쭑???ㅻ뵒??湲몄씠? ?숆린?붾릺吏 ?딆븯?듬땲?? "
                        f"(?덉슜 ?ㅼ감 {subtitle_sync_tolerance:.2f}s). fallback 吏꾪뻾"
                    )
            except Exception as e:
                print(f"[-] OpenAI ?먮쭑 ?뺣젹 ?ㅽ뙣: {e}")

        # 2) Final fallback: script split aligned only by script duration.
        if not subtitle_ok:
            try:
                print("[2-2/4] ?ㅽ겕由쏀듃 湲곕컲 ?먮쭑 遺꾪븷 fallback")
                max_chars = _coerce_int(config.get("subtitle_max_chars"), default=26, key="subtitle_max_chars", min_value=4)
                lines = split_for_captions_dense(job.script or "", max_chars=max_chars) or split_for_captions(job.script or "")
                write_srt(lines, duration, srt)
                if _apply_srt_timing_guard(
                    srt,
                    duration,
                    enabled=subtitle_sync_repair,
                    repair_max_drift=subtitle_sync_repair_max_drift,
                    max_scale_delta=subtitle_sync_max_scale_delta,
                    validate_max_drift=subtitle_sync_tolerance,
                    label="script_split",
                ):
                    subtitle_ok = True
                    subtitle_method = "script_split"
                else:
                    raise RuntimeError("script-based subtitles were out of sync")
            except Exception as e:
                raise RuntimeError(f"Could not generate valid subtitles: {e}") from e

        print(f"[i] Subtitles ready: source={subtitle_method}, sync_tolerance={subtitle_sync_tolerance:.2f}s")

        print("[3/3] Render video" if external_audio else "[3/4] Render video")
        bg, credit_line = ensure_background_for_job(config, job, duration_s=duration, out_path=bg_out)
        if bg == bg_out:
            generated_artifacts.append(bg)
        render_video(bg, audio, srt, video, config, job.title or "")
        generated_artifacts.append(video.with_suffix(".title.txt"))
        generated_artifacts.append(video.with_suffix(".subs.ass"))

        print(f"?뚮뜑 ?꾨즺: {video}")
        if credit_line:
            credit_path = out_dir / f"{stamp}.credits.txt"
            credit_path.write_text(credit_line + "\n", encoding="utf-8")
            print(f"?щ젅?? {credit_path}")
            generated_artifacts.append(credit_path)

        if no_upload:
            print("?낅줈???ㅽ궢 (--no-upload ?먮뒗 NO_UPLOAD=1)")
        else:
            yt_cfg = dict(config.get("youtube") or {})
            idempotency_key = _job_idempotency_key(job_path)
            idempotency_state_file = str(yt_cfg.get("upload_state_file", "logs/uploads.jsonl"))
            state_path = Path(idempotency_state_file)

            existing = None
            if (not bool(args.force_upload)) and bool(yt_cfg.get("idempotency_enabled", True)):
                existing = _lookup_uploaded_record(state_path, idempotency_key)

            if existing:
                idempotency_hit = True
                video_id = existing.get("video_id") if isinstance(existing.get("video_id"), str) else None
                upload_url = existing.get("upload_url") if isinstance(existing.get("upload_url"), str) else None
                if not upload_url and video_id:
                    upload_url = f"https://youtu.be/{video_id}"
                print(f"[4/4] ?좏뒠釉??낅줈???ㅽ궢 (?대? ?낅줈?쒕맖): {upload_url or (video_id or 'unknown')}")
            else:
                print("[4/4] Uploading to YouTube...")
                validate_upload_checklist(config, job, video)
                video_id = upload_video(config, job, video, credit_line=credit_line)
                upload_url = f"https://youtu.be/{video_id}"
                print(f"?낅줈???꾨즺: {upload_url}")

                # Persist as soon as we have a video id so reruns won't duplicate-upload.
                if bool(yt_cfg.get("idempotency_enabled", True)):
                    _append_jsonl(
                        state_path,
                        {
                            "ts": datetime.now().isoformat(timespec="seconds"),
                            "job_key": idempotency_key,
                            "job_path": str(job_path),
                            "video_id": video_id,
                            "upload_url": upload_url,
                        },
                    )

        _print_summary(
            {
                "status": "ok",
                "elapsed_s": round(time.monotonic() - started, 3),
                "job": str(job_path),
                "stamp": stamp,
                "no_upload": no_upload,
                "video": str(video) if video else None,
                "audio": str(audio) if audio else None,
                "srt": str(srt) if srt else None,
                "credits": str(credit_path) if credit_path else None,
                "duration_s": round(float(duration), 3) if duration is not None else None,
                "video_id": video_id,
                "upload_url": upload_url,
                "idempotency_hit": idempotency_hit,
                "idempotency_key": idempotency_key,
                "idempotency_state_file": idempotency_state_file,
            }
        )
        print(
            format_result_line(
                status="ok",
                elapsed_s=(time.monotonic() - started),
                video=video,
                video_id=video_id,
                upload_url=upload_url,
                no_upload=no_upload,
            ),
            flush=True,
        )
        return 0
    except Exception as e:
        trace_lines: list[str] = []
        if args.traceback:
            trace_lines = traceback.format_exc().splitlines()
        error_summary = f"{type(e).__name__}: {e}"
        summary_payload = {
            "status": "error",
            "elapsed_s": round(time.monotonic() - started, 3),
            "job": str(job_path),
            "stamp": stamp,
            "no_upload": no_upload,
            "video": str(video) if video else None,
            "audio": str(audio) if audio else None,
            "srt": str(srt) if srt else None,
            "credits": str(credit_path) if credit_path else None,
            "duration_s": round(float(duration), 3) if duration is not None else None,
            "error_type": type(e).__name__,
            "error": _one_line(str(e)),
            "idempotency_hit": idempotency_hit,
            "idempotency_key": idempotency_key,
            "idempotency_state_file": idempotency_state_file,
        }
        if args.traceback:
            summary_payload["traceback"] = _one_line(" | ".join(trace_lines))
        _print_summary(summary_payload)
        result_line = format_result_line(
            status="error",
            elapsed_s=(time.monotonic() - started),
            video=video,
            # Preserve video_id if upload succeeded but later steps failed
            # (e.g., idempotency state persistence). This keeps RESULT lines
            # actionable for reruns and debugging.
            video_id=video_id,
            upload_url=upload_url,
            no_upload=no_upload,
            error=error_summary,
        )
        log_payload = {
            "status": "error",
            "job": str(job_path),
            "stamp": stamp,
            "no_upload": no_upload,
            "video": str(video) if video else None,
            "audio": str(audio) if audio else None,
            "srt": str(srt) if srt else None,
            "credits": str(credit_path) if credit_path else None,
            "duration_s": round(float(duration), 3) if duration is not None else None,
            "error_type": type(e).__name__,
            "error": _one_line(str(e)),
            "error_summary": error_summary,
            "idempotency_hit": idempotency_hit,
            "idempotency_key": idempotency_key,
            "idempotency_state_file": idempotency_state_file,
            "result_line": result_line,
        }
        if args.traceback:
            log_payload["traceback"] = _one_line(" | ".join(trace_lines))
        _log_error_event(config, log_payload)
        should_notify = _coerce_openclaw_notify_flag(
            config,
            env_key="OPENCLAW_NOTIFY_ON_FAILURE",
            config_key="openclaw_notify_on_failure",
            default=True,
        )
        if should_notify:
            log_path = _openclaw_log_path(config)
            notify_tail_lines = _coerce_int(config.get("openclaw_notify_tail_lines"), default=20, key="openclaw_notify_tail_lines")
            error_tail = _read_tail_lines(log_path, max_lines=notify_tail_lines)
            notify_message = _format_openclaw_message(
                status="error",
                job=str(job_path),
                error_type=type(e).__name__,
                error=_one_line(str(e)),
                result_line=result_line,
                log_file=log_path,
            )
            if error_tail:
                notify_message = f"{notify_message} | log_tail={_one_line(' | '.join(error_tail))}"

            _notify_openclaw(notify_message, config=config)

        print(
            result_line,
            flush=True,
        )
        if args.traceback:
            raise
        return 1
    finally:
        if not keep_intermediate_artifacts:
            _cleanup_paths(generated_artifacts, preserve=preserved_artifacts)
            if out_dir is not None:
                for artifact in list(out_dir.glob(f"{stamp}.*")):
                    if artifact not in preserved_artifacts and artifact.is_file():
                        try:
                            artifact.unlink(missing_ok=True)
                        except Exception as e:
                            print(f"[-] Failed to remove temporary artifact {artifact}: {_one_line(str(e))}")


if __name__ == "__main__":
    raise SystemExit(main())
