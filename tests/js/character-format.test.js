/** 角色库纯函数单测（V2.0 / 5.4）。 */

import assert from 'node:assert/strict';
import test from 'node:test';

import {
  appendAlias,
  characterInitial,
  characterSummary,
  formatTags,
  parseTags,
  saveStateText,
} from '../../frontend/js/character-format.js';

test('parseTags：中英文分隔符、去空、去重', () => {
  assert.deepEqual(parseTags('剑修，复仇线、剑修; 世家'), ['剑修', '复仇线', '世家']);
  assert.deepEqual(parseTags(''), []);
  assert.deepEqual(parseTags(null), []);
  assert.deepEqual(parseTags('  ， , 、 '), []);
});

test('parseTags：最多 20 个', () => {
  const text = Array.from({ length: 30 }, (_, i) => `标签${i}`).join('，');
  assert.equal(parseTags(text).length, 20);
});

test('formatTags 与 parseTags 互逆', () => {
  const tags = ['剑修', '复仇线'];
  assert.equal(formatTags(tags), '剑修，复仇线');
  assert.deepEqual(parseTags(formatTags(tags)), tags);
  assert.equal(formatTags(null), '');
});

test('characterInitial：取首字，空名回退', () => {
  assert.equal(characterInitial('林昭'), '林');
  assert.equal(characterInitial('  沈砚 '), '沈');
  assert.equal(characterInitial(''), '?');
  assert.equal(characterInitial(null), '?');
});

test('appendAlias：空值与重复忽略', () => {
  assert.deepEqual(appendAlias(['小昭'], '昭儿'), ['小昭', '昭儿']);
  assert.deepEqual(appendAlias(['小昭'], '小昭'), ['小昭']);
  assert.deepEqual(appendAlias(['小昭'], '  '), ['小昭']);
  assert.deepEqual(appendAlias(null, '阿蛮'), ['阿蛮']);
});

test('characterSummary：标签拼接与缺失回退', () => {
  assert.equal(
    characterSummary({ role_label: '主角', status_label: '存活' }),
    '主角 · 存活',
  );
  assert.equal(characterSummary({}), '未分类 · 状态未知');
  assert.equal(characterSummary(null), '未选择角色');
});

test('saveStateText：三态文案', () => {
  assert.equal(saveStateText('saving'), '保存中…');
  assert.equal(saveStateText('saved', '14:32'), '已保存 14:32');
  assert.equal(saveStateText('error', '', '网络错误'), '保存失败：网络错误');
  assert.equal(saveStateText('idle'), '就绪');
});
