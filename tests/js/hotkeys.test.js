/** 快捷键注册表单测（阶段三 3.7 / 报告 §7.5 / C-06 / 回归 24）。
 *
 * 这里钉死三件事：
 *   · 组合键归一化与展示（Ctrl+Shift+F / Esc）只来自一个实现；
 *   · IME 组合、对话框、输入框三道门禁都在**匹配阶段**生效，不依赖各处理器自觉；
 *   · 命中后统一 preventDefault，未命中不碰事件。
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  HOTKEY_SCOPES,
  ariaKeyshortcuts,
  comboOf,
  createRegistry,
  formatShortcut,
  installHotkeys,
  isCommandCombo,
  isEditorSurface,
  isTextEntryElement,
  matchShortcut,
  matchShortcutOnKeyUp,
} from '../../frontend/js/hotkeys.js';

function keyEvent(overrides = {}) {
  return {
    key: 's',
    ctrlKey: false,
    shiftKey: false,
    altKey: false,
    metaKey: false,
    isComposing: false,
    keyCode: 83,
    ...overrides,
  };
}

const SAVE = {
  id: 'save',
  combo: 'ctrl+s',
  scope: HOTKEY_SCOPES.WRITER,
  inField: true,
  run() {},
};

const SEARCH = {
  id: 'search',
  combo: 'ctrl+shift+f',
  scope: HOTKEY_SCOPES.GLOBAL,
  run() {},
};

test('组合键归一化：Ctrl+S / Ctrl+Shift+F / Esc / 空格', () => {
  assert.equal(comboOf(keyEvent({ ctrlKey: true })), 'ctrl+s');
  assert.equal(
    comboOf(keyEvent({ key: 'F', ctrlKey: true, shiftKey: true })),
    'ctrl+shift+f',
  );
  assert.equal(comboOf(keyEvent({ key: 'Escape' })), 'escape');
  assert.equal(comboOf(keyEvent({ key: ' ' })), 'space');
  assert.equal(comboOf(keyEvent({ key: 'Shift' })), '');
  assert.equal(comboOf(null), '');
});

test('Win 键不与应用快捷键混同（meta 单独成段，永不命中 ctrl 条目）', () => {
  assert.equal(comboOf(keyEvent({ key: 'f', metaKey: true })), 'meta+f');
  assert.equal(matchShortcut(keyEvent({ key: 'f', metaKey: true }), [SEARCH]), null);
});

test('展示：formatShortcut / aria-keyshortcuts 与实际组合键同源', () => {
  assert.equal(formatShortcut('ctrl+s'), 'Ctrl+S');
  assert.equal(formatShortcut('ctrl+shift+f'), 'Ctrl+Shift+F');
  assert.equal(formatShortcut('escape'), 'Esc');
  assert.equal(formatShortcut(''), '');
  assert.equal(
    ariaKeyshortcuts('ctrl+shift+f'),
    'Control+Shift+F',
  );
});

test('IME 组合期间（isComposing / keyCode 229）一律放行，不响应任何快捷键', () => {
  assert.equal(
    matchShortcut(keyEvent({ ctrlKey: true, isComposing: true }), [SAVE], { view: 'writer' }),
    null,
  );
  assert.equal(
    matchShortcut(keyEvent({ ctrlKey: true, keyCode: 229 }), [SAVE], { view: 'writer' }),
    null,
  );
  assert.equal(
    matchShortcut(keyEvent({ ctrlKey: true, keyCode: 0 }), [SAVE], { view: 'writer' }),
    SAVE,
  );
});

test('作用域：writer 键位只在写作页生效；global 到处生效', () => {
  assert.equal(
    matchShortcut(keyEvent({ ctrlKey: true }), [SAVE], { view: 'writer' }),
    SAVE,
  );
  assert.equal(
    matchShortcut(keyEvent({ ctrlKey: true }), [SAVE], { view: 'documents' }),
    null,
  );
  assert.equal(
    matchShortcut(
      keyEvent({ key: 'f', ctrlKey: true, shiftKey: true }),
      [SEARCH],
      { view: 'projects' },
    ),
    SEARCH,
  );
});

test('对话框门禁：默认不触发；显式声明 inDialog 的条目才穿过', () => {
  const enter = keyEvent({ key: 'Enter' });
  const confirm = {
    id: 'dialog-confirm',
    combo: 'enter',
    inDialog: true,
    run() {},
  };
  assert.equal(matchShortcut(enter, [confirm], { view: 'writer' }), null);
  assert.equal(
    matchShortcut(enter, [confirm], { view: 'writer', inDialog: true }),
    confirm,
  );
});

test('输入框门禁：默认不触发；Ctrl+S 例外（inField: true）', () => {
  const onTitleInput = keyEvent({ ctrlKey: true });
  assert.equal(matchShortcut(onTitleInput, [SAVE], { view: 'writer', inField: true }), SAVE);
  assert.equal(
    matchShortcut(onTitleInput, [SEARCH], { view: 'writer', inField: true }),
    null,
    '搜索快捷键在输入框里不该抢键',
  );
  assert.equal(
    matchShortcut(keyEvent({ ctrlKey: true }), [SAVE], {
      view: 'writer',
      inField: false,
    }),
    SAVE,
  );
});

test('enabled() 返回 false 时跳过该条目，继续尝试后面的同组合键条目', () => {
  const disabled = { ...SAVE, id: 'disabled', enabled: () => false };
  const fallback = { ...SAVE, id: 'fallback' };
  assert.equal(
    matchShortcut(keyEvent({ ctrlKey: true }), [disabled, fallback], { view: 'writer' }),
    fallback,
  );
});

test('注册表：命中才 preventDefault 并执行一次；未命中不碰事件', () => {
  const registry = createRegistry();
  const calls = [];
  registry.add({ id: 'demo', combo: 'ctrl+n', run: () => calls.push('run') });

  let prevented = 0;
  const hit = registry.handle({
    ...keyEvent({ key: 'n', ctrlKey: true }),
    preventDefault: () => {
      prevented += 1;
    },
  });
  assert.equal(hit.id, 'demo');
  assert.equal(prevented, 1);
  assert.deepEqual(calls, ['run']);

  const miss = registry.handle({
    ...keyEvent({ key: 'x' }),
    preventDefault: () => {
      prevented += 1;
    },
  });
  assert.equal(miss, null);
  assert.equal(prevented, 1);
});

test('注册表：id 重复 / 缺 run 直接抛错，避免静默覆盖', () => {
  const registry = createRegistry();
  registry.add({ id: 'a', combo: 'ctrl+a', run() {} });
  assert.throws(() => registry.add({ id: 'a', combo: 'ctrl+b', run() {} }), /重复/);
  assert.throws(() => registry.add({ id: 'b', combo: 'ctrl+b' }), /combo 与 run/);
});

test('长按重复的 keydown 默认忽略，只有声明 repeat 的条目放行', () => {
  const event = keyEvent({ ctrlKey: true, repeat: true });
  assert.equal(matchShortcut(event, [SAVE], { view: 'writer' }), null);
  const repeatable = { ...SAVE, id: 'repeatable', repeat: true };
  assert.equal(
    matchShortcut(event, [repeatable], { view: 'writer' }),
    repeatable,
  );
});

test('isTextEntryElement：只拦文本输入，不拦按钮类控件', () => {
  assert.equal(isTextEntryElement({ tagName: 'INPUT', type: 'text' }), true);
  assert.equal(isTextEntryElement({ tagName: 'INPUT', type: 'search' }), true);
  assert.equal(isTextEntryElement({ tagName: 'INPUT', type: 'checkbox' }), false);
  assert.equal(isTextEntryElement({ tagName: 'INPUT', type: 'file' }), false);
  assert.equal(isTextEntryElement({ tagName: 'TEXTAREA' }), true);
  assert.equal(isTextEntryElement({ tagName: 'SELECT' }), true);
  assert.equal(isTextEntryElement({ tagName: 'DIV', isContentEditable: true }), true);
  assert.equal(isTextEntryElement({ tagName: 'DIV' }), false);
  assert.equal(isTextEntryElement(null), false);
});

test('isEditorSurface：Quill 正文是主输入面，不算「输入框门禁」', () => {
  const editorNode = { closest: (selector) => (selector === '.ql-editor' ? {} : null) };
  const plainNode = { closest: () => null };
  assert.equal(isEditorSurface(editorNode), true);
  assert.equal(isEditorSurface(plainNode), false);
  assert.equal(isEditorSurface(null), false);
});

// ---------------------------------------------------------------------------
// keyup 兜底（2026-10-24 真机缺陷：微软拼音中文态吞掉 Ctrl+Shift+F 的 keydown）
// ---------------------------------------------------------------------------

test('isCommandCombo：只有带 Ctrl/Alt/Win 的组合才算命令', () => {
  assert.equal(isCommandCombo('ctrl+shift+f'), true);
  assert.equal(isCommandCombo('ctrl+s'), true);
  assert.equal(isCommandCombo('alt+arrowdown'), true);
  assert.equal(isCommandCombo('meta+f'), true);
  assert.equal(isCommandCombo('escape'), false);
  assert.equal(isCommandCombo('space'), false);
  assert.equal(isCommandCombo('shift+f'), false);
  assert.equal(isCommandCombo(''), false);
  assert.equal(isCommandCombo(null), false);
});

test('IME 门禁默认仍然生效；只有 keyup 兜底显式 ignoreIme 才放行', () => {
  const composing = keyEvent({
    key: 'f',
    ctrlKey: true,
    shiftKey: true,
    isComposing: true,
  });
  assert.equal(matchShortcut(composing, [SEARCH], { view: 'documents' }), null);
  assert.equal(
    matchShortcut(composing, [SEARCH], { view: 'documents', ignoreIme: true }),
    SEARCH,
  );
  const ime229 = keyEvent({ key: 'f', ctrlKey: true, shiftKey: true, keyCode: 229 });
  assert.equal(matchShortcut(ime229, [SEARCH], { view: 'documents' }), null);
  assert.equal(
    matchShortcut(ime229, [SEARCH], { view: 'documents', ignoreIme: true }),
    SEARCH,
  );
});

test('matchShortcutOnKeyUp：输入法吞掉 keydown 时，keyup 仍能命中 Ctrl+Shift+F', () => {
  // 微软拼音中文态实测：Control / Shift 的 keydown 到达，F 只有 keyup
  const keyupF = keyEvent({ key: 'F', ctrlKey: true, shiftKey: true, keyCode: 70 });
  assert.equal(
    matchShortcutOnKeyUp(keyupF, [SEARCH], { view: 'documents' }),
    SEARCH,
  );
  // 作用域照旧：writer 作用域的条目在 documents 下不命中
  const writerOnly = { ...SEARCH, id: 'writer-only', scope: HOTKEY_SCOPES.WRITER };
  assert.equal(matchShortcutOnKeyUp(keyupF, [writerOnly], { view: 'documents' }), null);
  assert.equal(matchShortcutOnKeyUp(keyupF, [writerOnly], { view: 'writer' }), writerOnly);
});

test('matchShortcutOnKeyUp：无修饰键 / 输入法 Process 事件一律不兜底', () => {
  const escapeUp = keyEvent({ key: 'Escape', keyCode: 27 });
  const escapeEntry = { id: 'esc', combo: 'escape', run() {} };
  assert.equal(matchShortcutOnKeyUp(escapeUp, [escapeEntry], { view: 'writer' }), null);

  const plainF = keyEvent({ key: 'f', keyCode: 70 });
  assert.equal(matchShortcutOnKeyUp(plainF, [SEARCH], { view: 'documents' }), null);

  const processUp = keyEvent({
    key: 'Process',
    keyCode: 229,
    ctrlKey: true,
    shiftKey: true,
  });
  assert.equal(
    matchShortcutOnKeyUp(processUp, [SEARCH], { view: 'documents' }),
    null,
  );
});

/** 极简 EventTarget：够 installHotkeys() 用（只关心 add/remove/dispatch）。 */
function fakeTarget() {
  const listeners = { keydown: [], keyup: [] };
  return {
    listeners,
    addEventListener(type, fn) {
      if (listeners[type]) {
        listeners[type].push(fn);
      }
    },
    removeEventListener(type, fn) {
      if (listeners[type]) {
        listeners[type] = listeners[type].filter((item) => item !== fn);
      }
    },
    dispatch(type, event) {
      for (const fn of [...(listeners[type] || [])]) {
        fn(event);
      }
    },
    count(type) {
      return (listeners[type] || []).length;
    },
  };
}

