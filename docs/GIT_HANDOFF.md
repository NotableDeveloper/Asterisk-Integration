# 로컬 Git 초기화 및 커밋 기록

작성일: 2026-10-19 (Asia/Seoul)

사용자 요청에 따라 기존 작업을 로컬 Git 저장소의 main 브랜치에 단계별로 커밋했다. GitHub remote 추가나 push는 수행하지 않았다.

## 커밋 구분

1. `chore: initialize Docker and Asterisk runtime configuration` — Docker, Asterisk 설정, 모델 다운로드/샘플 준비/시작 스크립트, 제외 규칙.
2. `feat: add ARI RTP transcription pipeline and integration tests` — ARI 제어, RTP 처리, STT, HTTP/WebSocket, 단위·통합·모델 비교 테스트.
3. `feat: add transcript dashboard and SIP.js web softphone` — 자막 UI, SIP.js 소스와 실행 번들, npm lockfile, 라이브러리 라이선스.
4. `docs: record implementation progress and validation evidence` — README, 작업/운영/아키텍처/검증/소프트폰 문서, 원본 로그와 화면 증거, 본 기록.

기존 개발 내용을 파일 역할별로 분리한 커밋이며, 각 중간 커밋이 독립적으로 실행 가능한 릴리스라는 의미는 아니다. 전체 기능은 마지막 커밋 기준이다.

## 추적 제외

- models의 실제 모델 가중치와 다운로드 샘플. models/.gitkeep만 추적한다.
- asterisk/sounds/*.wav (준비 스크립트로 재생성).
- .venv, .venv-test, web/node_modules, Python 캐시, .DS_Store.
- .env 및 .env.* (향후 .env.example은 추적 허용).

문서의 로그·JSONL·화면 이미지는 작업 증거로 포함한다. 로그에 있는 로컬 경로·컨테이너 정보·공식 샘플 인식 결과는 원본 그대로 유지한다. 설정의 비밀번호는 기존 로컬 데모용 값이며 실제 서비스 자격 증명으로 사용하지 않는다.

## 확인

- 기존 Git 작성자 설정을 사용했다. 전역 Git 설정은 변경하지 않았다.
- 코드 staged diff 검사에서 STT 파일의 후행 공백 1곳을 제거했다. 실행 로직 변경 없음.
- 모델·가상환경·node_modules가 추적되지 않는지 최종 검사한다.
- 원본 테스트 증거는 보존했고, 커밋 정리만을 위해 서비스를 재시작하거나 테스트 통화를 다시 실행하지 않았다.

현재 이력과 작업 상태 확인:

```sh
git log --oneline --reverse
git status --short
git remote -v
```
