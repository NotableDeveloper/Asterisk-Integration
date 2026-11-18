# Fast Contact Router

가전제품 고객센터의 인바운드 전화를 고객 문의와 상담사의 전문 분야에 맞춰 연결하는 시스템입니다.

고객의 초기 문의를 Asterisk에서 녹음하고, 로컬 CPU의 단일 STT 모델로 전사합니다. Jev가 제품과 문의 유형을 분류하면 서버가 짧은 문장을 만들고, 해당 스킬을 가진 대기 상담사를 예약해 연결합니다.

- 작업 브랜치: `codex/fast-contact-router`
- 현재 단계: Asterisk·단일 Whisper 모델·웹 소프트폰의 로컬 Compose 실행 환경. Jev와 자동 배정은 설계 단계입니다.

이 설계는 이전 STT 실험 코드를 전제로 하지 않습니다.

## 로컬 실행

Docker Desktop 또는 Docker Engine과 Compose가 필요합니다. ARM64/AMD64 네이티브 이미지를 사용하며 GPU는 필요하지 않습니다.

```sh
python3 scripts/init_env.py
docker compose up -d --build
docker compose ps
docker compose logs -f whisper
```

처음 시작하면 고정한 revision의 다국어 Whisper small을 다운로드합니다. 모델 로드가 끝나야 Whisper가 healthy가 됩니다. 캐시는 `whisper_models` named volume에 보존되며, 기존 `models/`의 다른 모델들은 사용하지 않습니다. 재시작 때도 캐시 확인을 위한 네트워크 접근이 있을 수 있습니다.

`.env`에는 무작위 ARI/SIP 비밀번호가 생성됩니다. 초기화 스크립트는 기존 파일을 덮어쓰지 않습니다. 비밀번호와 `.env`는 Git에 포함하지 않습니다.

| 서비스 | 로컬 주소 | 확인 |
| --- | --- | --- |
| 웹 소프트폰 | http://localhost:8080 | 브라우저 전화기 연결·문의 안내·에코 통화 |
| Whisper | http://127.0.0.1:8000 | `GET /health`, `POST /transcribe`, `/docs` |
| Asterisk ARI | http://127.0.0.1:8088/ari | 사용자 `router`, 비밀번호는 `.env`의 ARI_PASSWORD |
| SIP | 127.0.0.1:5060 / UDP | 사용자·인증 ID `1001`, 비밀번호는 `.env`의 SIP_PASSWORD |
| RTP | 127.0.0.1:10000–10019 / UDP | 로컬 음성 시험용 |

포트와 SIP의 광고 주소는 이 컴퓨터에서 사용하는 설정입니다. LAN 단말·외부 trunk를 연결하려면 바인딩, 광고 주소, 방화벽과 인증을 함께 조정해야 합니다.

## 웹 소프트폰으로 시험하기

