from __future__ import annotations

import json
from typing import Iterable

from .config import Config
from .models import ScriptPackage, TopicCandidate


def build_topic_pool_prompt(
    config: Config,
    *,
    count: int,
    existing_topics: Iterable[str],
) -> tuple[str, str, dict[str, object]]:
    history_lines = [item.strip() for item in existing_topics if item and item.strip()]
    history_tail = "\n".join("- %s" % item for item in history_lines[-80:]) or "(none)"
    constraints = "\n".join("- %s" % item for item in config.content.series_constraints) or "- Keep it simple and safe."
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "candidates": {
                "type": "array",
                "minItems": max(1, count),
                "maxItems": max(1, count) + 4,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "candidate_id": {"type": "string"},
                        "series_name": {"type": "string"},
                        "topic": {"type": "string"},
                        "angle": {"type": "string"},
                        "target_emotion": {"type": "string"},
                    },
                    "required": ["candidate_id", "series_name", "topic", "angle", "target_emotion"],
                },
            }
        },
        "required": ["candidates"],
    }
    system = (
        "You are a Shorts topic planner. "
        "Generate instantly understandable Korean YouTube Shorts topics for a calm explanatory channel. "
        "Each topic must support a 20-35 second script, a strong first-line hook, and future series expansion. "
        "Avoid emojis, hashtags, precise unverifiable claims, politics, medical claims, and legal advice. "
        "Return only valid JSON matching the schema."
    )
    user = (
        "Channel category: %s\n"
        "Series name: %s\n"
        "Series brief: %s\n"
        "Audience: %s\n"
        "Series constraints:\n%s\n"
        "Generate %d topic candidates.\n"
        "Rules:\n"
        "- topic must be immediately understandable in Korean\n"
        "- angle must explain the twist or observation in one sentence\n"
        "- target_emotion should be a short English or Korean phrase like curiosity, surprise, discomfort\n"
        "- keep topic short enough for titles/subtitles\n"
        "Avoid repeating these recently used topics:\n%s\n"
    ) % (
        config.content.channel_category,
        config.content.series_name,
        config.content.series_brief,
        config.content.series_audience,
        constraints,
        count,
        history_tail,
    )
    return system, user, schema


def build_topic_evaluation_prompt(
    config: Config,
    *,
    candidates: list[TopicCandidate],
) -> tuple[str, str, dict[str, object]]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "evaluations": {
                "type": "array",
                "minItems": len(candidates),
                "maxItems": len(candidates),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "candidate_id": {"type": "string"},
                        "clarity": {"type": "integer", "minimum": 1, "maximum": 10},
                        "hook_strength": {"type": "integer", "minimum": 1, "maximum": 10},
                        "retention_potential": {"type": "integer", "minimum": 1, "maximum": 10},
                        "twist_potential": {"type": "integer", "minimum": 1, "maximum": 10},
                        "series_fit": {"type": "integer", "minimum": 1, "maximum": 10},
                        "repetition_risk": {"type": "integer", "minimum": 1, "maximum": 10},
                        "monetization_safety": {"type": "integer", "minimum": 1, "maximum": 10},
                        "selection_reason": {"type": "string"},
                    },
                    "required": [
                        "candidate_id",
                        "clarity",
                        "hook_strength",
                        "retention_potential",
                        "twist_potential",
                        "series_fit",
                        "repetition_risk",
                        "monetization_safety",
                        "selection_reason",
                    ],
                },
            }
        },
        "required": ["evaluations"],
    }
    candidate_json = json.dumps([item.to_dict() for item in candidates], ensure_ascii=False, indent=2)
    system = (
        "You are a Shorts editorial evaluator. "
        "Score each topic candidate for clarity, hook strength, retention potential, twist potential, series fit, repetition risk, and monetization safety. "
        "Use the full 1-10 scale carefully and stay consistent across candidates. "
        "Return only valid JSON matching the schema."
    )
    user = (
        "Channel category: %s\n"
        "Series name: %s\n"
        "Series brief: %s\n"
        "Evaluate these topic candidates:\n%s\n"
        "Guidance:\n"
        "- clarity: can the viewer understand the topic instantly?\n"
        "- hook_strength: can the first line create immediate curiosity?\n"
        "- retention_potential: can this sustain 20-35 seconds?\n"
        "- twist_potential: does it have a reveal, reversal, or comparison?\n"
        "- series_fit: does it belong to this channel series?\n"
        "- repetition_risk: higher is worse and means it feels repetitive\n"
        "- monetization_safety: higher is safer\n"
    ) % (
        config.content.channel_category,
        config.content.series_name,
        config.content.series_brief,
        candidate_json,
    )
    return system, user, schema


