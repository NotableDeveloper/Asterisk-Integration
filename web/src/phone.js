import { Web } from 'sip.js';

const el = id => document.getElementById(id);
let phone, registered = false, calling = false, busy = false;
function status(text) { el('phone-status').textContent = text; }
function render() {
  el('phone-register').disabled = registered || busy || calling;
  el('phone-unregister').disabled = !registered || busy || calling;
  el('phone-call').disabled = !registered || busy || calling;
  el('phone-hangup').disabled = !calling;
  el('phone-destination').disabled = busy || calling;
  el('phone-password').disabled = registered || busy || calling;
}
function failure(error) {
  const message = error?.name === 'NotAllowedError' ? '마이크 사용을 허용한 뒤 다시 발신하세요.' :
    error?.name === 'NotFoundError' ? '마이크를 찾을 수 없습니다. 입력 장치를 연결하세요.' :
    error?.message || String(error);
  status('오류: ' + message);
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
el('phone-register').onclick = async () => {
  busy = true; render(); status('SIP 등록 중…');
  try {
    await dispose();
    const instance = new Web.SimpleUser(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/sip`, {
      aor: 'sip:1003@asterisk',
      reconnectionAttempts: 0,
      media: {constraints: {audio: true, video: false}, remote: {audio: el('phone-audio')}},
      userAgentOptions: {
        authorizationUsername: '1003', authorizationPassword: el('phone-password').value,
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
          status('SIP 연결 종료 · 다시 등록하세요.'); render();
        },
        onCallCreated() { calling = true; render(); },
        onCallAnswered() {
          busy = false; status('통화 연결됨 · 9998에서는 마이크로 말씀하세요.'); render();
          el('phone-audio').play().catch(() => status('통화 연결됨 · 아래 재생 버튼을 눌러 음성을 들으세요.'));
        },
        onCallHangup() { calling = false; busy = false; status(registered ? '통화 종료 · 발신 대기' : '통화 종료'); render(); },
        onCallReceived() { instance.decline().catch(failure); }
      }
    });
    phone = instance;
    await instance.connect();
    await instance.register({requestDelegate: {
      onReject(response) { busy = false; registered = false; status(`SIP 등록 실패 (${response.message.statusCode}) · 비밀번호를 확인하세요.`); render(); }
    }});
  } catch (error) { await dispose(); busy = false; failure(error); render(); }
};
el('phone-unregister').onclick = async () => {
  busy = true; render(); await dispose(); busy = false; status('SIP 등록 해제됨'); render();
};
el('phone-call').onclick = async () => {
  if (!registered || !phone) return;
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    status('마이크 통화는 localhost 또는 HTTPS에서 지원됩니다.'); return;
  }
  busy = true; render(); status('마이크 권한 확인 및 발신 중…');
  try {
    await phone.call(`sip:${el('phone-destination').value}@asterisk`, undefined, {
      requestDelegate: {onReject(response) { status(`발신 거절 (${response.message.statusCode})`); }}
    });
  } catch (error) {
    try { await phone.hangup(); } catch {}
    busy = false; calling = false; failure(error); render();
  }
};
el('phone-hangup').onclick = async () => {
  try { await phone.hangup(); } catch (error) { failure(error); }
};
window.addEventListener('pagehide', () => { phone?.disconnect().catch(() => {}); });
render();
