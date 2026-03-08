#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SECRET_KEYS = {
    "openai_api_key",
    "google_api_key",
    "youtube_api_key",
    "elevenlabs_api_key",
    "pexels_api_key",
    "api_key",
    "client_secret",
    "private_key",
    "access_token",
    "refresh_token",
}

API_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{10,}\b"),
]

PLACEHOLDER_PATTERNS = {
    "${OPENAI_API_KEY}",
    "${GOOGLE_API_KEY}",
    "${YOUTUBE_API_KEY}",
    "${ELEVENLABS_API_KEY}",
    "${PEXELS_API_KEY}",
    "your_openai_api_key",
    "your_google_api_key",
    "your_youtube_api_key",
    "your_elevenlabs_api_key",
    "your_pexels_api_key",
    "test-key",
    "api-key",
    "changeme",
    "change_me",
}


def _is_placeholder(value: str) -> bool:
    if value == "":
        return True
    if value.startswith("${") and value.endswith("}"):
        return True
    return value.lower() in PLACEHOLDER_PATTERNS


def _walk_json(node: Any, *, key_path: str, found: list[tuple[str, str]]):
    if isinstance(node, dict):
        for key, value in node.items():
            next_path = f"{key_path}.{key}" if key_path else key
            _walk_json(value, key_path=next_path, found=found)
            if isinstance(key, str) and key in SECRET_KEYS and isinstance(value, str) and not _is_placeholder(value):
                found.append((next_path, value))
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            _walk_json(item, key_path=f"{key_path}[{idx}]", found=found)


def _scan_text_patterns(text: str, *, path: str, found: list[tuple[str, str]]):
    for regex in API_PATTERNS:
        for match in regex.findall(text):
            if match and not _is_placeholder(match):
                found.append((path, match))


def _scan_file(path: Path, found: list[tuple[str, str]]) -> None:
    if not path.exists():
        return
    if path.is_dir():
        for child in path.glob("**/*"):
            if child.is_file():
                _scan_file(child, found)
        return

    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return

    if path.suffix.lower() in {".json", ".config", ".txt", ".env", ".yaml", ".yml"}:
        try:
            _walk_json(json.loads(text), key_path=str(path), found=found)
        except Exception:
            pass
    _scan_text_patterns(text, path=str(path), found=found)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan config/secrets for real API keys.")
    parser.add_argument("paths", nargs="+", help="Paths to scan (files or directories)")
    args = parser.parse_args()

    found: list[tuple[str, str]] = []
    for raw in args.paths:
        _scan_file(Path(raw), found)

    # Remove duplicates and obvious placeholders
    cleaned: list[tuple[str, str]] = []
    seen = set()
    for path, value in found:
        if value in PLACEHOLDER_PATTERNS or value.strip() == "":
            continue
        if value.startswith("${") and value.endswith("}"):
            continue
        key = (path, value)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append((path, value))

    if cleaned:
        print("ERROR: Possible real secret detected in target files:")
        for path, value in cleaned:
            print(f" - {path}: {value[:12]}...")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
