# 작업 기록

## 2026-10-18 착수
- 요청: README의 4단계 구축 계획 실행, 중간 과정 문서화.
- 초기 상태: README.md만 존재, Git 저장소 없음. 상위 AGENTS.md 없음.
- 확인 환경: Python 3.11.9, Docker 28.3.2, Docker Desktop Linux/arm64 실행 가능.
- 구현 순서: 모델 확보 → 컨테이너/전화 설정 → ARI/RTP/2-pass → UI → 자동/실제 통합 검증.
- 원본 계획서의 RTF·정확도·메모리 수치는 보장값이 아닌 가설로 취급한다.
- SenseVoice 공식 INT8 아카이브는 `...sense-voice-zh-en-ja-ko-yue-int8-2024-07-17`로 README의 비양자화 경로와 구별한다.
- 외부 미디어는 RTP 정적 payload type 0인 ulaw/8kHz를 사용해 slin16 동적 payload 매핑 문제를 피한다.
- 데모는 Local 채널로 한국어 샘플을 재생하여 소프트폰 없이도 실제 Asterisk → RTP → STT 경로를 통과하도록 구성한다.

## 참고한 공식 자료
- https://k2-fsa.github.io/sherpa/onnx/pretrained_models/online-transducer/zipformer-transducer-models.html
- https://k2-fsa.github.io/sherpa/onnx/sense-voice/pretrained.html
- https://docs.asterisk.org/Development/Reference-Information/Asterisk-Framework-and-API-Examples/External-Media-and-ARI/
- https://docs.asterisk.org/Latest_API/API_Documentation/Asterisk_REST_Interface/Channels_REST_API/

## 모델 확보 및 구현 결정
- `download_models.py:download`의 urllib HTTPS 요청에서 CERTIFICATE_VERIFY_FAILED 발생. Python 3.11 프레임워크의 기본 CA 탐색 문제로 판단하고 시스템 CA `/etc/ssl/cert.pem`을 `SSL_CERT_FILE`로 지정해 재시도했다. TLS 검증 해제는 하지 않는다.
- 아카이브는 임시 디렉터리에 다운로드·안전 검사·추출 후 교체한다. SHA256 manifest는 로컬 무결성 기록이며 공급자 서명 검증을 뜻하지 않는다.
- Asterisk는 Ubuntu 24.04 저장소의 ARM64 패키지, STT는 Python 3.11 및 고정 버전 의존성을 사용한다.
- RTP PCMU 디코딩은 NumPy 구현으로 audioop에 의존하지 않는다. 시퀀스 중복/늦은 패킷 제거, 짧은 timestamp 간격 무음 보충, 큐 상한을 둔다.
- CPU 추론은 전용 단일 executor에서 직렬화하여 모델 동시 접근과 asyncio 이벤트 루프 차단을 피한다. 모델은 공유하고 스트림/VAD/리샘플러는 화자별로 분리한다.

## ARI 및 UI 구현
- ARI 원본 채널과 내부 snoop/media 채널을 구분하여 재귀 생성 방지. 화자마다 UDP 소켓 및 별도 mixing bridge를 만든다.
- 실제 내선은 ARI가 상대 PJSIP 내선을 originate하고 원본 통화 브리지에 연결한다. 각 원본 RX를 따로 복제한다.
- 소프트폰 없는 테스트는 Local/9999@sample/n, 소프트폰 9999는 재생 방향(out)을 snoop한다.
- StasisEnd/ChannelDestroyed 및 ARI 재접속 시 채널·브리지·소켓·추론 큐 정리 경로를 구현했다.
- 웹 화면은 partial을 같은 segment 행에서 갱신하고 final로 확정한다. 텍스트는 textContent로 표시한다. WebSocket 재접속, 최근 300개 이벤트, 느린 구독자 제한을 적용했다.
- 최초 Docker 빌드 실패: requirements의 sherpa-onnx 1.12.14는 현재 Python 3.11 Linux ARM64 인덱스에 휠이 없다. pip가 제공한 목록의 1.12.40으로 수정하고 재빌드한다.
- 모델 3종 다운로드 완료 및 models/manifest.json 생성. 한국어 음성은 공식 SenseVoice 배포본의 ko.wav를 이용한다.

