import { SimpleUser } from "sip.js/lib/platform/web/index.js";

const $ = (id) => document.getElementById(id);
const state = { registration: "offline", call: "idle", muted: false };
let user;
let inquiryKey;
let audioContext;
let meterSource;
let meterFrame;
let timer;
let registrationTimer;
let startedAt;
const remoteAudio = $("remote-audio");
remoteAudio.volume = 0.8;

function record(message) {
  const list = $("events");
  list.querySelector(".empty")?.remove();
  const item = document.createElement("li");
  const time = document.createElement("time");
  const now = new Date();
  const pad = value => String(value).padStart(2, "0");
  time.dateTime = now.toISOString();
  const date = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  const clock = `${pad(now.getHours() % 12 || 12)}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
  time.textContent = `${date} ${clock}`;
  const text = document.createElement("span");
  text.textContent = message;
  item.append(time, text);
  list.prepend(item);
  while (list.children.length > 6) list.lastChild.remove();
}

function showError(message = "") {
  $("error").textContent = message;
  $("error").hidden = !message;
}

function render() {
  const calling = state.call !== "idle";
  const ready = state.registration === "ready";
  const status = calling ? state.call : state.registration;
  $("status").dataset.state = status;
  $("status").hidden = status === "offline";
  $("status").textContent = ({ offline: "", connecting: "연결 중", ready: "연결됨", dialing: "발신 중", active: "통화 중", ending: "종료 중" })[status];
  $("connect").textContent = ready ? "전화기 연결 해제" : state.registration === "connecting" ? "전화기 연결 중…" : "전화기 연결";
  $("connect").disabled = state.registration === "connecting" || calling;
  $("call-router").disabled = !ready || calling;
  $("hangup").disabled = !calling || state.call === "ending";
  $("mute").disabled = state.call !== "active";
  $("mute").textContent = state.muted ? "마이크 켜기" : "마이크 끄기";
  $("mute").setAttribute("aria-pressed", String(state.muted));
  $("call-label").textContent = calling ? "문의 안내 테스트 · 7000" : ready ? "전화할 준비가 됐습니다" : "통화 준비";
  $("call-description").textContent = state.call === "active" ? state.muted ? "마이크가 꺼져 있습니다." : "마이크가 켜져 있습니다." : state.call === "dialing" ? "마이크를 허용하고 잠시 기다려 주세요." : ready ? "문의 안내 테스트를 눌러 주세요." : "아래 버튼으로 전화기를 연결해 주세요.";
}

function stopMediaDisplay() {
  clearInterval(timer);
  cancelAnimationFrame(meterFrame);
  meterSource?.disconnect();
  meterSource = undefined;
  $("mic-level").value = 0;
  $("duration").value = "00:00";
}

function ended() {
  const wasCalling = state.call !== "idle";
  state.call = "idle";
  state.muted = false;
  stopMediaDisplay();
  render();
  if (wasCalling) {
    record("통화가 종료되었습니다.");
    if (inquiryKey) void showTranscript(inquiryKey);
  }
}

function startMediaDisplay() {
  startedAt = Date.now();
  timer = setInterval(() => {
    const seconds = Math.floor((Date.now() - startedAt) / 1000);
    $("duration").value = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  }, 1000);
  const stream = user.localMediaStream;
  if (!stream || !audioContext) return;
  const analyser = audioContext.createAnalyser();
  analyser.fftSize = 256;
  meterSource = audioContext.createMediaStreamSource(stream);
  meterSource.connect(analyser);
  const samples = new Float32Array(analyser.fftSize);
  function draw() {
    analyser.getFloatTimeDomainData(samples);
    const rms = Math.sqrt(samples.reduce((sum, value) => sum + value * value, 0) / samples.length);
    $("mic-level").value = state.muted ? 0 : Math.min(1, rms * 6);
    meterFrame = requestAnimationFrame(draw);
  }
  draw();
}

async function disconnect() {
  clearTimeout(registrationTimer);
  const previous = user;
  user = undefined;
  state.registration = "offline";
  ended();
  await previous?.disconnect();
}

$("connect").addEventListener("click", async () => {
  showError();
  if (state.registration === "ready") {
    try { await disconnect(); record("전화기 연결을 해제했습니다."); }
    catch { showError("연결 해제 중 문제가 발생했습니다. 새로고침 후 다시 시도해 주세요."); }
    return;
  }
  state.registration = "connecting";
  render();
  try {
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      throw new Error("전화기는 http://localhost:8080 또는 http://127.0.0.1:8080에서 열어 주세요.");
    }
    const response = await fetch("/config.json", { cache: "no-store" });
    if (!response.ok) throw new Error("전화기 설정을 불러오지 못했습니다.");
    const config = await response.json();
    const current = new SimpleUser(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`, {
      aor: `sip:${config.username}@localhost`,
      media: { constraints: { audio: true, video: false }, remote: { audio: remoteAudio } },
      reconnectionAttempts: 0,
      userAgentOptions: {
        authorizationUsername: config.username,
        authorizationPassword: config.password,
        displayName: "Local Webphone",
        logBuiltinEnabled: false,
        sessionDescriptionHandlerFactoryOptions: { peerConnectionConfiguration: { iceServers: [] } },
      },
      delegate: {
        onRegistered() {
          if (user !== current) return;
          clearTimeout(registrationTimer);
          state.registration = "ready";
          record("전화기가 연결되었습니다.");
          render();
        },
        onUnregistered() {
          if (user !== current) return;
          state.registration = "offline";
          clearTimeout(registrationTimer);
          render();
          showError("전화기 등록이 해제되었습니다. 다시 연결해 주세요.");
          void disconnect().catch(() => {});
        },
        onServerDisconnect() {
          if (user !== current) return;
          record("서버와의 연결이 끊어졌습니다.");
          showError("서버 연결이 끊어졌습니다. 전화기를 다시 연결해 주세요.");
          void disconnect().catch(() => {});
        },
        onCallAnswered() {
          if (user !== current) return;
          state.call = "active";
          record("7000 통화가 연결되었습니다.");
          render();
          startMediaDisplay();
          remoteAudio.play().catch(() => showError("소리 재생이 차단되었습니다. 브라우저의 소리 재생 권한을 확인해 주세요."));
        },
        onCallHangup() { if (user === current) ended(); },
        onCallReceived() { void current.decline(); },
      },
    });
    // Retire any previous failed registration before creating another one.
    const previous = user;
    user = current;
    await previous?.disconnect();
    await current.connect();
    registrationTimer = setTimeout(() => {
      if (user !== current || state.registration !== "connecting") return;
      showError("전화기 등록 시간이 초과되었습니다. 다시 시도해 주세요.");
      void disconnect().catch(() => {});
    }, 15000);
    await current.register();
  } catch (error) {
    showError(error.message || "전화기 연결에 실패했습니다.");
    await disconnect().catch(() => {});
  }
});

