# JavaScript 웹 소프트폰

## 사용 방법

1. 같은 Mac에서 http://localhost:8000 을 연다. Chrome/Edge 등 WebRTC와 마이크를 지원하는 브라우저를 권장한다.
2. 화면이 열리면 SIP가 자동 등록된다. `SIP 등록 완료 · 내선 1003`이 표시되면 등록 성공이다. 실패 시 서버의 SIP 계정 설정을 확인한 후 화면을 새로고침한다.
3. **통화 시작**을 누른다.
   - **9998 · 마이크 음성 → STT**: 마이크 권한을 허용하고 말하면 아래 대화록에 중간·최종 자막이 나온다. 자신의 목소리를 되돌려 들려주는 에코 서비스는 아니다.
4. **통화 종료**를 누른다. 사용을 마치면 탭을 닫는다.

연결 정보는 화면에 상시 표시되며 서버 상태는 10초마다 갱신된다. 마이크 정보에는 권한, 기본 입력 장치와 실제 통화에 사용 중인 입력 트랙의 장치 이름·상태가 표시된다. 권한 허용 전에는 브라우저가 장치 이름을 숨길 수 있다. 페이지 로딩 시 마이크를 켜지 않고 통화 시작 시에만 사용한다. 활성 트랙 표시는 음량이나 STT 인식 성공을 보장하지 않는다.

브라우저 자동 재생이 차단되면 소프트폰 아래 오디오 재생 버튼을 누른다. 마이크 권한이 거절되면 브라우저의 localhost 사이트 권한에서 마이크를 허용한 뒤 다시 발신한다. 앱 내 브라우저가 마이크를 지원하지 않으면 일반 브라우저에서 같은 주소를 연다.

기본 데모 계정은 `1003 / demo-web-1003`이다. 기본 비밀번호는 웹 소프트폰 코드에 포함되며 설정 화면은 제공하지 않는다. 계정을 변경할 때는 서버 설정과 `web/src/phone.js`를 일치시키고 번들을 다시 빌드한다. 단일 등록/단일 통화를 대상으로 하므로 여러 탭에서 같은 내선을 동시에 등록하지 않는다.

## 구현 범위

- JavaScript SIP.js 0.21.2: SIP REGISTER / Digest 인증 / INVITE / BYE, 마이크 입력, 수신 오디오 재생.
- `web/src/phone.js`: 사람이 수정하는 소스.
- `stt-server/static/phone.js`: esbuild로 생성한 실행 번들. CDN 접근 없이 제공된다.
- `web/package-lock.json`: 프런트엔드 의존성 고정.
- `stt-server/static/vendor/SIP.js-LICENSE.md`: 라이브러리 라이선스.
- 발신 대상은 마이크 STT 내선 9998로 제한한다. 수신·전환·보류·연락처·녹음 기능은 제공하지 않는다.

## 연결 구조

```text
Browser SIP.js ── ws://localhost:8000/sip ── FastAPI relay ── Asterisk :8088/ws
Browser WebRTC ── ICE + DTLS-SRTP / PCMU ── Docker UDP 12000–12020 ── Asterisk
                                                                     │
                                                        RX snoop (9998)
                                                                     │
                                              ExternalMedia → STT → /ws 자막
```

`/sip`는 SIP 하위 프로토콜과 동일 Origin만 허용한다. 기존 `/ws`는 자막 이벤트용으로 유지한다. Asterisk HTTP/ARI 포트를 호스트에 추가 노출하지 않는다.

Asterisk의 `transport-ws`와 WebRTC 전용 PJSIP endpoint 1003을 추가했다. `webrtc=yes`, `dtls_auto_generate_cert=yes`, `ulaw`, `direct_media=no`를 사용한다. 구형 `chan_sip`이 WebSocket의 `sip` 프로토콜을 선점하지 않도록 modules.conf에서 로드를 막았다.

9998의 Stasis 인수는 `microphone`이다. ARI가 고객 RX를 snoop하고 silence generator로 미디어 흐름을 유지한다.

## 로컬 네트워크 전제

HTTP localhost는 브라우저가 마이크를 허용하는 secure context이다. 로컬 데모의 SIP 신호는 WS이고 미디어는 DTLS-SRTP로 암호화된다. 일반 LAN HTTP 주소에서는 마이크가 차단될 수 있다. 외부 사용은 HTTPS/WSS와 올바른 ICE/TURN/NAT 설정이 별도로 필요하다.

Asterisk entrypoint가 컨테이너 IP를 찾아 ICE 후보를 `127.0.0.1`로 매핑한다. 호스트와 컨테이너의 RTP 포트 번호는 동일하게 유지한다. 다른 호스트에서 접속하는 구성은 이번 검증 대상이 아니다. 변경 시 Compose의 Asterisk environment에 `WEBRTC_MEDIA_ADDRESS`를 지정하고 포트 바인딩과 HTTPS 설정도 함께 조정해야 한다.