## 첫 실제 통합 검증과 수정
- 포트 5060 바인딩 실패: 기존 Docker의 Asterisk 서비스가 점유 중. 기존 서비스는 유지하고 본 프로젝트 SIP=15060, RTP=12000–12020으로 변경했다.
- RTP 단위 테스트 5개 통과: μ-law 기준값, CSRC/extension/padding, 잘못된 헤더, sequence wrap/손실/지연/overflow, SSRC 분리.
- 최초 통합 테스트: 274개 RTP 패킷은 수신했으나 partial/final 없음. Asterisk `file.c:ast_openstream_full`에서 `File custom/ko does not exist in any format`, `app_playback.c:playback_exec`에서 Playback failed 발생.
- 확인: WAV는 /var/lib/asterisk/sounds/custom에 존재하지만 설치 패키지의 astdatadir은 /usr/share/asterisk. 파일 부재 자체가 아니라 검색 경로와 마운트 경로 불일치. Compose 마운트 목적지를 /usr/share/asterisk/sounds/custom으로 수정한다.
- Local originate의 기본 코덱이 slin192인 것도 로그에서 확인되어 테스트 originate formats=ulaw를 명시했다.
- 이미지 inspect 및 컨테이너 uname에서 두 서비스 모두 arm64/aarch64 확인.

## 전화망 대역에서 Zipformer 빈 출력 재현 및 보완
- 사운드 경로 수정 후 SenseVoice final과 감정 메타데이터는 정상 도착했으나 Zipformer partial은 없었다.
- `scripts/probe_online.py`에서 원본 WAV를 직접 넣으면 INT8/FP32 모두 한국어 출력됨을 확인했다.
- `scripts/probe_telephony.py`로 두 공식 샘플 × INT8/FP32 × 원본/8kHz 왕복 비교. 원본은 4건 모두 텍스트, 8kHz→16kHz는 4건 모두 빈 문자열. VAD/ARI와 무관한 모델 입력 대역 문제를 분리 재현했다. 증거: docs/telephony-probe.log.
- 관련 upstream 제보: https://github.com/k2-fsa/sherpa-onnx/issues/2886 (학습/평가 데이터 외 입력에 대한 빈 출력 제보). 이 보고가 전화 대역 문제의 확정 원인은 아니며, 본 환경의 비교 실험을 근거로 한다.
- 계획서의 '8k 전화 음성 업샘플링만으로 native streaming 가능' 전제는 검증에서 성립하지 않았다. Zipformer 경로는 유지하되 결과가 없는 발화는 SenseVoice rolling partial(1초 간격, 최근 최대 8초)을 제공한다. UI 및 이벤트 engine 필드에 보완 경로를 명시한다.
- fallback은 PARTIAL_FALLBACK=0으로 끌 수 있다. Final은 기존 VAD 발화 단위 SenseVoice를 유지한다. 감정 EMO_UNKNOWN은 UNKNOWN으로 정규화한다.
- Docker up --build 후 실행 중 컨테이너가 이전 image ID를 유지한 사례를 inspect로 확인하여 최종 검증에서는 --force-recreate로 배포 소스와 실행 이미지를 맞춘다.

## 최종 검증 및 인계
- SenseVoice fallback 적용 후 실제 통합 PASS: partial 3회, final 1회, 505 패킷, 손실/큐 초과 0, 종료 후 세션 0.
- Asterisk CLI 확인: active channels/calls 0, bridge 없음. 종료 정리 확인.
- 최종 단위 테스트 8개 통과. compileall 및 Compose config 검증 통과.
- 모델 manifest SHA256 20개 재검증 통과. 다운로드 스크립트에 --verify 및 불완전 폴더 감지 추가.
- 브라우저에서 직접 샘플 버튼을 눌러 두 번째 실제 통화를 수행했다. 한국어 final/중립 배지/종료 및 버튼 재활성화를 확인하고 docs/ui-verified.jpg 저장.
- 실제 final에 첫 구절 누락·띄어쓰기 오류가 있어 정확도 보장 없이 검증 문서에 명시했다.
- docs/RUNBOOK.md: 시작/정지·내선·포트·NAT·문제 확인. docs/ARCHITECTURE.md: 흐름·자원·이벤트 계약·보완 경로. docs/VALIDATION.md: 결과·실측·미검증 범위. README 상단에 구현 상태와 설계 대비 차이, 문서 링크 추가.
- 현재 두 컨테이너를 실행 상태로 유지하고 http://localhost:8000 브라우저 탭을 결과물로 남긴다. 기존 다른 프로젝트의 컨테이너는 변경하지 않았다.

