from __future__ import annotations

import json
import textwrap
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Optional

import requests

from .captions import fmt_time, split_for_captions, split_for_captions_dense
from .config import Config
from .models import DraftJob, RenderJob


def openai_api_key(config: Config) -> str:
    key = config.content.openai_api_key.strip()
    if not key:
        raise RuntimeError(
            "OpenAI integration is active but OPENAI_API_KEY/content.openai_api_key is missing."
        )
    return key


def generate_topics(
    config: Config,
    *,
    count: int,
    language: str,
    niche: str,
    style: str,
    existing_topics: Optional[Iterable[str]] = None,
) -> list[str]:
    key = openai_api_key(config)
    existing = [item.strip() for item in (existing_topics or []) if item and item.strip()]
    existing_tail = "\n".join("- %s" % item for item in existing[-80:]) or "(none)"
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "topics": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": max(1, count),
                "maxItems": max(1, count) + 5,
            }
        },
        "required": ["topics"],
    }
    system = (
        "You generate high-retention YouTube Shorts topic ideas. "
        "Do not include emojis. Do not include hashtags. "
        "Avoid precise claims that need fact-checking. "
        "Output only valid JSON matching the schema."
    )
    user = (
        "Language: %s\n"
        "Niche: %s\n"
        "Style: %s\n"
        "Date: %s\n"
        "Generate %d topics. Each topic should be one line, <= 35 characters if Korean.\n"
        "Prefer topics that can be explained in ~25-35 seconds.\n"
        "Avoid repeating these recent topics if possible:\n"
        "%s\n"
    ) % (language, niche, style, date.today().isoformat(), count, existing_tail)
    payload = _responses_payload(
        model=config.content.openai_topic_model or config.content.openai_model,
        system=system,
        user=user,
        schema_name="topics",
        schema=schema,
        temperature=config.content.openai_topic_temperature,
        max_output_tokens=config.content.openai_topic_max_output_tokens,
    )
    data = _responses_request(config, key, payload)
    obj = _decode_output_json(data)
    topics = [item.strip() for item in obj.get("topics") or [] if isinstance(item, str) and item.strip()]

    seen = set()
    filtered = []
    existing_set = set(existing)
    for topic in topics:
        if topic in seen:
            continue
        seen.add(topic)
        if topic in existing_set:
            continue
        filtered.append(topic)
        if len(filtered) >= count:
            break

    if len(filtered) < max(1, count // 2):
        filtered = (filtered or topics)[:count]
    return filtered


def generate_render_job(config: Config, draft_job: DraftJob) -> RenderJob:
    key = openai_api_key(config)
    target_seconds = draft_job.target_seconds or config.app.shorts_target_seconds
    system = (
        "You write high-retention YouTube Shorts scripts (Korean). "
        "Do not invent precise statistics, dates, prices, quotes, or named sources. "
        "If you need numbers, use vague ranges or omit them. "
        "Keep sentences short and punchy. "
        "Output must be valid JSON matching the provided schema."
    )
    user = (
        "Language: %s\n"
        "Topic: %s\n"
        "Style: %s\n"
        "Tone: %s\n"
        "Target duration: about %d seconds of narration.\n"
        "Output rules:\n"
        "- title: <= 28 chars, curiosity-driven, no clickbait lies.\n"
        "- script: 5-7 sentences total. First sentence must be the hook.\n"
        "- script: avoid long clauses; prefer short lines that are easy to subtitle.\n"
        "- description: 1-2 sentences summary.\n"
        "- hashtags: 3-5 tags including #shorts.\n"
        "- pexels_query: 4-8 English words, no brand names.\n"
    ) % (
        config.content.openai_language or config.app.default_language,
        draft_job.topic,
        draft_job.style or "tech news / explain like I am busy",
        draft_job.tone or "confident, concise",
        target_seconds,
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
    payload = _responses_payload(
        model=config.content.openai_model,
        system=system,
        user=user,
        schema_name="render_job",
        schema=schema,
        temperature=config.content.openai_temperature,
        max_output_tokens=config.content.openai_max_output_tokens,
    )
    data = _responses_request(config, key, payload)
    obj = _decode_output_json(data)
    return RenderJob(
        title=str(obj["title"]).strip(),
        script=str(obj["script"]).strip(),
        description=str(obj["description"]).strip(),
        hashtags=str(obj["hashtags"]).strip(),
        pexels_query=str(obj["pexels_query"]).strip() or None,
    )


def write_srt_aligned_openai(
    config: Config,
    *,
    audio_path: Path,
    srt_path: Path,
    prompt_text: str,
    script_text: str,
) -> None:
    api_key = openai_api_key(config)
    base_url = config.content.openai_base_url.rstrip("/")
    model = config.content.openai_transcribe_model.strip() or "whisper-1"
    timeout_s = config.content.openai_transcribe_timeout_s
    language = (config.content.openai_transcribe_language or config.app.default_language).strip()

    files = {"file": (audio_path.name, audio_path.read_bytes(), "audio/mpeg")}
    data = {
        "model": model,
        "response_format": "verbose_json",
        "prompt": (prompt_text or "")[:4000],
        "timestamp_granularities[]": ["word", "segment"],
    }
    if language:
        data["language"] = language

    response = requests.post(
        "%s/audio/transcriptions" % base_url,
        headers={"Authorization": "Bearer %s" % api_key},
        files=files,
        data=data,
        timeout=timeout_s,
    )
    response.raise_for_status()
    obj = response.json()

    max_chars = config.render.subtitle_max_chars
    min_cue = config.render.subtitle_min_cue_s
    max_cue = config.render.subtitle_max_cue_s
    max_words = config.render.subtitle_words_per_cue
    blocks = []
    windows = []
    transcript_lines = []

    def add_window(start: float, end: float) -> None:
        if end <= start:
            end = start + min_cue
        duration = end - start
        if duration < min_cue:
            end = start + min_cue
        elif duration > max_cue:
            end = start + max_cue
        windows.append((start, end))

    def add_block(index: int, start: float, end: float, text: str) -> None:
        if not text.strip():
            return
        blocks.append("%d\n%s --> %s\n%s\n" % (index, fmt_time(start), fmt_time(end), text.strip()))

    words = obj.get("words") or []
    if isinstance(words, list) and words:
        cue_words = []
        cue_text = ""
        for word in words:
            if not isinstance(word, dict):
                continue
            token = str(word.get("word") or "").strip()
            if not token:
                continue
            cue_words.append(word)
            cue_text = (cue_text + (" " if cue_text else "") + token).strip()
            if len(cue_words) >= max_words or len(cue_text) >= max_chars or token.endswith((".", "!", "?", "…")):
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
        segments = obj.get("segments") or []
        if not isinstance(segments, list) or not segments:
            raise RuntimeError("transcription returned no segments/words")
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            text = str(segment.get("text") or "").strip()
            if not text:
                continue
            start = float(segment.get("start") or 0.0)
            end = float(segment.get("end") or start)
            parts = textwrap.wrap(text, width=max_chars, break_long_words=False) or [text]
            if len(parts) == 1:
                add_window(start, end)
                transcript_lines.append(parts[0].strip())
                continue
            total = sum(max(1, len(part)) for part in parts)
            cursor = start
            for part in parts:
                share = (max(1, len(part)) / total) * max(0.01, end - start)
                add_window(cursor, cursor + share)
                transcript_lines.append(part.strip())
                cursor += share

    text_source = (config.render.subtitle_text_source or "transcript").strip().lower()
    if text_source not in ("transcript", "script"):
        text_source = "transcript"

    if text_source == "script":
        lines = split_for_captions_dense(script_text or "", max_chars=max_chars) or split_for_captions(script_text or "")
        if not windows:
            raise RuntimeError("no timing windows produced")

        def resample_windows(src: list[tuple[float, float]], target_count: int) -> list[tuple[float, float]]:
            if target_count <= len(src):
                return src[:target_count]
            out = list(src)
            while len(out) < target_count:
                index = max(range(len(out)), key=lambda item: (out[item][1] - out[item][0]))
                start, end = out[index]
                if end - start <= (min_cue * 2.05):
                    break
                midpoint = (start + end) / 2.0
                out[index : index + 1] = [(start, midpoint), (midpoint, end)]
            while len(out) < target_count:
                _start, end = out[-1]
                out.append((end, end + min_cue))
            return out

        matched_windows = resample_windows(windows, len(lines))
        for index, ((start, end), text) in enumerate(zip(matched_windows, lines), start=1):
            add_block(index, start, end, text)
        srt_path.write_text("\n".join(blocks), encoding="utf-8")
        return

    for index, ((start, end), text) in enumerate(zip(windows, transcript_lines), start=1):
        add_block(index, start, end, text)
    srt_path.write_text("\n".join(blocks), encoding="utf-8")


def _responses_payload(
    *,
    model: str,
    system: str,
    user: str,
    schema_name: str,
    schema: dict[str, Any],
    temperature: float,
    max_output_tokens: int,
) -> dict[str, Any]:
    return {
        "model": model,
        "input": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "schema": schema,
                "strict": True,
            }
        },
        "store": False,
    }


def _responses_request(config: Config, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(
        "%s/responses" % config.content.openai_base_url.rstrip("/"),
        headers={"Authorization": "Bearer %s" % api_key, "Content-Type": "application/json"},
        json=payload,
        timeout=config.content.openai_timeout_s,
    )
    response.raise_for_status()
    return response.json()


def _decode_output_json(data: dict[str, Any]) -> dict[str, Any]:
    text = None
    for item in data.get("output", []) or []:
        for content in item.get("content", []) or []:
            if content.get("type") in ("output_text", "text") and isinstance(content.get("text"), str):
                text = content["text"]
                break
        if text:
            break
    if not text:
        raise RuntimeError("OpenAI response did not include output text.")
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise RuntimeError("OpenAI response JSON must be an object.")
    return obj
