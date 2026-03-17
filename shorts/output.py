from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Literal, Optional


Status = Literal["ok", "error"]


def one_line(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def env_truthy(name: str) -> bool:
    value = (os.environ.get(name) or "").strip().lower()
    return value in {"1", "true", "yes", "y", "on"}


def summary_line(summary: dict[str, Any]) -> str:
    return "SUMMARY " + json.dumps(summary, ensure_ascii=False, separators=(",", ":"))


def print_summary(summary: dict[str, Any]) -> None:
    print(summary_line(summary), flush=True)


def format_result_line(
    *,
    status: Status,
    elapsed_s: float,
    video: Optional[Path],
    video_id: Optional[str],
    upload_url: Optional[str],
    no_upload: bool,
    error: Optional[str] = None,
) -> str:
    parts = [
        "RESULT",
        "status=%s" % status,
        "elapsed_s=%.3f" % elapsed_s,
    ]
    if video is not None:
        parts.append("video=%s" % video)
    if video_id:
        parts.append("video_id=%s" % video_id)
    if no_upload:
        parts.append("upload=SKIPPED")
    elif upload_url:
        parts.append("upload=%s" % upload_url)
    if error:
        parts.append("error=%s" % one_line(error))
    return " ".join(parts)


_env_truthy = env_truthy
_one_line = one_line
_summary_line = summary_line
