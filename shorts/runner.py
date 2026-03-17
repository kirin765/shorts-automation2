from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import captions, media, providers, upload
from .config import Config
from .models import load_render_job
from .output import env_truthy, format_result_line, one_line, print_summary


@dataclass
class RunOutcome:
    status: str
    result_line: str
    summary: dict[str, object]
    elapsed_s: float
    video: Optional[Path] = None
    video_id: Optional[str] = None
    upload_url: Optional[str] = None
    error: Optional[str] = None


def run_render_job_file(
    config: Config,
    job_path: Path,
    *,
    no_upload: bool,
    force_upload: bool,
    audio_path: Optional[str] = None,
    traceback: bool = False,
) -> RunOutcome:
    started = time.monotonic()
    no_upload = bool(no_upload) or env_truthy("NO_UPLOAD")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    audio = None
    srt = None
    video = None
    credit_path = None
    duration = None
    video_id = None
    upload_url = None
    idempotency_hit = False
    idempotency_key = None
    idempotency_state_file = None

    try:
        job = load_render_job(job_path)
        out_dir = Path(config.app.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        external_audio = bool(audio_path)
        audio = Path(audio_path) if external_audio else (out_dir / ("%s.mp3" % stamp))
        srt = out_dir / ("%s.srt" % stamp)
        video = out_dir / ("%s.mp4" % stamp)
        background_tmp = out_dir / ("%s.bg.mp4" % stamp)

        if external_audio:
            if not audio.exists():
                raise FileNotFoundError("--audio not found: %s" % audio)
            print("[1/3] TTS skipped (--audio)")
        else:
            print("[1/4] TTS generation")
            media.synthesize_speech(config, job, audio, srt)

        print("[2/3] Subtitle generation" if external_audio else "[2/4] Subtitle generation")
        duration = media.probe_duration(audio, ffprobe=media.resolve_ffprobe(config))
        tolerance = config.render.subtitle_sync_drift_tolerance
        repair_enabled = config.render.subtitle_sync_repair
        repair_max_drift = config.render.subtitle_sync_repair_max_drift
        max_scale_delta = min(1.0, max(0.0, config.render.subtitle_sync_max_scale_delta))

        subtitle_ok = False
        subtitle_method = "none"

        if (not external_audio) and config.render.subtitle_align_openai:
            try:
                print("[2-1/4] OpenAI subtitle alignment")
                providers.write_srt_aligned_openai(
                    config,
                    audio_path=audio,
                    srt_path=srt,
                    prompt_text=job.script,
                    script_text=job.script,
                )
                if captions.apply_srt_timing_guard(
                    srt,
                    duration,
                    enabled=repair_enabled,
                    repair_max_drift=repair_max_drift,
                    max_scale_delta=max_scale_delta,
                    validate_max_drift=tolerance,
                    label="openai",
                ):
                    subtitle_ok = True
                    subtitle_method = "openai"
                else:
                    print("[-] OpenAI subtitles drifted beyond tolerance; falling back.")
            except Exception as exc:
                print("[-] OpenAI subtitle alignment failed: %s" % exc)

        if (not subtitle_ok) and (not external_audio) and config.render.subtitle_align_edge:
            if srt.exists() and srt.stat().st_size > 0:
                if captions.apply_srt_timing_guard(
                    srt,
                    duration,
                    enabled=repair_enabled,
                    repair_max_drift=repair_max_drift,
                    max_scale_delta=max_scale_delta,
                    validate_max_drift=tolerance,
                    label="edge",
                ):
                    subtitle_ok = True
                    subtitle_method = "edge"
                else:
                    print("[-] Edge subtitles failed timing validation; falling back.")
            else:
                print("[-] Edge subtitles were not generated; falling back.")

        if not subtitle_ok:
            try:
                print("[2-2/4] Script split subtitle fallback")
                lines = captions.split_for_captions_dense(
                    job.script,
                    max_chars=config.render.subtitle_max_chars,
                ) or captions.split_for_captions(job.script)
                captions.write_srt(lines, duration, srt)
                if captions.apply_srt_timing_guard(
                    srt,
                    duration,
                    enabled=repair_enabled,
                    repair_max_drift=repair_max_drift,
                    max_scale_delta=max_scale_delta,
                    validate_max_drift=tolerance,
                    label="script_split",
                ):
                    subtitle_ok = True
                    subtitle_method = "script_split"
                else:
                    raise RuntimeError("script-based subtitles were out of sync")
            except Exception as exc:
                raise RuntimeError("Could not generate valid subtitles: %s" % exc) from exc

        print("[i] Subtitles ready: source=%s sync_tolerance=%.2fs" % (subtitle_method, tolerance))
        print("[3/3] Rendering video" if external_audio else "[3/4] Rendering video")
        background, credit_line = media.ensure_background_for_job(
            config,
            job,
            duration_s=duration,
            out_path=background_tmp,
        )
        media.render_video(config, job, background, audio, srt, video)
        print("Render completed: %s" % video)
        if credit_line:
            credit_path = out_dir / ("%s.credits.txt" % stamp)
            credit_path.write_text(credit_line + "\n", encoding="utf-8")
            print("Credits: %s" % credit_path)

        if no_upload:
            print("Upload skipped (--no-upload or NO_UPLOAD=1)")
        else:
            idempotency_key = upload.job_idempotency_key(job_path)
            idempotency_state_file = config.youtube.upload_state_file
            state_path = Path(idempotency_state_file)
            existing = None
            if (not force_upload) and config.youtube.idempotency_enabled:
                existing = upload.lookup_uploaded_record(state_path, idempotency_key)
            if existing:
                idempotency_hit = True
                if isinstance(existing.get("video_id"), str):
                    video_id = existing.get("video_id")
                if isinstance(existing.get("upload_url"), str):
                    upload_url = existing.get("upload_url")
                if not upload_url and video_id:
                    upload_url = "https://youtu.be/%s" % video_id
                print("[4/4] Upload skipped (already uploaded): %s" % (upload_url or video_id or "unknown"))
            else:
                print("[4/4] Uploading to YouTube")
                upload.validate_upload_checklist(config, job, video)
                video_id = upload.upload_video(config, job, video, credit_line=credit_line)
                upload_url = "https://youtu.be/%s" % video_id
                print("Upload completed: %s" % upload_url)
                if config.youtube.idempotency_enabled:
                    upload.append_jsonl(
                        state_path,
                        {
                            "ts": datetime.now().isoformat(timespec="seconds"),
                            "job_key": idempotency_key,
                            "job_path": str(job_path),
                            "video_id": video_id,
                            "upload_url": upload_url,
                        },
                    )

        elapsed_s = time.monotonic() - started
        summary = {
            "status": "ok",
            "elapsed_s": round(elapsed_s, 3),
            "job": str(job_path),
            "stamp": stamp,
            "no_upload": no_upload,
            "video": str(video) if video else None,
            "audio": str(audio) if audio else None,
            "srt": str(srt) if srt else None,
            "credits": str(credit_path) if credit_path else None,
            "duration_s": round(float(duration), 3) if duration is not None else None,
            "video_id": video_id,
            "upload_url": upload_url,
            "idempotency_hit": idempotency_hit,
            "idempotency_key": idempotency_key,
            "idempotency_state_file": idempotency_state_file,
        }
        result_line = format_result_line(
            status="ok",
            elapsed_s=elapsed_s,
            video=video,
            video_id=video_id,
            upload_url=upload_url,
            no_upload=no_upload,
        )
        print_summary(summary)
        print(result_line, flush=True)
        return RunOutcome(
            status="ok",
            result_line=result_line,
            summary=summary,
            elapsed_s=elapsed_s,
            video=video,
            video_id=video_id,
            upload_url=upload_url,
        )
    except Exception as exc:
        elapsed_s = time.monotonic() - started
        summary = {
            "status": "error",
            "elapsed_s": round(elapsed_s, 3),
            "job": str(job_path),
            "stamp": stamp,
            "no_upload": no_upload,
            "video": str(video) if video else None,
            "audio": str(audio) if audio else None,
            "srt": str(srt) if srt else None,
            "credits": str(credit_path) if credit_path else None,
            "duration_s": round(float(duration), 3) if duration is not None else None,
            "error_type": type(exc).__name__,
            "error": one_line(str(exc)),
            "idempotency_hit": idempotency_hit,
            "idempotency_key": idempotency_key,
            "idempotency_state_file": idempotency_state_file,
        }
        result_line = format_result_line(
            status="error",
            elapsed_s=elapsed_s,
            video=video,
            video_id=video_id,
            upload_url=upload_url,
            no_upload=no_upload,
            error="%s: %s" % (type(exc).__name__, exc),
        )
        print_summary(summary)
        print(result_line, flush=True)
        if traceback:
            raise
        return RunOutcome(
            status="error",
            result_line=result_line,
            summary=summary,
            elapsed_s=elapsed_s,
            video=video,
            video_id=video_id,
            upload_url=upload_url,
            error=str(exc),
        )
