/** 自动保存调度单测（任务 2.4 / D-03 / BR-2）。
 *
 * 用可手动推进的假时钟断言真实时序：停输 3s、最长 30s、失败 1s/3s/9s、
 * 三次重试耗尽后交由调用方落本地暂存、3002 冲突不重试。
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { createAutosave } from '../../frontend/js/autosave.js';
import { FakeClock, installWindow } from './support/env.js';

function setup(saveImpl) {
  const clock = new FakeClock();
  installWindow({ clock });
  const statuses = [];
  const autosave = createAutosave({
    save: saveImpl,
    onStatus: (message, kind) => statuses.push([message, kind]),
  });
  return { clock, statuses, autosave };
}

test('BR-2：连续失败按 1s / 3s / 9s 重试三次，耗尽后提示已本地暂存', async () => {
  const calls = [];
  const { clock, statuses, autosave } = setup(async (reason) => {
    calls.push(reason);
    return { ok: false, message: 'PUT /api/chapters/1/content 失败：HTTP 500' };
  });

  autosave.schedule();
  assert.equal(autosave.hasPending(), true);

  await clock.advance(2999);
  assert.equal(calls.length, 0, '停输未满 3s 不应保存');
  await clock.advance(1);
  assert.deepEqual(calls, ['debounce'], '停输 3s 触发首次保存');
  assert.equal(clock.pending, 2, '应排入 1s 重试与 30s 最长间隔两个计时器');

  await clock.advance(1000);
  assert.equal(calls.length, 2, '第 1 次重试在 1s 后');
  await clock.advance(3000);
  assert.equal(calls.length, 3, '第 2 次重试在 3s 后');
  await clock.advance(9000);
  assert.equal(calls.length, 4, '第 3 次重试在 9s 后');

  assert.equal(autosave.hasPending(), false, '重试耗尽后不应再有待执行计时器');
  assert.deepEqual(statuses, [
    ['保存失败，1 秒后重试（1/3）', 'error'],
    ['保存失败，3 秒后重试（2/3）', 'error'],
    ['保存失败，9 秒后重试（3/3）', 'error'],
    ['保存失败，已本地暂存', 'error'],
  ]);
});

test('D-03：持续输入时 30s 最长间隔强制保存一次', async () => {
  const calls = [];
  const { clock, autosave } = setup(async (reason) => {
    calls.push(reason);
    return { ok: true };
  });

  autosave.schedule();
  for (let elapsed = 0; elapsed < 28000; elapsed += 2000) {
    await clock.advance(2000);
    autosave.schedule(); // 模拟每 2s 有一次输入，停输计时器不断重置
  }
  assert.equal(calls.length, 0, '持续输入时不能每 3s 保存一次');

  await clock.advance(2000); // 到达 30s
  assert.deepEqual(calls, ['max-interval'], '30s 最长间隔必须强制保存');
  assert.equal(clock.pending, 0);
});

test('保存成功后重试计数归零，下一轮仍从 1/3 开始', async () => {
  const results = [false, false, true, false];
  const { clock, statuses, autosave } = setup(async () => ({
    ok: results.length === 0 ? true : results.shift(),
  }));

  assert.equal(await autosave.flush('manual'), false);
  await clock.advance(1000); // 第 1 次重试仍失败
  await clock.advance(3000); // 第 2 次重试成功

  assert.equal(await autosave.flush('manual'), false, '成功后再次失败应重新计数');
  assert.deepEqual(statuses, [
    ['保存失败，1 秒后重试（1/3）', 'error'],
    ['保存失败，3 秒后重试（2/3）', 'error'],
    ['保存失败，1 秒后重试（1/3）', 'error'],
  ]);
  autosave.stop();
  assert.equal(clock.pending, 0);
});

test('3002 版本冲突不重试，直接提示用户', async () => {
  const calls = [];
  const conflictMessage = 'PUT /api/chapters/1/content 失败：code=3002 版本冲突';
  const { clock, statuses, autosave } = setup(async () => {
    calls.push('save');
    return { ok: false, conflict: true, message: conflictMessage };
  });

  const saved = await autosave.flush('manual');
  assert.equal(saved, false);
  assert.equal(calls.length, 1);
  assert.equal(clock.pending, 0, '冲突不应排重试计时器');
  assert.deepEqual(statuses, [[conflictMessage, 'error']]);
});

test('flush 立即保存并清空待执行计时器', async () => {
  let calls = 0;
  const { clock, autosave } = setup(async () => {
    calls += 1;
    return { ok: true };
  });

  autosave.schedule();
  assert.equal(autosave.hasPending(), true);
  assert.equal(await autosave.flush('manual'), true);
  assert.equal(calls, 1);
  assert.equal(clock.pending, 0);

  await clock.advance(30000);
  assert.equal(calls, 1, '已清空的计时器不应再次触发保存');
});