function keydown(key, overrides = {}) {
  return {
    ...keyEvent({ key, ...overrides }),
    target: { tagName: 'DIV' },
    preventDefault() {},
  };
}

/** shortcutContext() 会读 document.querySelector('dialog[open]')，Node 里给个空壳。 */
function withFakeDocument(fn) {
  const had = Object.prototype.hasOwnProperty.call(globalThis, 'document');
  const previous = globalThis.document;
  globalThis.document = { querySelector: () => null };
  try {
    return fn();
  } finally {
    if (had) {
      globalThis.document = previous;
    } else {
      delete globalThis.document;
    }
  }
}

test('installHotkeys：普通按键只在 keydown 触发一次，keyup 不重复触发', () => {
  withFakeDocument(() => {
    const registry = createRegistry();
    const calls = [];
    registry.add({
      id: 'global-search',
      combo: 'ctrl+shift+f',
      scope: HOTKEY_SCOPES.GLOBAL,
      run: () => calls.push('search'),
    });
    const target = fakeTarget();
    const uninstall = installHotkeys(registry, { getView: () => 'documents', target });

    target.dispatch('keydown', keydown('F', { ctrlKey: true, shiftKey: true, keyCode: 70 }));
    assert.deepEqual(calls, ['search']);
    target.dispatch('keyup', keydown('F', { ctrlKey: true, shiftKey: true, keyCode: 70 }));
    assert.deepEqual(calls, ['search'], 'keydown 已执行过，keyup 不能再触发一次');

    target.dispatch('keydown', keydown('Shift', { ctrlKey: true, shiftKey: true, keyCode: 16 }));
    assert.deepEqual(calls, ['search'], '只按住修饰键不触发');

    uninstall();
    assert.equal(target.count('keydown'), 0);
    assert.equal(target.count('keyup'), 0);
  });
});

