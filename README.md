# YouTube Shorts 자동화

단일 진입점은 `python -m shorts` 입니다. 예전 `run_short.py` 및 운영 셸 스크립트는 제거되었습니다.

## 1) 설치

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

필수 외부 도구:

- `ffmpeg`
- `ffprobe`

## 2) 설정

- 기본값은 코드에 내장되어 있습니다.
- 선택적으로 `config.example.json`을 복사해 사용자 설정 파일로 쓸 수 있습니다.
- 로딩 순서: `코드 기본값 -> 선택적 JSON 파일 -> 환경변수`
- 환경변수 오버라이드는 `SECTION__KEY=value` 형식입니다.
- 예외적 비밀값 환경변수:
  - `OPENAI_API_KEY`
  - `PEXELS_API_KEY`
  - `ELEVENLABS_API_KEY`
  - `ELEVENLABS_VOICE_ID`

예:

```bash
APP__DEFAULT_LANGUAGE=ko RENDER__SUBTITLE_FONT_SIZE=96 python -m shorts render --config ENV --job jobs/today.json --no-upload
```

## 3) 잡 스키마

`DraftJob`:

```json
{
  "topic": "AI.com 도메인이 다시 주목받는 이유",
  "style": "테크 뉴스",
  "tone": "빠르고 자신있게",
  "target_seconds": 28
}
```

`RenderJob`:

```json
{
  "title": "AI.com이 다시 뜨는 이유",
  "script": "첫 문장 훅. 이어서 5~7문장.",
  "description": "영상 설명",
  "hashtags": "#shorts #AI #tech",
  "pexels_query": "artificial intelligence abstract technology"
}
```

`queue run`은 `RenderJob`만 처리합니다.

## 4) 명령

토픽 생성:

```bash
python -m shorts topics generate --config ENV --count 10
```

토픽/드래프트를 렌더 잡으로 변환:

```bash
python -m shorts jobs draft --config ENV --topic "AI.com 도메인이 다시 주목받는 이유"
python -m shorts jobs draft --config ENV --topics-file jobs/topics.txt --count 3
```

단일 렌더:

```bash
python -m shorts render --config ENV --job jobs/today.json --no-upload
```

큐 실행:

```bash
python -m shorts queue run --config ENV --queue-dir jobs/queue --no-upload
```

일일 파이프라인:

```bash
python -m shorts pipeline daily --config ENV --count 1 --no-upload
```

## 5) 출력 계약

- 성공/실패와 무관하게 단일 행 `SUMMARY {...}` 출력
- 성공/실패와 무관하게 단일 행 `RESULT ...` 출력
- 기본 동작은 traceback 비노출
- `render --traceback`으로만 traceback 출력

## 6) 산출물

- 기본 출력 디렉터리: `output/`
- 렌더 결과:
  - `output/YYYYMMDD_HHMMSS.mp3`
  - `output/YYYYMMDD_HHMMSS.srt`
  - `output/YYYYMMDD_HHMMSS.mp4`
  - `output/YYYYMMDD_HHMMSS.credits.txt` (Pexels 사용 시)

큐 관련 기본 디렉터리:

- `jobs/queue`
- `jobs/done`
- `jobs/failed`

## 7) 스케줄링

Linux/WSL cron:

```bash
scripts/install_crontab.sh 09:00
```

Windows Task Scheduler:

```powershell
powershell -ExecutionPolicy Bypass -File .\\scripts\\windows_create_task.ps1 -TaskName "shorts-daily" -Time "09:00"
```
