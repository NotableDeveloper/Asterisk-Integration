# STT 코드베이스 안내서

이 문서는 저장소에서 음성이 Asterisk를 거쳐 STT 모델에 들어가고, 자막 이벤트로 브라우저에 표시되기까지의 실제 구현을 설명한다. 모델 동작이나 음성 처리 코드를 직접 바꿀 때 어느 파일을 수정해야 하는지, 어떤 약속을 유지해야 하는지를 빠르게 찾는 것이 목적이다.

## 가장 먼저 볼 파일

STT 인식 동작의 중심은 [`stt_pipeline.py`](../stt-server/app/stt_pipeline.py)의 `Engines`와 `Pipeline`이다. 모델 로딩은 `Engines`, 통화별 입력 스트림과 중간·최종 인식은 `Pipeline`이 담당한다. 오디오가 이 코드에 도착하는 경로는 [`rtp_receiver.py`](../stt-server/app/rtp_receiver.py)와 [`main.py`](../stt-server/app/main.py), Asterisk 통화에서 해당 경로를 여는 부분은 [`ari_client.py`](../stt-server/app/ari_client.py)에서 찾을 수 있다.

```text
마이크
  → 브라우저 WebRTC / SIP
  → Asterisk 내선 9998, Stasis(microphone)
  → ARI가 원본 채널의 RX(in)를 snoop
  → ExternalMedia(PCMU)와 통화별 UDP 포트
  → RTPReceiver가 패킷 검증·μ-law 디코딩
  → main.Audio의 제한된 큐와 worker
  → Pipeline.feed (8 kHz PCM → 16 kHz)
       ├─ Zipformer → partial 이벤트
       ├─ Silero VAD → 발화 구간 분리
       └─ SenseVoice → final 이벤트
  → Audio.worker → STT_RESULT 로그 (partial 및 final)
                 → Hub → WebSocket /ws → 브라우저 대화록 (final만)
```

브라우저의 `getUserMedia` 마이크 트랙은 통화가 시작될 때 SIP.js가 만든다. STT 서버에서 직접 마이크를 열지 않는다. 따라서 브라우저 입력 장치나 WebRTC 송신 문제는 [`phone.js`](../web/src/phone.js), RTP 수신 이후의 문제는 아래 서버 파일에서 조사한다. `STT_AUDIO` 로그는 RTP가 디코딩되어 STT 입력으로 전달되는 상태를 보여 주지만, 실제 음성인지 또는 모델이 인식했는지는 `STT_RESULT` 로그의 partial/final 이벤트로 따로 확인해야 한다. 화면에는 final만 표시한다.

## 모듈별 책임

| 파일 | 책임 | 이 파일을 수정할 때 |
|---|---|---|
| `stt-server/app/rtp_receiver.py` | RTP 헤더 검증, PT 0 PCMU 제한, μ-law를 `float32` PCM으로 디코딩, 순서·SSRC 확인, 짧은 패킷 공백 보충, RTP 통계 | 코덱·패킷 형식·손실 처리를 바꿀 때 샘플 레이트와 테스트도 함께 조정한다. 네트워크 콜백에서 모델 추론을 실행하지 않는다. |
| `stt-server/app/main.py`의 `Session`, `Audio` | 화자별 UDP endpoint, 최대 길이가 정해진 큐, 비동기 worker, 추론 executor 호출, 오디오 로그와 metrics 이벤트 | asyncio와 모델 스레드의 경계를 유지한다. 세션을 열면 종료·ARI 재연결 시 반드시 닫고 대기 작업도 정리한다. |
| `stt-server/app/stt_pipeline.py`의 `Engines` | Zipformer, SenseVoice, Silero VAD 및 모델 설정을 서버 시작 때 한 번 생성 | 모델 경로·인식기 초기화·디코딩 옵션을 바꿀 때 모델 파일과 `scripts/download_models.py`의 다운로드 목록을 함께 확인한다. |
| `stt-server/app/stt_pipeline.py`의 `Pipeline` | 화자별 streaming stream, VAD, soxr 리샘플러와 발화 상태를 소유한다. partial/final을 생성한다. | 인식 타이밍, 발화 경계, 결과 정규화, 이벤트 종류를 바꿀 때 주로 수정한다. 같은 Pipeline 인스턴스는 추론 executor에서 순서대로 호출되어야 한다. |
| `stt-server/app/ari_client.py` | Asterisk ARI 이벤트, Stasis 채널, snoop 및 ExternalMedia 수명 관리 | 음성 원본 방향·화자 분리·채널 생성·종료를 바꿀 때 수정한다. STT 신호처리 코드는 여기 넣지 않는다. |
| `stt-server/static/index.html` | 실시간 이벤트를 받아 대화록과 통화 상태를 그리는 HTML/JavaScript | 이벤트 표시, UI 레이아웃을 바꿀 때 수정한다. 이벤트 텍스트는 `textContent`로 넣어 HTML 해석을 피한다. |
| `tests/test_rtp.py`, `tests/test_ari.py`, `tests/test_audio_logging.py` | RTP 파서·디코더, ARI 호출 수명, 오디오 레벨 로그 검증 | 해당 모듈 동작이 바뀌면 책임 경계에 맞는 단위 테스트를 추가하거나 갱신한다. |

