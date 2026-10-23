/** 前端日志脱敏单测（任务 2.13 / NFR-M4）。
 *
 * 防的是「碰巧安全」：即使日志参数里混入正文片段或密钥，
 * 也不能整条丢弃诊断信息，更不能把密钥原样带出去。
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { createLogger, redactSecrets, sanitizeText } from '../../frontend/js/logger.js';
import { FakeClock, flushTasks, installFetch, installWindow } from './support/env.js';

test('按值脱敏：只替换密钥值，保留路径与错误码', () => {
  assert.equal(
    redactSecrets('GET /api/search?q=黑水河&sig=SECRET123 失败：code=4004'),
    'GET /api/search?q=黑水河&sig=*** 失败：code=4004',
  );
  assert.equal(
    redactSecrets('X-Inkwell-Token: abcdefg'),
    'X-Inkwell-Token: ***',
  );
  assert.equal(redactSecrets('token=abc, level=error'), 'token=***, level=error');
  assert.equal(redactSecrets('signature="abc" 无效'), 'signature=*** 无效');
  // 没有「关键字=值」形态时不应误伤
  assert.equal(
    redactSecrets('token 已过期，请刷新页面'),
    'token 已过期，请刷新页面',
  );
});

test('sanitizeText 限长 1000 字符', () => {
  assert.equal(sanitizeText('甲'.repeat(1500)).length, 1000);
  assert.equal(sanitizeText({ code: 3002, message: '冲突' }), '{"code":3002,"message":"冲突"}');
});

test('error 上报前已完成脱敏（#44）', async () => {
  installWindow({ clock: new FakeClock() });
  const calls = [];
  installFetch((req) => {
    calls.push(req);
    return {
      ok: true,
      status: 200,
      json: async () => ({ code: 0, message: 'ok', data: { logged: true } }),
    };
  });

  const original = console.error;
  console.error = () => {};
  try {
    createLogger('writer').error('保存失败 token=RAW_SECRET 正文');
  } finally {
    console.error = original;
  }
  await flushTasks();

  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, '/api/system/logs');
  assert.match(calls[0].body.message, /token=\*\*\*/);
  assert.ok(!calls[0].body.message.includes('RAW_SECRET'));
  assert.match(calls[0].body.message, /保存失败/);
});