def build_script_package_prompt(
    config: Config,
    *,
    topic_payload: dict[str, object],
) -> tuple[str, str, dict[str, object]]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "hook_options": {
                "type": "array",
                "minItems": 3,
                "items": {"type": "string"},
            },
            "best_hook": {"type": "string"},
            "script_lines": {
                "type": "array",
                "minItems": 4,
                "items": {"type": "string"},
            },
            "ending": {"type": "string"},
            "title_options": {
                "type": "array",
                "minItems": 5,
                "maxItems": 5,
                "items": {"type": "string"},
            },
            "visual_cues": {
                "type": "array",
                "minItems": 3,
                "items": {"type": "string"},
            },
            "duration_sec": {"type": "integer", "minimum": 20, "maximum": 35},
            "retention_score": {"type": "integer", "minimum": 1, "maximum": 10},
            "novelty_score": {"type": "integer", "minimum": 1, "maximum": 10},
            "risk_flags": {"type": "array", "items": {"type": "string"}},
            "fact_check_points": {"type": "array", "items": {"type": "string"}},
            "pexels_query": {"type": "string"},
        },
        "required": [
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
        ],
    }
    constraints = "\n".join("- %s" % item for item in config.content.series_constraints) or "- Keep it simple and safe."
    payload_json = json.dumps(topic_payload, ensure_ascii=False, indent=2)
    system = (
        "You are a Shorts script writer. "
        "Write Korean shorts scripts with a strong first line, short subtitle-sized sentences, one idea per line, and a memorable ending. "
        "Avoid fluff, hedging, emojis, hashtags, and precise claims that require citation unless the script itself flags them for fact checking. "
        "Return only valid JSON matching the schema."
    )
    user = (
        "Channel category: %s\n"
        "Series name: %s\n"
        "Series brief: %s\n"
        "Audience: %s\n"
        "Series constraints:\n%s\n"
        "Selected topic payload:\n%s\n"
        "Script rules:\n"
        "- hook_options: at least 3 distinct first-line hooks\n"
        "- best_hook: one of hook_options\n"
        "- script_lines: 4-7 short lines after the hook, each easy to subtitle\n"
        "- ending: short last line that leaves an aftertaste\n"
        "- title_options: exactly 5 options\n"
        "- visual_cues: short cues for edits/B-roll\n"
        "- duration_sec: 20-35\n"
        "- pexels_query: 4-8 English words without brand names\n"
    ) % (
        config.content.channel_category,
        config.content.series_name,
        config.content.series_brief,
        config.content.series_audience,
        constraints,
        payload_json,
    )
    return system, user, schema


def build_script_review_prompt(
    config: Config,
    *,
    script_package: ScriptPackage,
) -> tuple[str, str, dict[str, object]]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "approved": {"type": "boolean"},
            "selected_title": {"type": "string"},
            "description": {"type": "string"},
            "hashtags": {"type": "string"},
            "retention_score": {"type": "integer", "minimum": 1, "maximum": 10},
            "novelty_score": {"type": "integer", "minimum": 1, "maximum": 10},
            "risk_flags": {"type": "array", "items": {"type": "string"}},
            "fact_check_points": {"type": "array", "items": {"type": "string"}},
            "review_notes": {"type": "array", "items": {"type": "string"}},
            "rewrite_instructions": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "approved",
            "selected_title",
            "description",
            "hashtags",
            "retention_score",
            "novelty_score",
            "risk_flags",
            "fact_check_points",
            "review_notes",
            "rewrite_instructions",
        ],
    }
    package_json = json.dumps(script_package.to_dict(), ensure_ascii=False, indent=2)
    system = (
        "You are a Shorts script reviewer and editor. "
        "Review hook strength, subtitle readability, ending quality, factual risk, series fit, and packaging quality. "
        "If the script is weak, mark approved=false and give concise rewrite instructions. "
        "If it is strong, choose the best title, write a short description, and finalize hashtags including #shorts. "
        "Return only valid JSON matching the schema."
    )
    user = (
        "Review thresholds:\n"
        "- retention_score must be >= %d\n"
        "- novelty_score must be >= %d\n"
        "- duration_sec must stay between 20 and 35\n"
        "- blocking risk flags should be avoided\n"
        "Script package:\n%s\n"
    ) % (
        config.content.review_min_retention_score,
        config.content.review_min_novelty_score,
        package_json,
    )
    return system, user, schema


def build_script_rewrite_prompt(
    config: Config,
    *,
    script_package: ScriptPackage,
    rewrite_instructions: list[str],
) -> tuple[str, str, dict[str, object]]:
    system, user, schema = build_script_package_prompt(
        config,
        topic_payload={
            "series_name": script_package.series_name,
            "topic": script_package.topic,
            "angle": script_package.angle,
            "target_emotion": script_package.target_emotion,
            "candidate_id": script_package.candidate_id,
        },
    )
    current_json = json.dumps(script_package.to_dict(), ensure_ascii=False, indent=2)
    rewrite_text = "\n".join("- %s" % item for item in rewrite_instructions if item.strip()) or "- Tighten the hook and improve subtitle readability."
    user = user + (
        "\nCurrent script package:\n%s\n"
        "Rewrite instructions:\n%s\n"
        "Keep the same topic and series fit, but fix the weaknesses directly.\n"
    ) % (current_json, rewrite_text)
    return system, user, schema