async function showTranscript(key) {
  const output = $("transcript");
  output.textContent = "전사 결과를 확인하고 있습니다…";
  for (let attempt = 0; attempt < 300 && key === inquiryKey; attempt++) {
    try {
      const response = await fetch(`/inquiries/${key}`, { cache: "no-store", signal: AbortSignal.timeout(5000) });
      if (key !== inquiryKey) return;
      if (response.status === 404 && attempt >= 2) {
        output.textContent = "완료된 녹음이 없습니다. 첫 안내가 끝난 뒤 말하고 3초 동안 기다려 주세요.";
        return;
      }
      if (response.ok) {
        const result = await response.json();
        if (key !== inquiryKey) return;
        if (result.status === "done") {
          output.textContent = result.text || "인식된 단어가 없습니다.";
          return;
        }
        if (result.status === "failed") {
          output.textContent = "녹음 전사에 실패했습니다. 다시 통화해 주세요.";
          return;
        }
      } else if (response.status !== 404 && attempt >= 2) {
        break;
      }
    } catch {
      if (attempt >= 2) break;
    }
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  if (key === inquiryKey) output.textContent = "전사 결과를 가져오지 못했습니다. Whisper 서비스 상태를 확인해 주세요.";
}

async function callInquiry() {
  if (state.registration !== "ready" || state.call !== "idle") return;
  showError();
  inquiryKey = crypto.randomUUID().replaceAll("-", "");
  $("transcript").textContent = "첫 안내가 끝나면 문의를 말씀해 주세요.";
  state.call = "dialing";
  render();
  record("7000에 전화합니다.");
  try {
    // Resume from the click gesture so the meter/audio can run under autoplay rules.
    audioContext ??= new AudioContext();
    await audioContext.resume();
    await user.call("sip:7000@localhost", { extraHeaders: [`X-Inquiry-Key: ${inquiryKey}`] });
  } catch (error) {
    const message = error.name === "NotAllowedError" ? "마이크 권한이 거부되었습니다. 주소창의 사이트 설정에서 마이크를 허용해 주세요." : error.name === "NotFoundError" ? "사용할 마이크를 찾지 못했습니다. 마이크 연결을 확인해 주세요." : "통화를 시작하지 못했습니다. 마이크와 전화기 연결을 확인해 주세요.";
    showError(message);
    await user?.hangup().catch(() => {});
    ended();
  }
}

$("call-router").addEventListener("click", callInquiry);
$("hangup").addEventListener("click", async () => {
  if (state.call === "idle" || state.call === "ending") return;
  state.call = "ending";
  render();
  try { await user.hangup(); }
  catch { showError("통화 종료 요청을 확인하지 못했습니다. 전화기를 다시 연결해 주세요."); }
  finally { ended(); }
});
$("mute").addEventListener("click", () => {
  if (state.call !== "active") return;
  state.muted ? user.unmute() : user.mute();
  state.muted = !state.muted;
  record(state.muted ? "마이크를 껐습니다." : "마이크를 켰습니다.");
  render();
});
$("volume").addEventListener("input", () => { remoteAudio.volume = Number($("volume").value); });
// Best-effort SIP cleanup when leaving; Asterisk's RTP timeout covers abrupt exits.
window.addEventListener("pagehide", () => { void user?.disconnect().catch(() => {}); });
render();
