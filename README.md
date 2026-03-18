# YouTube Shorts 자동화

단일 진입점은 `python -m shorts` 입니다. 생성 파이프라인은 `주제 생성 -> 주제 평가 -> 스크립트 생성 -> 리뷰/재작성 -> 패키징 -> 렌더/큐 실행`으로 바뀌었습니다.

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
APP__DEFAULT_LANGUAGE=ko CONTENT__SERIES_NAME="AI 현상 해설" python -m shorts topics generate --config ENV --count 8
```

## 3) 내부 아티팩트와 큐

생성 단계 산출물은 기본적으로 `jobs/work/<run_id>/` 아래에 저장됩니다.

- `topic_pool.json`
- `selected_topic_01.json`
- `script_package_01.json`
- `reviewed_package_01.json`

`queue run`과 `render`는 계속 최종 `RenderJob`만 처리합니다.

`RenderJob` 예시:

```json
{
  "title": "AI.com이 다시 뜨는 이유",
  "script": "첫 문장 훅\n둘째 줄\n셋째 줄\n마지막 줄",
  "description": "영상 설명",
  "hashtags": "#shorts #AI #tech",
  "pexels_query": "artificial intelligence abstract technology"
}
```

## 4) 명령

토픽 풀 생성:

```bash
python -m shorts topics generate --config ENV --count 8
```

토픽 평가 및 선택:

```bash
python -m shorts topics evaluate --config ENV --topic-pool jobs/work/20260318_090000/topic_pool.json --count 1
```

선택된 토픽으로 스크립트 초안 생성:

```bash
python -m shorts scripts generate --config ENV --selected-topic jobs/work/20260318_090000/selected_topic_01.json
```

수동 토픽으로 바로 스크립트 생성:

```bash
python -m shorts scripts generate --config ENV --topic "AI.com 도메인이 다시 주목받는 이유"
```

스크립트 리뷰 및 1회 자동 재작성:

```bash
python -m shorts scripts review --config ENV --script-package jobs/work/20260318_090000/script_package_01.json
```

리뷰 통과본을 큐용 렌더 잡으로 패키징:

```bash
python -m shorts jobs package --config ENV --reviewed-package jobs/work/20260318_090000/reviewed_package_01.json
```

단일 렌더:

```bash
python -m shorts render --config ENV --job jobs/queue/2026-03-18_ai-com_01.json --no-upload
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

- `render`와 `queue run`은 단일 행 `RESULT ...`를 유지합니다.
- 생성 단계 명령도 성공 시 단일 행 `RESULT status=ok ...`를 출력합니다.
- 실패 시 traceback 대신 `ERROR ...`와 `RESULT status=error ...`를 출력합니다.
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
- `jobs/work`

## 7) 스케줄링

Linux/WSL cron:

```bash
scripts/install_crontab.sh 09:00
```

Windows Task Scheduler:

```powershell
powershell -ExecutionPolicy Bypass -File .\\scripts\\windows_create_task.ps1 -TaskName "shorts-daily" -Time "09:00"
```
