#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import date
from pathlib import Path


def slug(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "topic"


def read_topics(path: Path) -> list[str]:
    topics: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        topics.append(line)
    return topics


def main() -> int:
    ap = argparse.ArgumentParser(description="Enqueue topic-only jobs then run the queue.")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--queue-dir", default="jobs/queue")
    ap.add_argument("--topics-file", help="Text file: 1 topic per line (# comment supported)")
    ap.add_argument("--topic", action="append", help="Repeatable. Adds a single topic.")
    ap.add_argument("--count", type=int, default=1, help="How many jobs to enqueue (from the provided topics)")
    ap.add_argument("--target-seconds", type=int, default=28)
    ap.add_argument("--style", default=None)
    ap.add_argument("--tone", default=None)
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--run-queue", default="scripts/run_queue.sh")
    args = ap.parse_args()

    topics: list[str] = []
    if args.topics_file:
        topics.extend(read_topics(Path(args.topics_file)))
    if args.topic:
        topics.extend([t for t in args.topic if t and t.strip()])
    if not topics:
        raise SystemExit("No topics. Use --topic or --topics-file.")

    queue_dir = Path(args.queue_dir)
    queue_dir.mkdir(parents=True, exist_ok=True)

    today = date.today().strftime("%Y-%m-%d")
    n = max(1, min(args.count, len(topics)))

    created: list[Path] = []
    for i in range(n):
        topic = topics[i].strip()
        name = f"{today}_{slug(topic)[:40]}_{i+1:02d}.json"
        p = queue_dir / name
        payload: dict = {"topic": topic, "target_seconds": args.target_seconds}
        if args.style:
            payload["style"] = args.style
        if args.tone:
            payload["tone"] = args.tone
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        created.append(p)

    print("Enqueued:")
    for p in created:
        print(f"- {p}")

    cmd = [args.run_queue, "--config", args.config, "--queue-dir", str(queue_dir)]
    if args.no_upload:
        cmd.append("--no-upload")
    print("\nRunning queue:")
    print(" ".join(cmd))
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())

