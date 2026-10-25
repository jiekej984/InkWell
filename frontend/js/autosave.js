/** 自动保存调度（任务 2.4 / D-03：停输 3s 或最长 30s）。
 *
 * 失败重试 1s / 3s / 9s（BR-2）；3 次仍失败时由调用方落本地双份暂存。
 * 版本冲突（3002）不重试 —— 重试只会再次冲突，必须先恢复/刷新。
 *
 * ``save`` 约定返回 ``{ ok, conflict, message }``；本模块不关心具体保存实现。
 *
 * 阶段三 3.5：``onStatus(message, kind, meta)`` 第三参数给出结构化阶段，
 * 供状态栏三态区分「重试倒计时 / 重试耗尽 / 版本冲突」：
 *
 *     meta.phase = 'retry' | 'exhausted' | 'conflict'
 *     meta.attempt / meta.delayMs 仅在 retry 时有值
 *
 * ``retryNow()`` 供状态栏「重试」按钮使用：清零重试计数后立即保存，
 * 让手动重试重新走完整的 1s/3s/9s 阶梯，而不是一次失败就直接进暂存态。
 *
 * 自检修复：``flush()`` 遇到「正在保存」时不再直接返回 false，而是排队等待
 * 当前保存结束、再保存一次最新内容。调用方（切章 / Ctrl+S / 离开写作页）
 * 因此拿到的是真实结果 —— 之前会把「正在保存」误判为「保存失败」。
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
  let pendingSchedule = false;
  let disposed = false;
  // 串行队列：并发的 flush（例如切章与 Ctrl+S 同时发生）按调用顺序依次保存，
  // 后一次能看到前一次刚写完的内容与版本号。
  let chain = Promise.resolve(true);

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

  function report(message, kind, meta) {
    if (onStatus) {
      onStatus(message, kind, meta);
    }
  }

  /** 内容变化后调用：重新计时 3s，同时保留 30s 最长间隔。 */
  function schedule() {
    if (disposed) {
      return;
    }
    if (inFlight) {
      // 保存期间又输入了：等这次保存结束再排定，不能把输入事件丢掉
      pendingSchedule = true;
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

  /** 执行一次保存（由队列串行调用，不自行并发）。 */
  async function runSave(reason) {
    if (disposed) {
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
        report(result.message || '版本冲突，内容已本地暂存', 'error', {
          phase: 'conflict',
        });
        return false;
      }
      if (retryCount < RETRY_DELAYS_MS.length) {
        const delay = RETRY_DELAYS_MS[retryCount];
        retryCount += 1;
        report(`保存失败，${delay / 1000} 秒后重试（${retryCount}/3）`, 'error', {
          phase: 'retry',
          attempt: retryCount,
          delayMs: delay,
        });
        clearRetry();
        retryTimer = window.setTimeout(() => {
          retryTimer = null;
          flush('retry');
        }, delay);
        return false;
      }
      clearMax();
      report('保存失败，已本地暂存', 'error', { phase: 'exhausted' });
      return false;
    } finally {
      inFlight = false;
      if (pendingSchedule && !disposed) {
        pendingSchedule = false;
        schedule();
      }
    }
  }

  /** 立即保存（手动 / 切换章节 / 离开页面）；并发调用会排队等待。 */
  function flush(reason = 'manual') {
    if (disposed) {
      return Promise.resolve(false);
    }
    clearDebounce();
    const task = chain.then(
      () => runSave(reason),
      () => runSave(reason),
    );
    chain = task.then(
      (value) => value,
      () => false,
    );
    return task;
  }

  /** 状态栏「重试」：清零计数后立即保存，失败重新走 1s/3s/9s 阶梯。 */
  async function retryNow() {
    if (disposed) {
      return false;
    }
    retryCount = 0;
    clearRetry();
    return flush('retry-manual');
  }

  function reset() {
    clearDebounce();
    clearMax();
    clearRetry();
    retryCount = 0;
    pendingSchedule = false;
  }

  function stop() {
    disposed = true;
    reset();
  }

  function hasPending() {
    return (
      debounceTimer !== null ||
      maxTimer !== null ||
      retryTimer !== null ||
      pendingSchedule
    );
  }

  return { schedule, flush, retryNow, reset, stop, hasPending };
}