test('installHotkeys：keydown 被输入法吞掉时，keyup 兜底打开全局搜索（本缺陷回归）', () => {
  withFakeDocument(() => {
    const registry = createRegistry();
    const calls = [];
    registry.add({
      id: 'global-search',
      combo: 'ctrl+shift+f',
      scope: HOTKEY_SCOPES.GLOBAL,
      run: () => calls.push('search'),
    });
    const target = fakeTarget();
    installHotkeys(registry, { getView: () => 'documents', target });

    // 微软拼音中文态真实事件序列：Control↓ Shift↓ (F↓ 被吞) F↑ Shift↑ Control↑
    target.dispatch('keydown', keydown('Control', { ctrlKey: true, keyCode: 17 }));
    target.dispatch('keydown', keydown('Shift', { ctrlKey: true, shiftKey: true, keyCode: 16 }));
    assert.deepEqual(calls, [], 'F 的 keydown 没到，keydown 路径不该触发');

    target.dispatch('keyup', keydown('F', { ctrlKey: true, shiftKey: true, keyCode: 70 }));
    assert.deepEqual(calls, ['search'], 'keyup 兜底必须触发一次');
    target.dispatch('keyup', keydown('Shift', { ctrlKey: true, keyCode: 16 }));
    target.dispatch('keyup', keydown('Control', { keyCode: 17 }));
    assert.deepEqual(calls, ['search'], '松修饰键不再重复触发');
  });
});

