from __future__ import annotations

import re
import textwrap
from pathlib import Path
from typing import List, Tuple


TimingLine = Tuple[int, float, float]


def split_for_captions(text: str) -> list[str]:
    clean = re.sub(r"\s+", " ", text).strip()
    chunks = re.split(r"(?<=[.!?])\s+", clean)
    out = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        if len(chunk) > 28:
            out.extend(textwrap.wrap(chunk, width=26, break_long_words=False))
        else:
            out.append(chunk)
    return out


def split_for_captions_dense(text: str, *, max_chars: int = 22) -> list[str]:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return []

    chunks = re.split(r"(?<=[.!?…])\s+|[,:;，：；]\s*", clean)
    out = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        if len(chunk) > max_chars + 6:
            for connector in (
                " 그리고 ",
                " 그래서 ",
                " 하지만 ",
                " 그런데 ",
                " 그러면 ",
                " 즉 ",
                " 다시 말해 ",
                " 예를 들어 ",
                " 왜냐하면 ",
                " 왜냐면 ",
                " 반대로 ",
                " 대신 ",
            ):
                chunk = chunk.replace(connector, connector.rstrip() + "\n")
            parts = [part.strip() for part in chunk.split("\n") if part.strip()]
        else:
            parts = [chunk]

        for part in parts:
            part = re.sub(r"\s*[-/|]\s*", " ", part).strip()
            if len(part) > max_chars:
                out.extend(textwrap.wrap(part, width=max_chars, break_long_words=False))
            else:
                out.append(part)
    return out


def fmt_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    whole_seconds = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return "%02d:%02d:%02d,%03d" % (hours, minutes, whole_seconds, millis)


def write_srt(lines: list[str], duration: float, srt_path: Path) -> None:
    if not lines:
        lines = ["..."]
    chunk = duration / len(lines)
    cursor = 0.0
    blocks = []
    for index, line in enumerate(lines, start=1):
        start = cursor
        end = duration if index == len(lines) else cursor + chunk
        blocks.append("%d\n%s --> %s\n%s\n" % (index, fmt_time(start), fmt_time(end), line))
        cursor = end
    srt_path.write_text("\n".join(blocks), encoding="utf-8")


