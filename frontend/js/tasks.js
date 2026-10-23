/** 长任务轮询（S2-03：500ms；成功读 result 后 DELETE 清理）。
 *
 * 供备份 / 恢复（2.9）、导出（2.10）、重建索引（2.11）复用。
 */

import { request } from './api.js';

const POLL_MS = 500;
const DEFAULT_TIMEOUT_MS = 120 * 1000;

export function runTask(tid, { onProgress, timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
  return new Promise((resolve, reject) => {
    const started = Date.now();

    const poll = async () => {
      try {
        const data = await request(`/api/tasks/${tid}`);
        if (onProgress) {
          onProgress(data);
        }
        if (data.state === 'success') {
          await request(`/api/tasks/${tid}`, { method: 'DELETE' }).catch(() => {});
          resolve(data);
          return;
        }
        if (data.state === 'failed') {
          reject(new Error(data.error || '任务失败'));
          return;
        }
        if (Date.now() - started > timeoutMs) {
          reject(new Error('任务超时'));
          return;
        }
        window.setTimeout(poll, POLL_MS);
      } catch (error) {
        reject(error);
      }
    };

    poll();
  });
}