test('installHotkeys：keyup 兜底不抢普通按键（Esc 松键不触发写作页查找关闭）', () => {
  withFakeDocument(() => {
    const registry = createRegistry();
    const calls = [];
    registry.add({
      id: 'writer-find-escape',
      combo: 'escape',
      scope: HOTKEY_SCOPES.WRITER,
      run: () => calls.push('escape'),
    });
    const target = fakeTarget();
    installHotkeys(registry, { getView: () => 'writer', target });

    target.dispatch('keyup', keydown('Escape', { keyCode: 27 }));
    assert.deepEqual(calls, []);
    target.dispatch('keydown', keydown('Escape', { keyCode: 27 }));
    assert.deepEqual(calls, ['escape']);
  });
});

test('installHotkeys：keyup 兜底同样受输入框 / 对话框门禁约束', () => {
  withFakeDocument(() => {
    const registry = createRegistry();
    const calls = [];
    registry.add({
      id: 'global-search',
      combo: 'ctrl+shift+f',
      scope: HOTKEY_SCOPES.GLOBAL,
      run: () => calls.push('search'),
    });
    const target = fakeTarget();
    installHotkeys(registry, { getView: () => 'documents', target });

    const input = { tagName: 'INPUT', type: 'text' };
    target.dispatch(
      'keyup',
      { ...keydown('F', { ctrlKey: true, shiftKey: true, keyCode: 70 }), target: input },
    );
    assert.deepEqual(calls, [], '输入框里不抢键');

    const editor = {
      tagName: 'DIV',
      closest: (selector) => (selector === '.ql-editor' ? {} : null),
    };
    target.dispatch(
      'keyup',
      { ...keydown('F', { ctrlKey: true, shiftKey: true, keyCode: 70 }), target: editor },
    );
    assert.deepEqual(calls, ['search'], 'Quill 正文不算输入框');
  });
});

