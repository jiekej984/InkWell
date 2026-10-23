/** 双份暂存与恢复链路单测（任务 2.4 / BR-2 / 回归 15）。
 *
 * 只替换 localStorage 与 HTTP 两层（Node 无浏览器），
 * 被测对象是真实的 autosave.js / fallback.js / pending.js / api.js。
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { request } from '../../frontend/js/api.js';
import { createAutosave } from '../../frontend/js/autosave.js';
import { createDraftStore, isConflictError } from '../../frontend/js/fallback.js';
import {
  FakeClock,
  createDraftBackend,
  installFetch,
  installWindow,
  silentLog,
} from './support/env.js';

test('回归 15：保存连续失败 → 双份暂存 → 重启后恢复并自动补写', async () => {
  const backend = createDraftBackend();
  const { clock, storage } = installWindow({ clock: new FakeClock() });
  let offline = true;
  installFetch((req) => {
    if (offline && req.path.startsWith('/api/chapters/')) {
      throw new TypeError('Failed to fetch'); // 模拟后端不可用
    }
    return backend.handle(req);
  });

  const store = createDraftStore({ log: silentLog });
  let currentHtml = '<p>强杀前最后一段：深夜的码头</p>';

  /** 与 writer.js 的 saveContent 同构：成功清暂存，失败落双份暂存。 */
  async function saveContent() {
    try {
      await request('/api/chapters/1/content', {
        method: 'PUT',
        body: { content_html: currentHtml },
      });
      await store.clear(1);
      return { ok: true };
    } catch (error) {
      await store.persist(1, currentHtml, 'save_failed');
      return {
        ok: false,
        conflict: isConflictError(error),
        message: error.message,
      };
    }
  }

  const statuses = [];
  const autosave = createAutosave({
    save: saveContent,
    onStatus: (message) => statuses.push(message),
  });

  autosave.schedule();
  await clock.advance(3000); // 首次保存失败
  await clock.advance(1000); // 重试 1/3
  await clock.advance(3000); // 重试 2/3
  await clock.advance(9000); // 重试 3/3 → 耗尽

  assert.equal(autosave.hasPending(), false);
  assert.equal(statuses.at(-1), '保存失败，已本地暂存');
  assert.ok(storage.getItem('inkwell:draft:1'), 'localStorage 应留下第一份暂存');
  assert.equal(
    backend.drafts.get(1)?.content_html,
    currentHtml,
    '服务端 drafts/ 应留下第二份暂存',
  );

  // 「重启」：新进程只有两份暂存，服务端优先恢复
  const restarted = createDraftStore({ log: silentLog });
  const draft = await restarted.recover(1);
  assert.ok(draft, '重启后应能读到暂存');
  assert.equal(draft.content_html, currentHtml);

  // 恢复后自动补写：正文写回成功，双份暂存一并清理
  currentHtml = draft.content_html;
  offline = false;
  const result = await saveContent();

  assert.deepEqual(result, { ok: true });
  assert.equal(backend.chapters.get(1), currentHtml, '补写应写回恢复出的正文');
  assert.equal(backend.drafts.size, 0, '补写成功后服务端暂存应清空');
  assert.equal(storage.getItem('inkwell:draft:1'), null, '补写成功后本地暂存应清空');
});

test('服务端暂存缺失时从 localStorage 恢复', async () => {
  const backend = createDraftBackend();
  const { storage } = installWindow({ clock: new FakeClock() });
  installFetch((req) => backend.handle(req));

  const store = createDraftStore({ log: silentLog });
  assert.equal(await store.recover(1), null, '两份都没有时应返回 null');

  storage.setItem(
    'inkwell:draft:1',
    JSON.stringify({
      content: '<p>本地兜底内容</p>',
      saved_at: '2026-10-23T10:00:00Z',
      reason: 'editing',
    }),
  );

  const draft = await store.recover(1);
  assert.equal(draft.content_html, '<p>本地兜底内容</p>');
  assert.equal(draft.saved_at, '2026-10-23T10:00:00Z');
  assert.equal(draft.reason, 'editing');
});

test('服务端暂存失败时本地仍落盘，不阻断写作', async () => {
  const { storage } = installWindow({ clock: new FakeClock() });
  installFetch(() => {
    throw new TypeError('Failed to fetch');
  });

  const store = createDraftStore({ log: silentLog });
  const result = await store.persist(9, '<p>离线内容</p>', 'save_failed');

  assert.deepEqual(result, { local: true, remote: false });
  assert.match(String(storage.getItem('inkwell:draft:9')), /离线内容/);
});

test('清理暂存时服务端不存在（2001）不算错误', async () => {
  const backend = createDraftBackend();
  const { storage } = installWindow({ clock: new FakeClock() });
  installFetch((req) => backend.handle(req));

  const store = createDraftStore({ log: silentLog });
  storage.setItem('inkwell:draft:5', '{"content":"<p>x</p>"}');

  await store.clear(5); // 服务端没有该暂存 → 2001，应静默
  assert.equal(storage.getItem('inkwell:draft:5'), null);
});

test('isConflictError 只识别 3002', () => {
  assert.equal(isConflictError(new Error('PUT /x 失败：code=3002 版本冲突')), true);
  assert.equal(isConflictError(new Error('PUT /x 失败：code=4002 文件不合法')), false);
  assert.equal(isConflictError(null), false);
});
