/** 自动保存调度（任务 2.4 / D-03：停输 3s 或最长 30s）。
 *
 * 失败重试 1s / 3s / 9s（BR-2）；3 次仍失败时由调用方落本地双份暂存。
 * 版本冲突（3002）不重试 —— 重试只会再次冲突，必须先恢复/刷新。
 *
 * ``save`` 约定返回 ``{ ok, conflict, message }``；本模块不关心具体保存实现。
 */

export const DEBOUNCE_MS = 3000;
export const MAX_INTERVAL_MS = 30000;
export const RETRY_DELAYS_MS = [1000, 3000, 9000];

export function createAutosave({
  save,
  onStatus,
  debounceMs = DEBOUNCE_MS,
  maxIntervalMs = MAX_INTERVAL_MS,
}) {
  let debounceTimer = null;
  let maxTimer = null;
  let retryTimer = null;
  let retryCount = 0;
  let inFlight = false;
  let disposed = false;

  function clearDebounce() {
    if (debounceTimer !== null) {
      window.clearTimeout(debounceTimer);
      debounceTimer = null;
    }
  }

  function clearMax() {
    if (maxTimer !== null) {
      window.clearTimeout(maxTimer);
      maxTimer = null;
    }
  }

  function clearRetry() {
    if (retryTimer !== null) {
      window.clearTimeout(retryTimer);
      retryTimer = null;
    }
  }

  function report(message, kind) {
    if (onStatus) {
      onStatus(message, kind);
    }
  }

  /** 内容变化后调用：重新计时 3s，同时保留 30s 最长间隔。 */
  function schedule() {
    if (disposed || inFlight) {
      return;
    }
    clearDebounce();
    debounceTimer = window.setTimeout(() => {
      debounceTimer = null;
      flush('debounce');
    }, debounceMs);
    if (maxTimer === null) {
      maxTimer = window.setTimeout(() => {
        maxTimer = null;
        clearDebounce();
        flush('max-interval');
      }, maxIntervalMs);
    }
  }

  /** 立即保存（手动 / 切换章节 / 离开页面）。 */
  async function flush(reason = 'manual') {
    if (disposed || inFlight) {
      return false;
    }
    clearDebounce();
    inFlight = true;
    try {
      const result = await save(reason);
      if (result && result.ok) {
        retryCount = 0;
        clearRetry();
        clearMax();
        return true;
      }
      if (result && result.conflict) {
        clearRetry();
        clearMax();
        report(result.message || '版本冲突，内容已本地暂存', 'error');
        return false;
      }
      if (retryCount < RETRY_DELAYS_MS.length) {
        const delay = RETRY_DELAYS_MS[retryCount];
        retryCount += 1;
        report(`保存失败，${delay / 1000} 秒后重试（${retryCount}/3）`, 'error');
        clearRetry();
        retryTimer = window.setTimeout(() => {
          retryTimer = null;
          flush('retry');
        }, delay);
        return false;
      }
      clearMax();
      report('保存失败，已本地暂存', 'error');
      return false;
    } finally {
      inFlight = false;
    }
  }

  function reset() {
    clearDebounce();
    clearMax();
    clearRetry();
    retryCount = 0;
  }

  function stop() {
    disposed = true;
    reset();
  }

  function hasPending() {
    return debounceTimer !== null || maxTimer !== null || retryTimer !== null;
  }

  return { schedule, flush, reset, stop, hasPending };
}
