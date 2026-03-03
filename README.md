# YouTube Shorts 자동화 (편집 + 업로드)

## 1) 준비
Linux/WSL:
```bash
cd shorts
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Python 기준 버전:
- 로컬/CI 검증 기준은 **Python 3.9** 입니다.
- 테스트 실행: `python3 -m pytest -q`

### 설정 파일(config.json) 운영 가이드

- `config.json`은 **선택**입니다. 이제 이 프로젝트는 `config.json` 없이도 실행됩니다(`--config ENV` 기본값).
- 기본 설정은 `config.example.json`을 사용하고, 민감한 값(API 키 등)은 `.env`(환경변수)로 넣는 것을 권장합니다.
- `config.json`을 쓰는 경우 gitignore 대상이라 **커밋/푸시 금지**입니다.
- OAuth 파일도 로컬 전용:
  - `secrets/client_secret.json`
  - `secrets/token.json`

한 번에 셋업:
```bash
./scripts/setup_linux.sh
```

## 0) ffmpeg/ffprobe
이 프로젝트는 렌더에 `ffmpeg`, 길이 측정에 `ffprobe`가 필요합니다.
- PATH에 잡혀있으면 자동 사용
- PATH에 없으면 `config.json`에 `ffmpeg_bin`, `ffprobe_bin`로 절대경로 지정

## 자막(Subtitle) 주의
이 프로젝트는 `.srt` 파일을 유튜브에 따로 업로드하지 않고, 렌더링 단계에서 자막을 영상에 **하드서브(덮어씌움)** 합니다.

- WSL 환경에서는 `ffmpeg`의 `subtitles`(libass)가 한글 폰트를 못 찾으면 자막이 안 보일 수 있습니다.
- 기본 동작: `font_file`로 선택된 폰트의 폴더를 `subtitles`에 `fontsdir`로 자동 지정합니다.
- 필요하면 `config.json`에 `subtitle_fontsdir`를 직접 지정하세요. 예: `/mnt/c/Windows/Fonts`

## 2) 유튜브 API 연결
1. Google Cloud Console에서 YouTube Data API v3 활성화
2. OAuth Client(Desktop App) 생성
3. `shorts/secrets/client_secret.json` 저장

첫 업로드 시 브라우저 인증이 뜨고 `token.json`이 자동 저장됨.

## 3) 잡 파일 작성
`jobs/today.json` 예시:
```json
{
  "title": "제목",
  "script": "나레이션 원문",
  "description": "영상 설명",
  "hashtags": "#shorts #AI"
}
```

대본 자동 생성(OpenAI) 예시(최소):
```json
{
  "topic": "AI.com 도메인이 왜 다시 주목받는지",
  "style": "테크 뉴스",
  "tone": "빠르고 자신있게",
  "target_seconds": 28
}
```

## 4) 실행
렌더만:
```bash
python run_short.py --config ENV --job jobs/today.json --no-upload
```

내일 운영용 원커맨드(토픽 생성 + 실행 + 로그 저장):
```bash
./scripts/run_once.sh --count 1
```

업로드 없이(검수용):
```bash
NO_UPLOAD=1 ./scripts/run_once.sh --count 1
```

NO_UPLOAD 환경변수로 업로드 스킵(원커맨드):
```bash
NO_UPLOAD=1 python -u run_short.py --config ENV --job jobs/today.json 2>&1 | tee logs/run_$(date +%Y%m%d_%H%M%S).log
```

산출물 위치:
- 기본 출력 폴더: `output/` (또는 `config.json`의 `output_dir`)
- 파일명 규칙: `output/YYYYMMDD_HHMMSS.{mp3,srt,mp4}` (+ Pexels 사용 시 `.credits.txt`)
- 콘솔 요약 라인: `SUMMARY {...}` / `RESULT status=... elapsed_s=... video=... upload=...`

산출물 검증 체크리스트(영상/자막/메타데이터): `notes/verification_checklist.md`

렌더 + 업로드:
```bash
python run_short.py --config ENV --job jobs/today.json
```

업로드 재시도/타임아웃(선택):
- `config.json`의 `youtube.upload_max_attempts` (기본 5)
- `config.json`의 `youtube.upload_timeout_s` (기본 900초)
- `config.json`의 `youtube.upload_initial_backoff_s` (기본 2초)
- `config.json`의 `youtube.upload_max_backoff_s` (기본 30초)

중복 업로드 방지(아이템포턴시, 권장):
- 기본 동작: 같은 `--job` 파일이 이미 업로드된 기록이 있으면 업로드를 스킵합니다.
- 상태 파일: `config.json`의 `youtube.upload_state_file` (기본 `logs/uploads.jsonl`)
- 강제로 다시 업로드하려면: `python run_short.py ... --force-upload`

## 완전 자동화(큐/데일리)
토픽만 넣고 여러 개를 한 번에 돌리려면 큐 방식이 가장 단순합니다.

1) 큐 실행(폴더 내 *.json 순회):
```bash
scripts/run_queue.sh --config ENV --queue-dir jobs/queue
```

2) 토픽을 큐에 넣고 바로 실행:
```bash
python scripts/run_daily.py --config ENV --topics-file jobs/topics.txt --count 3 --no-upload
```

`jobs/topics.txt`는 "한 줄 = 토픽" 형식입니다.
생성된 잡 파일은 `jobs/queue/`에 쌓이고, 성공하면 `jobs/done/`, 실패하면 `jobs/failed/`로 이동합니다.
로그는 `logs/`에 저장됩니다.

## 토픽 자동 생성(OpenAI)
아침마다 토픽을 자동 생성해서 `jobs/topics.txt`에 저장할 수 있습니다:
```bash
python3 scripts/generate_topics.py --config ENV --out jobs/topics.txt --count 10
```
생성된 토픽은 `jobs/topics_history.txt`에 누적되어 중복을 최대한 피합니다.

## 스케줄러(Windows/WSL)
가장 안정적인 방법은 Windows 작업 스케줄러에서 WSL을 호출하는 방식입니다.

1) Windows Task Scheduler 등록(권장)
PowerShell에서:
```powershell
powershell -ExecutionPolicy Bypass -File .\\scripts\\windows_create_task.ps1 -TaskName "shorts-daily" -Time "09:00"
```
이 작업은 WSL에서 `scripts/run_scheduled.sh`를 실행합니다.

2) WSL cron 등록(선택)
```bash
scripts/install_crontab.sh 09:00
```
WSL 환경에 따라 cron이 기본으로 돌지 않을 수 있으니, 그 경우 systemd/cron 활성화가 필요합니다.

## 폴더 구조
- `assets/background.mp4` : 배경 영상(없으면 자동 생성)
- `assets/fonts/NotoSansKR-Bold.ttf` : 폰트(선택)
- `output/*.mp4` : 결과물
- `secrets/client_secret.json`, `secrets/token.json` : 업로드 인증

## Pexels 배경 영상(선택)
주제에 맞는 배경 영상을 Pexels에서 자동으로 내려받아 사용 가능합니다.
- `config.json`에서 `"background_provider": "pexels"` 설정
- API 키는 `pexels_api_key` 또는 환경변수 `PEXELS_API_KEY`
- 잡 파일에 `"pexels_query": "검색 키워드"`를 넣으면 해당 키워드를 우선 사용

Pexels 배경을 쓰면 렌더 시 `output/YYYYMMDD_HHMMSS.credits.txt`가 같이 생성되며,
업로드 시(기본값) 영상 설명에 크레딧이 자동으로 추가됩니다.

## 운영 팁
- `privacy_status`를 `private`로 시작하고 검수 후 공개 추천
- 제목 첫 30자에 강한 훅 넣기
- 해시태그는 3~5개로 유지

## 레이아웃/자막 커스터마이즈
- `top_bar_height`, `bottom_bar_height`로 상/하단 검은바 높이 조절
- 상단 제목은 자동으로 고정 표시됨(잡 파일의 `title` 사용)
- 자막 위치는 `subtitle_align`로 제어: `bottom`(기본), `center`, `top`
- `subtitle_vshift`(px)로 가운데/상단 정렬 시 수직 오프셋 미세 조정(음수면 위로 이동)
- `subtitle_font_size`, `subtitle_outline`, `subtitle_margin_v`로 자막 가독성 조정

## 영상 퀄리티
- `video_preset`: `ultrafast|superfast|veryfast|faster|fast|medium|slow|slower|veryslow`
- `video_crf`: 17~28 권장(낮을수록 화질 좋음)
- `video_bitrate`: 필요 시 고정 비트레이트 지정(예: `4500k`, 비워두면 CRF만 사용)
- `audio_bitrate`: 예: `192k`, `256k`
- 기본값은 `config.example.json` 참고

## TTS 자연스럽게(추천)
- 기본은 `tts_provider: edge` (무료/빠름)
- 더 자연스럽게는 `tts_provider: elevenlabs` + `elevenlabs_api_key`, `elevenlabs_voice_id` 설정
  - 보안을 위해 키는 환경변수(`ELEVENLABS_API_KEY`)로 넣는 것도 가능

## 대본 자동 생성(OpenAI)
- `jobs/*.json`에 `title/script/description/hashtags/pexels_query`가 없으면 OpenAI로 자동 생성합니다.
- API 키는 `config.json`의 `openai_api_key` 또는 환경변수 `OPENAI_API_KEY`
- 끄려면 `--no-llm`

## CI (GitHub Actions)

- `main` 푸시 / PR 시 `pytest`를 자동 실행합니다.
- 렌더/업로드(E2E)는 포함하지 않고, 순수 유닛 테스트만 돌립니다.
