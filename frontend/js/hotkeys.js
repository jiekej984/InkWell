/** 全局快捷键注册表（阶段三 3.7 / 报告 §7.5 / C-06 / S3-03）。
 *
 * 设计要点：
 *   1. **一个注册表、一个入口**：所有键位登记在这里，`document` 上只挂一个
 *      keydown（捕获阶段），避免每个模块各挂一个监听、互相抢 `preventDefault`。
 *   2. **门禁优先**：IME 组合中（`isComposing` / `keyCode === 229`）直接放行；
 *      对话框打开、表单输入框聚焦时不触发（Ctrl+S 例外，见 C-06）。
 *   3. **纯函数可测**：组合键归一化、匹配、格式化都不碰 DOM，Node 单测直接覆盖；
 *      只有 `installHotkeys()` 与 `shortcutContext()` 读 DOM。
 *   4. **键位标注**：`formatShortcut()` 供按钮 tooltip / `aria-keyshortcuts` 复用，
 *      保证「提示的键位」与「真正注册的键位」只有一个来源。
 *   5. **keyup 兜底（2026-10-24 真机缺陷）**：微软拼音在中文态把 `Ctrl+Shift+F`
 *      当作「简体/繁体切换」系统热键，**keydown 被输入法吞掉、页面收不到 F**，
 *      但 `keyup` 仍会派发（target / ctrl / shift 都正常）。因此带 Ctrl/Alt/Win 的
 *      命令组合允许在 keyup 上补一次匹配：keydown 已经执行过的组合由去重表挡掉，
 *      不会双触发；无修饰键的按键（字母 / Esc / Enter）不参与兜底——它们在输入法里
 *      就是正文输入，不能凭 keyup 触发。详见 `docs/故障排查.md`。
 *
 * 键位（§7.5）：Ctrl+N 新建章节、Ctrl+S 保存 + 手动快照、Ctrl+F 章内查找、
 * Ctrl+Shift+F 全局搜索、Ctrl+Shift+V 版本历史、Ctrl+Shift+E 备份导出、
 * Esc 关闭查找条；Ctrl+B/I 交给 Quill（不注册）。
 */

export const HOTKEY_SCOPES = Object.freeze({
  GLOBAL: 'global',
  WRITER: 'writer',
  DOCUMENTS: 'documents',
});

/** 只按下修饰键时不构成快捷键。 */
const MODIFIER_KEYS = new Set([
  'control',
  'shift',
  'alt',
  'meta',
  'os',
  'altgraph',
  'capslock',
  'fn',
  'hyper',
  'super',
  'windows',
  'contextmenu',
]);

const KEY_LABELS = Object.freeze({
  escape: 'Esc',
  space: '空格',
  enter: 'Enter',
  tab: 'Tab',
  arrowup: '↑',
  arrowdown: '↓',
  arrowleft: '←',
  arrowright: '→',
  backspace: 'Backspace',
  delete: 'Delete',
  home: 'Home',
  end: 'End',
  pageup: 'PageUp',
  pagedown: 'PageDown',
});

/** 即使门禁拦下（输入框 / 对话框），也不交给 WebView2 默认行为的组合键。 */
const RESERVED_COMBOS = new Set(['ctrl+f', 'ctrl+n', 'ctrl+s']);

/** keydown 已执行过的组合，keyup 兜底时的去重窗口（毫秒，防止双触发）。 */
export const KEYUP_DEDUPE_MS = 5000;

function normalizeKey(raw) {
  const key = String(raw || '').toLowerCase();
  if (!key || MODIFIER_KEYS.has(key)) {
    return '';
  }
  if (key === ' ' || key === 'spacebar') {
    return 'space';
  }
  if (key === 'esc') {
    return 'escape';
  }
  return key;
}

/**
 * 事件 → 规范化组合键（如 `ctrl+shift+f`）。
 *
 * 只认 Ctrl（Windows 平台）；Meta 单独出现时保留为 `meta` 段，
 * 因此 Win+F 这类系统组合不会误中应用的 `f`。
 */
export function comboOf(event) {
  if (!event) {
    return '';
  }
  const key = normalizeKey(event.key);
  if (!key) {
    return '';
  }
  const parts = [];
  if (event.ctrlKey) {
    parts.push('ctrl');
  }
  if (event.metaKey) {
    parts.push('meta');
  }
  if (event.altKey) {
    parts.push('alt');
  }
  if (event.shiftKey) {
    parts.push('shift');
  }
  parts.push(key);
  return parts.join('+');
}

/**
 * 是否为「命令组合」：至少按住 Ctrl / Alt / Win 之一。
 *
 * 只有命令组合才允许用 keyup 兜底触发（见文件头 §5）。无修饰键的按键在中文输入法里
 * 就是正文输入，凭 keyup 触发会把「打字」误判成快捷键。
 */
export function isCommandCombo(combo) {
  if (!combo) {
    return false;
  }
  return String(combo)
    .split('+')
    .some((part) => part === 'ctrl' || part === 'alt' || part === 'meta');
}