## 2026-10-19 웹 소프트폰 구현 착수
- 요청: JavaScript 브라우저 SIP 등록 및 STT 내선 발신을 위한 최소 소프트폰.
- SIP.js 0.21.2를 로컬 번들로 제공하여 CDN 없이 실행. 내선 1003 / STT 마이크 9998 / 샘플 듣기 9999.
- Asterisk WebSocket transport, WebRTC/DTLS-SRTP endpoint 추가. 외부 ARI 노출 없이 FastAPI /sip에서 SIP WebSocket만 프록시한다.
- Docker 내부 IP 대신 호스트의 포트 매핑 주소를 ICE candidate로 광고한다. 기본은 동일 Mac 브라우저용 127.0.0.1.
- 마이크 내선은 RX snoop로 기존 파이프라인에 전달하고 silence generator로 미디어를 유지한다.
- 공식 참고: https://sipjs.com/guides/simple-user/ 및 https://docs.asterisk.org/Configuration/WebRTC/Configuring-Asterisk-for-WebRTC-Clients/
- 최초 브라우저 REGISTER는 403. 로그의 chan_sip.c:handle_request_register와 res_pjsip_transport_websocket declined to load를 연결해 조사했다. 기본 설치의 구형 chan_sip이 SIP WebSocket 프로토콜을 선점한 것이 원인이다. modules.conf에서 chan_sip만 비활성화하고 PJSIP WebSocket을 사용하도록 수정한다.
- PJSIP 충돌 수정 후 브라우저 SIP.js에서 등록 완료 및 등록 해제를 직접 확인했다.
- aiortc 테스트 클라이언트로 호스트 WAV를 송신하여 마이크 권한/주변 음성 수집 없이 실제 WebRTC 경로 검증. 9998: REGISTER/INVITE/BYE 200, ICE/DTLS connected, SRTP 320패킷, partial 3회/final 1회, 정상 종료.
- 9999 수신 테스트도 PASS: 213개 수신 오디오 프레임, 한국어 final 확인.
- microphone 역할의 RX snoop/silence/종료 정리를 단위 테스트로 추가. 총 9개 PASS. 기존 Local 샘플 통합 테스트 PASS(505패킷, 손실/큐 초과 0).
- 실제 브라우저 마이크 발신은 사용자 마이크 권한과 장치가 필요하므로 자동 WebRTC 테스트와 구별하여 docs/WEBPHONE.md에 기록했다.
- 최종 브라우저는 내선 1003 SIP 등록 완료 상태로 남겼고 docs/webphone-registered.jpg 및 webphone-contacts.log를 저장했다. 실제 마이크는 사용하지 않았다.
- 잘못된 Origin 또는 SIP 하위 프로토콜이 없는 /sip 핸드셰이크는 403으로 거절됨을 확인했다. Python/JavaScript 구문 및 Compose 구성 검증도 통과했다.
- docs/WEBPHONE.md 신설, README/RUNBOOK/ARCHITECTURE/VALIDATION에 사용 방법·변경 내용·검증 범위를 반영했다.

## 2026-10-19 로컬 Git 커밋 정리
- 요청: 지금까지의 작업을 GitHub에 올리기 전 로컬 Git부터 단계적으로 커밋.
- 기존 .git이 없어 main 브랜치로 초기화했다. 기존 사용자 Git 작성자 설정을 그대로 사용했다.
- 실행 환경, STT 서버·테스트, 웹 UI·소프트폰, 문서·검증 증거의 4개 커밋으로 분리했다.
- 모델 약 687MB, 테스트 가상환경 약 107MB, npm 의존성 약 12MB 및 생성 WAV/캐시는 제외한다. 구현 소스·프런트 번들·lockfile·문서·원본 증거 로그/이미지는 포함한다.
- 실서비스 토큰/개인키 패턴 점검에서 추가로 확인된 값은 없었으며, 설정의 기존 데모 자격 증명은 데모 구성으로 유지한다. 전체 보안 감사의 의미는 아니다.
- STT 코드의 후행 공백 1곳만 정리했고 실행 로직은 변경하지 않았다.
- GitHub remote 설정과 push는 수행하지 않았다. 상세 내용은 docs/GIT_HANDOFF.md.
