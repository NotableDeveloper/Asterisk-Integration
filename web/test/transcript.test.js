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
  assert.equal(elements.feed.children[0].querySelector('.text').textContent, '<확정 결과>');
  assert.equal(elements.count.textContent, '1 문장');
});
