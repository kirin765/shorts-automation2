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
        return cls(
            topic=_require_text(data, "topic", "DraftJob"),
            style=_optional_text(data, "style", "DraftJob"),
            tone=_optional_text(data, "tone", "DraftJob"),
            target_seconds=_optional_positive_int(data, "target_seconds", "DraftJob"),
        )


@dataclass
class TopicCandidate:
    candidate_id: str
    series_name: str
    topic: str
    angle: str
    target_emotion: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TopicCandidate":
        _validate_dict(data, "TopicCandidate", {"candidate_id", "series_name", "topic", "angle", "target_emotion"})
        return cls(
            candidate_id=_require_text(data, "candidate_id", "TopicCandidate"),
            series_name=_require_text(data, "series_name", "TopicCandidate"),
            topic=_require_text(data, "topic", "TopicCandidate"),
            angle=_require_text(data, "angle", "TopicCandidate"),
            target_emotion=_require_text(data, "target_emotion", "TopicCandidate"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "series_name": self.series_name,
            "topic": self.topic,
            "angle": self.angle,
            "target_emotion": self.target_emotion,
        }


@dataclass
class TopicPool:
    run_id: str
    channel_category: str
    series_name: str
    generated_at: str
    candidates: list[TopicCandidate]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TopicPool":
        _validate_dict(data, "TopicPool", {"run_id", "channel_category", "series_name", "generated_at", "candidates"})
        candidates = _require_object_list(data, "candidates", "TopicPool")
        return cls(
            run_id=_require_text(data, "run_id", "TopicPool"),
            channel_category=_require_text(data, "channel_category", "TopicPool"),
            series_name=_require_text(data, "series_name", "TopicPool"),
            generated_at=_require_text(data, "generated_at", "TopicPool"),
            candidates=[TopicCandidate.from_dict(item) for item in candidates],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "channel_category": self.channel_category,
            "series_name": self.series_name,
            "generated_at": self.generated_at,
            "candidates": [item.to_dict() for item in self.candidates],
        }


@dataclass
class TopicScores:
    clarity: int
    hook_strength: int
    retention_potential: int
    twist_potential: int
    series_fit: int
    repetition_risk: int
    monetization_safety: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TopicScores":
        _validate_dict(
            data,
            "TopicScores",
            {
                "clarity",
                "hook_strength",
                "retention_potential",
                "twist_potential",
                "series_fit",
                "repetition_risk",
                "monetization_safety",
            },
        )
        return cls(
            clarity=_score_value(data, "clarity", "TopicScores"),
            hook_strength=_score_value(data, "hook_strength", "TopicScores"),
            retention_potential=_score_value(data, "retention_potential", "TopicScores"),
            twist_potential=_score_value(data, "twist_potential", "TopicScores"),
            series_fit=_score_value(data, "series_fit", "TopicScores"),
            repetition_risk=_score_value(data, "repetition_risk", "TopicScores"),
            monetization_safety=_score_value(data, "monetization_safety", "TopicScores"),
        )

    def passes_thresholds(self) -> bool:
        return (
            self.clarity >= 7
            and self.hook_strength >= 7
            and self.retention_potential >= 7
            and self.series_fit >= 7
            and self.monetization_safety >= 8
            and self.repetition_risk <= 5
        )

    def overall_score(self) -> float:
        return (
            self.clarity
            + self.hook_strength
            + self.retention_potential
            + self.twist_potential
            + self.series_fit
            + self.monetization_safety
            - self.repetition_risk
        ) / 6.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "clarity": self.clarity,
            "hook_strength": self.hook_strength,
            "retention_potential": self.retention_potential,
            "twist_potential": self.twist_potential,
            "series_fit": self.series_fit,
            "repetition_risk": self.repetition_risk,
            "monetization_safety": self.monetization_safety,
        }


