#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path
import re
from typing import Any
from xml.etree import ElementTree as ET

import requests

from config_loader import ENV_SENTINEL, load_config


def openai_key(config: dict) -> str:
    key = (config.get("openai_api_key") or os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        raise SystemExit("Missing OpenAI API key. Set env OPENAI_API_KEY (or config openai_api_key).")
    return key


def read_existing_topics(path: Path) -> set[str]:
    if not path.exists():
        return set()
    out: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.add(s)
    return out


def _response_text(data: dict) -> str:
    for item in data.get("output", []) or []:
        for content in item.get("content", []) or []:
            if content.get("type") in ("output_text", "text") and isinstance(content.get("text"), str):
                return content["text"]
    raise RuntimeError("OpenAI response: no output text found")


def _responses_json(
    *,
    base_url: str,
    api_key: str,
    timeout_s: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    response = requests.post(
        f"{base_url}/responses",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=timeout_s,
    )
    response.raise_for_status()
    return json.loads(_response_text(response.json()))


def _coerce_int(value: object, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_str(value: object, *, default: str = "") -> str:
    text = (str(value).strip() if value is not None else "")
    return text or default


def _coerce_list(value: object, *, default: list[str] | None = None) -> list[str]:
    if default is None:
        default = []
    if value is None:
        return default[:]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            text = str(item).strip() if item is not None else ""
            if text:
                out.append(text)
        return out
    return default[:]


def _coerce_bool(value: object, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


_LOW_INTEREST_MARKERS = {
    "test",
    "sample",
    "dummy",
    "placeholder",
    "todo",
    "temp",
    "template",
    "random",
    "generic",
    "basic",
    "기본",
    "테스트",
    "샘플",
}

_STYLE_RULES: list[tuple[list[str], str]] = [
    (["smartphone", "ios", "android", "아이폰", "갤럭시", "모바일", "휴대폰", "배터리", "화면 잠금"], "테크 뉴스, 한 문장 짧게"),
    (["ai", "인공지능", "인공 지능", "머신러닝", "딥러닝", "챗", "gpt", "llm", "모델"], "테크 뉴스, 실무형 단문 위주"),
    (["stock", "주식", "코인", "경제", "금융", "비트코인", "환율", "투자", "금리", "ETF", "암호화폐"], "금융/경제 트렌드, 핵심 포인트 중심"),
    (["recipe", "요리", "커피", "식단", "헬스", "운동", "다이어트", "건강", "의료", "질병"], "실생활/건강 팁, 바로 실행 가능한 방식"),
    (["game", "게임", "아이돌", "연예", "영화", "드라마", "음악", "리뷰"], "엔터/리뷰형, 비교형 포인트 우선"),
    (["travel", "여행", "국내", "해외", "가성비", "숙소", "호텔", "항공", "휴양"], "라이프/여행 가이드형, 바로 실행 가능한 체크리스트"),
]


def _infer_style_from_trends(niche: str, trend_seeds: list[str], fallback_style: str) -> str:
    """Infer a topic-style hint from niche/trend context.

    Keeps the provided fallback when no rule matches.
    """
    context = _normalize_text(f"{niche} {' '.join(trend_seeds)}").lower()
    if not context:
        return fallback_style

    for markers, style in _STYLE_RULES:
        if any(marker in context for marker in markers):
            return style

    return fallback_style


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _normalize_topic_key(line: str) -> str:
    main, sub = _split_topic_and_subtopic(line)
    return _normalize_text(main).casefold()


def _split_topic_and_subtopic(line: str) -> tuple[str, str]:
    raw = _normalize_text(line).replace("\r", "")
    if "\t" in raw:
        main, sub = raw.split("\t", 1)
        return main.strip(), sub.strip()
    if " | " in raw:
        main, sub = raw.split(" | ", 1)
        return main.strip(), sub.strip()
    return raw, ""


def _is_high_interest_topic(topic: str) -> bool:
    """Heuristic guard for obviously low-value generated topics."""
    topic_norm = _normalize_text(_split_topic_and_subtopic(topic)[0]).lower()
    if not topic_norm:
        return False

    # Reject obvious placeholders and empty garbage.
    tokens = set(topic_norm.replace("-", " ").split())
    if len(topic_norm) < 8:
        return False
    if any(mark in topic_norm for mark in _LOW_INTEREST_MARKERS):
        return False
    if len(tokens) == 1 and all(len(t) < 5 for t in tokens):
        return False
    if not re.search(r"[?！!?.:：]", topic_norm):
        # Encourage a curiosity hook, practical angle, or comparative framing.
        hook_words = {
            "why",
            "how",
            "what",
            "when",
            "누구",
            "왜",
            "어떻게",
            "무엇",
            "어디",
            "진짜",
            "비밀",
            "주의",
            "오류",
            "실수",
            "차이",
            "비교",
            "방법",
        }
        if not any(w in topic_norm for w in hook_words):
            # At least 2 words gives enough structure for a usable hook.
            if len(topic_norm.split()) < 2:
                return False
            if not any(ch.isdigit() for ch in topic_norm):
                return False

        if len(topic_norm) > 80:
            return False
    return True


def fetch_google_trending_topics(cfg: dict, *, geo: str, limit: int, timeout_s: int) -> list[str]:
    # Unofficial RSS endpoint without API key.
    url = "https://trends.google.com/trendingsearches/daily/rss"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(
            url,
            params={"geo": geo, "hl": "ko"},
            timeout=timeout_s,
            headers=headers,
        )
    except requests.RequestException as exc:
        print(f"[topics] google trending request failed: {exc}")
        return []
    if response.status_code == 404:
        print("[topics] google trending endpoint is unavailable (404); skipping google source")
        return []
    response.raise_for_status()
    root = ET.fromstring(response.text)
    out: list[str] = []
    for item in root.findall(".//item"):
        title = _normalize_text(item.findtext("title"))
        if not title:
            continue
        out.append(title)
        if len(out) >= max(1, limit):
            break
    if not out:
        print("Google Trends RSS returned no topics")
    return out


def fetch_youtube_trending_topics(cfg: dict, *, geo: str, limit: int, timeout_s: int) -> list[str]:
    key = (
        cfg.get("google_api_key")
        or cfg.get("youtube_api_key")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("YOUTUBE_API_KEY")
        or ""
    ).strip()
    if not key:
        raise RuntimeError("No API key for YouTube trends. Set GOOGLE_API_KEY or YOUTUBE_API_KEY.")

    params = {
        "part": "snippet",
        "chart": "mostPopular",
        "regionCode": geo,
        "maxResults": max(1, min(20, limit)),
        "key": key,
    }
    response = requests.get("https://www.googleapis.com/youtube/v3/videos", params=params, timeout=timeout_s)
    response.raise_for_status()
    data: dict[str, Any] = response.json()
    out: list[str] = []
    for item in data.get("items", []) or []:
        title = _normalize_text((item.get("snippet") or {}).get("title"))
        if title:
            out.append(title)
        if len(out) >= max(1, limit):
            break
    if not out:
        raise RuntimeError("YouTube trending returned no titles")
    return out


def collect_trend_seeds(cfg: dict) -> list[str]:
    sources = _coerce_list(cfg.get("trend_sources"), default=["google", "youtube"])
    geo = _coerce_str(cfg.get("trend_region"), default="KR")
    limit = _coerce_int(cfg.get("trend_seed_count", 8), default=8)
    timeout_s = _coerce_int(cfg.get("trend_timeout_s", 12), default=12)
    has_youtube_key = bool(
        (
            cfg.get("google_api_key")
            or cfg.get("youtube_api_key")
            or os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("YOUTUBE_API_KEY")
        ).strip()
    )
    if not has_youtube_key:
        print("[topics] YouTube trend source skipped: no API key. Set GOOGLE_API_KEY or YOUTUBE_API_KEY.")

    providers = {
        "google": fetch_google_trending_topics,
        "youtube": fetch_youtube_trending_topics,
    }

    out: list[str] = []
    seen: set[str] = set()
    for source in sources:
        fn = providers.get(source.lower())
        if not fn:
            print(f"[topics] unknown trend source skipped: {source!r}")
            continue
        if source.lower() == "youtube" and not has_youtube_key:
            continue
        try:
            for item in fn(cfg, geo=geo, limit=limit, timeout_s=timeout_s):
                key = _normalize_topic_key(item)
                if not key or key in seen:
                    continue
                out.append(item)
                seen.add(key)
        except Exception as exc:
            print(f"[topics] trend source failed: source={source!r} {exc}")
            continue
    return out


def _count_today_trend_uploads(cfg: dict, today: str) -> int:
    uploads_path = Path(
        _coerce_str(((cfg.get("youtube") or {}).get("upload_state_file")), default="logs/uploads.jsonl")
    )
    if not uploads_path.exists():
        return 0
    count = 0
    for line in uploads_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if str(obj.get("topic_source") or "").strip().lower() != "trend":
            continue
        if str(obj.get("ts") or "").strip()[:10] == today:
            count += 1
    return count


def ground_trend_topic(
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout_s: int,
    topic: str,
    subtopic: str,
    trend_seeds: list[str],
) -> dict[str, Any]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "grounded": {"type": "boolean"},
            "note": {"type": "string"},
        },
        "required": ["grounded", "note"],
    }
    trend_tail = "\n".join(f"- {t}" for t in trend_seeds[:12]) if trend_seeds else "(none)"
    system = (
        "You resolve the actual meaning of a trending Korean YouTube topic before script writing. "
        "Reject topics when the noun/proper noun meaning is unclear. "
        "Prevent semantic mistakes such as treating an unknown word like an app/SNS when it is not."
    )
    user = (
        f"Topic: {topic}\n"
        f"Subtopic: {subtopic or '(none)'}\n"
        "Recent YouTube trend seeds:\n"
        f"{trend_tail}\n\n"
        "Return grounded=false if you cannot confidently explain what the main noun/proper noun means.\n"
        "If grounded=true, note must briefly explain:\n"
        "- what this topic/term actually refers to\n"
        "- what it does NOT refer to\n"
        "- 2-3 meaning anchors the script must keep\n"
        "Keep note short, factual, and directly usable in a writing prompt."
    )
    return _responses_json(
        base_url=base_url,
        api_key=api_key,
        timeout_s=timeout_s,
        payload={
            "model": model,
            "input": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2,
            "max_output_tokens": 240,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "trend_grounding",
                    "schema": schema,
                    "strict": True,
                }
            },
            "store": False,
        },
    )


