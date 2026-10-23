/** 展示层格式化纯函数单测（阶段三 3.3）。
 *
 * 运行：node --test tests/js/format.test.js
 *     或者走 pytest 入口 tests/test_frontend_js.py
 *
 * 时间断言全部用**本地时间构造**输入，因此换时区跑也不会失败。
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  formatCount,
  formatDuration,
  initialOf,
  percentLabel,
  progressPercent,
  relativeTime,
} from '../../frontend/js/format.js';

const NOW = new Date(2026, 9, 24, 9, 0, 0); // 2026-10-24 09:00（本地时区）

test('relativeTime：空值与不可解析返回空串', () => {
  assert.equal(relativeTime(null, NOW), '');
  assert.equal(relativeTime(undefined, NOW), '');
  assert.equal(relativeTime('', NOW), '');
  assert.equal(relativeTime('不是时间', NOW), '');
});

test('relativeTime：一分钟内是「刚刚」，一小时内按分钟', () => {
  assert.equal(relativeTime(new Date(2026, 9, 24, 8, 59, 30), NOW), '刚刚');
  assert.equal(relativeTime(new Date(2026, 9, 24, 8, 30, 0), NOW), '30 分钟前');
  assert.equal(relativeTime(new Date(2026, 9, 24, 8, 1, 0), NOW), '59 分钟前');
});

test('relativeTime：今天 / 昨天带时刻', () => {
  assert.equal(relativeTime(new Date(2026, 9, 24, 7, 5, 0), NOW), '今天 07:05');
  assert.equal(relativeTime(new Date(2026, 9, 23, 23, 59, 0), NOW), '昨天 23:59');
});

test('relativeTime：更早同年显示月日，跨年显示完整日期', () => {
  assert.equal(relativeTime(new Date(2026, 2, 5, 12, 0, 0), NOW), '03-05');
  assert.equal(relativeTime(new Date(2025, 11, 31, 12, 0, 0), NOW), '2025-12-31');
});

test('relativeTime：未来时间（时钟回拨）不显示负数', () => {
  assert.equal(relativeTime(new Date(2026, 9, 24, 9, 0, 30), NOW), '刚刚');
  assert.equal(relativeTime(new Date(2026, 9, 26, 9, 0, 0), NOW), '10-26');
});

test('relativeTime：ISO 字符串按本地时区折算', () => {
  const iso = new Date(2026, 9, 24, 8, 20, 0).toISOString();
  assert.equal(relativeTime(iso, NOW), '40 分钟前');
});

test('initialOf：书名首字，跳过书名号与前导空白', () => {
  assert.equal(initialOf('长夜将尽'), '长');
  assert.equal(initialOf('《潮汐》'), '潮');
  assert.equal(initialOf('  「灯塔」'), '灯');
  assert.equal(initialOf(''), '书');
  assert.equal(initialOf(null), '书');
  assert.equal(initialOf('   '), '书');
  // 按码点切分，不能把代理对拆一半
  assert.equal(initialOf('𝄞之歌'), '𝄞');
});

test('progressPercent：夹到 0~100，未知为 0', () => {
  assert.equal(progressPercent(null), 0);
  assert.equal(progressPercent(undefined), 0);
  assert.equal(progressPercent('abc'), 0);
  assert.equal(progressPercent(0), 0);
  assert.equal(progressPercent(0.5), 50);
  assert.equal(progressPercent(1), 100);
  assert.equal(progressPercent(2), 100);
  assert.equal(progressPercent(-1), 0);
});

test('percentLabel：未设目标为空，极小进度显示 <1%', () => {
  assert.equal(percentLabel(null), '');
  assert.equal(percentLabel(0), '0%');
  assert.equal(percentLabel(0.004), '<1%');
  assert.equal(percentLabel(0.456), '46%');
  assert.equal(percentLabel(1), '100%');
  assert.equal(percentLabel(3), '100%');
});

test('formatCount：一万以下按字，以上按万字', () => {
  assert.equal(formatCount(0), '0 字');
  assert.equal(formatCount(1234), '1234 字');
  assert.equal(formatCount(9999), '9999 字');
  assert.equal(formatCount(12000), '1.2 万字');
  assert.equal(formatCount('250000'), '25.0 万字');
});

test('formatDuration：秒与分秒', () => {
  assert.equal(formatDuration(0), '0 秒');
  assert.equal(formatDuration(45), '45 秒');
  assert.equal(formatDuration(80), '1 分 20 秒');
  assert.equal(formatDuration(120), '2 分钟');
});
