import { Web } from 'sip.js';

const el = id => document.getElementById(id);
let phone, registered = false, calling = false, busy = false;
let microphonePermission, microphoneDevices = [], microphoneError = '', devicesKnown = false;

function renderMicrophone() {
  const supported = window.isSecureContext && navigator.mediaDevices?.getUserMedia;
  const track = phone?.localMediaStream?.getAudioTracks()[0];
  const permission = microphonePermission?.state;
  el('microphone-permission').textContent = !supported ? '지원되지 않음 · localhost 또는 HTTPS 필요' :
    ({granted: '허용됨', denied: '차단됨', prompt: '통화 시작 시 허용 필요'}[permission] || '통화 시작 시 확인');
  el('microphone-device').textContent = track?.readyState === 'live' ?
    (track.label || '장치 이름 제공되지 않음') : '사용 중인 장치 없음';
  const defaultDevice = microphoneDevices.find(device => device.deviceId === 'default');
  el('microphone-default').textContent = defaultDevice?.label ||
    (devicesKnown && !microphoneDevices.length ? '감지된 입력 장치 없음' : '시스템 기본 장치 · 이름 확인 불가');
  el('microphone-state').textContent = !supported ? '마이크 사용 불가' :
    microphoneError || (track ?
      (track.readyState === 'ended' ? '입력 장치 연결 종료' :
        !track.enabled || track.muted ? '입력 중단 또는 음소거' : '연결됨 · 입력 트랙 활성') :
      permission === 'denied' ? '마이크 권한 차단됨' :
      calling ? '마이크 연결 중' : '대기 · 마이크 미사용');
}

async function refreshMicrophoneDevices() {
  try {
    microphoneDevices = (await navigator.mediaDevices.enumerateDevices()).filter(device => device.kind === 'audioinput');
    devicesKnown = true;
  } catch { devicesKnown = false; }
  renderMicrophone();
}

async function initializeMicrophone() {
  try {
    microphonePermission = await navigator.permissions.query({name: 'microphone'});
    microphonePermission.addEventListener('change', refreshMicrophoneDevices);
  } catch { /* Some browsers do not expose microphone permission queries. */ }
  navigator.mediaDevices?.addEventListener('devicechange', refreshMicrophoneDevices);
  await refreshMicrophoneDevices();
}
function status(text) { el('phone-status').textContent = text; }
function render() {
  const registration = registered ? '등록됨 · 내선 1003' : busy ? '등록 중…' : '미등록';
  el('sip-connection-state').textContent = registration;
  el('microphone-call').disabled = !registered || busy || calling;
  el('microphone-call').title = registered ? '9998로 발신하여 마이크 음성 인식' : 'SIP 등록 완료 후 사용할 수 있습니다.';
  el('phone-hangup').disabled = !calling;
  renderMicrophone();
}
function failure(error) {
  const message = error?.name === 'NotAllowedError' ? '마이크 사용을 허용한 뒤 다시 발신하세요.' :
    error?.name === 'NotFoundError' ? '마이크를 찾을 수 없습니다. 입력 장치를 연결하세요.' :
    error?.message || String(error);
  status('오류: ' + message);
  if (['NotAllowedError', 'NotFoundError', 'NotReadableError'].includes(error?.name)) {
    microphoneError = message;
    renderMicrophone();
  }
}
async function dispose() {
  const previous = phone;
  phone = undefined;
  registered = false;
  if (previous) {
    try { await previous.unregister(); } catch {}
    try { await previous.disconnect(); } catch {}
  }
}
async function register() {
  if (registered || busy || calling || !['http:', 'https:'].includes(location.protocol)) return;
  busy = true; render(); status('SIP 등록 중…');
  try {
    await dispose();
    const instance = new Web.SimpleUser(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/sip`, {
      aor: 'sip:1003@asterisk',
      reconnectionAttempts: 0,
      media: {constraints: {audio: true, video: false}, remote: {audio: el('phone-audio')}},
      userAgentOptions: {
        authorizationUsername: '1003', authorizationPassword: 'demo-web-1003',
        logLevel: 'error',
        sessionDescriptionHandlerFactoryOptions: {
          peerConnectionConfiguration: {iceServers: []}, iceGatheringTimeout: 3000
        }
      },
      delegate: {
        onRegistered() { registered = true; busy = false; status('SIP 등록 완료 · 내선 1003'); render(); },
        onUnregistered() { registered = false; render(); },
        onServerDisconnect() {
          registered = false; calling = false; busy = false;
          status('SIP 연결 종료 · 화면을 새로고침하세요.'); render();
        },
        onCallCreated() { calling = true; render(); },
        onCallAnswered() {
          busy = false; status('통화 연결됨 · 마이크로 말씀하세요.'); render();
          refreshMicrophoneDevices();
          el('phone-audio').play().catch(() => status('통화 연결됨 · 대화록 아래 재생 버튼을 눌러 음성을 들으세요.'));
        },
        onCallHangup() { calling = false; busy = false; status(registered ? '통화 종료 · 발신 대기' : '통화 종료'); render(); },
        onCallReceived() { instance.decline().catch(failure); }
      }
    });
    phone = instance;
    await instance.connect();
    await instance.register({requestDelegate: {
      onReject(response) { busy = false; registered = false; status(`SIP 등록 실패 (${response.message.statusCode}) · 서버의 SIP 계정 설정을 확인한 후 새로고침하세요.`); render(); }
    }});
  } catch (error) { await dispose(); busy = false; failure(error); render(); }
}
async function call() {
  if (!registered || !phone || busy || calling) return;
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    status('마이크 통화는 localhost 또는 HTTPS에서 지원됩니다.'); return;
  }
  microphoneError = '';
  busy = true; render(); status('마이크 권한 확인 및 발신 중…');
  try {
    await phone.call('sip:9998@asterisk', undefined, {
      requestDelegate: {onReject(response) { status(`발신 거절 (${response.message.statusCode})`); }}
    });
  } catch (error) {
    try { await phone.hangup(); } catch {}
    busy = false; calling = false; failure(error); render();
  }
}
el('microphone-call').onclick = call;
el('phone-hangup').onclick = async () => {
  try { await phone.hangup(); } catch (error) { failure(error); }
};
const microphoneTimer = setInterval(renderMicrophone, 1000);
window.addEventListener('pagehide', () => {
  clearInterval(microphoneTimer);
  phone?.disconnect().catch(() => {});
});
render();
initializeMicrophone();
register();