/** `ctrl+shift+f` → `Ctrl+Shift+F`（tooltip / aria-keyshortcuts 用）。 */
export function formatShortcut(combo) {
  if (!combo) {
    return '';
  }
  return String(combo)
    .split('+')
    .map((part) => {
      if (part === 'ctrl') {
        return 'Ctrl';
      }
      if (part === 'shift') {
        return 'Shift';
      }
      if (part === 'alt') {
        return 'Alt';
      }
      if (part === 'meta') {
        return 'Win';
      }
      if (KEY_LABELS[part]) {
        return KEY_LABELS[part];
      }
      return part.length === 1 ? part.toUpperCase() : part;
    })
    .join('+');
}

/** 组合键 → `aria-keyshortcuts` 值（WAI-ARIA 要求 Control/Shift/Alt 全拼）。 */
export function ariaKeyshortcuts(combo) {
  const map = { ctrl: 'Control', shift: 'Shift', alt: 'Alt', meta: 'Meta' };
  return String(combo || '')
    .split('+')
    .map((part) => map[part] || formatShortcut(part))
    .join('+');
}

/**
 * 是否为「正在输入」的控件。
 *
 * 注意：Quill 正文也是 contenteditable，但它是写作主输入面，快捷键必须可用；
 * 调用方用 `isEditorSurface()` 把它排除（见 `shortcutContext()`）。
 */
export function isTextEntryElement(node) {
  if (!node || typeof node !== 'object') {
    return false;
  }
  const tag = String(node.tagName || '').toUpperCase();
  if (tag === 'TEXTAREA' || tag === 'SELECT') {
    return true;
  }
  if (tag === 'INPUT') {
    const type = String(node.type || 'text').toLowerCase();
    // 按钮/勾选类控件不承载文本输入，不阻止快捷键
    return ![
      'checkbox',
      'radio',
      'button',
      'submit',
      'reset',
      'range',
      'color',
      'file',
    ].includes(type);
  }
  if (node.isContentEditable === true) {
    return true;
  }
  if (
    typeof node.closest === 'function' &&
    node.closest('[contenteditable="true"]')
  ) {
    return true;
  }
  return false;
}

/** 是否落在 Quill 正文里（正文需要响应全局快捷键）。 */
export function isEditorSurface(node) {
  return Boolean(
    node &&
      typeof node.closest === 'function' &&
      node.closest('.ql-editor') !== null,
  );
}

/**
 * 事件 → 匹配上下文。
 *
 * @param {KeyboardEvent} event
 * @param {string} view 当前视图（`projects` / `writer` / `documents` / …）
 */
export function shortcutContext(event, view = '') {
  const target = event ? event.target : null;
  return {
    view,
    inDialog: Boolean(document.querySelector('dialog[open]')),
    inField: isTextEntryElement(target) && !isEditorSurface(target),
  };
}

/**
 * 在注册表中找命中的条目；未命中返回 `null`。
 *
 * 门禁顺序：IME → 组合键 → 作用域 → 对话框 → 输入框 → 长按 repeat → `enabled()`。
 *
 * `ignoreIme: true` 只给 keyup 兜底用：输入法把 keydown 吃掉时，keyup 往往还会派发
 * （`key` 是正常字母、`isComposing` 为 false），此时不应再被 IME 门禁挡掉。
 * keydown 一律使用默认值，组合输入期间的按键继续放行给输入法。
 */
export function matchShortcut(
  event,
  entries,
  { view = '', inDialog = false, inField = false, ignoreIme = false } = {},
) {
  if (!event) {
    return null;
  }
  if (!ignoreIme && (event.isComposing || event.keyCode === 229)) {
    return null;
  }
  const combo = comboOf(event);
  if (!combo) {
    return null;
  }
  for (const entry of entries) {
    if (!entry || entry.combo !== combo) {
      continue;
    }
    if (
      entry.scope &&
      entry.scope !== HOTKEY_SCOPES.GLOBAL &&
      entry.scope !== view
    ) {
      continue;
    }
    if (inDialog && !entry.inDialog) {
      continue;
    }
    if (!inDialog && entry.inDialog === true) {
      // `inDialog: true` 表示「只在对话框里生效」，对话框外同样不触发
      continue;
    }
    if (inField && !entry.inField) {
      continue;
    }
    if (event.repeat === true && entry.repeat !== true) {
      // 长按重复触发的 keydown：默认忽略（否则按住 Ctrl+S 会连发快照）
      continue;
    }
    if (typeof entry.enabled === 'function' && !entry.enabled()) {
      continue;
    }
    return entry;
  }
  return null;
}

