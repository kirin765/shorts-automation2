#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

try:
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    from playwright.async_api import async_playwright
except Exception as e:  # pragma: no cover - import-time dependency feedback
    print(f"ERROR: Playwright dependency is missing. Run: pip install -r requirements.txt && playwright install. {e}", file=sys.stderr)
    raise


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Upload a video to TikTok using a browser session.")
    ap.add_argument("--video", required=True, help="Path to uploaded video file")
    ap.add_argument("--title", default="", help="Title for fallback caption input")
    ap.add_argument("--description", default="", help="Description/caption text")
    ap.add_argument(
        "--state-path",
        default="secrets/tiktok_state.json",
        help="Playwright storage_state path with an active logged-in TikTok session",
    )
    ap.add_argument(
        "--headless",
        default="true",
        help="Run browser headless (true/false). Default: true",
    )
    ap.add_argument(
        "--upload-timeout",
        default="600",
        help="Upload/upload-command timeout in seconds. Default: 600",
    )
    return ap.parse_args()


def _to_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    return raw in {"1", "true", "yes", "on", "y"}


def _extract_video_url(text: str) -> str | None:
    if not text:
        return None
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                for key in ("upload_url", "url", "link", "video_url"):
                    value = data.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
        except Exception:
            pass

    match = re.search(r"https?://www\.tiktok\.com/[^\s\"'<>()\[\]{}|`]*", text)
    if match:
        return match.group(0).rstrip(")]},.;:\t\n\r ")
    return None


async def _first_visible(page, selectors: list[str], *, timeout_ms: int = 8000):
    for selector in selectors:
        try:
            locator = page.locator(selector)
            if await locator.count() == 0:
                continue
            element = locator.first
            if await element.is_visible(timeout=timeout_ms):
                return element
        except Exception:
            continue
    return None


async def _find_and_set_input_file(page, path: Path, timeout_ms: int) -> bool:
    selectors = [
        'input[type="file"][accept*="video"]',
        'input[type="file"]',
    ]
    for selector in selectors:
        node = await _first_visible(page, [selector], timeout_ms=timeout_ms)
        if node is None:
            continue
        try:
            await node.set_input_files(str(path))
            return True
        except Exception:
            continue
    return False


async def _fill_textarea_candidates(page, text: str, timeout_ms: int) -> bool:
    selector_groups = [
        "textarea[placeholder*='description' i]",
        "textarea[placeholder*='caption' i]",
        "textarea[aria-label*='caption' i]",
        "[contenteditable='true'][aria-label*='caption' i]",
        "textarea",
    ]
    for selector in selector_groups:
        try:
            node = await _first_visible(page, [selector], timeout_ms=timeout_ms)
            if node is None:
                continue
            await node.fill(text)
            return True
        except Exception:
            continue
    return False


async def _click_candidates(page, labels: list[str], timeout_ms: int) -> bool:
    for label in labels:
        xpath = f'button:has-text("{label}")'
        try:
            node = await _first_visible(page, [xpath], timeout_ms=timeout_ms)
            if node is None:
                continue
            await node.click()
            return True
        except Exception:
            continue

    role_selector = "button"
    try:
        for label in labels:
            node = page.get_by_role("button", name=label)
            if await node.count() == 0:
                continue
            if await node.first.is_visible():
                await node.first.click()
                return True
    except Exception:
        pass
    return False


def _parse_video_candidates(page_url: str | None, html: str) -> str | None:
    if page_url:
        match = re.search(r"https?://www\.tiktok\.com/[^\s\"'<>()\[\]{}|`]*", page_url)
        if match:
            return match.group(0).rstrip(")]},.;:\t\n\r ")

    if not html:
        return None
    match = re.search(r"https?://www\.tiktok\.com/[^\s\"'<>()\[\]{}|`]*", html)
    if match:
        return match.group(0).rstrip(")]},.;:\t\n\r ")
    return None


async def _find_video_url(page) -> str:
    # Poll for a url containing /video/ while upload finalizes.
    deadline_ms = 600_000
    elapsed_ms = 0
    wait_ms = 1000
    last_error = None
    while elapsed_ms <= deadline_ms:
        try:
            page_url = page.url
            html = await page.content()
            maybe = _parse_video_candidates(page_url, html)
            if maybe and re.search(r"/video/\d+", maybe):
                return maybe

            anchors = await page.eval_on_selector_all(
                "a[href]",
                "els => els.map((el) => el.href)",
            )
            if isinstance(anchors, list):
                for anchor in anchors:
                    if isinstance(anchor, str) and "/video/" in anchor:
                        maybe = _extract_video_url(anchor)
                        if maybe and re.search(r"/video/\d+", maybe):
                            return maybe
        except Exception as e:
            last_error = e
        await asyncio.sleep(wait_ms / 1000)
        elapsed_ms += wait_ms

    if last_error is not None:
        raise RuntimeError(f"Failed to capture uploaded video URL: {last_error}")
    raise RuntimeError("Failed to capture uploaded video URL")


def _parse_video_id(url: str) -> str | None:
    match = re.search(r"/video/(\d+)", url)
    if not match:
        return None
    return match.group(1)


async def _main_async(args: argparse.Namespace) -> int:
    video_path = Path(args.video)
    if not video_path.exists():
        print(f"ERROR: video file not found: {video_path}", file=sys.stderr)
        return 2

    state_path = Path(args.state_path)
    if not state_path.exists():
        print(
            "ERROR: TikTok storage state file missing. Create it by logging in once and saving session state.",
            file=sys.stderr,
        )
        return 2

    headless = _to_bool(args.headless)
    try:
        upload_timeout = int(float(args.upload_timeout))
    except Exception:
        upload_timeout = 600

    caption = (args.description or "").strip()
    if args.title and args.title.strip():
        title_text = args.title.strip()
        caption = f"{title_text}\n\n{caption}" if caption else title_text
    timeout_ms = max(20_000, upload_timeout * 1000)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            storage_state=str(state_path),
            viewport={"width": 1366, "height": 2400},
        )
        page = await context.new_page()
        try:
            await page.goto("https://www.tiktok.com/upload", wait_until="domcontentloaded", timeout=timeout_ms)

            upload_area = await _first_visible(page, [
                'div[data-testid="upload-btn"]',
                '[data-e2e="upload-file-select-button"]',
                '[data-e2e="upload-video-upload-button"]',
            ], timeout_ms=timeout_ms)
            if upload_area is not None:
                await upload_area.click()

            if not await _find_and_set_input_file(page, video_path, timeout_ms):
                raise RuntimeError("Could not find TikTok upload file input")

            await _fill_textarea_candidates(page, caption, timeout_ms=timeout_ms)

            await _click_candidates(page, ["Next", "Next step", "Upload"], timeout_ms)
            await _click_candidates(page, ["Post", "Publish", "Share"], timeout_ms)

            video_url = await asyncio.wait_for(
                _find_video_url(page),
                timeout=upload_timeout,
            )
        finally:
            await context.close()
            await browser.close()

    if not video_url:
        print("ERROR: Upload completed but no video URL found", file=sys.stderr)
        return 2

    result = {"upload_url": video_url, "video_id": _parse_video_id(video_url)}
    print(json.dumps(result, ensure_ascii=False))
    return 0


def main() -> int:
    args = _parse_args()
    try:
        return asyncio.run(_main_async(args))
    except PlaywrightTimeoutError as e:
        print(f"ERROR: TikTok upload timeout: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
