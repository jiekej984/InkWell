/** 章内查找的单测（阶段三 3.8 / 回归 25）。
 *
 * 只测纯函数 `findMatches()`：中英混排、emoji、大小写、正则特殊字符、不重叠。
 * DOM 高亮 / 滚动 / Esc 关闭由窗口冒烟覆盖（`tests/e2e/window_smoke.py`）。
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { findMatches } from '../../frontend/js/find.js';

test('中文短语：返回全部命中的 UTF-16 区间', () => {
  const text = '潮汐与灯塔。深夜的码头，潮汐又来了。';
  assert.deepEqual(findMatches(text, '潮汐'), [
    { start: 0, end: 2 },
    { start: 12, end: 14 },
  ]);
});

test('英文默认不区分大小写，开启后只命中原样', () => {
  const text = 'The Tide and the tide.';
  assert.equal(findMatches(text, 'tide').length, 2);
  assert.deepEqual(findMatches(text, 'tide', { caseSensitive: true }), [
    { start: 17, end: 21 },
  ]);
  assert.equal(findMatches(text, 'Tide', { caseSensitive: true }).length, 1);
});

test('emoji 按 UTF-16 下标命中，区间不拆代理对', () => {
  const text = '潮水退了 🌊🌙，她笑了 😀。';
  const hits = findMatches(text, '🌊');
  assert.equal(hits.length, 1);
  assert.equal(text.slice(hits[0].start, hits[0].end), '🌊');
  // 整个 emoji 占 2 个码元；下一个 emoji 仍从正确边界开始
  assert.equal(text.slice(hits[0].end, hits[0].end + 2), '🌙');
});

test('正则特殊字符按字面量查找', () => {
  const text = 'a.b*c（d）';
  assert.deepEqual(findMatches(text, 'a.b'), [{ start: 0, end: 3 }]);
  assert.equal(findMatches(text, 'b*c').length, 1);
  assert.equal(findMatches(text, '（d）').length, 1);
});

test('不重叠：aaaa 里找 aaa 只有一处', () => {
  assert.deepEqual(findMatches('aaaa', 'aaa'), [{ start: 0, end: 3 }]);
});

test('空查询 / 空文本 / 无命中返回空数组', () => {
  assert.deepEqual(findMatches('', '潮'), []);
  assert.deepEqual(findMatches('潮', ''), []);
  assert.deepEqual(findMatches('潮', '   '), []);
  assert.deepEqual(findMatches('潮', '汐'), []);
});

test('超长查询截到 200 字符，避免把整章粘进查找框', () => {
  const text = 'a'.repeat(500);
  const query = 'a'.repeat(300);
  const hits = findMatches(text, query);
  assert.equal(hits.length, 2, '500 个 a 里按 200 长度不重叠命中 2 处');
  assert.equal(hits[0].end - hits[0].start, 200);
});
