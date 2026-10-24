/** 状态栏保存态渲染（阶段三 3.5）。
 *
 * 判定逻辑全在 `savestate.js`（纯函数，Node 单测覆盖）；这里只负责写 DOM：
 *   · `#save-state` 的 `data-state` 驱动颜色
 *   · `#save-state-icon` / `#save-status` 承担图标与文案（`aria-live="polite"`）
 *   · 失败 / 冲突时按状态显示「重试 / 导出本章 / 刷新并恢复」
 *
 * 另有一条**临时提示**通道（`#status-note`）：标题已保存、已回滚、导出结果等
 * 与保存三态无关的消息走这里，避免互相覆盖；默认 5 秒后自动消失。
 */

import { describeSaveState, SAVE_STATES } from './savestate.js';

const NOTE_TIMEOUT_MS = 5000;

export function createSaveBar({
  root = null,
  icon = null,
  text = null,
  note = null,
  actions = {},
} = {}) {
  let state = SAVE_STATES.IDLE;
  let noteTimer = null;

  /** 渲染状态；返回渲染后的视图，便于调用方断言。 */
  function set(next, options = {}) {
    const view = describeSaveState(next, options);
    state = view.state;
    if (root) {
      root.dataset.state = view.state;
    }
    if (icon) {
      icon.textContent = view.icon;
    }
    if (text) {
      text.textContent = view.text;
    }
    for (const [name, node] of Object.entries(actions)) {
      if (node) {
        node.hidden = !view.actions.includes(name);
      }
    }
    return view;
  }

  /** 临时提示；`timeoutMs <= 0` 表示常驻，直到被下一条覆盖。 */
  function notify(
    message,
    kind = '',
    { timeoutMs = NOTE_TIMEOUT_MS, title = '' } = {},
  ) {
    if (!note) {
      return;
    }
    if (noteTimer !== null) {
      window.clearTimeout(noteTimer);
      noteTimer = null;
    }
    note.textContent = message || '';
    note.title = title || '';
    note.dataset.kind = kind || '';
    note.hidden = !message;
    if (!message || timeoutMs <= 0) {
      return;
    }
    noteTimer = window.setTimeout(() => {
      noteTimer = null;
      note.textContent = '';
      note.title = '';
      note.hidden = true;
    }, timeoutMs);
  }

  function getState() {
    return state;
  }

  return { set, notify, getState };
}
