#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

import requests


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def openai_key(config: dict) -> str:
    key = (config.get("openai_api_key") or os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        raise SystemExit(
            "Missing OpenAI API key. Set config.json:openai_api_key or env OPENAI_API_KEY."
        )
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate Shorts topics with OpenAI and write jobs/topics.txt")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--out", default="jobs/topics.txt")
    ap.add_argument("--history", default="jobs/topics_history.txt")
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--language", default="ko")
    ap.add_argument("--niche", default="테크/AI/인터넷 트렌드")
    ap.add_argument("--style", default="테크 뉴스, 한 문장 짧게")
    ap.add_argument("--avoid-days", type=int, default=60, help="Avoid repeating history within N days (best-effort)")
    args = ap.parse_args()

    cfg = load_json(Path(args.config))
    key = openai_key(cfg)
    base_url = (cfg.get("openai_base_url") or "https://api.openai.com/v1").rstrip("/")
    model = (cfg.get("openai_topic_model") or cfg.get("openai_model") or "gpt-4o-mini").strip()
    timeout_s = int(cfg.get("openai_timeout_s", 40))
    temperature = float(cfg.get("openai_topic_temperature", cfg.get("openai_temperature", 0.7)))
    max_tokens = int(cfg.get("openai_topic_max_output_tokens", 500))

    out_path = Path(args.out)
    hist_path = Path(args.history)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    hist_path.parent.mkdir(parents=True, exist_ok=True)

    existing = read_existing_topics(hist_path)
    existing_list = sorted(existing)
    existing_tail = "\n".join(f"- {t}" for t in existing_list[-80:])

    today = date.today().isoformat()
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "topics": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": max(1, args.count),
                "maxItems": max(1, args.count) + 5,
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
        f"Language: {args.language}\n"
        f"Niche: {args.niche}\n"
        f"Style: {args.style}\n"
        f"Date: {today}\n"
        f"Generate {args.count} topics. Each topic should be one line, <= 35 characters if Korean.\n"
        "Prefer topics that can be explained in ~25-35 seconds.\n"
        "Avoid repeating these recent topics if possible:\n"
        f"{existing_tail if existing_tail else '(none)'}\n"
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

    r = requests.post(
        f"{base_url}/responses",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
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
        raise SystemExit("OpenAI response: no output text found")

    obj = json.loads(text_out)
    topics = [t.strip() for t in (obj.get("topics") or []) if isinstance(t, str) and t.strip()]
    # Dedup preserving order; drop ones already in history.
    seen: set[str] = set()
    filtered: list[str] = []
    for t in topics:
        if t in seen:
            continue
        seen.add(t)
        if t in existing:
            continue
        filtered.append(t)
        if len(filtered) >= args.count:
            break

    if len(filtered) < max(1, args.count // 2):
        # If we couldn't avoid repeats, at least output something.
        filtered = (filtered or topics)[: args.count]

    out_path.write_text("\n".join(filtered) + "\n", encoding="utf-8")
    with hist_path.open("a", encoding="utf-8") as f:
        for t in filtered:
            f.write(t + "\n")

    print(f"Wrote {len(filtered)} topics to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

