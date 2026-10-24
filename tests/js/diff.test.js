/** 行级差异对比单测（阶段三 3.6 / P5 / FR-5.4）。
 *
 * 覆盖：增/删/改的行级判定、长段折叠、CRLF、空行忽略、5 万字与段落数双重上限。
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  CONTEXT_LINES,
  MAX_DIFF_CHARS,
  diffLines,
  splitLines,
} from '../../frontend/js/diff.js';

test('splitLines：去空行、统一 CRLF、去首尾空白', () => {
  assert.deepEqual(splitLines('第一段\r\n\r\n  第二段  \n'), ['第一段', '第二段']);
  assert.deepEqual(splitLines(''), []);
  assert.deepEqual(splitLines(null), []);
});

test('完全一致：全部 equal，统计为 0', () => {
  const result = diffLines('甲\n乙\n丙', '甲\n乙\n丙');
  assert.equal(result.tooLarge, false);
  assert.deepEqual(result.stats, { added: 0, removed: 0 });
  assert.equal(result.rows.every((row) => row.type === 'equal'), true);
  assert.deepEqual(result.lines, { before: 3, after: 3 });
});

test('新增行 / 删除行 / 修改行统计正确', () => {
  const added = diffLines('甲\n乙', '甲\n乙\n丙');
  assert.deepEqual(added.stats, { added: 1, removed: 0 });
  assert.equal(added.rows.at(-1).type, 'add');
  assert.equal(added.rows.at(-1).text, '丙');

  const removed = diffLines('甲\n乙\n丙', '甲\n乙');
  assert.deepEqual(removed.stats, { added: 0, removed: 1 });
  assert.equal(removed.rows.at(-1).type, 'del');

  const changed = diffLines('甲\n乙\n丙', '甲\n乙改\n丙');
  assert.deepEqual(changed.stats, { added: 1, removed: 1 });
  assert.deepEqual(
    changed.rows.map((row) => row.type),
    ['equal', 'del', 'add', 'equal'],
  );
});

test('长段相同内容折叠为 skip，并保留上下文', () => {
  const before = Array.from({ length: 20 }, (_, i) => `第 ${i} 行`).join('\n');
  const after = `${before}\n新增一行`;
  const result = diffLines(before, after);

  const skip = result.rows.find((row) => row.type === 'skip');
  assert.ok(skip, '20 行相同内容应被折叠');
  assert.equal(skip.count, 20 - CONTEXT_LINES * 2, '折叠掉中间 14 行');
  const contextEquals = result.rows.filter((row) => row.type === 'equal').length;
  assert.equal(contextEquals, CONTEXT_LINES * 2, '折叠后上下文各保留 3 行');
});

test('超过 5 万字符（按码点计）返回 tooLarge，不渲染差异', () => {
  const big = '字'.repeat(MAX_DIFF_CHARS + 1);
  const result = diffLines(big, '小段');
  assert.equal(result.tooLarge, true);
  assert.deepEqual(result.rows, []);
  assert.match(result.reason, /上限/);

  // emoji 占两个 UTF-16 单元、一个码点：5000 个 emoji 仍远低于上限
  const emoji = '😀'.repeat(5000);
  assert.equal(diffLines(emoji, emoji).tooLarge, false);
});

test('段落数过多（n×m 超上限）也走 tooLarge，避免卡死界面', () => {
  const many = Array.from({ length: 2001 }, (_, i) => `行${i}`).join('\n');
  const result = diffLines(many, `${many}\n尾行`);
  assert.equal(result.tooLarge, true);
  assert.match(result.reason, /段落过多/);
});

test('自定义 context 生效', () => {
  const before = Array.from({ length: 12 }, (_, i) => `L${i}`).join('\n');
  const result = diffLines(before, `${before}\n追加`, { context: 1 });
  const equals = result.rows.filter((row) => row.type === 'equal').length;
  assert.equal(equals, 2);
});
