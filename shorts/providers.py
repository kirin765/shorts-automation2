from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

import requests

from . import prompts
from .captions import fmt_time, split_for_captions, split_for_captions_dense
from .config import Config
from .models import DraftJob, ReviewedPackage, RenderJob, ScriptPackage, SelectedTopic, TopicCandidate, TopicPool, TopicScores


@dataclass
class ReviewFeedback:
    approved: bool
    selected_title: str
    description: str
    hashtags: str
    retention_score: int
    novelty_score: int
    risk_flags: list[str]
    fact_check_points: list[str]
    review_notes: list[str]
    rewrite_instructions: list[str]


def openai_api_key(config: Config) -> str:
    key = config.content.openai_api_key.strip()
    if not key:
        raise RuntimeError(
            "OpenAI integration is active but OPENAI_API_KEY/content.openai_api_key is missing."
        )
    return key


def generate_topic_pool(
    config: Config,
    *,
    run_id: str,
    count: int,
    existing_topics: Optional[Iterable[str]] = None,
) -> TopicPool:
    key = openai_api_key(config)
    existing = [item.strip() for item in (existing_topics or []) if item and item.strip()]
    system, user, schema = prompts.build_topic_pool_prompt(config, count=count, existing_topics=existing)
    payload = _responses_payload(
        model=config.content.openai_topic_model or config.content.openai_model,
        system=system,
        user=user,
        schema_name="topic_pool",
        schema=schema,
        temperature=config.content.openai_topic_temperature,
        max_output_tokens=config.content.openai_topic_max_output_tokens,
    )
    data = _responses_request(config, key, payload)
    obj = _decode_output_json(data)
    seen = set()
    existing_set = set(existing)
    candidates = []
    for index, raw in enumerate(obj.get("candidates") or [], start=1):
        if not isinstance(raw, dict):
            continue
        payload_item = dict(raw)
        payload_item["candidate_id"] = str(payload_item.get("candidate_id") or "candidate_%02d" % index).strip() or "candidate_%02d" % index
        candidate = TopicCandidate.from_dict(payload_item)
        topic_key = candidate.topic.strip()
        if topic_key in seen or topic_key in existing_set:
            continue
        seen.add(topic_key)
        candidates.append(candidate)
        if len(candidates) >= count:
            break
    if not candidates:
        raise RuntimeError("topic generation returned no usable candidates")
    return TopicPool(
        run_id=run_id,
        channel_category=config.content.channel_category,
        series_name=config.content.series_name,
        generated_at=datetime.now().isoformat(timespec="seconds"),
        candidates=candidates,
    )


def evaluate_topic_pool(config: Config, topic_pool: TopicPool, *, select_count: int) -> list[SelectedTopic]:
    key = openai_api_key(config)
    system, user, schema = prompts.build_topic_evaluation_prompt(config, candidates=topic_pool.candidates)
    payload = _responses_payload(
        model=config.content.openai_topic_model or config.content.openai_model,
        system=system,
        user=user,
        schema_name="topic_evaluations",
        schema=schema,
        temperature=config.content.openai_topic_temperature,
        max_output_tokens=config.content.openai_topic_max_output_tokens,
    )
    data = _responses_request(config, key, payload)
    obj = _decode_output_json(data)
    candidates_by_id = {item.candidate_id: item for item in topic_pool.candidates}
    selected = []
    for raw in obj.get("evaluations") or []:
        if not isinstance(raw, dict):
            continue
        candidate_id = str(raw.get("candidate_id") or "").strip()
        candidate = candidates_by_id.get(candidate_id)
        if not candidate:
            continue
        scores = TopicScores.from_dict(
            {
                "clarity": raw.get("clarity"),
                "hook_strength": raw.get("hook_strength"),
                "retention_potential": raw.get("retention_potential"),
                "twist_potential": raw.get("twist_potential"),
                "series_fit": raw.get("series_fit"),
                "repetition_risk": raw.get("repetition_risk"),
                "monetization_safety": raw.get("monetization_safety"),
            }
        )
        if not scores.passes_thresholds():
            continue
        selected.append(
            SelectedTopic(
                run_id=topic_pool.run_id,
                candidate_id=candidate.candidate_id,
                rank=0,
                series_name=candidate.series_name,
                topic=candidate.topic,
                angle=candidate.angle,
                target_emotion=candidate.target_emotion,
                scores=scores,
                overall_score=scores.overall_score(),
                selection_reason=str(raw.get("selection_reason") or "selected").strip() or "selected",
            )
        )
    selected.sort(key=lambda item: item.overall_score, reverse=True)
    for index, item in enumerate(selected, start=1):
        item.rank = index
    chosen = selected[: max(1, select_count)]
    if not chosen:
        raise RuntimeError("topic evaluation produced no candidates above threshold")
    return chosen


