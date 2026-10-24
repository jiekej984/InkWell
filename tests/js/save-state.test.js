/** 保存三态单测（阶段三 3.5 / 报告 §7.4 / 回归 23）。
 *
 * 状态栏的颜色/图标/文案/动作都由 `savestate.js` 的纯函数决定，
 * 这里直接把「三重编码」钉死：任一状态缺图标或缺文案都算回归。
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  SAVE_ACTIONS,
  SAVE_STATES,
  clockLabel,
  describeSaveState,
} from '../../frontend/js/savestate.js';

test('三态：图标 + 文案 + 色调（不只靠颜色）', () => {
  const saving = describeSaveState(SAVE_STATES.SAVING);
  assert.equal(saving.text, '保存中…');
  assert.equal(saving.icon, '◌');
  assert.equal(saving.tone, 'saving');
  assert.deepEqual(saving.actions, []);

  const saved = describeSaveState(SAVE_STATES.SAVED, { at: '23:45' });
  assert.equal(saved.text, '已保存 23:45');
  assert.equal(saved.icon, '✓');
  assert.equal(saved.tone, 'success');

  const failed = describeSaveState(SAVE_STATES.FAILED);
  assert.equal(failed.text, '保存失败，已本地暂存');
  assert.equal(failed.icon, '⚠');
  assert.equal(failed.tone, 'danger');
  assert.deepEqual(failed.actions, [SAVE_ACTIONS.RETRY, SAVE_ACTIONS.EXPORT]);
});

test('saved 无时间时退化为「已保存」', () => {
  assert.equal(describeSaveState(SAVE_STATES.SAVED).text, '已保存');
  assert.equal(describeSaveState(SAVE_STATES.SAVED, { at: '' }).text, '已保存');
});

test('失败态保留重试倒计时文案，但动作按钮不丢', () => {
  const view = describeSaveState(SAVE_STATES.FAILED, {
    message: '保存失败，1 秒后重试（1/3）',
  });
  assert.equal(view.text, '保存失败，1 秒后重试（1/3）');
  assert.deepEqual(view.actions, [SAVE_ACTIONS.RETRY, SAVE_ACTIONS.EXPORT]);
});

test('3002 冲突态：刷新并恢复 + 导出本章，不提供「重试」', () => {
  const view = describeSaveState(SAVE_STATES.CONFLICT);
  assert.equal(view.text, '版本冲突，已本地暂存');
  assert.equal(view.icon, '⚠');
  assert.equal(view.tone, 'danger');
  assert.deepEqual(view.actions, [SAVE_ACTIONS.RELOAD, SAVE_ACTIONS.EXPORT]);
  assert.ok(!view.actions.includes(SAVE_ACTIONS.RETRY), '冲突重试只会再撞一次 3002');
});

test('编辑态 / 就绪态无动作按钮', () => {
  const editing = describeSaveState(SAVE_STATES.EDITING);
  assert.deepEqual(editing.actions, []);
  assert.equal(editing.icon, '✎');
  assert.equal(editing.text, '未保存');

  const idle = describeSaveState(SAVE_STATES.IDLE);
  assert.deepEqual(idle.actions, []);
  assert.equal(idle.text, '就绪');
});

test('未知状态回退 idle，不抛错', () => {
  const view = describeSaveState('unknown-state');
  assert.equal(view.state, SAVE_STATES.IDLE);
  assert.equal(view.text, '就绪');
});

test('clockLabel：补零、接受 Date 与字符串、非法值返回空串', () => {
  assert.equal(clockLabel(new Date(2026, 9, 24, 23, 45)), '23:45');
  assert.equal(clockLabel(new Date(2026, 9, 24, 9, 5)), '09:05');
  assert.equal(clockLabel('不是时间'), '');
  assert.equal(clockLabel('2026-10-24T12:00:00Z').length, 5);
});
