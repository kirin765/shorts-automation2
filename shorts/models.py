from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


@dataclass
class DraftJob:
    topic: str
    style: Optional[str] = None
    tone: Optional[str] = None
    target_seconds: Optional[int] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DraftJob":
        _validate_dict(data, "DraftJob", {"topic", "style", "tone", "target_seconds"})
        topic = _require_text(data, "topic", "DraftJob")
        style = _optional_text(data, "style", "DraftJob")
        tone = _optional_text(data, "tone", "DraftJob")
        target_seconds = _optional_positive_int(data, "target_seconds", "DraftJob")
        return cls(topic=topic, style=style, tone=tone, target_seconds=target_seconds)


@dataclass
class RenderJob:
    title: str
    script: str
    description: str
    hashtags: str
    pexels_query: Optional[str] = None
    background_provider: Optional[str] = None
    background_video: Optional[str] = None
    subtitle_position: Optional[str] = None
    subtitle_font_size: Optional[int] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RenderJob":
        _validate_dict(
            data,
            "RenderJob",
            {
                "title",
                "script",
                "description",
                "hashtags",
                "pexels_query",
                "background_provider",
                "background_video",
                "subtitle_position",
                "subtitle_font_size",
            },
        )
        return cls(
            title=_require_text(data, "title", "RenderJob"),
            script=_require_text(data, "script", "RenderJob"),
            description=_require_text(data, "description", "RenderJob"),
            hashtags=_require_text(data, "hashtags", "RenderJob"),
            pexels_query=_optional_text(data, "pexels_query", "RenderJob"),
            background_provider=_optional_text(data, "background_provider", "RenderJob"),
            background_video=_optional_text(data, "background_video", "RenderJob"),
            subtitle_position=_optional_text(data, "subtitle_position", "RenderJob"),
            subtitle_font_size=_optional_positive_int(data, "subtitle_font_size", "RenderJob"),
        )

    def to_dict(self) -> dict[str, Any]:
        out = {
            "title": self.title,
            "script": self.script,
            "description": self.description,
            "hashtags": self.hashtags,
        }
        if self.pexels_query:
            out["pexels_query"] = self.pexels_query
        if self.background_provider:
            out["background_provider"] = self.background_provider
        if self.background_video:
            out["background_video"] = self.background_video
        if self.subtitle_position:
            out["subtitle_position"] = self.subtitle_position
        if self.subtitle_font_size is not None:
            out["subtitle_font_size"] = self.subtitle_font_size
        return out


def load_draft_job(path: Path) -> DraftJob:
    return DraftJob.from_dict(_load_json_dict(path, "DraftJob"))


def load_render_job(path: Path) -> RenderJob:
    return RenderJob.from_dict(_load_json_dict(path, "RenderJob"))


def write_render_job(path: Path, job: RenderJob) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(job.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_topics_text(path: Path) -> list[str]:
    topics = []
    for line in path.read_text(encoding="utf-8").splitlines():
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        topics.append(item)
    return topics


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    slug = slug.strip("-")
    return slug or "topic"


def make_draft_jobs(
    *,
    topics: Iterable[str],
    style: Optional[str],
    tone: Optional[str],
    target_seconds: Optional[int],
) -> list[DraftJob]:
    jobs = []
    for topic in topics:
        cleaned = topic.strip()
        if not cleaned:
            continue
        jobs.append(
            DraftJob(
                topic=cleaned,
                style=style,
                tone=tone,
                target_seconds=target_seconds,
            )
        )
    return jobs


def _load_json_dict(path: Path, kind: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError("%s file not found: %s" % (kind, path))
    except json.JSONDecodeError as exc:
        raise ValueError("%s file is not valid JSON: %s" % (kind, exc))
    if not isinstance(payload, dict):
        raise ValueError("%s file must contain a JSON object: %s" % (kind, path))
    return payload


def _validate_dict(data: dict[str, Any], kind: str, allowed_keys: set[str]) -> None:
    unknown = sorted(set(data.keys()) - allowed_keys)
    if unknown:
        raise ValueError("%s has unknown keys: %s" % (kind, ", ".join(unknown)))


def _require_text(data: dict[str, Any], key: str, kind: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s requires non-empty '%s'" % (kind, key))
    return value.strip()


def _optional_text(data: dict[str, Any], key: str, kind: str) -> Optional[str]:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("%s '%s' must be a string" % (kind, key))
    cleaned = value.strip()
    return cleaned or None


def _optional_positive_int(data: dict[str, Any], key: str, kind: str) -> Optional[int]:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("%s '%s' must be an integer" % (kind, key))
    if value <= 0:
        raise ValueError("%s '%s' must be > 0" % (kind, key))
    return value
