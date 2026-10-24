import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';

const html = readFileSync(new URL('../../stt-server/static/index.html', import.meta.url), 'utf8');
const script = html.split('<script>')[1].split('function setConnection')[0];

test('live and snapshot partials stay hidden; finals render as text once', () => {
  function element() {
    return {children: [], textContent: '', append(...items) {this.children.push(...items)},
      remove() {}, querySelector(selector) {
        return this.children.flatMap(child => [child, ...child.children])
          .find(child => child.className === selector.slice(1));
      }};
  }
  const elements = Object.fromEntries(['feed', 'empty', 'count'].map(id => [id, element()]));
  const context = vm.createContext({document: {
    getElementById: id => elements[id], createElement: element,
  }});
  vm.runInContext(script, context);
  const send = event => {context.message = event; vm.runInContext('event(message)', context)};
  const base = {call_id: 'call', speaker: 'customer', segment_id: 0};
  send({type: 'snapshot', epoch: 'epoch', events: [{...base, id: 1, type: 'partial', text: '중간'}]});
  send({...base, id: 2, type: 'partial', text: '중간 결과'});
  assert.equal(elements.feed.children.length, 0);
  const final = {...base, id: 3, type: 'final', text: '<확정 결과>'};
  send(final);
  send({type: 'snapshot', epoch: 'epoch', events: [final]});
  assert.equal(elements.feed.children.length, 1);
  assert.equal(elements.feed.children[0].querySelector('.text').textContent, '고객 : <확정 결과>');
  assert.equal(elements.count.textContent, '1 문장');
  send({type: 'snapshot', epoch: 'epoch', events: [
    {...base, segment_id: 1, id: 4, type: 'final', text: '你好。こんにちは！'},
  ]});
  send({...base, segment_id: 2, id: 5, type: 'final', text: 'Привет! 😀'});
  assert.equal(elements.feed.children.length, 1);
  assert.equal(elements.count.textContent, '1 문장');
  const mixed = {...base, segment_id: 3, id: 6, type: 'final', text: '안녕하세요 日本語 Hello 123!'};
  send(mixed);
  assert.equal(elements.feed.children[1].querySelector('.text').textContent, '고객 : 안녕하세요 Hello 123!');
  assert.equal(elements.count.textContent, '2 문장');
  assert.equal(mixed.text, '안녕하세요 日本語 Hello 123!');
});

test('display filter preserves Korean, English and numbers without joining removed words', () => {
  const context = vm.createContext({});
  vm.runInContext(script, context);
  const clean = text => {context.text = text; return vm.runInContext('transcriptText(text)', context)};
  assert.equal(clean('한글 ABC xyz 123, 45.6%?'), '한글 ABC xyz 123, 45.6%?');
  assert.equal(clean('Hello你好world'), 'Hello world');
  assert.equal(clean('ㅎㅏ ㄱㄴ 한글'), 'ㅎㅏ ㄱㄴ 한글');
  assert.equal(clean('中文 日本語 العربية Русский 😀'), '');
});
