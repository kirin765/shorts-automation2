# 자막 줄바꿈 개선 샘플 (전/후)

기준: `split_for_captions()` (전) vs `split_for_captions_dense()` (후)

## 샘플 1 (한국어, 빠른 템포)

입력:
```
오늘은 AI.com 도메인이 왜 다시 주목받는지 이야기해볼게요. 그런데 핵심은 단순합니다. 그래서 결론부터 말하면, 브랜드와 기억이 전부예요.
```

전(`split_for_captions`):
```
오늘은 AI.com 도메인이 왜 다시 주목받는지 이야기해볼게요.
그런데 핵심은 단순합니다.
그래서 결론부터 말하면, 브랜드와 기억이 전부예요.
```

후(`split_for_captions_dense`):
```
오늘은 AI.com 도메인이 왜
다시 주목받는지
이야기해볼게요.
그런데 핵심은 단순합니다.
그래서 결론부터 말하면
브랜드와 기억이 전부예요.
```

## 샘플 2 (영문, 쉼표/세미콜론)

입력:
```
This is the punchline, keep it short; split on pauses, and avoid long lines on mobile.
```

전(`split_for_captions`):
```
This is the punchline, keep it short; split on pauses, and avoid long lines on mobile.
```

후(`split_for_captions_dense`):
```
This is the punchline
keep it short
split on pauses
and avoid long lines
on mobile.
```

