/** 保存状态三态（阶段三 3.5 / 报告 §7.4 / BR-2）。
 *
 * 纯函数，不碰 DOM：把「状态」翻译成**图标 + 文案 + 色调 + 可用动作**，
 * 由 `savebar.js` 渲染到状态栏，Node 单测（`tests/js/save-state.test.js`）直接断言。
 *
 * 三重编码（不只靠颜色）：
 *   · 颜色：`data-state` 驱动 CSS（见 `style.css`「3.5」段）
 *   · 图标：✓ / ⚠ / ✎ / ◌
 *   · 文案：已保存 HH:MM / 保存失败，已本地暂存 / 版本冲突…
 *
 * 状态机：
 *
 *     idle ──改动──▶ editing ──调度触发──▶ saving ──成功──▶ saved
 *                                            │
 *                                            ├─失败──▶ failed（附 重试 / 导出本章）
 *                                            └─3002─▶ conflict（附 刷新并恢复 / 导出本章）
 *     saved ──改动──▶ editing（失败/冲突态下继续输入不改变状态，避免掩盖问题）
 */

export const SAVE_STATES = Object.freeze({
  IDLE: 'idle',
  EDITING: 'editing',
  SAVING: 'saving',
  SAVED: 'saved',
  FAILED: 'failed',
  CONFLICT: 'conflict',
});

/** 失败态的可执行动作（与 `index.html` 里按钮的 `data-action` 同名）。 */
export const SAVE_ACTIONS = Object.freeze({
  RETRY: 'retry',
  EXPORT: 'export',
  RELOAD: 'reload',
});

const VIEWS = Object.freeze({
  idle: { icon: '', text: '就绪', tone: 'idle', actions: [] },
  editing: { icon: '✎', text: '未保存', tone: 'idle', actions: [] },
  saving: { icon: '◌', text: '保存中…', tone: 'saving', actions: [] },
  saved: { icon: '✓', text: '已保存', tone: 'success', actions: [] },
  failed: {
    icon: '⚠',
    text: '保存失败，已本地暂存',
    tone: 'danger',
    actions: [SAVE_ACTIONS.RETRY, SAVE_ACTIONS.EXPORT],
  },
  conflict: {
    icon: '⚠',
    text: '版本冲突，已本地暂存',
    tone: 'danger',
    actions: [SAVE_ACTIONS.RELOAD, SAVE_ACTIONS.EXPORT],
  },
});

/** ``HH:MM`` 本地时间；非法时间返回空串（文案退化为「已保存」）。 */
export function clockLabel(value = new Date()) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '';
  }
  return `${String(date.getHours()).padStart(2, '0')}:${String(
    date.getMinutes(),
  ).padStart(2, '0')}`;
}

/** 状态 → 可渲染视图；未知状态按 idle 处理，永不抛错。 */
export function describeSaveState(state, { at = '', message = '' } = {}) {
  const resolved = Object.prototype.hasOwnProperty.call(VIEWS, state)
    ? state
    : SAVE_STATES.IDLE;
  const base = VIEWS[resolved];

  let text = base.text;
  if (resolved === SAVE_STATES.SAVED && at) {
    text = `已保存 ${at}`;
  } else if (
    (resolved === SAVE_STATES.FAILED ||
      resolved === SAVE_STATES.CONFLICT ||
      resolved === SAVE_STATES.SAVING) &&
    message
  ) {
    // 「保存失败，1 秒后重试（1/3）」这类过程文案覆盖默认文案
    text = String(message);
  }

  return {
    state: resolved,
    icon: base.icon,
    text,
    tone: base.tone,
    actions: [...base.actions],
  };
}