@dataclass
class SelectedTopic:
    run_id: str
    candidate_id: str
    rank: int
    series_name: str
    topic: str
    angle: str
    target_emotion: str
    scores: TopicScores
    overall_score: float
    selection_reason: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SelectedTopic":
        _validate_dict(
            data,
            "SelectedTopic",
            {
                "run_id",
                "candidate_id",
                "rank",
                "series_name",
                "topic",
                "angle",
                "target_emotion",
                "scores",
                "overall_score",
                "selection_reason",
            },
        )
        scores = data.get("scores")
        if not isinstance(scores, dict):
            raise ValueError("SelectedTopic 'scores' must be an object")
        return cls(
            run_id=_require_text(data, "run_id", "SelectedTopic"),
            candidate_id=_require_text(data, "candidate_id", "SelectedTopic"),
            rank=_positive_int(data, "rank", "SelectedTopic"),
            series_name=_require_text(data, "series_name", "SelectedTopic"),
            topic=_require_text(data, "topic", "SelectedTopic"),
            angle=_require_text(data, "angle", "SelectedTopic"),
            target_emotion=_require_text(data, "target_emotion", "SelectedTopic"),
            scores=TopicScores.from_dict(scores),
            overall_score=_require_number(data, "overall_score", "SelectedTopic", minimum=0.0),
            selection_reason=_require_text(data, "selection_reason", "SelectedTopic"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "candidate_id": self.candidate_id,
            "rank": self.rank,
            "series_name": self.series_name,
            "topic": self.topic,
            "angle": self.angle,
            "target_emotion": self.target_emotion,
            "scores": self.scores.to_dict(),
            "overall_score": round(self.overall_score, 3),
            "selection_reason": self.selection_reason,
        }


@dataclass
class ScriptPackage:
    run_id: str
    candidate_id: str
    series_name: str
    topic: str
    angle: str
    target_emotion: str
    hook_options: list[str]
    best_hook: str
    script_lines: list[str]
    ending: str
    title_options: list[str]
    visual_cues: list[str]
    duration_sec: int
    retention_score: int
    novelty_score: int
    risk_flags: list[str]
    fact_check_points: list[str]
    pexels_query: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScriptPackage":
        _validate_dict(
            data,
            "ScriptPackage",
            {
                "run_id",
                "candidate_id",
                "series_name",
                "topic",
                "angle",
                "target_emotion",
                "hook_options",
                "best_hook",
                "script_lines",
                "ending",
                "title_options",
                "visual_cues",
                "duration_sec",
                "retention_score",
                "novelty_score",
                "risk_flags",
                "fact_check_points",
                "pexels_query",
            },
        )
        return cls(
            run_id=_require_text(data, "run_id", "ScriptPackage"),
            candidate_id=_require_text(data, "candidate_id", "ScriptPackage"),
            series_name=_require_text(data, "series_name", "ScriptPackage"),
            topic=_require_text(data, "topic", "ScriptPackage"),
            angle=_require_text(data, "angle", "ScriptPackage"),
            target_emotion=_require_text(data, "target_emotion", "ScriptPackage"),
            hook_options=_require_text_list(data, "hook_options", "ScriptPackage", minimum=3),
            best_hook=_require_text(data, "best_hook", "ScriptPackage"),
            script_lines=_require_text_list(data, "script_lines", "ScriptPackage", minimum=4),
            ending=_require_text(data, "ending", "ScriptPackage"),
            title_options=_require_text_list(data, "title_options", "ScriptPackage", minimum=5, maximum=5),
            visual_cues=_require_text_list(data, "visual_cues", "ScriptPackage", minimum=3),
            duration_sec=_bounded_int(data, "duration_sec", "ScriptPackage", minimum=20, maximum=35),
            retention_score=_score_value(data, "retention_score", "ScriptPackage"),
            novelty_score=_score_value(data, "novelty_score", "ScriptPackage"),
            risk_flags=_optional_text_list(data, "risk_flags", "ScriptPackage"),
            fact_check_points=_optional_text_list(data, "fact_check_points", "ScriptPackage"),
            pexels_query=_require_text(data, "pexels_query", "ScriptPackage"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "candidate_id": self.candidate_id,
            "series_name": self.series_name,
            "topic": self.topic,
            "angle": self.angle,
            "target_emotion": self.target_emotion,
            "hook_options": self.hook_options,
            "best_hook": self.best_hook,
            "script_lines": self.script_lines,
            "ending": self.ending,
            "title_options": self.title_options,
            "visual_cues": self.visual_cues,
            "duration_sec": self.duration_sec,
            "retention_score": self.retention_score,
            "novelty_score": self.novelty_score,
            "risk_flags": self.risk_flags,
            "fact_check_points": self.fact_check_points,
            "pexels_query": self.pexels_query,
        }


@dataclass
class ReviewedPackage(ScriptPackage):
    selected_title: str = ""
    description: str = ""
    hashtags: str = ""
    review_notes: Optional[list[str]] = None
    rewrite_applied: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewedPackage":
        _validate_dict(
            data,
            "ReviewedPackage",
            {
                "run_id",
                "candidate_id",
                "series_name",
                "topic",
                "angle",
                "target_emotion",
                "hook_options",
                "best_hook",
                "script_lines",
                "ending",
                "title_options",
                "visual_cues",
                "duration_sec",
                "retention_score",
                "novelty_score",
                "risk_flags",
                "fact_check_points",
                "pexels_query",
                "selected_title",
                "description",
                "hashtags",
                "review_notes",
                "rewrite_applied",
            },
        )
        base = ScriptPackage.from_dict(
            {
                key: value
                for key, value in data.items()
                if key
                in {
                    "run_id",
                    "candidate_id",
                    "series_name",
                    "topic",
                    "angle",
                    "target_emotion",
                    "hook_options",
                    "best_hook",
                    "script_lines",
                    "ending",
                    "title_options",
                    "visual_cues",
                    "duration_sec",
                    "retention_score",
                    "novelty_score",
                    "risk_flags",
                    "fact_check_points",
                    "pexels_query",
                }
            }
        )
        rewrite_applied = data.get("rewrite_applied")
        if not isinstance(rewrite_applied, bool):
            raise ValueError("ReviewedPackage 'rewrite_applied' must be a boolean")
        return cls(
            run_id=base.run_id,
            candidate_id=base.candidate_id,
            series_name=base.series_name,
            topic=base.topic,
            angle=base.angle,
            target_emotion=base.target_emotion,
            hook_options=base.hook_options,
            best_hook=base.best_hook,
            script_lines=base.script_lines,
            ending=base.ending,
            title_options=base.title_options,
            visual_cues=base.visual_cues,
            duration_sec=base.duration_sec,
            retention_score=base.retention_score,
            novelty_score=base.novelty_score,
            risk_flags=base.risk_flags,
            fact_check_points=base.fact_check_points,
            pexels_query=base.pexels_query,
            selected_title=_require_text(data, "selected_title", "ReviewedPackage"),
            description=_require_text(data, "description", "ReviewedPackage"),
            hashtags=_require_text(data, "hashtags", "ReviewedPackage"),
            review_notes=_optional_text_list(data, "review_notes", "ReviewedPackage"),
            rewrite_applied=rewrite_applied,
        )

    def to_dict(self) -> dict[str, Any]:
        out = super().to_dict()
        out.update(
            {
                "selected_title": self.selected_title,
                "description": self.description,
                "hashtags": self.hashtags,
                "review_notes": self.review_notes or [],
                "rewrite_applied": self.rewrite_applied,
            }
        )
        return out


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


def load_topic_pool(path: Path) -> TopicPool:
    return TopicPool.from_dict(_load_json_dict(path, "TopicPool"))


def write_topic_pool(path: Path, value: TopicPool) -> None:
    _write_json(path, value.to_dict())


def load_selected_topic(path: Path) -> SelectedTopic:
    return SelectedTopic.from_dict(_load_json_dict(path, "SelectedTopic"))


def write_selected_topic(path: Path, value: SelectedTopic) -> None:
    _write_json(path, value.to_dict())


def load_script_package(path: Path) -> ScriptPackage:
    return ScriptPackage.from_dict(_load_json_dict(path, "ScriptPackage"))


def write_script_package(path: Path, value: ScriptPackage) -> None:
    _write_json(path, value.to_dict())


def load_reviewed_package(path: Path) -> ReviewedPackage:
    return ReviewedPackage.from_dict(_load_json_dict(path, "ReviewedPackage"))


def write_reviewed_package(path: Path, value: ReviewedPackage) -> None:
    _write_json(path, value.to_dict())


def load_render_job(path: Path) -> RenderJob:
    return RenderJob.from_dict(_load_json_dict(path, "RenderJob"))


def write_render_job(path: Path, job: RenderJob) -> None:
    _write_json(path, job.to_dict())


def load_topics_text(path: Path) -> list[str]:
    topics = []
    for line in path.read_text(encoding="utf-8").splitlines():
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        topics.append(item)
    return topics


def append_topics_text(path: Path, topics: list[str]) -> None:
    if not topics:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for topic in topics:
            cleaned = topic.strip()
            if cleaned:
                handle.write(cleaned + "\n")


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
        jobs.append(DraftJob(topic=cleaned, style=style, tone=tone, target_seconds=target_seconds))
    return jobs


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def _require_object_list(data: dict[str, Any], key: str, kind: str) -> list[dict[str, Any]]:
    value = data.get(key)
    if not isinstance(value, list) or not value:
        raise ValueError("%s requires non-empty '%s'" % (kind, key))
    out = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("%s '%s' must contain objects" % (kind, key))
        out.append(item)
    return out


def _require_text_list(
    data: dict[str, Any],
    key: str,
    kind: str,
    *,
    minimum: int = 1,
    maximum: Optional[int] = None,
) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list):
        raise ValueError("%s '%s' must be a list" % (kind, key))
    out = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("%s '%s' must contain non-empty strings" % (kind, key))
        out.append(item.strip())
    if len(out) < minimum:
        raise ValueError("%s '%s' must contain at least %d items" % (kind, key, minimum))
    if maximum is not None and len(out) > maximum:
        raise ValueError("%s '%s' must contain at most %d items" % (kind, key, maximum))
    return out


def _optional_text_list(data: dict[str, Any], key: str, kind: str) -> list[str]:
    value = data.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("%s '%s' must be a list" % (kind, key))
    out = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("%s '%s' must contain strings" % (kind, key))
        cleaned = item.strip()
        if cleaned:
            out.append(cleaned)
    return out


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


def _positive_int(data: dict[str, Any], key: str, kind: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("%s '%s' must be > 0" % (kind, key))
    return value


def _bounded_int(data: dict[str, Any], key: str, kind: str, *, minimum: int, maximum: int) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("%s '%s' must be an integer" % (kind, key))
    if value < minimum or value > maximum:
        raise ValueError("%s '%s' must be between %d and %d" % (kind, key, minimum, maximum))
    return value


def _score_value(data: dict[str, Any], key: str, kind: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 10:
        raise ValueError("%s '%s' must be an integer between 1 and 10" % (kind, key))
    return value


def _require_number(data: dict[str, Any], key: str, kind: str, *, minimum: float = 0.0) -> float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("%s '%s' must be numeric" % (kind, key))
    result = float(value)
    if result < minimum:
        raise ValueError("%s '%s' must be >= %s" % (kind, key, minimum))
    return result
