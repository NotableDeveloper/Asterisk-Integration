# Fast Contact Router

가전제품 고객센터의 문의를 로컬 STT와 Jev로 분류하고 전문 상담사에게 연결하는 프로젝트입니다.

현재는 Asterisk와 단일 Whisper 모델의 로컬 실행 환경 및 파일 전사 API를 제공합니다. 전화 녹음의 자동 전달, Jev 분류와 상담사 배정은 후속 구현 대상입니다.

## 실행

Docker와 Compose가 필요합니다. GPU 없이 Whisper small을 CPU INT8로 실행합니다.

```sh
python3 scripts/init_env.py
docker compose up -d --build
docker compose ps
```

첫 기동 때 고정 revision의 모델을 다운로드하여 named volume에 보관합니다. `.env`의 무작위 ARI/SIP 비밀번호는 Git에서 제외합니다. 서비스 포트는 이 컴퓨터의 loopback에만 공개합니다.

- Whisper: `http://127.0.0.1:8000`, API 문서는 `/docs`.
- Asterisk ARI: `http://127.0.0.1:8088/ari`, 사용자 `router`, 비밀번호는 `.env`의 ARI_PASSWORD.
- SIP: `127.0.0.1:5060/UDP`, 사용자 `1001`, 비밀번호는 `.env`의 SIP_PASSWORD.
- RTP: `127.0.0.1:10000–10019/UDP`.

SIP 단말에서 `600`을 누르면 에코 시험을 할 수 있습니다. `7000`은 향후 제어 앱의 진입점입니다.

## 전사 및 확인

전사 API는 한국어 16-bit PCM WAV(mono/stereo, 8–48kHz, 최대 120초·16MiB)를 받습니다. 별도 VAD 모델 없이 단일 모델로 전사하고, 처리 중 추가 요청은 429로 거절합니다.

```sh
curl --fail http://127.0.0.1:8000/health
curl --fail -X POST http://127.0.0.1:8000/transcribe \
  -H 'Content-Type: audio/wav' --data-binary @/absolute/path/inquiry.wav
python3 scripts/smoke_test.py --audio /absolute/path/inquiry.wav
docker compose exec whisper python -m unittest discover -s tests -v
```

`docker compose stop`으로 정지하고 `docker compose down`으로 컨테이너를 제거할 수 있습니다. `down -v`는 모델 캐시와 Asterisk 영속 데이터도 삭제합니다.
