#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

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
) -> list[str]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "topics": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": max(1, request_count),
                "maxItems": max(1, request_count) + 5,
            }
        },
        "required": ["topics"],
    }

    avoid_tail = "\n".join(f"- {t}" for t in avoid_topics[-120:])
    system = (
        "You generate high-retention YouTube Shorts topic ideas. "
        "Do not include emojis. Do not include hashtags. "
        "Avoid precise claims that need fact-checking. "
        "Output only valid JSON matching the schema."
    )
    user = (
        f"Language: {language}\n"
        f"Niche: {niche}\n"
        f"Style: {style}\n"
        f"Date: {today}\n"
        f"Generate {request_count} topics. Each topic should be one line, <= 35 characters if Korean.\n"
        "Prefer topics that can be explained in ~25-35 seconds.\n"
        "Avoid repeating these recent topics:\n"
        f"{avoid_tail if avoid_tail else '(none)'}\n"
    )

    payload = {
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
    }

    response = requests.post(
        f"{base_url}/responses",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=timeout_s,
    )
    response.raise_for_status()
    obj = json.loads(_response_text(response.json()))
    return [t.strip() for t in (obj.get("topics") or []) if isinstance(t, str) and t.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate Shorts topics with OpenAI and write jobs/topics.txt")
    ap.add_argument("--config", default=ENV_SENTINEL)
    ap.add_argument("--out", default="jobs/topics.txt")
    ap.add_argument("--history", default="jobs/topics_history.txt")
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--language", default="ko")
    ap.add_argument("--niche", default="tech/ai/internet")
    ap.add_argument("--style", default="tech news, concise")
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

    out_path = Path(args.out)
    hist_path = Path(args.history)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    hist_path.parent.mkdir(parents=True, exist_ok=True)

    existing = read_existing_topics(hist_path)
    accepted: list[str] = []
    accepted_set: set[str] = set()
    all_candidates: list[str] = []
    today = date.today().isoformat()

    print(
        f"[topics] policy mode={uniqueness_mode} target_count={args.count} max_attempts={max_attempts} "
        f"history_size={len(existing)}"
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
                niche=args.niche,
                style=args.style,
                today=today,
                request_count=request_count,
                avoid_topics=avoid_topics,
            )
        except Exception as e:
            raise SystemExit(f"topic generation failed on attempt {attempt}/{max_attempts}: {e}") from e

        if not batch:
            print(f"[topics] attempt {attempt}/{max_attempts}: no topics returned")
            continue

        all_candidates.extend(batch)
        added_this_attempt = 0
        for topic in batch:
            if topic in accepted_set:
                continue
            if uniqueness_mode == "strict" and topic in existing:
                continue
            accepted_set.add(topic)
            accepted.append(topic)
            added_this_attempt += 1
            if len(accepted) >= args.count:
                break

        print(
            f"[topics] attempt {attempt}/{max_attempts}: returned={len(batch)} "
            f"added={added_this_attempt} accepted={len(accepted)}/{args.count}"
        )

    if len(accepted) < args.count and uniqueness_mode == "best_effort":
        for topic in all_candidates:
            if topic in accepted_set:
                continue
            accepted_set.add(topic)
            accepted.append(topic)
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
    out_path.write_text("\n".join(final_topics) + "\n", encoding="utf-8")
    with hist_path.open("a", encoding="utf-8") as f:
        for topic in final_topics:
            f.write(topic + "\n")

    print(f"Wrote {len(final_topics)} topics to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