def request_topics_once(
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout_s: int,
    temperature: float,
    max_tokens: int,
    language: str,
    niche: str,
    style: str,
    today: str,
    request_count: int,
    avoid_topics: list[str],
    trend_seeds: list[str],
    trend_quota_remaining: int,
) -> list[dict[str, str]]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "topics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "topic": {"type": "string"},
                        "topic_source": {"type": "string", "enum": ["regular", "trend"]},
                    },
                    "required": ["topic", "topic_source"],
                },
                "minItems": max(1, request_count),
                "maxItems": max(1, request_count) + 5,
            }
        },
        "required": ["topics"],
    }

    avoid_tail = "\n".join(f"- {t}" for t in avoid_topics[-120:])
    trend_tail = "\n".join(f"- {t}" for t in trend_seeds) if trend_seeds else "(none)"
    system = (
        "You generate high-retention YouTube Shorts topic ideas. "
        "Do not include emojis. Do not include hashtags. "
        "Avoid precise claims that need fact-checking. "
        "Prioritize curiosity-driven, practical, and discussion-worthy topics. "
        "Avoid generic placeholders like 'topic x', 'daily update', or bland one-liners. "
        "Output only valid JSON matching the schema."
    )
    user = (
        f"Language: {language}\n"
        f"Niche: {niche}\n"
        f"Style: {style}\n"
        f"Date: {today}\n"
        f"Generate {request_count} topics in this exact format: main_topic\\tsubtopic.\n"
        "Keep each item short and practical.\n"
        "Prefer topics that can be explained in ~25-35 seconds.\n"
        "Prioritize strong hooks (why/why now/how to/hidden mistake). "
        "Include concrete situations, decisions, comparisons, numbers, or clear mistakes.\n"
        f"Trend-topic quota remaining today: {max(0, trend_quota_remaining)}.\n"
        "Set topic_source='trend' only when the topic directly depends on a current trend seed.\n"
        "Set topic_source='regular' for evergreen or non-trend topics.\n"
        "If trend-topic quota remaining is 0, all returned items must use topic_source='regular' and must not rely on trend seeds.\n"
        "Avoid generic placeholders or reworded duplicates like 'daily update', 'topic idea', 'news', 'misc'.\n"
        "Use these trend seeds:\n"
        f"{trend_tail}\n"
        "Avoid repeating these recent topics:\n"
        f"{avoid_tail if avoid_tail else '(none)'}\n"
    )

    obj = _responses_json(
        base_url=base_url,
        api_key=api_key,
        timeout_s=timeout_s,
        payload={
            "model": model,
            "input": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "max_output_tokens": max_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "topics",
                    "schema": schema,
                    "strict": True,
                }
            },
            "store": False,
        },
    )
    out: list[dict[str, str]] = []
    for item in (obj.get("topics") or []):
        if not isinstance(item, dict):
            continue
        topic = _coerce_str(item.get("topic"))
        if not topic:
            continue
        source = _coerce_str(item.get("topic_source"), default="regular").lower()
        if source not in {"regular", "trend"}:
            source = "regular"
        out.append({"topic": topic, "topic_source": source})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate Shorts topics with OpenAI and write jobs/topics.txt")
    ap.add_argument("--config", default=ENV_SENTINEL)
    ap.add_argument("--out", default="jobs/topics.txt")
    ap.add_argument("--history", default="jobs/topics_history.txt")
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--language", default="ko")
    ap.add_argument("--niche", default="")
    ap.add_argument("--style", default="")
    ap.add_argument(
        "--style-mode",
        choices=("auto", "fixed"),
        default="",
        help="auto: infer style from niche+trend seeds, fixed: use provided --style value",
    )
    ap.add_argument("--avoid-days", type=int, default=60, help="Reserved for future date-scoped history filtering.")
    ap.add_argument(
        "--uniqueness-mode",
        choices=("strict", "best_effort"),
        default=None,
        help="strict: fail if unique topics are insufficient. best_effort: write whatever is available.",
    )
    ap.add_argument(
        "--max-attempts",
        type=int,
        default=None,
        help="Max OpenAI attempts used to fill required unique topics.",
    )
    args = ap.parse_args()

    cfg = load_config(args.config)
    api_key = openai_key(cfg)
    base_url = (cfg.get("openai_base_url") or "https://api.openai.com/v1").rstrip("/")
    model = (cfg.get("openai_topic_model") or cfg.get("openai_model") or "gpt-4o-mini").strip()
    timeout_s = int(cfg.get("openai_timeout_s", 40))
    temperature = float(cfg.get("openai_topic_temperature", cfg.get("openai_temperature", 0.7)))
    max_tokens = int(cfg.get("openai_topic_max_output_tokens", 500))
    uniqueness_mode = (args.uniqueness_mode or cfg.get("openai_topic_uniqueness_mode") or "strict").strip().lower()
    if uniqueness_mode not in {"strict", "best_effort"}:
        raise SystemExit(f"Invalid uniqueness mode: {uniqueness_mode!r}. expected strict|best_effort")
    max_attempts = int(args.max_attempts or cfg.get("openai_topic_max_attempts", 5))
    if max_attempts < 1:
        raise SystemExit(f"--max-attempts must be >= 1 (got {max_attempts})")
    trend_seeds = collect_trend_seeds(cfg)
    trend_topic_daily_cap = max(0, _coerce_int(cfg.get("trend_topic_daily_cap", 1), default=1))
    trend_grounding_enabled = _coerce_bool(cfg.get("trend_grounding_enabled"), default=True)
    niche = _coerce_str(
        args.niche,
        default=_coerce_str(cfg.get("topic_niche_default"), default="테크/AI/인터넷 트렌드"),
    )
    style_default = _coerce_str(
        args.style,
        default=_coerce_str(cfg.get("topic_style_default"), default="tech news, concise"),
    )
    style_mode = _coerce_str((args.style_mode or cfg.get("topic_style_mode")), default="auto").strip().lower()
    if style_mode not in {"auto", "fixed"}:
        raise SystemExit(f"Invalid style mode: {style_mode!r}. expected auto|fixed")
    style = style_default if style_mode == "fixed" else _infer_style_from_trends(niche, trend_seeds, style_default)

    out_path = Path(args.out)
    hist_path = Path(args.history)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    hist_path.parent.mkdir(parents=True, exist_ok=True)

    existing = read_existing_topics(hist_path)
    accepted: list[dict[str, str]] = []
    accepted_set: set[str] = {_normalize_topic_key(t) for t in existing}
    all_candidates: list[dict[str, str]] = []
    today = date.today().isoformat()
    trend_quota_remaining = max(0, trend_topic_daily_cap - _count_today_trend_uploads(cfg, today))

    print(
        f"[topics] policy mode={uniqueness_mode} target_count={args.count} max_attempts={max_attempts} "
        f"history_size={len(existing)} trend_seeds={len(trend_seeds)} style={style} trend_quota_remaining={trend_quota_remaining}"
    )

    for attempt in range(1, max_attempts + 1):
        remaining = max(0, args.count - len(accepted))
        if remaining == 0:
            break

        request_count = min(max(remaining + 3, remaining), max(args.count, 1) + 8)
        avoid_topics = sorted(existing.union(accepted_set))
        try:
            batch = request_topics_once(
                base_url=base_url,
                api_key=api_key,
                model=model,
                timeout_s=timeout_s,
                temperature=temperature,
                max_tokens=max_tokens,
                language=args.language,
                niche=niche,
                style=style,
                today=today,
                request_count=request_count,
                avoid_topics=avoid_topics,
                trend_seeds=trend_seeds,
                trend_quota_remaining=trend_quota_remaining,
            )
        except Exception as e:
            raise SystemExit(f"topic generation failed on attempt {attempt}/{max_attempts}: {e}") from e

        if not batch:
            print(f"[topics] attempt {attempt}/{max_attempts}: no topics returned")
            continue

        high_interest_batch: list[dict[str, str]] = []
        for item in batch:
            raw = _coerce_str(item.get("topic"))
            source = _coerce_str(item.get("topic_source"), default="regular").lower()
            t = raw.strip()
            if not t:
                continue
            if "\t" not in t and " | " in t:
                t = t.replace(" | ", "\t", 1)
            if not _is_high_interest_topic(t):
                continue
            high_interest_batch.append({"topic": t, "topic_source": source if source in {"regular", "trend"} else "regular"})
        all_candidates.extend(high_interest_batch)
        added_this_attempt = 0
        for item in high_interest_batch:
            topic_line = item["topic"]
            key = _normalize_topic_key(topic_line)
            if not key or key in accepted_set:
                continue
            if uniqueness_mode == "strict" and key in {_normalize_topic_key(t) for t in existing}:
                continue
            source = item.get("topic_source", "regular")
            if source == "trend" and trend_quota_remaining <= 0:
                continue
            topic_main, topic_sub = _split_topic_and_subtopic(topic_line)
            grounding_note = ""
            if source == "trend" and trend_grounding_enabled:
                grounding = ground_trend_topic(
                    base_url=base_url,
                    api_key=api_key,
                    model=(cfg.get("openai_judge_model") or cfg.get("openai_topic_model") or cfg.get("openai_model") or "gpt-4o-mini").strip(),
                    timeout_s=timeout_s,
                    topic=topic_main,
                    subtopic=topic_sub,
                    trend_seeds=trend_seeds,
                )
                if not bool(grounding.get("grounded")):
                    print(f"[topics] grounding rejected trend topic: {topic_main}")
                    continue
                grounding_note = _coerce_str(grounding.get("note"))
            accepted_set.add(key)
            accepted.append(
                {
                    "topic": topic_main,
                    "subtopic": topic_sub,
                    "topic_source": source,
                    "grounding_note": grounding_note,
                }
            )
            added_this_attempt += 1
            if source == "trend":
                trend_quota_remaining -= 1
            if len(accepted) >= args.count:
                break

        print(
            f"[topics] attempt {attempt}/{max_attempts}: returned={len(batch)} "
            f"added={added_this_attempt} accepted={len(accepted)}/{args.count}"
        )

    if len(accepted) < args.count and uniqueness_mode == "best_effort":
        for item in all_candidates:
            topic_line = item["topic"]
            key = _normalize_topic_key(topic_line)
            if not key or key in accepted_set:
                continue
            source = item.get("topic_source", "regular")
            if source == "trend" and trend_quota_remaining <= 0:
                continue
            topic_main, topic_sub = _split_topic_and_subtopic(topic_line)
            accepted_set.add(key)
            accepted.append(
                {
                    "topic": topic_main,
                    "subtopic": topic_sub,
                    "topic_source": source,
                    "grounding_note": "",
                }
            )
            if source == "trend":
                trend_quota_remaining -= 1
            if len(accepted) >= args.count:
                break
        print(f"[topics] best_effort fallback accepted={len(accepted)}/{args.count}")

    if len(accepted) < args.count:
        mode_note = "unique set" if uniqueness_mode == "strict" else "sufficient set"
        raise SystemExit(
            f"topic generation failed to provide {mode_note}: got {len(accepted)} of {args.count} "
            f"(mode={uniqueness_mode}, attempts={max_attempts})"
        )

    final_topics = accepted[: args.count]
    out_lines = [
        "\t".join(
            [
                item.get("topic", "").strip(),
                item.get("subtopic", "").strip(),
                item.get("topic_source", "regular").strip() or "regular",
                (item.get("grounding_note", "") or "").replace("\n", " ").strip(),
            ]
        ).rstrip("\t")
        for item in final_topics
    ]
    out_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    with hist_path.open("a", encoding="utf-8") as f:
        for item in final_topics:
            history_line = item.get("topic", "").strip()
            if item.get("subtopic"):
                history_line = f"{history_line}\t{item['subtopic'].strip()}"
            f.write(history_line + "\n")

    print(f"Wrote {len(final_topics)} topics to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