1. 이 컴퓨터의 Chrome에서 [웹 소프트폰](http://localhost:8080)을 엽니다. `http://127.0.0.1:8080`도 사용할 수 있습니다.
2. **전화기 연결**을 누릅니다. 내선 `1002`가 자동 등록되며 비밀번호를 직접 입력할 필요가 없습니다.
3. **에코 테스트**를 누르고 브라우저의 마이크 권한을 허용합니다. 자기 목소리가 되돌아오는지 확인하고 **통화 종료**를 누릅니다. 헤드셋을 권장합니다.
4. **문의 안내 테스트**를 누르고 최초 안내가 끝난 후 말합니다. 말을 마치고 3초 동안 조용히 있으면 두 번째 안내를 듣습니다. **마이크 끄기** 버튼으로 무음을 시험할 수도 있습니다.

마이크 입력 표시, 수신 음량, 통화 시간, 로컬 상태 기록을 제공합니다. 등록이나 마이크 접근이 실패하면 화면에서 다시 시도할 수 있습니다. 두 번째 안내가 끝나면 통화가 종료되는 현재 서버 동작도 화면에서 설명합니다.

프런트엔드는 SIP.js 0.21.2를 번들하여 외부 CDN 없이 제공합니다. Nginx가 동일 출처 `/ws`를 Asterisk에 전달하고, WebRTC의 DTLS-SRTP로 음성을 주고받습니다. 로컬 HTTP/WS 구성은 localhost의 마이크 사용을 전제로 하며 외부 공개용 HTTPS/WSS 배포는 아닙니다. Docker 내부 ICE 주소를 호스트의 `127.0.0.1`로 광고하며 기존 UDP 내선 `1001`도 유지합니다.

개발용 SIP 인증정보는 런타임의 `/config.json`에서 브라우저 메모리로 전달합니다. 저장소·번들·localStorage에 비밀번호를 넣지 않습니다. 서비스는 loopback에만 공개하고 허용 Host/Origin을 제한하며 설정 응답을 캐시하지 않습니다. 다른 호스트로 공개하려면 이 자동 로그인 방식을 먼저 변경해야 합니다. WebRTC 내선은 `.env`의 SIP_PASSWORD를 사용하며 한 화면에서 한 통화를 지원합니다. 탭을 닫을 때 연결 해제를 시도하고 비정상 종료 시 Asterisk의 RTP 무수신 제한(30초)이 남은 통화를 정리합니다.

웹 소프트폰 수정 후에는 `docker compose up -d --build webphone`을 실행합니다. 개발 검증에는 Node.js와 Chrome이 필요합니다.

```sh
cd webphone
npm ci
npm run build
npm test
```

브라우저 시험은 가상 마이크를 사용하여 실제 Asterisk SIP 등록·양방향 에코 음성·음소거·종료·문의 안내 후 종료·마이크 거부·발신 취소·모바일 화면·로컬 접근 제한을 확인합니다. 실제 마이크와 스피커의 동작은 위 수동 시험으로 확인합니다.

## API 및 SIP 단말 시험

```sh
curl --fail http://127.0.0.1:8000/health
curl --fail -X POST http://127.0.0.1:8000/transcribe \
  -H 'Content-Type: audio/wav' --data-binary @/absolute/path/inquiry.wav
docker compose exec asterisk asterisk -rx 'core show version'
docker compose exec asterisk asterisk -rx 'pjsip show endpoints'
python3 scripts/smoke_test.py --audio /absolute/path/inquiry.wav
docker compose exec whisper python -m unittest discover -s tests -v
```

전사 API는 한국어를 고정하고 **16-bit PCM WAV, mono/stereo, 8–48kHz, 최대 120초·16MiB**를 받습니다. 응답은 `text`, `language`, `audio_seconds`, `processing_seconds`입니다. 단일 모델을 상주 로드하고 추론 중 다른 전사 요청은 429로 거절합니다. 별도 VAD 모델은 실행하지 않습니다. 업로드 음성은 메모리에서 처리하며 서비스가 파일로 보관하지 않습니다.

SIP softphone을 등록하고 `600`을 누르면 Echo 시험을 할 수 있습니다. `7000`을 누르면 아래 문의 안내 흐름을 실행합니다.

1. 응답 후 “안녕하세요. 무엇을 도와드릴까요? 상담이 가능한 항목은 '세탁기', '청소기', '에어컨' 입니다.” 재생.
2. 고객의 첫 발화를 기다립니다. 최초부터 조용하다는 이유로 연결 멘트를 재생하지 않습니다.
3. 첫 발화 감지 후 연속 3초 무음이면 “고객님의 문의 내용을 바탕으로 상담사를 연결해드리겠습니다. 잠시만 기다려주세요.” 재생. 3초 미만의 쉼 뒤 다시 말하면 무음 시간이 다시 계산됩니다. `#` 입력은 필요하지 않습니다.
4. 이후 `Stasis(fast-contact-router,inbound)`로 넘깁니다. **현재는 제어 앱이 없어 두 번째 멘트 후 통화가 종료됩니다. 실제 상담사 연결은 아직 수행하지 않습니다.**

첫 발화 대기는 최대 30초이며, 첫 발화 이후 120초 동안 연속 3초 무음이 없으면 미완료로 종료합니다. 이런 시간 초과에는 연결 멘트를 재생하지 않습니다. 최초 멘트 재생 중 끼어들기는 지원하지 않습니다. 음성 감지는 Asterisk의 기본 DSP로 처리하므로 배경 소음도 발화로 감지될 수 있습니다.

두 음원은 `asterisk/sounds/*.wav`에 포함되어 있어 컨테이너에서 TTS를 실행하지 않습니다. 원문은 같은 폴더의 `.txt` 파일에 있습니다. macOS의 Yuna와 FFmpeg로 재생성하려면 `python3 scripts/generate_prompts.py`를 실행한 뒤 Asterisk 이미지를 다시 빌드합니다.

```sh
# Test dependencies only; these are not installed in the runtime containers.
python3 -m pip install -r scripts/requirements-test.txt
python3 scripts/test_prompt_flow.py
```

위 시험은 실제 Asterisk Local 채널에 합성 음성을 넣어 멘트 재생, 첫 발화 전 무음, 2초 중간 쉼, 마지막 발화 후 3초 무음, 무발화 종료를 확인합니다. SIP 단말과 실제 전화 잡음에 대한 시험은 별도로 필요합니다.

**자동 녹음→Whisper 전달, Jev 분류, 상담사 배정은 아직 구현하지 않았습니다.** 현재 멘트와 무음 감지는 실행되며 Whisper는 파일 전사 API로 사용할 수 있습니다.

```sh
docker compose stop         # 컨테이너 정지, 모델 캐시 유지
docker compose down         # 컨테이너·네트워크 제거, volume 유지
```

`docker compose down -v`는 모델 캐시와 Asterisk의 영속 데이터를 삭제합니다.

## 기동 검증 기록

2026-11-18, ARM64 Docker Desktop 환경에서 Asterisk 20.6.0과 Whisper small CPU INT8의 healthy 상태 및 ARI 인증 응답을 확인했습니다. 기존 한국어 테스트 WAV(4.608초)의 첫 전사는 1.244초가 걸렸습니다. 이는 기동 확인용 단일 샘플이며 한국어 고객센터 정확도·동시 통화 성능의 평가 결과는 아닙니다.
