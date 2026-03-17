from __future__ import annotations

import copy
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency already in requirements
    load_dotenv = None


ENV_SENTINEL = "ENV"


DEFAULT_CONFIG = {
    "app": {
        "channel_name": "Kiwan Shorts",
        "default_language": "ko",
        "shorts_target_seconds": 28,
        "output_dir": "output",
        "logs_dir": "logs",
        "queue_dir": "jobs/queue",
        "done_dir": "jobs/done",
        "failed_dir": "jobs/failed",
        "topics_file": "jobs/topics.txt",
        "topics_history_file": "jobs/topics_history.txt",
        "ffmpeg_bin": "",
        "ffprobe_bin": "",
    },
    "content": {
        "openai_api_key": "",
        "openai_model": "gpt-4o-mini",
        "openai_topic_model": "gpt-4o-mini",
        "openai_base_url": "https://api.openai.com/v1",
        "openai_timeout_s": 40,
        "openai_temperature": 0.7,
        "openai_max_output_tokens": 650,
        "openai_topic_temperature": 0.7,
        "openai_topic_max_output_tokens": 500,
        "openai_language": "ko",
        "openai_transcribe_model": "whisper-1",
        "openai_transcribe_timeout_s": 60,
        "openai_transcribe_language": "ko",
    },
    "tts": {
        "provider": "edge",
        "voice": "ko-KR-SunHiNeural",
        "edge_rate": "+0%",
        "edge_volume": "+0%",
        "edge_pitch": "+0Hz",
        "edge_timeout_s": 25,
        "edge_proxy": "",
        "elevenlabs_api_key": "",
        "elevenlabs_voice_id": "",
    },
    "render": {
        "top_bar_height": 260,
        "bottom_bar_height": 260,
        "font_file": "",
        "subtitle_fontsdir": "",
        "subtitle_playres_y": 288,
        "subtitle_position": "center,middle",
        "subtitle_font_size": 88,
        "subtitle_outline": 8,
        "subtitle_margin_v": 0,
        "subtitle_margin_top_v": 120,
        "subtitle_margin_bottom_v": 320,
        "subtitle_vshift": 0,
        "subtitle_sync_drift_tolerance": 0.5,
        "subtitle_sync_repair": True,
        "subtitle_sync_repair_max_drift": 0.5,
        "subtitle_sync_max_scale_delta": 0.12,
        "subtitle_align_openai": True,
        "subtitle_align_edge": True,
        "subtitle_text_source": "transcript",
        "subtitle_max_chars": 26,
        "subtitle_words_per_cue": 10,
        "subtitle_min_cue_s": 0.45,
        "subtitle_max_cue_s": 3.5,
        "video_preset": "medium",
        "video_crf": 21,
        "video_bitrate": "",
        "audio_bitrate": "192k",
        "bgm_file": "assets/bgm.mp3",
    },
    "background": {
        "provider": "local",
        "local_video": "assets/background.mp4",
        "regenerate_local": False,
        "append_credit_to_description": True,
        "pexels_api_key": "",
        "pexels_query": "",
        "pexels_orientation": "portrait",
        "pexels_per_page": 10,
        "pexels_min_height": 1600,
        "pexels_clip_count": 3,
        "pexels_cache_dir": "assets/pexels_cache",
        "pexels_timeout_s": 20,
        "pexels_download_timeout_s": 120,
    },
    "youtube": {
        "client_secret_file": "secrets/client_secret.json",
        "token_file": "secrets/token.json",
        "category_id": "28",
        "privacy_status": "private",
        "idempotency_enabled": True,
        "upload_state_file": "logs/uploads.jsonl",
        "upload_max_attempts": 5,
        "upload_timeout_s": 900,
        "upload_initial_backoff_s": 2.0,
        "upload_max_backoff_s": 30.0,
        "max_duration_s": 60.0,
        "min_width": 720,
        "min_height": 1280,
        "require_portrait": True,
        "require_aspect_9_16": True,
        "aspect_tolerance": 0.07,
    },
}


