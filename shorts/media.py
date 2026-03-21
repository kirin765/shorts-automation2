from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

from .captions import densify_srt_inplace
from .config import Config
from .models import RenderJob


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("Command failed: %s\n%s" % (" ".join(cmd), result.stderr))


def resolve_bin(explicit: str, default: str) -> str:
    explicit = (explicit or "").strip()
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
        "Required binary not found: %s. Install it or set its config path explicitly." % default
    )


def resolve_ffmpeg(config: Config) -> str:
    return resolve_bin(config.app.ffmpeg_bin, "ffmpeg")


def resolve_ffprobe(config: Config) -> str:
    return resolve_bin(config.app.ffprobe_bin, "ffprobe")


def probe_duration(path: Path, *, ffprobe: str) -> float:
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


def tts_edge(
    text: str,
    voice: str,
    out_mp3: Path,
    *,
    rate: str,
    pitch: str,
    volume: str,
    out_srt: Optional[Path],
    proxy: Optional[str],
    timeout_s: int,
) -> None:
    cmd = [
        sys.executable,
        "-m",
        "edge_tts",
        "--text",
        text,
        "--voice",
        voice,
        "--rate",
        rate,
        "--volume",
        volume,
        "--pitch",
        pitch,
        "--write-media",
        str(out_mp3),
    ]
    if out_srt is not None:
        cmd += ["--write-subtitles", str(out_srt)]
    if proxy:
        cmd += ["--proxy", proxy]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    if result.returncode != 0:
        raise RuntimeError("edge-tts failed (exit %d): %s" % (result.returncode, result.stderr.strip()))
    if out_srt is not None and (not out_srt.exists() or out_srt.stat().st_size == 0):
        raise RuntimeError("edge-tts did not produce subtitles (SRT)")


def tts_elevenlabs(text: str, out_mp3: Path, *, voice_id: str, api_key: str, model_id: str = "eleven_multilingual_v2") -> None:
    import requests

    response = requests.post(
        "https://api.elevenlabs.io/v1/text-to-speech/%s" % voice_id,
        headers={
            "xi-api-key": api_key,
            "accept": "audio/mpeg",
            "content-type": "application/json",
        },
        json={
            "text": text,
            "model_id": model_id,
            "voice_settings": {
                "stability": 0.45,
                "similarity_boost": 0.80,
                "style": 0.25,
                "use_speaker_boost": True,
            },
        },
        timeout=40,
    )
    response.raise_for_status()
    out_mp3.write_bytes(response.content)


def tts_gtts(text: str, out_mp3: Path, *, lang: str) -> None:
    from gtts import gTTS

    gTTS(text=text, lang=lang).save(str(out_mp3))


def synthesize_speech(config: Config, job: RenderJob, out_mp3: Path, out_srt: Path) -> None:
    provider = (config.tts.provider or "edge").strip().lower()
    if provider == "elevenlabs":
        try:
            if not config.tts.elevenlabs_api_key or not config.tts.elevenlabs_voice_id:
                raise RuntimeError("ElevenLabs requires elevenlabs_api_key and elevenlabs_voice_id.")
            tts_elevenlabs(
                job.script,
                out_mp3,
                voice_id=config.tts.elevenlabs_voice_id,
                api_key=config.tts.elevenlabs_api_key,
            )
            return
        except Exception as exc:
            print("ElevenLabs TTS failed, falling back to Edge TTS: %s" % exc)
            provider = "edge"

    if provider == "edge":
        try:
            out_srt_path = out_srt if config.render.subtitle_align_edge else None
            proxy = config.tts.edge_proxy.strip() or None
            tts_edge(
                job.script,
                config.tts.voice,
                out_mp3,
                rate=config.tts.edge_rate,
                pitch=config.tts.edge_pitch,
                volume=config.tts.edge_volume,
                out_srt=out_srt_path,
                proxy=proxy,
                timeout_s=config.tts.edge_timeout_s,
            )
            if out_srt_path is not None and out_srt.exists():
                densify_srt_inplace(out_srt, max_chars=config.render.subtitle_max_chars)
            return
        except Exception as exc:
            print("Edge TTS failed, falling back to gTTS: %s" % exc)
            provider = "gtts"

    if provider == "gtts":
        try:
            tts_gtts(job.script, out_mp3, lang=config.app.default_language)
            return
        except Exception as exc:
            raise RuntimeError(
                "TTS generation failed. Network access is required for Edge TTS/gTTS.\n"
                "You can retry with --audio to skip TTS.\n"
                "gTTS error: %s" % exc
            ) from exc

    raise RuntimeError("Unsupported tts.provider: %s" % config.tts.provider)


