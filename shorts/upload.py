from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Optional

from .config import Config
from .models import RenderJob
from .output import one_line


SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def get_youtube_client(client_secret_file: Path, token_file: Path):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_file), SCOPES)
            creds = flow.run_local_server(port=0)
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds)


def retry_upload_next_chunk(
    req: Any,
    *,
    max_attempts: int,
    timeout_s: Optional[float],
    initial_backoff_s: float,
    max_backoff_s: float,
    is_retryable_exc: Callable[[BaseException], bool],
    sleep_fn: Callable[[float], None] = time.sleep,
    time_fn: Callable[[], float] = time.monotonic,
    log_fn: Callable[[str], None] = print,
) -> dict[str, Any]:
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    started = time_fn()
    attempt = 0
    backoff_s = float(initial_backoff_s)
    timeout_s = float(timeout_s) if timeout_s is not None else None

    log_fn(
        "[upload] policy max_attempts=%d timeout_s=%s initial_backoff_s=%.1f max_backoff_s=%.1f"
        % (max_attempts, timeout_s if timeout_s is not None else "none", initial_backoff_s, max_backoff_s)
    )

    while True:
        if timeout_s is not None and (time_fn() - started) > timeout_s:
            raise TimeoutError("upload timed out after %.1fs" % timeout_s)

        attempt += 1
        try:
            _, response = req.next_chunk()
            if response is not None:
                if not isinstance(response, dict):
                    raise RuntimeError("unexpected upload response type: %s" % type(response).__name__)
                return response
        except Exception as exc:
            if attempt >= max_attempts or not is_retryable_exc(exc):
                raise
            if timeout_s is not None:
                elapsed = time_fn() - started
                if elapsed + backoff_s > timeout_s:
                    raise TimeoutError("upload timed out after %.1fs" % timeout_s) from exc
            log_fn(
                "[upload] next_chunk failed (attempt %d/%d): %s: %s"
                % (attempt, max_attempts, type(exc).__name__, one_line(str(exc)))
            )
            log_fn("[upload] retrying in %.1fs" % backoff_s)
            sleep_fn(backoff_s)
            backoff_s = min(backoff_s * 2.0, float(max_backoff_s))


def upload_video(config: Config, job: RenderJob, video_path: Path, *, credit_line: Optional[str] = None) -> str:
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    youtube = config.youtube
    client = get_youtube_client(Path(youtube.client_secret_file), Path(youtube.token_file))
    description = (job.description + "\n\n" + job.hashtags).strip()
    if credit_line and config.background.append_credit_to_description:
        description = (description + "\n\n" + credit_line).strip()

    body = {
        "snippet": {
            "title": job.title[:100],
            "description": description[:5000],
            "categoryId": youtube.category_id,
            "defaultLanguage": config.app.default_language,
            "defaultAudioLanguage": config.app.default_language,
        },
        "status": {
            "privacyStatus": youtube.privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }
    req = client.videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(str(video_path), chunksize=-1, resumable=True),
    )

    def is_retryable(exc: BaseException) -> bool:
        if isinstance(exc, TimeoutError):
            return True
        if isinstance(exc, OSError):
            return True
        if isinstance(exc, HttpError):
            status = getattr(getattr(exc, "resp", None), "status", None)
            return status in {408, 429, 500, 502, 503, 504}
        return False

    response = retry_upload_next_chunk(
        req,
        max_attempts=youtube.upload_max_attempts,
        timeout_s=youtube.upload_timeout_s,
        initial_backoff_s=youtube.upload_initial_backoff_s,
        max_backoff_s=youtube.upload_max_backoff_s,
        is_retryable_exc=is_retryable,
    )
    video_id = response.get("id")
    if not isinstance(video_id, str) or not video_id:
        raise RuntimeError("upload response did not include a video id")
    return video_id


def job_idempotency_key(job_path: Path) -> str:
    try:
        return str(job_path.resolve())
    except Exception:
        return str(job_path)