## 모델과 오디오의 규약

### 입력 오디오

Asterisk ExternalMedia는 `format=ulaw`, 8 kHz PCMU RTP를 보낸다. `RTPReceiver`는 RTP payload type이 0인지 검증하고 payload를 `float32` 배열로 변환한다. 값은 대략 `[-1.0, 1.0]` 범위다. RTP sequence 중복·늦은 패킷은 제외하고, 동일 SSRC를 확인한다. 8 kHz 기준 최대 4,000 sample(0.5초)인 timestamp 간격만 무음 배열로 보충한다. 더 긴 간격은 임의의 긴 무음을 만들지 않는다.

큐 크기는 세션당 100개 청크다. 가득 찬 큐에 새 패킷이 오면 폐기하고 `overflow`를 올린다. 처리 지연이 생겨도 큐가 끝없이 커지지 않도록 한 제한이다. 다른 코덱을 받으려면 payload 형식 협상, 파서·디코더, 샘플 레이트 변환, RTP 테스트와 Asterisk 설정을 함께 바꿔야 한다.

### 리샘플링과 모델 실행

`Pipeline`은 PCMU 디코딩된 8 kHz `float32` 입력을 `soxr.ResampleStream(8000, 16000, ...)`으로 16 kHz로 바꾼다. 모델 입력과 VAD 설정은 16 kHz다. VAD의 `window_size`보다 짧은 입력은 `pending`에 모았다가 완전한 window 단위로 Zipformer와 VAD에 전달한다.

모델 인스턴스는 공유하지만, 온라인 recognizer stream, VAD, resampler, 발화 및 partial 상태는 **Pipeline 인스턴스마다** 분리된다. 인식 연산은 `main.py`의 전용 단일 `ThreadPoolExecutor`에서 실행한다. 네트워크 이벤트 루프를 막거나 모델 인스턴스를 여러 스레드에서 동시에 호출하면 세션 간 지연·상태 오염 문제가 생길 수 있다.

### 중간 인식과 최종 인식

- **Zipformer partial:** 새 audio window를 온라인 stream에 넣고 준비된 동안 `decode_stream()`을 호출한다. 결과 문자열이 비어 있지 않고 직전 partial과 다르면 `engine="zipformer"`인 `partial`을 낸다. 설정상 Zipformer endpoint detection은 비활성화되어 있다.
- **SenseVoice 보완 partial:** 기본 활성화(`PARTIAL_FALLBACK=1`)다. VAD가 음성을 감지했고 Zipformer 결과가 비어 있을 때 16,000 sample(16 kHz로 1초)이 더 쌓이며 VAD가 현재 발화 구간을 비우지 않은 경우, 최근 최대 8초를 SenseVoice로 추론한다. 새 결과에는 `engine="sensevoice-fallback"`을 표시한다. 비활성화는 컨테이너 환경에 `PARTIAL_FALLBACK=0`을 준다.
- **SenseVoice final:** VAD가 확정한 각 발화 구간을 SenseVoice로 디코딩한다. `final=True` 입력에는 resampler의 마지막 chunk와 1초의 끝 무음을 전달해 버퍼에 남은 오디오와 마지막 발화를 처리한다. 최종 결과 후 online stream 및 해당 partial 상태를 새로 만든다.

SenseVoice 결과에서 `<|...|>` 형태의 task/language 토큰을 정리한다. 감정 결과가 없거나 `EMO_UNKNOWN`이면 `UNKNOWN`으로 표시한다. 이 정규화는 UI 계약에 영향을 주므로 결과 처리 방식을 바꿀 때 실제 모델 출력 예를 확인한다.

## 바꾸려는 내용에 따라 찾기

| 원하는 변경 | 먼저 볼 위치 |
|---|---|
| 로그에 남기는 partial 생성 빈도 변경 | `Pipeline.feed`: Zipformer 결과 비교와 SenseVoice fallback 조건·누적량 |
| final이 나오는 시점, 문장 분리, 무음 처리 변경 | `Engines`의 `vad_config`, `Pipeline.feed`, `Pipeline.drain` |
| 더 긴 문장을 부분 인식에 사용 | `Pipeline.rolling` 크기·fallback 호출 규칙. VAD 최대 발화 시간 및 큐 메모리 영향을 함께 측정한다. |
| 다른 모델 또는 디코딩 옵션 사용 | `Engines.__init__`와 모델 파일 배치. 모델 공급원·이름·tokens와 encoder/decoder/joiner 또는 SenseVoice 파일 계약 확인 |
| 입력 코덱·샘플 레이트 변경 | Asterisk/ARI ExternalMedia 형식, `rtp_receiver.py`, `Pipeline` resampler, `tests/test_rtp.py`를 함께 변경 |
| 자막 이벤트 필드 추가 | `Pipeline.event` 및 생성 지점, `Hub.publish`, `index.html` 이벤트 렌더링. 기존 `type`, `call_id`, `speaker`, `segment_id`, `text` 소비자를 유지할지 결정 |
| 화자·통화 경로 변경 | `ari_client.py`의 `handle`, `attach`, `cleanup`; `tests/test_ari.py` |
| 오디오 수신 또는 음량 디버깅 | `main.py`의 `Session.observe/report`; 기록된 음성 내용 대신 패킷 수·RMS·peak를 먼저 확인 |