@dataclass(frozen=True)
class AppConfig:
    channel_name: str
    default_language: str
    shorts_target_seconds: int
    output_dir: str
    logs_dir: str
    queue_dir: str
    done_dir: str
    failed_dir: str
    topics_file: str
    topics_history_file: str
    ffmpeg_bin: str
    ffprobe_bin: str


@dataclass(frozen=True)
class ContentConfig:
    openai_api_key: str
    openai_model: str
    openai_topic_model: str
    openai_base_url: str
    openai_timeout_s: int
    openai_temperature: float
    openai_max_output_tokens: int
    openai_topic_temperature: float
    openai_topic_max_output_tokens: int
    openai_language: str
    openai_transcribe_model: str
    openai_transcribe_timeout_s: int
    openai_transcribe_language: str


@dataclass(frozen=True)
class TTSConfig:
    provider: str
    voice: str
    edge_rate: str
    edge_volume: str
    edge_pitch: str
    edge_timeout_s: int
    edge_proxy: str
    elevenlabs_api_key: str
    elevenlabs_voice_id: str


@dataclass(frozen=True)
class RenderConfig:
    top_bar_height: int
    bottom_bar_height: int
    font_file: str
    subtitle_fontsdir: str
    subtitle_playres_y: int
    subtitle_position: str
    subtitle_font_size: int
    subtitle_outline: int
    subtitle_margin_v: int
    subtitle_margin_top_v: int
    subtitle_margin_bottom_v: int
    subtitle_vshift: int
    subtitle_sync_drift_tolerance: float
    subtitle_sync_repair: bool
    subtitle_sync_repair_max_drift: float
    subtitle_sync_max_scale_delta: float
    subtitle_align_openai: bool
    subtitle_align_edge: bool
    subtitle_text_source: str
    subtitle_max_chars: int
    subtitle_words_per_cue: int
    subtitle_min_cue_s: float
    subtitle_max_cue_s: float
    video_preset: str
    video_crf: int
    video_bitrate: str
    audio_bitrate: str
    bgm_file: str


@dataclass(frozen=True)
class BackgroundConfig:
    provider: str
    local_video: str
    regenerate_local: bool
    append_credit_to_description: bool
    pexels_api_key: str
    pexels_query: str
    pexels_orientation: str
    pexels_per_page: int
    pexels_min_height: int
    pexels_clip_count: int
    pexels_cache_dir: str
    pexels_timeout_s: int
    pexels_download_timeout_s: int


@dataclass(frozen=True)
class YouTubeConfig:
    client_secret_file: str
    token_file: str
    category_id: str
    privacy_status: str
    idempotency_enabled: bool
    upload_state_file: str
    upload_max_attempts: int
    upload_timeout_s: float
    upload_initial_backoff_s: float
    upload_max_backoff_s: float
    max_duration_s: float
    min_width: int
    min_height: int
    require_portrait: bool
    require_aspect_9_16: bool
    aspect_tolerance: float


@dataclass(frozen=True)
class Config:
    app: AppConfig
    content: ContentConfig
    tts: TTSConfig
    render: RenderConfig
    background: BackgroundConfig
    youtube: YouTubeConfig