def guess_pexels_query(job: RenderJob) -> str:
    if (job.pexels_query or "").strip():
        return job.pexels_query.strip()
    text = ("%s %s" % (job.title, job.script)).lower()
    if "ai.com" in text or "ai" in text or "인공지능" in text:
        return "artificial intelligence abstract technology"
    if "주식" in text or "stock" in text:
        return "stock market abstract"
    if "부동산" in text or "real estate" in text:
        return "city skyline"
    return "abstract background"


def pexels_video_search(
    *,
    api_key: str,
    query: str,
    orientation: str,
    per_page: int,
    min_height: int,
    timeout_s: int,
) -> dict[str, object]:
    import requests

    url = (
        "https://api.pexels.com/videos/search"
        f"?query={quote_plus(query)}&per_page={per_page}&orientation={quote_plus(orientation)}"
    )
    response = requests.get(url, headers={"Authorization": api_key}, timeout=timeout_s)
    response.raise_for_status()
    data = response.json()

    best_video = None
    best_file = None
    best_score = -1
    for video in data.get("videos", []) or []:
        width = int(video.get("width") or 0)
        height = int(video.get("height") or 0)
        if height <= 0 or width <= 0 or height < width:
            continue
        for video_file in video.get("video_files", []) or []:
            if (video_file.get("file_type") or "").lower() != "video/mp4":
                continue
            file_width = int(video_file.get("width") or 0)
            file_height = int(video_file.get("height") or 0)
            if file_height < file_width or file_height < min_height:
                continue
            score = file_height * 10000 + file_width
            if score > best_score:
                best_score = score
                best_video = video
                best_file = video_file
    if not best_video or not best_file:
        raise RuntimeError("No suitable Pexels portrait mp4 found for query=%r" % query)
    return {
        "video_id": best_video.get("id"),
        "page_url": best_video.get("url"),
        "user_name": (best_video.get("user") or {}).get("name"),
        "user_url": (best_video.get("user") or {}).get("url"),
        "download_url": best_file.get("link"),
        "width": best_file.get("width"),
        "height": best_file.get("height"),
        "duration": best_video.get("duration"),
        "query": query,
        "orientation": orientation,
    }


def pexels_video_search_many(
    *,
    api_key: str,
    query: str,
    orientation: str,
    per_page: int,
    min_height: int,
    count: int,
    timeout_s: int,
) -> list[dict[str, object]]:
    import requests

    url = (
        "https://api.pexels.com/videos/search"
        f"?query={quote_plus(query)}&per_page={per_page}&orientation={quote_plus(orientation)}"
    )
    response = requests.get(url, headers={"Authorization": api_key}, timeout=timeout_s)
    response.raise_for_status()
    data = response.json()

    scored = []
    for video in data.get("videos", []) or []:
        width = int(video.get("width") or 0)
        height = int(video.get("height") or 0)
        if height <= 0 or width <= 0 or height < width:
            continue
        video_id = video.get("id")
        if not video_id:
            continue
        for video_file in video.get("video_files", []) or []:
            if (video_file.get("file_type") or "").lower() != "video/mp4":
                continue
            file_width = int(video_file.get("width") or 0)
            file_height = int(video_file.get("height") or 0)
            if file_height < file_width or file_height < min_height:
                continue
            score = file_height * 10000 + file_width
            scored.append((score, video, video_file))

    scored.sort(key=lambda item: item[0], reverse=True)
    out = []
    seen_ids = set()
    for _score, video, video_file in scored:
        video_id = int(video.get("id"))
        if video_id in seen_ids:
            continue
        seen_ids.add(video_id)
        out.append(
            {
                "video_id": video.get("id"),
                "page_url": video.get("url"),
                "user_name": (video.get("user") or {}).get("name"),
                "user_url": (video.get("user") or {}).get("url"),
                "download_url": video_file.get("link"),
                "width": video_file.get("width"),
                "height": video_file.get("height"),
                "duration": video.get("duration"),
                "query": query,
                "orientation": orientation,
            }
        )
        if len(out) >= count:
            break
    if not out:
        raise RuntimeError("No suitable Pexels portrait mp4 found for query=%r" % query)
    return out


def download_file(url: str, out_path: Path, *, timeout_s: int) -> None:
    import requests

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".part")
    with requests.get(url, stream=True, timeout=timeout_s) as response:
        response.raise_for_status()
        with tmp.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if chunk:
                    handle.write(chunk)
    tmp.replace(out_path)