/**
 * keyup 兜底匹配（2026-10-24 真机缺陷修复）。
 *
 * 场景：微软拼音中文态把 `Ctrl+Shift+F` 认作「简/繁切换」系统热键，keydown 被输入法
 * 吞掉，页面只收到 Control / Shift 的 keydown 与 **F 的 keyup**。此时按 keyup 再匹配一次，
 * 全局搜索才能打开。
 *
 * 只处理带 Ctrl / Alt / Win 的命令组合；`Process`（keyCode 229）这类输入法事件不参与，
 * 免得把组合输入中的普通按键当成快捷键。
 */
export function matchShortcutOnKeyUp(event, entries, context = {}) {
  if (!event) {
    return null;
  }
  if (event.key === 'Process' || event.keyCode === 229) {
    return null;
  }
  if (!isCommandCombo(comboOf(event))) {
    return null;
  }
  return matchShortcut(event, entries, { ...context, ignoreIme: true });
}

/** 注册表：`add()` 登记，`handle()` 统一匹配并执行。 */
export function createRegistry() {
  const entries = [];

  return {
    entries,
    add(entry) {
      if (!entry || !entry.combo || typeof entry.run !== 'function') {
        throw new TypeError('快捷键条目需要 combo 与 run');
      }
      if (entries.some((item) => item.id && item.id === entry.id)) {
        throw new Error(`快捷键 id 重复：${entry.id}`);
      }
      entries.push(entry);
      return entry;
    },
    match(event, context) {
      return matchShortcut(event, entries, context);
    },
    /** 命中则 `preventDefault()` 并执行；返回命中的条目。 */
    handle(event, context) {
      const entry = matchShortcut(event, entries, context);
      if (!entry) {
        return null;
      }
      if (entry.preventDefault !== false) {
        event.preventDefault();
      }
      entry.run(event);
      return entry;
    },
  };
}

/** 应用唯一的快捷键注册表（各模块 import 后登记自己的键位）。 */
export const hotkeys = createRegistry();

/**
 * 把注册表挂到 `document`（捕获阶段：先于 Quill / 输入框的处理器）。
 *
 * keydown 是主路径；keyup 只做兜底（输入法吞掉 keydown 时补一次），并用
 * 「keydown 已执行的组合」去重表保证一次按键只触发一次。
 *
 * @param {object} registry `createRegistry()` 的返回值
 * @param {{getView: () => string, target?: EventTarget}} options
 * @returns {() => void} 卸载函数（测试 / 热重载用）
 */
export function installHotkeys(
  registry,
  { getView = () => '', target = document } = {},
) {
  /** keydown 已执行过的命令组合 → 执行时间（keyup 兜底去重用）。 */
  const handledOnKeyDown = new Map();

  const pruneHandled = (now) => {
    for (const [combo, at] of handledOnKeyDown) {
      if (now - at > KEYUP_DEDUPE_MS) {
        handledOnKeyDown.delete(combo);
      }
    }
  };

  const runEntry = (entry, event) => {
    if (entry.preventDefault !== false) {
      event.preventDefault();
    }
    try {
      entry.run(event);
    } catch (error) {
      // 快捷键动作写日志，不让一次异常打断后续键位
      console.error('[hotkeys]', entry.id, error);
    }
  };

  const onKeyDown = (event) => {
    const entry = matchShortcut(
      event,
      registry.entries,
      shortcutContext(event, getView()),
    );
    if (!entry) {
      // 输入框 / 对话框 / IME 组合中被门禁拦下的保留键也不落到 WebView2：
      // 否则 Ctrl+S 弹「保存网页」、Ctrl+F 弹浏览器查找、Ctrl+N 开新窗口
      if (
        !event.isComposing &&
        event.keyCode !== 229 &&
        RESERVED_COMBOS.has(comboOf(event))
      ) {
        event.preventDefault();
      }
      return;
    }
    const combo = comboOf(event);
    if (isCommandCombo(combo)) {
      // 记下「已经执行过」：这一下松键时不再兜底触发第二次
      handledOnKeyDown.set(combo, Date.now());
    }
    runEntry(entry, event);
  };

  const onKeyUp = (event) => {
    const combo = comboOf(event);
    if (!combo) {
      // 修饰键松开 = 一轮按键结束：清掉去重表，即使某个 keyup 丢了也不会挡住下一次
      handledOnKeyDown.clear();
      return;
    }
    if (!isCommandCombo(combo)) {
      return;
    }
    const now = Date.now();
    pruneHandled(now);
    if (handledOnKeyDown.has(combo)) {
      // keydown 已经执行过（普通情况），keyup 只负责收尾
      handledOnKeyDown.delete(combo);
      return;
    }
    const entry = matchShortcutOnKeyUp(
      event,
      registry.entries,
      shortcutContext(event, getView()),
    );
    if (!entry) {
      return;
    }
    runEntry(entry, event);
  };

  target.addEventListener('keydown', onKeyDown, true);
  target.addEventListener('keyup', onKeyUp, true);
  return () => {
    target.removeEventListener('keydown', onKeyDown, true);
    target.removeEventListener('keyup', onKeyUp, true);
    handledOnKeyDown.clear();
  };
}