def load_config(config_arg: Optional[str]) -> Config:
    if load_dotenv is not None:
        load_dotenv()

    merged = copy.deepcopy(DEFAULT_CONFIG)
    if config_arg and config_arg.strip() and config_arg.strip().upper() != ENV_SENTINEL:
        path = Path(config_arg)
        if not path.exists():
            raise FileNotFoundError("config file not found: %s" % path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("config file is not valid JSON: %s" % exc)
        if not isinstance(payload, dict):
            raise ValueError("config file must contain a JSON object")
        _merge_known(merged, payload, path="config")

    _apply_special_env_overrides(merged)
    _apply_section_env_overrides(merged)
    return _build_config(merged)


def _parse_env_value(raw: str) -> Any:
    value = raw.strip()
    if not value:
        return ""
    lowered = value.lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    if value[0] in '{["' and (value[-1] in '}]' or (value[0] == '"' and value[-1] == '"')):
        try:
            return json.loads(value)
        except Exception:
            pass
    if re.fullmatch(r"-?\d+", value):
        try:
            return int(value)
        except Exception:
            return value
    if re.fullmatch(r"-?\d+\.\d+", value):
        try:
            return float(value)
        except Exception:
            return value
    return value


def _merge_known(base: dict[str, Any], incoming: dict[str, Any], *, path: str) -> None:
    for key, value in incoming.items():
        if key not in base:
            raise ValueError("unknown config key: %s.%s" % (path, key))
        current = base[key]
        if isinstance(current, dict):
            if not isinstance(value, dict):
                raise ValueError("config section %s.%s must be an object" % (path, key))
            _merge_known(current, value, path="%s.%s" % (path, key))
            continue
        base[key] = value


def _apply_special_env_overrides(data: dict[str, Any]) -> None:
    secret_map = {
        "OPENAI_API_KEY": ("content", "openai_api_key"),
        "PEXELS_API_KEY": ("background", "pexels_api_key"),
        "ELEVENLABS_API_KEY": ("tts", "elevenlabs_api_key"),
        "ELEVENLABS_VOICE_ID": ("tts", "elevenlabs_voice_id"),
    }
    for env_name, (section, key) in secret_map.items():
        if os.environ.get(env_name):
            data[section][key] = os.environ[env_name].strip()


def _apply_section_env_overrides(data: dict[str, Any]) -> None:
    sections = set(data.keys())
    for env_name, raw in os.environ.items():
        if "__" not in env_name:
            continue
        head, tail = env_name.split("__", 1)
        section = head.strip().lower()
        if section not in sections:
            continue
        parts = [part.strip().lower() for part in tail.split("__") if part.strip()]
        if not parts:
            continue
        current = data[section]
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                raise ValueError("unknown config key from env: %s" % env_name)
            current = current[part]
        leaf = parts[-1]
        if leaf not in current:
            raise ValueError("unknown config key from env: %s" % env_name)
        current[leaf] = _parse_env_value(raw)


def _build_config(data: dict[str, Any]) -> Config:
    app = data["app"]
    content = data["content"]
    tts = data["tts"]
    render = data["render"]
    background = data["background"]
    youtube = data["youtube"]

    return Config(
        app=AppConfig(
            channel_name=_expect_str(app, "channel_name", "app"),
            default_language=_expect_str(app, "default_language", "app"),
            shorts_target_seconds=_expect_int(app, "shorts_target_seconds", "app", minimum=1),
            output_dir=_expect_str(app, "output_dir", "app"),
            logs_dir=_expect_str(app, "logs_dir", "app"),
            queue_dir=_expect_str(app, "queue_dir", "app"),
            done_dir=_expect_str(app, "done_dir", "app"),
            failed_dir=_expect_str(app, "failed_dir", "app"),
            topics_file=_expect_str(app, "topics_file", "app"),
            topics_history_file=_expect_str(app, "topics_history_file", "app"),
            ffmpeg_bin=_expect_str(app, "ffmpeg_bin", "app"),
            ffprobe_bin=_expect_str(app, "ffprobe_bin", "app"),
        ),
        content=ContentConfig(
            openai_api_key=_expect_str(content, "openai_api_key", "content"),
            openai_model=_expect_str(content, "openai_model", "content"),
            openai_topic_model=_expect_str(content, "openai_topic_model", "content"),
            openai_base_url=_expect_str(content, "openai_base_url", "content"),
            openai_timeout_s=_expect_int(content, "openai_timeout_s", "content", minimum=1),
            openai_temperature=_expect_float(content, "openai_temperature", "content", minimum=0.0),
            openai_max_output_tokens=_expect_int(content, "openai_max_output_tokens", "content", minimum=1),
            openai_topic_temperature=_expect_float(content, "openai_topic_temperature", "content", minimum=0.0),
            openai_topic_max_output_tokens=_expect_int(content, "openai_topic_max_output_tokens", "content", minimum=1),
            openai_language=_expect_str(content, "openai_language", "content"),
            openai_transcribe_model=_expect_str(content, "openai_transcribe_model", "content"),
            openai_transcribe_timeout_s=_expect_int(content, "openai_transcribe_timeout_s", "content", minimum=1),
            openai_transcribe_language=_expect_str(content, "openai_transcribe_language", "content"),
        ),
        tts=TTSConfig(
            provider=_expect_str(tts, "provider", "tts"),
            voice=_expect_str(tts, "voice", "tts"),
            edge_rate=_expect_str(tts, "edge_rate", "tts"),
            edge_volume=_expect_str(tts, "edge_volume", "tts"),
            edge_pitch=_expect_str(tts, "edge_pitch", "tts"),
            edge_timeout_s=_expect_int(tts, "edge_timeout_s", "tts", minimum=1),
            edge_proxy=_expect_str(tts, "edge_proxy", "tts"),
            elevenlabs_api_key=_expect_str(tts, "elevenlabs_api_key", "tts"),
            elevenlabs_voice_id=_expect_str(tts, "elevenlabs_voice_id", "tts"),
        ),
        render=RenderConfig(
            top_bar_height=_expect_int(render, "top_bar_height", "render", minimum=0),
            bottom_bar_height=_expect_int(render, "bottom_bar_height", "render", minimum=0),
            font_file=_expect_str(render, "font_file", "render"),
            subtitle_fontsdir=_expect_str(render, "subtitle_fontsdir", "render"),
            subtitle_playres_y=_expect_int(render, "subtitle_playres_y", "render", minimum=1),
            subtitle_position=_expect_str(render, "subtitle_position", "render"),
            subtitle_font_size=_expect_int(render, "subtitle_font_size", "render", minimum=1),
            subtitle_outline=_expect_int(render, "subtitle_outline", "render", minimum=0),
            subtitle_margin_v=_expect_int(render, "subtitle_margin_v", "render"),
            subtitle_margin_top_v=_expect_int(render, "subtitle_margin_top_v", "render"),
            subtitle_margin_bottom_v=_expect_int(render, "subtitle_margin_bottom_v", "render"),
            subtitle_vshift=_expect_int(render, "subtitle_vshift", "render"),
            subtitle_sync_drift_tolerance=_expect_float(render, "subtitle_sync_drift_tolerance", "render", minimum=0.0),
            subtitle_sync_repair=_expect_bool(render, "subtitle_sync_repair", "render"),
            subtitle_sync_repair_max_drift=_expect_float(render, "subtitle_sync_repair_max_drift", "render", minimum=0.0),
            subtitle_sync_max_scale_delta=_expect_float(render, "subtitle_sync_max_scale_delta", "render", minimum=0.0),
            subtitle_align_openai=_expect_bool(render, "subtitle_align_openai", "render"),
            subtitle_align_edge=_expect_bool(render, "subtitle_align_edge", "render"),
            subtitle_text_source=_expect_str(render, "subtitle_text_source", "render"),
            subtitle_max_chars=_expect_int(render, "subtitle_max_chars", "render", minimum=1),
            subtitle_words_per_cue=_expect_int(render, "subtitle_words_per_cue", "render", minimum=1),
            subtitle_min_cue_s=_expect_float(render, "subtitle_min_cue_s", "render", minimum=0.0),
            subtitle_max_cue_s=_expect_float(render, "subtitle_max_cue_s", "render", minimum=0.0),
            video_preset=_expect_str(render, "video_preset", "render"),
            video_crf=_expect_int(render, "video_crf", "render", minimum=0),
            video_bitrate=_expect_str(render, "video_bitrate", "render"),
            audio_bitrate=_expect_str(render, "audio_bitrate", "render"),
            bgm_file=_expect_str(render, "bgm_file", "render"),
        ),
        background=BackgroundConfig(
            provider=_expect_str(background, "provider", "background"),
            local_video=_expect_str(background, "local_video", "background"),
            regenerate_local=_expect_bool(background, "regenerate_local", "background"),
            append_credit_to_description=_expect_bool(background, "append_credit_to_description", "background"),
            pexels_api_key=_expect_str(background, "pexels_api_key", "background"),
            pexels_query=_expect_str(background, "pexels_query", "background"),
            pexels_orientation=_expect_str(background, "pexels_orientation", "background"),
            pexels_per_page=_expect_int(background, "pexels_per_page", "background", minimum=1),
            pexels_min_height=_expect_int(background, "pexels_min_height", "background", minimum=1),
            pexels_clip_count=_expect_int(background, "pexels_clip_count", "background", minimum=1),
            pexels_cache_dir=_expect_str(background, "pexels_cache_dir", "background"),
            pexels_timeout_s=_expect_int(background, "pexels_timeout_s", "background", minimum=1),
            pexels_download_timeout_s=_expect_int(background, "pexels_download_timeout_s", "background", minimum=1),
        ),
        youtube=YouTubeConfig(
            client_secret_file=_expect_str(youtube, "client_secret_file", "youtube"),
            token_file=_expect_str(youtube, "token_file", "youtube"),
            category_id=_expect_str(youtube, "category_id", "youtube"),
            privacy_status=_expect_str(youtube, "privacy_status", "youtube"),
            idempotency_enabled=_expect_bool(youtube, "idempotency_enabled", "youtube"),
            upload_state_file=_expect_str(youtube, "upload_state_file", "youtube"),
            upload_max_attempts=_expect_int(youtube, "upload_max_attempts", "youtube", minimum=1),
            upload_timeout_s=_expect_float(youtube, "upload_timeout_s", "youtube", minimum=0.0),
            upload_initial_backoff_s=_expect_float(youtube, "upload_initial_backoff_s", "youtube", minimum=0.0),
            upload_max_backoff_s=_expect_float(youtube, "upload_max_backoff_s", "youtube", minimum=0.0),
            max_duration_s=_expect_float(youtube, "max_duration_s", "youtube", minimum=1.0),
            min_width=_expect_int(youtube, "min_width", "youtube", minimum=1),
            min_height=_expect_int(youtube, "min_height", "youtube", minimum=1),
            require_portrait=_expect_bool(youtube, "require_portrait", "youtube"),
            require_aspect_9_16=_expect_bool(youtube, "require_aspect_9_16", "youtube"),
            aspect_tolerance=_expect_float(youtube, "aspect_tolerance", "youtube", minimum=0.0),
        ),
    )


def _expect_str(data: dict[str, Any], key: str, section: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ValueError("config %s.%s must be a string" % (section, key))
    return value


def _expect_int(data: dict[str, Any], key: str, section: str, minimum: Optional[int] = None) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("config %s.%s must be an integer" % (section, key))
    if minimum is not None and value < minimum:
        raise ValueError("config %s.%s must be >= %s" % (section, key, minimum))
    return value


def _expect_float(data: dict[str, Any], key: str, section: str, minimum: Optional[float] = None) -> float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("config %s.%s must be numeric" % (section, key))
    result = float(value)
    if minimum is not None and result < minimum:
        raise ValueError("config %s.%s must be >= %s" % (section, key, minimum))
    return result


def _expect_bool(data: dict[str, Any], key: str, section: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise ValueError("config %s.%s must be a boolean" % (section, key))
    return value
