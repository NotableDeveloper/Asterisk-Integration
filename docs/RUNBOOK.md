# 실행 및 운영 가이드

## 시작

필수: Docker Engine/Compose, Python 3.11 이상, 모델 다운로드용 인터넷, 여유 디스크 약 3GB 이상. macOS ARM64에서 검증하며 Linux에서도 Compose bridge를 사용한다.

```sh
cd /Users/seongjin/workspaces/Asterisk-Integration
./scripts/start.sh
```

브라우저에서 http://localhost:8000 을 열고 **자동 SIP 등록 완료 → 통화 시작**을 누른다. 최초 실행은 모델 다운로드와 이미지 빌드가 필요하다. 이후에는 `docker compose up -d --wait`만 실행한다. 모델은 모델 디렉터리에 남으므로 다시 받지 않는다.

```sh
docker compose ps
curl -f http://localhost:8000/health/ready
docker compose logs -f stt
docker compose down
```

`down`은 이 Compose 프로젝트의 서비스만 종료한다. 모델 파일은 유지한다. 원문 통화 오디오는 저장하지 않으며 최근 이벤트 300개는 메모리에만 보관되고 서버 재시작으로 지워진다. 테스트 스크립트의 출력에는 샘플 대화록이 포함된다.

## 웹 소프트폰

별도 앱 없이 웹 화면의 **자동 SIP 등록 완료 → 통화 시작 → 마이크 허용**으로 음성을 STT에 전달한다. [웹 소프트폰 가이드](WEBPHONE.md)에 설정과 검증 범위를 정리했다.

## 소프트폰 2대

| 설정 | 상담원 | 고객 |
|---|---|---|
| 서버 | 127.0.0.1 | 127.0.0.1 |
| SIP 포트/전송 | 15060 / UDP | 15060 / UDP |
| 사용자/인증 ID | 1001 | 1002 |
| 데모 비밀번호 | demo-agent-1001 | demo-customer-1002 |
| 코덱 | G.711 μ-law | G.711 μ-law |

고객 1002에서 1001로 전화하고 상담원이 받는다. 두 채널의 RX를 분리하여 고객/상담원 행에 표시한다. 반대 방향 1001→1002도 지원한다.

기존 환경이 5060을 사용하므로 이 프로젝트는 호스트 SIP 15060, RTP 12000–12020을 사용한다. SIP는 `SIP_PORT=5060 docker compose up -d`로 변경 가능하다. RTP 변경 시 `rtp.conf`와 Compose 매핑을 함께 변경하고 Asterisk 이미지를 재빌드한다.

Docker Desktop과 소프트폰의 NAT 환경에 따라 `pjsip.conf`의 transport에 Mac의 실제 IP를 `external_media_address`, `external_signaling_address`로 설정하고 Docker subnet을 `local_net`으로 지정해야 한다. LAN 단말을 쓰려면 loopback 포트 바인딩을 해당 LAN IP로 변경한다. 현재 기본 설정은 동일 Mac의 로컬 데모용이다. 실제 소프트폰 양방향 음성은 별도 단말 환경에서 확인해야 한다.

## 설정과 제한

- ARI는 Compose 내부 8088에서만 접근하며 호스트에 공개하지 않는다.
- ARI URL/계정은 Compose 환경 변수와 `ari.conf`가 일치해야 한다.
- 내선 및 ARI 비밀번호는 공개된 데모용이다. 외부 배포 시 변경하고 인증·TLS·접근 통제를 추가한다.
- 서버는 최대 2통화(각 2화자)를 수용한다. 이 값은 성능 보장이 아니다.
- RTP는 PCMU/PT0 전용이다. 다른 코덱은 무시하고 malformed 카운트를 올린다.
- 패킷 재정렬을 기다리는 jitter buffer는 없다. 늦은/중복 패킷은 버리고 최대 0.5초의 timestamp 간격만 무음 보충한다. Compose 내부 네트워크 데모를 대상으로 한다.
- 오디오 큐는 화자당 100개 패킷, VAD 최대 발화는 15초다. 큐 초과는 overflow 지표와 UI 알림으로 드러난다.
- 추론은 단일 worker에서 수행하므로 동시 통화 시 지연이 증가할 수 있다. 다채널 운영은 워커 분산 및 용량 측정이 필요하다.
- Zipformer가 8kHz 전화 음성에서 빈 결과를 내면 SenseVoice가 1초 간격의 중간 자막을 생성한다. UI의 `SenseVoice 보완` 표시로 구별한다.
- SenseVoice 감정은 추정치이며 UNKNOWN도 정상 결과다. 감정을 인위적으로 NEUTRAL로 채우지 않는다.
- README의 모델 성능 비교는 설계 단계 자료다. 이 환경 실측은 VALIDATION.md를 기준으로 한다.

## 문제 확인

| 증상 | 확인 및 조치 |
|---|---|
| 모델 다운로드 인증서 오류 | macOS는 `SSL_CERT_FILE=/etc/ssl/cert.pem python3 scripts/download_models.py`. start.sh는 자동 적용한다. |
| 포트 충돌 | `docker compose ps`, `lsof -nP -iUDP:15060`로 확인하고 SIP_PORT 변경. 기존 컨테이너를 임의 종료하지 않는다. |
| readiness 503 | `docker compose logs stt`, Asterisk `ari show apps` 확인. |
| 자막 없음 | metrics packets가 0인지 확인. ARI 채널/브리지 생성 및 ulaw 설정을 확인. |
| 음성 인식 지연 | overflow와 rtf 확인. CPU 할당·동시 통화 수·발화 길이 확인. |
| 일부 모델 파일 손상 | models/manifest.json과 비교하고 해당 모델 폴더를 별도 보관한 후 재다운로드. |

## 개발 검증

마이크 경로의 WAV 송신 통합 테스트는 [웹 소프트폰 가이드](WEBPHONE.md)를 따른다.

```sh
docker compose config --quiet
docker compose run --rm --no-deps -v "$PWD/tests:/tests:ro" stt python -m unittest discover -s /tests -v

```

모델 및 테스트 음원의 이용 조건은 원 배포처의 LICENSE/README를 확인한다. 모델 파일은 Git 추적 대상에서 제외했다. 로컬 SHA256 manifest는 다운로드 파일의 이후 변경 검사용이며 공급자의 검증된 체크섬은 아니다.
