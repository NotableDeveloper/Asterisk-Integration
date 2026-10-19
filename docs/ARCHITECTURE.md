# 구현 구조와 설계 결정

## 흐름

```text
PJSIP 1002 ↔ 원본 mixing bridge ↔ PJSIP 1001
     │ RX snoop                       │ RX snoop
     ▼                                ▼
독립 tap bridge                  독립 tap bridge
     │ ExternalMedia ulaw             │ ExternalMedia ulaw
     ▼                                ▼
화자별 UDP 소켓 → RTP 파싱 → PCMU 디코딩 → soxr 8k→16k
     ├─ Zipformer online stream → partial (출력 없으면 SenseVoice rolling partial)
     └─ Silero VAD → SenseVoice INT8 → final + emotion
                        ↓
             bounded event hub → /ws → 브라우저
```

- 원본 bridge에는 snoop/media 채널을 넣지 않는다. 추출 경로가 통화 믹싱을 변경하지 않도록 격리한다.
- snoop의 `spy=in`은 원본 채널로 유입되는 음성이므로 각 전화기의 발화가 분리된다. 소프트폰 9999 샘플 Playback은 반대 방향이므로 `out`을 쓴다.
- Local 테스트의 `/n`은 Local 채널 최적화 제거를 막는다. `;2`에서 재생된 샘플이 `;1` RX로 들어온다.
- ExternalMedia의 direction=both는 ARI RTP 드라이버의 지원 방식이다. 서버는 송신하지 않아 통화에 음성을 주입하지 않는다.

## 상태 및 자원

ARI `Call`이 원본/상대방/내부 채널 ID, bridge ID, audio session을 소유한다. ID는 REST 생성 전 등록하여 부분 실패도 정리한다. 종료 이벤트에서 Call을 먼저 pop해 중복 종료를 멱등 처리하고, 채널·bridge 삭제 → UDP close → 큐 drain 및 마지막 발화 flush → metrics → call_ended 순서로 정리한다.

CPU 모델은 서버 시작 시 로드한다. per-speaker Pipeline은 online stream, VAD, streaming resampler를 별도로 가진다. 전용 executor가 모든 모델 연산을 직렬화한다. asyncio는 ARI·UDP·HTTP·WebSocket 처리를 담당한다.

## WebSocket 계약

공통 필드: `id`(서버 내 증가 정수), `time`(Unix seconds), `type`. 통화 이벤트에는 `call_id`가 포함된다.

| type | 주요 필드 | UI 처리 |
|---|---|---|
| snapshot | events | 재연결 시 최근 300개 재생, id로 중복 제거 |
| call_started / call_ended | call_id | 통화 상태 |
| partial | speaker, segment_id, text, engine | 동일 화자·segment 행 갱신 |
| final | 위 필드 + emotion, acoustic_event, final_inference_ms | 문장 확정 |
| metrics | packets, lost, late, malformed, overflow, audio_seconds, inference_seconds, rtf | 종료 시 성능·전송 상태 |
| error | text | 처리 오류 표시 |

VAD 경계마다 segment_id가 증가한다. offline 결과의 감정/event 메타데이터를 별도 필드로 읽는다. final_inference_ms는 SenseVoice 실행 시간이며 종단 지연이나 VAD 대기 시간을 포함하지 않는다. rtf는 화자별 추론 CPU 작업 경과 시간/수신 오디오 길이이며 executor 큐 대기는 제외한다.

## 원 계획에서 구체화·변경한 내용

1. INT8 전용 SenseVoice 공식 경로 사용.
2. 동적 RTP payload type 혼선을 피하기 위해 ulaw 고정.
3. 기존 서비스와 충돌을 피하기 위해 호스트 SIP 15060 및 RTP 12000–12020 사용.
4. 샘플은 새 음성 합성 대신 공식 한국어 테스트 WAV 사용.
5. 모델 속도·정확도에 대한 계획서 수치를 보장하지 않고 실제 측정값 기록.
6. 금융 hotwords는 이번 데모의 필수 단계에 없으므로 기본 greedy decoder 사용. hotword 가중치를 사용하려면 modified_beam_search 및 모델의 토큰화 조건을 추가 검증해야 한다.

## 8kHz 입력 보완 경로

`docs/telephony-probe.log`에서 원본 WAV는 Zipformer INT8/FP32 모두 인식했지만 8k→16k 변환 후에는 빈 결과였다. 따라서 발화가 감지됐고 online 결과가 없을 때 SenseVoice를 1초 주기로 실행한다. 입력은 최근 8초로 제한한다. 이 중간 자막은 `engine=sensevoice-fallback`으로 표시하며 native streaming 성능으로 보고하지 않는다. 8초보다 긴 발화의 중간 자막은 최근 구간만 보여 줄 수 있지만 final은 VAD 전체 발화(최대 15초)를 처리한다. 환경 변수 `PARTIAL_FALLBACK=0`은 비교 실험용으로 이 경로를 끈다.

## 웹 소프트폰 (2026-10-19)

웹 화면의 SIP.js → 동일 Origin `/sip` 프록시 → Asterisk PJSIP WebSocket으로 SIP 신호를 전달한다. 음성은 WebRTC ICE/DTLS-SRTP로 직접 호스트 UDP 포트를 통해 Asterisk에 도착한다. 내선 1003은 webphone 컨텍스트의 9998/9999만 사용한다. 9998은 RX 마이크 STT, 9999는 TX 샘플 STT이다. 상세 설정과 검증은 [WEBPHONE.md](WEBPHONE.md)를 참조한다.
