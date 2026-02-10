# 산출물 검증 체크리스트 (영상/자막/메타데이터)

목표: `output/*.mp4`를 업로드(또는 수동 게시)하기 전에, 실패를 초기에 잡고 재실행을 안전하게 만든다.

## 1) 실행/로그 빠른 확인

- 콘솔 마지막에 `RESULT status=...` 라인이 찍혔는가
- 같은 실행에서 `SUMMARY {...}` 단일 라인이 찍혔는가
- 로그 파일을 남겼는가 (추천):

```bash
NO_UPLOAD=1 python -u run_short.py --config config.json --job jobs/today.json 2>&1 | tee logs/run_$(date +%Y%m%d_%H%M%S).log
```

## 2) 파일 존재/경로

- `output/`(또는 `config.json`의 `output_dir`) 아래에 아래 파일이 생성됐는가
- `output/YYYYMMDD_HHMMSS.mp4`
- `output/YYYYMMDD_HHMMSS.mp3`
- `output/YYYYMMDD_HHMMSS.srt`
- (Pexels 사용 시) `output/YYYYMMDD_HHMMSS.credits.txt`

## 3) 영상 기본 스펙

추천 확인 커맨드:

```bash
ffprobe -hide_banner -v error \
  -show_entries stream=codec_type,width,height,avg_frame_rate,bit_rate \
  -show_entries format=duration,size \
  -of json \
  output/YOUR_FILE.mp4
```

- 세로(9:16)인지: 보통 `width < height` (예: 1080x1920)
- 오디오 스트림이 있는지: `codec_type=audio` 존재
- 길이: 60초 이하(Shorts 기준), 내부 목표는 25~35초
- 지나치게 작은 해상도/비트레이트가 아닌지

## 4) 자막(하드서브) 가시성

- 자막이 실제로 영상에 보이는지 (검은 화면/폰트 미탐지로 누락되는 케이스가 가장 흔함)
- 자막이 너무 작거나 너무 아래로 내려가서 UI에 가리지 않는지
- 줄바꿈이 과하게 깨지지 않는지 (한 줄이 너무 길거나, 1~2글자만 남는 줄이 반복되지 않는지)
- 제목 상단 바와 자막 하단 바가 서로 겹치지 않는지

WSL에서 한글 폰트가 안 잡히면 자막이 안 보일 수 있다.
- 기본 동작: `font_file`의 폴더를 `subtitles`에 `fontsdir`로 지정
- 필요하면 `config.json`에 `subtitle_fontsdir` 지정

## 5) 메타데이터(업로드/게시)

- 제목:
  - 거짓/과장 클릭베이트가 아닌지
  - 첫 30자에 훅이 있는지
  - 너무 길지 않은지(권장 28자 내외)
- 해시태그:
  - `#shorts` 포함
  - 3~5개 수준으로 과하지 않게
- 설명(description):
  - 링크/크레딧(필요 시) 포함
  - (Pexels 사용 시) 크레딧이 자동 추가됐는지

## 6) 업로드 전 자동 체크(가드레일)

이 프로젝트는 업로드 직전에 자동 체크를 수행한다(제목/해시태그/세로비율/오디오/길이 등).
체크를 강화/조정하려면 `config.json`의 `youtube.*` 제한값을 확인/수정한다.

