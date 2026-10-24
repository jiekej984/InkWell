/** 单章容量提示纯函数单测（阶段三 3.4 / FR-3.9）。
 *
 * 运行：node --test tests/js/capacity.test.js
 *     或者走 pytest 入口 tests/test_frontend_js.py
 *
 * 关注三件事：
 *   1. 两档阈值（5 万提示 / 8 万建议拆章）的边界不能错一格；
 *   2. 脏输入（NaN / 负数 / null / 字符串）不许抛异常 —— 状态栏在每次输入后都会调它；
 *   3. 文案必须带数字与动作建议，且 level 随字数单调不减。
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  CAPACITY_SPLIT,
  CAPACITY_WARN,
  chapterCapacity,
  formatWan,
} from '../../frontend/js/capacity.js';

test('阈值常量与报告口径一致（5 万 / 8 万）', () => {
  assert.equal(CAPACITY_WARN, 50000);
  assert.equal(CAPACITY_SPLIT, 80000);
});

test('formatWan：整万不留小数，非整万保留一位', () => {
  assert.equal(formatWan(50000), '5 万字');
  assert.equal(formatWan(82000), '8.2 万字');
  assert.equal(formatWan(123456), '12.3 万字');
});

test('formatWan：不足一万按字给（不会出现 0.5 万字）', () => {
  assert.equal(formatWan(0), '0 字');
  assert.equal(formatWan(9999), '9,999 字');
  assert.equal(formatWan(1234), '1,234 字');
});

test('level：阈值以下为 ok，5 万起 warn，8 万起 split', () => {
  assert.equal(chapterCapacity(0).level, 'ok');
  assert.equal(chapterCapacity(49999).level, 'ok');
  assert.equal(chapterCapacity(50000).level, 'warn');
  assert.equal(chapterCapacity(79999).level, 'warn');
  assert.equal(chapterCapacity(80000).level, 'split');
  assert.equal(chapterCapacity(123456).level, 'split');
});

test('ok 档不产生文案（调用方据此隐藏提示）', () => {
  const info = chapterCapacity(3200);
  assert.equal(info.label, '');
  assert.equal(info.detail, '');
});

test('warn 档：文案带当前字数与「5 万字」口径，detail 不阻断', () => {
  const info = chapterCapacity(52000);
  assert.equal(info.words, 52000);
  assert.match(info.label, /5\.2 万字/);
  assert.match(info.label, /5 万字/);
  assert.match(info.detail, /NFR-P2|AC-1/);
  assert.match(info.detail, /不受影响/);
});

test('split 档（回归 20 的 8 万字场景）：明确建议拆章且说明不影响保存', () => {
  const info = chapterCapacity(82000);
  assert.equal(info.words, 82000);
  assert.match(info.label, /8\.2 万字/);
  assert.match(info.label, /建议拆章/);
  assert.match(info.label, /不影响保存/);
  assert.match(info.detail, /拆成两三章/);
});

test('脏输入一律归一为 0，不抛异常', () => {
  for (const value of [null, undefined, NaN, -1, -99999, '不是数字', {}, []]) {
    const info = chapterCapacity(value);
    assert.equal(info.level, 'ok', `输入 ${String(value)} 应判为 ok`);
    assert.equal(info.words, 0);
  }
});

test('小数与字符串数字按整数处理', () => {
  assert.equal(chapterCapacity(52000.8).words, 52000);
  assert.equal(chapterCapacity('80000').level, 'split');
});

test('level 随字数单调不减（ok → warn → split，不会回落）', () => {
  const order = { ok: 0, warn: 1, split: 2 };
  let last = 0;
  for (let words = 0; words <= 200000; words += 5000) {
    const current = order[chapterCapacity(words).level];
    assert.ok(current >= last, `${words} 字的等级回退了`);
    last = current;
  }
});

test('极端大数不会溢出或改档', () => {
  const info = chapterCapacity(Number.MAX_SAFE_INTEGER);
  assert.equal(info.level, 'split');
  assert.ok(info.label.length > 0);
});