def manual_selected_topic(config: Config, *, run_id: str, topic: str) -> SelectedTopic:
    cleaned = topic.strip()
    if not cleaned:
        raise ValueError("manual topic must be non-empty")
    baseline = TopicScores(
        clarity=10,
        hook_strength=10,
        retention_potential=10,
        twist_potential=8,
        series_fit=10,
        repetition_risk=1,
        monetization_safety=10,
    )
    return SelectedTopic(
        run_id=run_id,
        candidate_id="manual_01",
        rank=1,
        series_name=config.content.series_name,
        topic=cleaned,
        angle="이 주제를 왜 지금 봐야 하는지 설명한다",
        target_emotion="curiosity",
        scores=baseline,
        overall_score=baseline.overall_score(),
        selection_reason="manual topic",
    )


def generate_script_package(config: Config, selected_topic: SelectedTopic) -> ScriptPackage:
    key = openai_api_key(config)
    system, user, schema = prompts.build_script_package_prompt(config, topic_payload=selected_topic.to_dict())
    payload = _responses_payload(
        model=config.content.openai_model,
        system=system,
        user=user,
        schema_name="script_package",
        schema=schema,
        temperature=config.content.openai_temperature,
        max_output_tokens=config.content.openai_max_output_tokens,
    )
    data = _responses_request(config, key, payload)
    obj = _decode_output_json(data)
    return ScriptPackage.from_dict(
        {
            "run_id": selected_topic.run_id,
            "candidate_id": selected_topic.candidate_id,
            "series_name": selected_topic.series_name,
            "topic": selected_topic.topic,
            "angle": selected_topic.angle,
            "target_emotion": selected_topic.target_emotion,
            **obj,
        }
    )


def review_script_package(config: Config, script_package: ScriptPackage) -> ReviewFeedback:
    key = openai_api_key(config)
    system, user, schema = prompts.build_script_review_prompt(config, script_package=script_package)
    payload = _responses_payload(
        model=config.content.openai_model,
        system=system,
        user=user,
        schema_name="script_review",
        schema=schema,
        temperature=config.content.openai_temperature,
        max_output_tokens=config.content.openai_max_output_tokens,
    )
    data = _responses_request(config, key, payload)
    obj = _decode_output_json(data)
    return _review_feedback_from_dict(obj)


def rewrite_script_package(config: Config, script_package: ScriptPackage, review_feedback: ReviewFeedback) -> ScriptPackage:
    key = openai_api_key(config)
    system, user, schema = prompts.build_script_rewrite_prompt(
        config,
        script_package=script_package,
        rewrite_instructions=review_feedback.rewrite_instructions,
    )
    payload = _responses_payload(
        model=config.content.openai_model,
        system=system,
        user=user,
        schema_name="script_package_rewrite",
        schema=schema,
        temperature=config.content.openai_temperature,
        max_output_tokens=config.content.openai_max_output_tokens,
    )
    data = _responses_request(config, key, payload)
    obj = _decode_output_json(data)
    return ScriptPackage.from_dict(
        {
            "run_id": script_package.run_id,
            "candidate_id": script_package.candidate_id,
            "series_name": script_package.series_name,
            "topic": script_package.topic,
            "angle": script_package.angle,
            "target_emotion": script_package.target_emotion,
            **obj,
        }
    )


def review_passes(config: Config, script_package: ScriptPackage, review_feedback: ReviewFeedback) -> bool:
    if not review_feedback.approved:
        return False
    if script_package.duration_sec < 20 or script_package.duration_sec > 35:
        return False
    if review_feedback.retention_score < config.content.review_min_retention_score:
        return False
    if review_feedback.novelty_score < config.content.review_min_novelty_score:
        return False
    if any(item.strip() for item in review_feedback.risk_flags):
        return False
    return True


