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
  isEditorSurface,
  isTextEntryElement,
  matchShortcut,
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