## 빌드 및 실행

### 마이크 입력 진단 로그

STT 서버는 통화별로 1초마다 `STT_AUDIO` 로그를 출력하고 종료 시 남은 구간도 출력한다.
PCMU 디코딩 및 손실 구간 무음 보충 후, `Pipeline.feed`에 전달하는 8 kHz PCM을 측정한다.
원본 음성이나 대화 내용은 기록하지 않는다.

```sh
docker compose logs -f --timestamps stt | rg STT_AUDIO
```

- `call_id`, `speaker`, `port`: 통화·화자·수신 UDP 포트.
- `packets`, `malformed`, `late`, `lost`, `overflow`: 해당 로그 구간의 RTP 수신·오류·손실·큐 초과 건수.
- `input_samples`, `input_seconds`: 해당 구간에 파이프라인으로 전달한 샘플 수·음성 길이.
- `rms_dbfs`, `peak`: 입력 평균 음량(dBFS)과 최대 절댓값(0~1). `-inf`는 정확한 무음이다.
- `state=no_input`: 파이프라인으로 전달한 입력 없음. 패킷 수·오류·큐 길이도 함께 확인한다.
- `state=digital_silence`: 입력은 있으나 샘플이 전부 0이다.
- `state=signal`: 0이 아닌 입력이 있다. 잡음도 포함하므로 사람의 발화나 인식 성공을 뜻하지 않는다.
- `queue`: 처리 대기 청크 수. `interval_s`는 실제 관측 시간, `final=True`는 종료 시 마지막 구간이다.

패킷 수는 Asterisk→STT 구간만 나타낸다. Asterisk가 생성한 무음도 전달될 수 있으므로
패킷 수만으로 브라우저 마이크 송신 성공을 판단하지 않는다.

실행 번들이 포함되어 있어 일반 실행에 Node.js는 필요 없다.

```sh
./scripts/start.sh
```

JS 소스를 수정한 경우:

```sh
npm --prefix web ci
npm --prefix web run build
docker compose build
docker compose up -d --force-recreate --wait
```

PJSIP transport 변경은 Asterisk 재시작이 필요하다.

## 검증 결과 (2026-10-19)

| 항목 | 결과 |
|---|---|
| 브라우저 SIP.js 등록 | 성공: 등록 완료 상태 및 발신 활성화 |
| 브라우저 등록 해제 | 성공: 발신 비활성화 및 재등록 가능 |
| 실제 9998 WebRTC 발신 | REGISTER/INVITE/BYE 200, ICE/DTLS connected, SRTP 320패킷 송신, 한국어 partial/final 수신 |
| RTP/ARI 단위 테스트 | 9개 PASS |

음성 자동 테스트는 aiortc가 **한국어 WAV를 마이크 대신 송신**하여 실제 SIP/WebRTC/Asterisk/STT 경로를 검증했다. 사용자의 실제 마이크를 켜거나 주변 소리를 수집하지 않았다. 브라우저의 실제 마이크 권한 허용과 사람이 말하는 통화는 사용자가 위 절차로 확인할 수 있다. 자동 테스트 클라이언트는 SIP.js가 아니므로 브라우저 전체 음성 경로의 검증과 구별한다.

과거 검증 증거: `webphone-media-test.log`, `webphone-unit-tests.log`. 기존 샘플 통화 로그는 제거 전 기능의 기록이며 현재 지원 기능이 아니다.

자동 WebRTC 테스트 재실행 (같은 내선을 등록한 브라우저 탭은 먼저 닫기):

```sh
python3 -m venv .venv-test
.venv-test/bin/pip install aiortc==1.14.0 aiohttp==3.12.15
.venv-test/bin/python scripts/test_webphone_media.py --wav /path/to/speech.wav
```

## 문제 확인

- **403 등록 실패**: 비밀번호 및 PJSIP endpoint 확인. `pjsip show endpoint 1003`. `res_pjsip_transport_websocket`이 Running인지 확인한다.
- **등록은 되지만 음성 없음**: UDP 12000–12020 매핑, ICE 주소, 마이크 권한, 오디오 재생 상태 확인.
- **마이크 접근 오류**: localhost/HTTPS인지 확인. 브라우저·OS 마이크 권한과 입력 장치 확인.
- **자막 없음**: `/health/ready`, STT 로그, 통화 종료 시 패킷 수 확인. 9998은 마이크 입력을 인식한다.
- **새 번들이 반영되지 않음**: `npm --prefix web run build` 후 STT 이미지 재빌드, 컨테이너 재생성, 브라우저 새로고침. 빌드가 스크립트 URL에 내용 해시를 붙이며 HTML은 매번 재검증하므로 새 화면에서 이전 번들을 재사용하지 않는다.