def build_reviewed_package(
    config: Config,
    script_package: ScriptPackage,
    review_feedback: ReviewFeedback,
    *,
    rewrite_applied: bool,
) -> ReviewedPackage:
    if not review_passes(config, script_package, review_feedback):
        raise RuntimeError("review did not pass thresholds")
    hashtags = _normalize_hashtags(review_feedback.hashtags)
    return ReviewedPackage.from_dict(
        {
            **script_package.to_dict(),
            "selected_title": review_feedback.selected_title,
            "description": review_feedback.description,
            "hashtags": hashtags,
            "review_notes": review_feedback.review_notes,
            "rewrite_applied": rewrite_applied,
            "retention_score": review_feedback.retention_score,
            "novelty_score": review_feedback.novelty_score,
            "risk_flags": review_feedback.risk_flags,
            "fact_check_points": review_feedback.fact_check_points,
        }
    )


def package_render_job(reviewed_package: ReviewedPackage) -> RenderJob:
    script_parts = [reviewed_package.best_hook] + reviewed_package.script_lines + [reviewed_package.ending]
    return RenderJob(
        title=reviewed_package.selected_title,
        script="\n".join(item.strip() for item in script_parts if item and item.strip()),
        description=reviewed_package.description,
        hashtags=_normalize_hashtags(reviewed_package.hashtags),
        pexels_query=reviewed_package.pexels_query,
    )


def generate_topics(
    config: Config,
    *,
    count: int,
    language: str,
    niche: str,
    style: str,
    existing_topics: Optional[Iterable[str]] = None,
) -> list[str]:
    _ = language, niche, style
    pool = generate_topic_pool(
        config,
        run_id="legacy-topics",
        count=count,
        existing_topics=existing_topics,
    )
    return [item.topic for item in pool.candidates[:count]]


def generate_render_job(config: Config, draft_job: DraftJob) -> RenderJob:
    selected = manual_selected_topic(config, run_id="legacy-render", topic=draft_job.topic)
    package = generate_script_package(config, selected)
    feedback = review_script_package(config, package)
    rewrite_applied = False
    if not review_passes(config, package, feedback):
        package = rewrite_script_package(config, package, feedback)
        feedback = review_script_package(config, package)
        rewrite_applied = True
    reviewed = build_reviewed_package(config, package, feedback, rewrite_applied=rewrite_applied)
    return package_render_job(reviewed)


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


def _normalize_hashtags(hashtags: str) -> str:
    cleaned = " ".join(part for part in hashtags.split() if part.strip())
    lowered = {part.lower() for part in cleaned.split()}
    if "#shorts" not in lowered:
        cleaned = "#shorts " + cleaned if cleaned else "#shorts"
    return cleaned.strip()


def _review_feedback_from_dict(data: dict[str, Any]) -> ReviewFeedback:
    approved = bool(data.get("approved"))
    selected_title = str(data.get("selected_title") or "").strip()
    description = str(data.get("description") or "").strip()
    hashtags = str(data.get("hashtags") or "").strip()
    retention_score = int(data.get("retention_score") or 0)
    novelty_score = int(data.get("novelty_score") or 0)
    risk_flags = _clean_text_list(data.get("risk_flags"))
    fact_check_points = _clean_text_list(data.get("fact_check_points"))
    review_notes = _clean_text_list(data.get("review_notes"))
    rewrite_instructions = _clean_text_list(data.get("rewrite_instructions"))
    if not selected_title:
        raise RuntimeError("review response missing selected_title")
    if not description:
        raise RuntimeError("review response missing description")
    if not hashtags:
        raise RuntimeError("review response missing hashtags")
    if retention_score < 1 or retention_score > 10:
        raise RuntimeError("review response retention_score must be 1-10")
    if novelty_score < 1 or novelty_score > 10:
        raise RuntimeError("review response novelty_score must be 1-10")
    return ReviewFeedback(
        approved=approved,
        selected_title=selected_title,
        description=description,
        hashtags=hashtags,
        retention_score=retention_score,
        novelty_score=novelty_score,
        risk_flags=risk_flags,
        fact_check_points=fact_check_points,
        review_notes=review_notes,
        rewrite_instructions=rewrite_instructions,
    )


def _clean_text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


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
