import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';
import {createHash} from 'node:crypto';

const source = readFileSync(new URL('../src/phone.js', import.meta.url), 'utf8').replace("import { Web } from 'sip.js';", '');
const html = readFileSync(new URL('../../stt-server/static/index.html', import.meta.url), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));

test('page loads the current bundle through a content-versioned URL', () => {
  const bundle = readFileSync(new URL('../../stt-server/static/phone.js', import.meta.url));
  const version = createHash('sha256').update(bundle).digest('hex').slice(0, 16);
  assert.ok(html.includes(`src="/static/phone.js?v=${version}"`), 'Run npm run build to update the page and bundle together');
});

async function setup({secure = true, permission = 'prompt', reject = false} = {}) {
  const elements = Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(([, id]) =>
    [id, {textContent: '', value: 'test', play: async () => {}}]));
  const intervals = [];
  let instance, permissionRequests = 0, registrations = 0;
  class SimpleUser {
    constructor(url, options) { this.delegate = options.delegate; instance = this; }
    async connect() {}
    async register(options) {
      registrations++;
      if (reject) options.requestDelegate.onReject({message: {statusCode: 403}});
      else this.delegate.onRegistered();
    }
    async unregister() { this.delegate.onUnregistered(); }
    async disconnect() {}
    async call(destination) {
      assert.equal(destination, 'sip:9998@asterisk');
      this.delegate.onCallCreated();
      this.track = {label: 'USB 마이크', readyState: 'live', enabled: true, muted: false};
      this.localMediaStream = {getAudioTracks: () => [this.track]};
      this.delegate.onCallAnswered();
    }
    async hangup() { this.localMediaStream = undefined; this.delegate.onCallHangup(); }
  }
  vm.runInNewContext(source, {
    Web: {SimpleUser}, document: {getElementById(id) { assert.ok(elements[id], `Missing element: ${id}`); return elements[id]; }},
    location: {protocol: 'http:', host: 'localhost:8000'},
    window: {isSecureContext: secure, addEventListener() {}},
    navigator: {
      permissions: {query: async () => ({state: permission, addEventListener() {}})},
      mediaDevices: {getUserMedia() { permissionRequests++; }, addEventListener() {},
        enumerateDevices: async () => [{kind: 'audioinput', deviceId: 'default', label: '기본값 - USB 마이크'}]}
    },
    setInterval(fn) { intervals.push(fn); }, clearInterval() {}
  });
  await flush();
  return {elements, intervals, get instance() { return instance; },
    get registrations() { return registrations; }, get permissionRequests() { return permissionRequests; }};
}

test('loads with automatic SIP registration, without opening the microphone', async () => {
  const app = await setup();
  assert.equal(app.registrations, 1);
  assert.equal(app.permissionRequests, 0);
  assert.equal(app.elements['microphone-call'].disabled, false);
  assert.match(app.elements['sip-connection-state'].textContent, /등록됨/);
  assert.equal(app.elements['microphone-device'].textContent, '사용 중인 장치 없음');
});

test('shows the actual call track, mute and disconnect states, and clears on hangup', async () => {
  const app = await setup();
  await app.elements['microphone-call'].onclick();
  assert.equal(app.elements['microphone-device'].textContent, 'USB 마이크');
  app.instance.track.muted = true;
  app.intervals[0]();
  assert.match(app.elements['microphone-state'].textContent, /음소거/);
  app.instance.track.readyState = 'ended';
  app.intervals[0]();
  assert.match(app.elements['microphone-state'].textContent, /연결 종료/);
  await app.elements['phone-hangup'].onclick();
  assert.equal(app.elements['microphone-device'].textContent, '사용 중인 장치 없음');
  assert.match(app.elements['microphone-state'].textContent, /대기/);
});

test('registration rejection keeps calling disabled and explains recovery', async () => {
  const app = await setup({reject: true});
  assert.equal(app.elements['microphone-call'].disabled, true);
  assert.match(app.elements['notice'].textContent, /새로고침/);
  assert.equal(app.registrations, 1);
});

test('reports denied permission and insecure-context limitations', async () => {
  const denied = await setup({permission: 'denied'});
  assert.match(denied.elements['microphone-state'].textContent, /권한 차단/);
  const insecure = await setup({secure: false});
  assert.match(insecure.elements['microphone-state'].textContent, /사용 불가/);
});