def _slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return value or "bg"


def _pick_pexels_offset(meta: dict[str, object], segment_s: float) -> float:
    try:
        duration = float(meta.get("duration") or 0.0)
    except Exception:
        duration = 0.0
    available = max(0.0, duration - segment_s - 0.1)
    if available <= 0.0:
        return 0.0
    try:
        video_id = int(meta.get("video_id") or 0)
    except Exception:
        video_id = 0
    return float((video_id * 2654435761) % int(available * 1000)) / 1000.0


def build_background_video_from_clips(
    config: Config,
    metas: list[dict[str, object]],
    out_path: Path,
    *,
    duration_s: float,
) -> tuple[Path, str]:
    ffmpeg = resolve_ffmpeg(config)
    clip_count = max(1, min(config.background.pexels_clip_count, len(metas)))
    metas = metas[:clip_count]
    cache_dir = Path(config.background.pexels_cache_dir)

    clip_paths = []
    credit_lines = []
    for meta in metas:
        name = "pexels_%s_%s_%sx%s.mp4" % (
            _slug(str(meta["query"])),
            meta["video_id"],
            meta["width"],
            meta["height"],
        )
        path = cache_dir / name
        if not path.exists():
            download_file(str(meta["download_url"]), path, timeout_s=config.background.pexels_download_timeout_s)
        clip_paths.append(path)
        credit_lines.append("- %s (by %s)" % (meta.get("page_url"), meta.get("user_name")))

    credit = "Background videos (Pexels):\n" + "\n".join(credit_lines)
    if clip_count == 1:
        return clip_paths[0], credit

    segment_s = duration_s / clip_count
    cmd = [ffmpeg, "-y"]
    for meta, path in zip(metas, clip_paths):
        offset = _pick_pexels_offset(meta, segment_s)
        cmd += ["-ss", "%.3f" % offset, "-t", "%.3f" % (segment_s + 0.25), "-i", str(path)]

    parts = []
    for index in range(clip_count):
        parts.append(
            "[%d:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,setsar=1,setpts=PTS-STARTPTS[v%d]" % (index, index)
        )
    concat_inputs = "".join("[v%d]" % index for index in range(clip_count))
    filter_complex = ";".join(parts) + ";%sconcat=n=%d:v=1:a=0[v]" % (concat_inputs, clip_count)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd += [
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-t",
        "%.3f" % duration_s,
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


def ensure_background_for_job(
    config: Config,
    job: RenderJob,
    *,
    duration_s: float,
    out_path: Path,
) -> tuple[Path, Optional[str]]:
    provider = (job.background_provider or config.background.provider or "local").strip().lower()
    if provider != "pexels":
        background_video = Path(job.background_video or config.background.local_video)
        if background_video.exists() and not config.background.regenerate_local:
            return background_video, None
        ffmpeg = resolve_ffmpeg(config)
        background_video.parent.mkdir(parents=True, exist_ok=True)
        run(
            [
                ffmpeg,
                "-y",
                "-f",
                "lavfi",
                "-i",
                "nullsrc=s=1080x1920:d=40",
                "-vf",
                "geq=r='42+18*sin(2*PI*(X/W+T/9))':"
                "g='56+18*sin(2*PI*(Y/H+T/8))':"
                "b='78+22*sin(2*PI*((X+Y)/(W+H)+T/10))',"
                "gblur=sigma=28,eq=saturation=0.72:contrast=1.06:brightness=-0.03,"
                "noise=alls=4:allf=t,drawgrid=w=140:h=140:t=1:c=white@0.025,"
                "drawbox=x=0:y=0:w=1080:h=1920:color=black@0.08:t=fill",
                "-t",
                "40",
                "-pix_fmt",
                "yuv420p",
                str(background_video),
            ]
        )
        return background_video, None

    api_key = (config.background.pexels_api_key or "").strip()
    if not api_key:
        raise RuntimeError("background.provider=pexels requires PEXELS_API_KEY/background.pexels_api_key.")

    query = (job.pexels_query or config.background.pexels_query or "").strip() or guess_pexels_query(job)
    if not (job.pexels_query or config.background.pexels_query):
        print("[bg] pexels query was not set; guessed query=%r" % query)

    clip_count = config.background.pexels_clip_count
    if clip_count <= 1:
        meta = pexels_video_search(
            api_key=api_key,
            query=query,
            orientation=config.background.pexels_orientation,
            per_page=config.background.pexels_per_page,
            min_height=config.background.pexels_min_height,
            timeout_s=config.background.pexels_timeout_s,
        )
        cache_dir = Path(config.background.pexels_cache_dir)
        name = "pexels_%s_%s_%sx%s.mp4" % (
            _slug(str(meta["query"])),
            meta["video_id"],
            meta["width"],
            meta["height"],
        )
        path = cache_dir / name
        if not path.exists():
            download_file(str(meta["download_url"]), path, timeout_s=config.background.pexels_download_timeout_s)
        credit = "Background video: %s (by %s)" % (meta.get("page_url"), meta.get("user_name"))
        return path, credit

    metas = pexels_video_search_many(
        api_key=api_key,
        query=query,
        orientation=config.background.pexels_orientation,
        per_page=max(config.background.pexels_per_page, 15),
        min_height=config.background.pexels_min_height,
        count=clip_count,
        timeout_s=config.background.pexels_timeout_s,
    )
    return build_background_video_from_clips(config, metas, out_path, duration_s=duration_s)


def _coerce_int(value: object, *, default: int, minimum: int = 0) -> int:
    try:
        number = int(value)
    except Exception:
        return default
    if number < minimum:
        return default
    return number


def _normalize_subtitle_position(value: str) -> str:
    normalized = str(value or "").strip().lower()
    parts = [part.strip() for part in normalized.split(",")]
    if len(parts) != 2:
        return "center,middle"
    horizontal, vertical = parts
    if horizontal not in {"left", "center", "right"}:
        return "center,middle"
    if vertical not in {"top", "middle", "bottom"}:
        return "center,middle"
    return "%s,%s" % (horizontal, vertical)


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


def _coerce_font_name(family: Optional[str], fontfile: Optional[str] = None) -> str:
    if family:
        return ",".join(part.strip() for part in family.split(",") if part.strip()) or "Noto Sans CJK KR"
    if fontfile:
        return _font_name_from_path(fontfile)
    return "Noto Sans CJK KR"


def _ffmpeg_escape(text: str) -> str:
    return (
        text.replace("\\", r"\\")
        .replace(":", r"\:")
        .replace("'", r"\'")
        .replace(",", r"\,")
        .replace("%", r"\%")
    )


def _srt_timestamp_to_ass(value: str) -> str:
    hours, minutes, rest = value.split(":")
    seconds, millis = rest.split(",")
    centis = int(round(int(millis) / 10.0))
    if centis >= 100:
        centis = 99
    return "%d:%02d:%02d.%02d" % (int(hours), int(minutes), int(seconds), centis)


def _ass_escape_text(text: str) -> str:
    escaped = text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")
    return escaped.replace("\n", r"\N")


def _build_ass_from_srt(
    srt_path: Path,
    ass_path: Path,
    *,
    playres_y: int,
    font_name: str,
    font_size: int,
    outline: int,
    alignment: int,
    margin_v: int,
    margin_lr: int,
) -> None:
    raw = srt_path.read_text(encoding="utf-8", errors="ignore").strip()
    blocks = re.split(r"\n\s*\n", raw, flags=re.M) if raw else []
    events = []
    timing_pattern = re.compile(
        r"^(?P<start>\d\d:\d\d:\d\d,\d\d\d)\s*-->\s*(?P<end>\d\d:\d\d:\d\d,\d\d\d)\s*$"
    )

    for block in blocks:
        lines = [line.rstrip("\r") for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        timing_line = lines[1] if "-->" in lines[1] else lines[0]
        match = timing_pattern.match(timing_line.strip())
        if not match:
            continue
        text_lines = lines[2:] if "-->" in lines[1] else lines[1:]
        text = _ass_escape_text("\n".join(text_lines).strip())
        if not text:
            continue
        events.append(
            "Dialogue: 0,%s,%s,Default,,0,0,0,,%s"
            % (
                _srt_timestamp_to_ass(match.group("start")),
                _srt_timestamp_to_ass(match.group("end")),
                text,
            )
        )

    ass_text = "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            "PlayResX: 1080",
            "PlayResY: %d" % playres_y,
            "WrapStyle: 0",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,"
            "Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
            "Alignment,MarginL,MarginR,MarginV,Encoding",
            "Style: Default,%s,%d,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
            "0,0,0,0,100,100,0,0,1,%d,0,%d,%d,%d,%d,1"
            % (font_name, font_size, outline, alignment, margin_lr, margin_lr, margin_v),
            "",
            "[Events]",
            "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
            *events,
            "",
        ]
    )
    ass_path.write_text(ass_text, encoding="utf-8")