## 자주 쓰는 설정 및 상태

- `MODEL_ROOT` 기본값은 `/models`; Compose가 저장소의 `models/`를 컨테이너에 읽기 전용으로 연결한다.
- 모델 디렉터리는 Git 추적에서 제외된다. `scripts/download_models.py`가 현재 고정된 Zipformer, SenseVoice, Silero VAD 파일을 내려받고 `models/manifest.json`을 만든다. `python3 scripts/download_models.py --verify`는 manifest 무결성을 검사한다. 모델 가중치 자체나 모델 배포물 변경을 코드 수정으로 착각하지 않는다.
- `PARTIAL_FALLBACK`은 online partial이 비어 있을 때 SenseVoice 중간 결과를 켜고 끄는 설정이다.
- `docker compose ps`, `curl -f http://localhost:8000/health/ready`로 서버·ARI 상태를 확인한다. `health/ready`는 모델이 로드되고 ARI가 연결됐는지 보여준다.
- `docker compose logs -f --timestamps stt | rg STT_AUDIO`로 1초 단위 입력 상태를 본다. `digital_silence`는 모델에 들어온 PCM이 모두 0임을, `signal`은 0이 아닌 신호가 있음을 뜻한다. `signal`은 사람의 발화나 인식 성공을 보장하지 않는다.

## 수정과 검증

Python 수정은 로컬에 별도 의존성이 없어도 이미 빌드된 STT 컨테이너 환경에서 확인할 수 있다. 저장소 루트에서 실행한다.

```sh
# RTP, ARI, 입력 로그 단위 테스트
# Docker 이미지에는 Python 의존성이 들어 있다.
docker compose run --rm --no-deps \
  -v "$PWD/tests:/tests:ro" \
  stt python -m unittest discover -s /tests -v

# 입력/인식 결과까지 보는 종단 검증은 웹 소프트폰으로 수행한다.
# SIP 등록 후 통화 시작을 누르고 말한 다음 STT_AUDIO와 partial/final을 확인한다.
docker compose logs -f --timestamps stt | rg 'STT_AUDIO|Audio worker failed|ARI event failed'
```

`stt-server/Dockerfile`은 `app/`와 `static/`을 이미지에 복사한다. Python 또는 웹 화면 소스를 수정한 후에는 실행 중인 컨테이너에 파일만 저장해도 바뀌지 않으므로 이미지를 다시 빌드하고 컨테이너를 재생성한다.

```sh
# Python API 또는 STT 코드 수정
# 웹 화면(HTML) 수정도 STT 이미지 안에 포함되므로 다시 빌드한다.
docker compose build stt
docker compose up -d --no-deps --force-recreate --wait stt

# web/src/phone.js를 수정했다면 번들을 만든 다음 STT 이미지를 빌드한다.
npm --prefix web run build
docker compose build stt
docker compose up -d --no-deps --force-recreate --wait stt
```

Asterisk 설정(`asterisk/config/*.conf`)을 변경한 경우에는 `asterisk` 이미지도 빌드하고 두 서비스를 재생성한다. 마이크 경로를 테스트할 때 SIP를 사용하는 같은 브라우저 탭이 이미 등록돼 있으면 자동 테스트 클라이언트와 충돌할 수 있다.

## 처음 코드를 읽을 때 추천 순서

1. 이 문서의 데이터 흐름을 보고 Asterisk가 음성을 STT로 전달하는 경로를 구분한다.
2. `stt_pipeline.py`의 `Engines.__init__`, `Pipeline.__init__`, `feed`, `drain`을 읽어 모델 상태와 결과 발생 시점을 이해한다.
3. `rtp_receiver.py`의 `parse_rtp`, `decode_ulaw`, `datagram_received`를 읽어 모델 입력이 되는 PCM을 확인한다.
4. `main.py`의 `Audio.open`, `worker`, `close`를 읽어 입력 queue와 추론 executor, 종료 시 마지막 발화 flush를 확인한다.
5. `ari_client.py`의 `handle`, `attach`, `cleanup`을 읽어 call ID, 화자, snoop 방향과 세션 정리를 확인한다.
6. 기존 테스트를 수정 의도에 맞춰 확장하고, 통화 중 로그와 화면 자막까지 확인한다.

통화·STT 코드를 처음부터 전부 다시 쓸 필요 없이, 원하는 동작이 있는 레이어를 찾아 그 레이어의 입력·출력 계약을 유지하면서 고치는 것이 가장 안전하다.