def parse_srt_timestamp_to_seconds(value: str) -> float:
    hours, minutes, rest = value.split(":")
    seconds, millis = rest.split(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000.0


def read_srt_timing_lines(path: Path) -> list[TimingLine]:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    if not raw.strip():
        raise ValueError("subtitle file is empty")
    lines = raw.splitlines()
    pattern = re.compile(r"^(?P<start>\d\d:\d\d:\d\d,\d\d\d)\s*-->\s*(?P<end>\d\d:\d\d:\d\d,\d\d\d)\s*$")
    out = []
    for index, line in enumerate(lines):
        if "-->" not in line:
            continue
        match = pattern.match(line.strip())
        if not match:
            raise ValueError("invalid timing format at line %d: %r" % (index + 1, line))
        start = parse_srt_timestamp_to_seconds(match.group("start"))
        end = parse_srt_timestamp_to_seconds(match.group("end"))
        out.append((index, start, end))
    if not out:
        raise ValueError("subtitle file has no timing lines")
    return out


def read_last_srt_end_time(path: Path) -> float:
    return read_srt_timing_lines(path)[-1][2]


def validate_srt_timing(path: Path, audio_duration: float, *, max_drift: float = 0.5) -> bool:
    try:
        last_end = read_last_srt_end_time(path)
    except Exception as exc:
        print("[-] Invalid subtitle timing (%s); file=%s" % (exc, path))
        return False
    if last_end <= 0:
        print("[-] Subtitle timing invalid: last_end=%.2f (file=%s)" % (last_end, path))
        return False
    drift = abs(last_end - audio_duration)
    if drift > max_drift:
        print(
            "[-] Subtitle timing drift=%.2fs exceeded threshold (%.2fs). file=%s, audio=%.2f, last_end=%.2f"
            % (drift, max_drift, path, audio_duration, last_end)
        )
        return False
    return True


def repair_srt_timing(
    path: Path,
    audio_duration: float,
    *,
    enabled: bool = True,
    max_drift: float = 0.5,
    max_scale_delta: float = 0.12,
    label: str = "srt",
) -> bool:
    if not enabled:
        print("[subtitles] repair disabled for %s; using raw timing." % label)
        return validate_srt_timing(path, audio_duration, max_drift=max_drift)
    try:
        entries = read_srt_timing_lines(path)
        raw_lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception as exc:
        print("[-] subtitle repair parse failed (%s): %s" % (label, exc))
        return False
    if not entries:
        print("[-] subtitle repair failed (%s): no timing entries found" % label)
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
        shift = -first_start
        entries = [(idx, max(0.0, start + shift), max(0.0, end + shift)) for idx, start, end in entries]
        first_start = 0.0
        last_end = entries[-1][2]
        applied_shift = shift
        should_apply = True

    drift_after_shift = abs(last_end - audio_duration)
    if drift_after_shift > max_drift and audio_duration > 0 and entries:
        target_scale = audio_duration / last_end
        target_scale = max(1.0 - max_scale_delta, min(1.0 + max_scale_delta, target_scale))
        if abs(target_scale - 1.0) > 1e-9:
            entries = [(idx, start * target_scale, end * target_scale) for idx, start, end in entries]
            last_end = entries[-1][2]
            applied_scale = target_scale
            should_apply = True

    if not should_apply:
        print(
            "[subtitles] %s timing repair skipped: first_start=%.3fs, initial_drift=%.2fs"
            % (label, first_start, initial_drift)
        )
        return True

    fixed_lines = raw_lines[:]
    for index, start, end in entries:
        fixed_lines[index] = "%s --> %s" % (fmt_time(start), fmt_time(end))
    try:
        path.write_text("\n".join(fixed_lines), encoding="utf-8")
    except Exception as exc:
        print("[-] Failed to write repaired subtitles (%s): %s" % (label, exc))
        return False

    final_drift = abs(last_end - audio_duration)
    print(
        "[subtitles] repair label=%s applied_shift=%.3fs applied_scale=%.6f initial_drift=%.2fs final_drift=%.2fs file=%s"
        % (label, applied_shift, applied_scale, initial_drift, final_drift, path)
    )
    return True


def apply_srt_timing_guard(
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
        if not repair_srt_timing(
            path,
            audio_duration,
            max_drift=repair_max_drift,
            max_scale_delta=max_scale_delta,
            label=label,
        ):
            print("[-] %s subtitle repair failed; moving to fallback." % label)
            return False
    return validate_srt_timing(path, audio_duration, max_drift=validate_max_drift)


def densify_srt_inplace(srt_path: Path, *, max_chars: int = 26) -> None:
    def parse_time(value: str) -> float:
        hours, minutes, rest = value.split(":")
        seconds, millis = rest.split(",")
        return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000.0

    raw = srt_path.read_text(encoding="utf-8", errors="ignore")
    blocks = re.split(r"\n\s*\n", raw.strip(), flags=re.M)
    out_blocks = []
    index = 1
    for block in blocks:
        lines = [line.rstrip("\r") for line in block.splitlines() if line.strip() != ""]
        if len(lines) < 3:
            continue
        timing = lines[1] if "-->" in lines[1] else lines[0]
        match = re.match(r"(\d\d:\d\d:\d\d,\d\d\d)\s*-->\s*(\d\d:\d\d:\d\d,\d\d\d)", timing)
        if not match:
            continue
        start = parse_time(match.group(1))
        end = parse_time(match.group(2))
        text = " ".join(lines[2:]).strip()
        if not text:
            continue
        parts = split_for_captions_dense(text, max_chars=max_chars) or [text]
        if len(parts) == 1:
            out_blocks.append("%d\n%s --> %s\n%s\n" % (index, fmt_time(start), fmt_time(end), parts[0]))
            index += 1
            continue
        total = sum(max(1, len(part)) for part in parts)
        cursor = start
        duration = max(0.01, end - start)
        for part in parts:
            share = (max(1, len(part)) / total) * duration
            out_blocks.append("%d\n%s --> %s\n%s\n" % (index, fmt_time(cursor), fmt_time(cursor + share), part))
            index += 1
            cursor += share
    srt_path.write_text("\n".join(out_blocks).strip() + "\n", encoding="utf-8")