def read_jsonl_last_by_key(path: Path, *, key_field: str) -> dict[str, dict[str, Any]]:
    out = {}
    if not path.exists():
        return out
    try:
        with path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue
                key = obj.get(key_field)
                if not isinstance(key, str) or not key:
                    continue
                out[key] = obj
    except OSError:
        return {}
    return out


def lookup_uploaded_record(state_path: Path, job_key: str) -> Optional[dict[str, Any]]:
    record = read_jsonl_last_by_key(state_path, key_field="job_key").get(job_key)
    if not record:
        return None
    if record.get("video_id") or record.get("upload_url"):
        return record
    return None


def append_jsonl(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")


def run_ffprobe_json(ffprobe_bin: str, path: Path) -> dict[str, Any]:
    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError("ffprobe failed (code %d): %s" % (proc.returncode, one_line(proc.stderr or proc.stdout or "")))
    try:
        return json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("ffprobe output is not valid JSON: %s" % exc) from exc


def as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        text = str(value).strip()
        if not text:
            return None
        return float(text)
    except Exception:
        return None


def validate_upload_checklist(
    config: Config,
    job: RenderJob,
    video_path: Path,
    *,
    ffprobe_data: Optional[dict[str, Any]] = None,
) -> None:
    if not job.title.strip():
        raise RuntimeError("upload checklist failed: missing title")
    if not job.hashtags.strip():
        raise RuntimeError("upload checklist failed: missing hashtags")
    if not video_path.exists():
        raise RuntimeError("upload checklist failed: video not found: %s" % video_path)
    try:
        if video_path.stat().st_size <= 0:
            raise RuntimeError("upload checklist failed: video is empty: %s" % video_path)
    except OSError as exc:
        raise RuntimeError("upload checklist failed: cannot stat video: %s: %s" % (video_path, exc)) from exc

    if ffprobe_data is None:
        ffprobe_data = run_ffprobe_json(config.app.ffprobe_bin or "ffprobe", video_path)

    streams = list(ffprobe_data.get("streams") or [])
    fmt = dict(ffprobe_data.get("format") or {})
    video_stream = next((stream for stream in streams if (stream or {}).get("codec_type") == "video"), None)
    audio_stream = next((stream for stream in streams if (stream or {}).get("codec_type") == "audio"), None)
    if not video_stream:
        raise RuntimeError("upload checklist failed: no video stream")
    if not audio_stream:
        raise RuntimeError("upload checklist failed: no audio stream")

    duration_s = as_float(fmt.get("duration"))
    if duration_s is not None and duration_s > config.youtube.max_duration_s + 1e-6:
        raise RuntimeError(
            "upload checklist failed: duration %.3fs exceeds %.1fs"
            % (duration_s, config.youtube.max_duration_s)
        )

    width = as_float(video_stream.get("width"))
    height = as_float(video_stream.get("height"))
    if width is None or height is None or width <= 0 or height <= 0:
        raise RuntimeError("upload checklist failed: invalid video resolution")
    if int(width) < config.youtube.min_width or int(height) < config.youtube.min_height:
        raise RuntimeError(
            "upload checklist failed: resolution %dx%d below %dx%d"
            % (int(width), int(height), config.youtube.min_width, config.youtube.min_height)
        )
    if config.youtube.require_portrait and not (height > width):
        raise RuntimeError("upload checklist failed: not portrait (got %dx%d)" % (int(width), int(height)))
    if config.youtube.require_aspect_9_16:
        aspect = float(width) / float(height)
        target = 9.0 / 16.0
        if abs(aspect - target) > config.youtube.aspect_tolerance:
            raise RuntimeError(
                "upload checklist failed: aspect %.4f not ~9:16 (tol %.3f)"
                % (aspect, config.youtube.aspect_tolerance)
            )


_retry_upload_next_chunk = retry_upload_next_chunk
_lookup_uploaded_record = lookup_uploaded_record
_append_jsonl = append_jsonl
_run_ffprobe_json = run_ffprobe_json
_as_float = as_float