def resolve_font_for_korean(config: Config) -> tuple[Optional[str], Optional[str]]:
    def fc_match(query: str) -> tuple[Optional[str], Optional[str]]:
        try:
            result = subprocess.run(
                ["fc-match", "-f", "%{file}\n%{family}\n", query],
                capture_output=True,
                text=True,
                check=False,
                timeout=2,
            )
        except Exception:
            return None, None
        if result.returncode != 0:
            return None, None
        lines = (result.stdout or "").splitlines()
        if not lines:
            return None, None
        fontfile = lines[0].strip()
        fontname = lines[1].strip() if len(lines) > 1 else None
        if fontfile and Path(fontfile).exists():
            return fontfile, fontname
        return None, None

    if config.render.font_file:
        path = Path(config.render.font_file)
        if path.exists():
            return str(path), _coerce_font_name(None, str(path))

    candidates = [
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
            return path, name

    for query in (
        "Noto Sans CJK KR:style=Bold",
        "Noto Sans CJK KR",
        "Noto Sans KR:style=Bold",
        "Apple SD Gothic Neo:style=Bold",
        ":lang=ko",
    ):
        fontfile, fontname = fc_match(query)
        if fontfile:
            return fontfile, _coerce_font_name(fontname, fontfile)

    return None, None


def format_title_for_titlefile(title: str) -> tuple[str, int]:
    clean = re.sub(r"\s+", " ", title).strip()
    if not clean:
        return "", 72

    def visual_len(value: str) -> float:
        total = 0.0
        for char in value:
            if char.isspace():
                total += 0.3
            elif ord(char) < 128:
                total += 0.6
            else:
                total += 1.0
        return total

    target_px = 980
    unit_px = 0.92

    def fit_fontsize(visual: float, cap: int) -> int:
        if visual <= 0:
            return min(72, cap)
        return max(52, min(cap, int(target_px / (visual * unit_px))))

    one_line_size = fit_fontsize(visual_len(clean), 92)
    if one_line_size >= 74:
        return clean, one_line_size

    tokens = [token for token in clean.split(" ") if token]
    if len(tokens) < 2:
        return clean, one_line_size

    best = None
    for index in range(1, len(tokens)):
        left = " ".join(tokens[:index]).strip()
        right = " ".join(tokens[index:]).strip()
        candidate = max(visual_len(left), visual_len(right))
        if best is None or candidate < best[0]:
            best = (candidate, left, right)

    if best is None:
        return clean, one_line_size

    max_line, left, right = best
    two_line_size = fit_fontsize(max_line, 88)
    return "%s\n%s" % (left, right), two_line_size


def render_video(config: Config, job: RenderJob, bg: Path, audio: Path, srt: Path, out_video: Path) -> None:
    ffmpeg = resolve_ffmpeg(config)
    ffprobe = resolve_ffprobe(config)
    duration = probe_duration(audio, ffprobe=ffprobe)
    srt_safe = srt.as_posix().replace("'", r"\'")

    fontfile, fontname = resolve_font_for_korean(config)
    font_opt = ""
    subs_font_name = "Noto Sans CJK KR"
    if fontfile:
        font_opt = ":fontfile=%s" % _ffmpeg_escape(fontfile)
        if fontname:
            subs_font_name = fontname

    subtitle_fontfile = fontfile or ""
    subtitle_font_name = _coerce_font_name(subs_font_name, subtitle_fontfile)
    fontsdir = None
    if fontfile:
        fontsdir = str(Path(fontfile).parent)
    elif Path("/mnt/c/Windows/Fonts").exists():
        fontsdir = "/mnt/c/Windows/Fonts"
    if config.render.subtitle_fontsdir:
        fontsdir = config.render.subtitle_fontsdir
    fontsdir_opt = ":fontsdir='%s'" % _ffmpeg_escape(fontsdir) if fontsdir else ""

    title_content, title_fontsize = format_title_for_titlefile(job.title)
    title_txt = out_video.with_suffix(".title.txt")
    title_txt.write_text(title_content + "\n", encoding="utf-8")
    title_txt_safe = _ffmpeg_escape(str(title_txt))
    ass_subs = out_video.with_suffix(".subs.ass")

    playres_y = config.render.subtitle_playres_y

    def px_to_ass(value_px: int, *, minimum: int = 1) -> int:
        return max(minimum, int(round(value_px * (playres_y / 1920.0))))

    subtitle_position = _normalize_subtitle_position(job.subtitle_position or config.render.subtitle_position)
    _horizontal, vertical = subtitle_position.split(",")
    subtitle_alignment = _align_from_position(subtitle_position)
    subtitle_font_size = (
        job.subtitle_font_size if job.subtitle_font_size is not None else config.render.subtitle_font_size
    )
    subtitle_outline = _coerce_int(config.render.subtitle_outline, default=8, minimum=0)
    subtitle_margin_default = config.render.subtitle_margin_v
    if vertical == "top":
        subtitle_margin_px = config.render.subtitle_margin_top_v
    elif vertical == "bottom":
        subtitle_margin_px = config.render.subtitle_margin_bottom_v
    else:
        subtitle_margin_px = subtitle_margin_default + config.render.subtitle_vshift

    print(
        "[subtitles] position=%s align=%s font=%s fontfile=%s font_size=%s outline=%s margin_v=%s"
        % (
            subtitle_position,
            subtitle_alignment,
            subtitle_font_name,
            subtitle_fontfile or "default",
            subtitle_font_size,
            subtitle_outline,
            subtitle_margin_px,
        )
    )

    margin_min = -300 if vertical == "middle" else 0
    subtitle_style = (
        "FontName=%s,"
        "FontSize=%s,"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,"
        "BackColour=&H00000000,"
        "BorderStyle=1,"
        "Outline=%s,"
        "Shadow=0,"
        "Alignment=%s,"
        "MarginV=%s"
        % (
            subtitle_font_name,
            px_to_ass(subtitle_font_size),
            px_to_ass(subtitle_outline),
            subtitle_alignment,
            px_to_ass(subtitle_margin_px, minimum=margin_min),
        )
    )
    _build_ass_from_srt(
        srt,
        ass_subs,
        playres_y=playres_y,
        font_name=subtitle_font_name,
        font_size=px_to_ass(subtitle_font_size),
        outline=px_to_ass(subtitle_outline),
        alignment=subtitle_alignment,
        margin_v=px_to_ass(subtitle_margin_px, minimum=margin_min),
        margin_lr=64,
    )
    ass_safe = _ffmpeg_escape(str(ass_subs))
    title_y = max(108, int(config.render.top_bar_height * 0.56))
    vf = (
        "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        "eq=saturation=0.90:contrast=1.04,"
        "drawbox=x=0:y=0:w=1080:h=%d:color=black@1.0:t=fill,"
        "drawbox=x=0:y=%d:w=1080:h=%d:color=black@1.0:t=fill,"
        "drawtext=textfile='%s'%s:reload=0:x=(w-text_w)/2:y=%d:fontsize=%d:"
        "fontcolor=white:borderw=8:bordercolor=black:line_spacing=10:text_align=C:fix_bounds=1,"
        "subtitles='%s'%s,"
        "drawbox=x=0:y=1892:w='1080*t/%.3f':h=10:color=0x00E5FF@0.9:t=fill"
        % (
            config.render.top_bar_height,
            1920 - config.render.bottom_bar_height,
            config.render.bottom_bar_height,
            title_txt_safe,
            font_opt,
            title_y,
            title_fontsize,
            ass_safe,
            fontsdir_opt,
            duration,
        )
    )

    cmd = [ffmpeg, "-y", "-stream_loop", "-1", "-i", str(bg), "-i", str(audio)]
    bgm_file = Path(config.render.bgm_file) if config.render.bgm_file else None
    use_bgm = bool(bgm_file and bgm_file.exists())
    if use_bgm:
        cmd += ["-stream_loop", "-1", "-i", str(bgm_file)]
        cmd += [
            "-t",
            "%.3f" % duration,
            "-filter_complex",
            "[0:v]%s[v];[1:a]volume=1.0[a1];[2:a]volume=0.08[a2];[a1][a2]amix=inputs=2:duration=first[a]"
            % vf,
            "-map",
            "[v]",
            "-map",
            "[a]",
        ]
    else:
        cmd += [
            "-t",
            "%.3f" % duration,
            "-vf",
            vf,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
        ]

    bitrate_args = ["-b:v", config.render.video_bitrate] if config.render.video_bitrate else []
    cmd += [
        "-c:v",
        "libx264",
        "-preset",
        config.render.video_preset,
        "-crf",
        str(config.render.video_crf),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        config.render.audio_bitrate or "192k",
        *bitrate_args,
        "-shortest",
        "-movflags",
        "+faststart",
        str(out_video),
    ]
    run(cmd)
