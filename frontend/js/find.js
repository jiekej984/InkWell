/** 章内查找（阶段三 3.8 / 报告 §7.5 / 回归 25）。
 *
 * 交互：`Ctrl+F` 打开查找条 → 输入即时定位 → `n/N` 匹配数 → 上一个 / 下一个 →
 * 区分大小写 → `Esc` 关闭。**不修改正文**，只做高亮与滚动定位。
 *
 * 高亮：优先 CSS Custom Highlight API（`::highlight()`，WebView2 支持时），
 * 不可用时降级为 Selection + `scrollIntoView`（V-02）。
 *
 * 匹配按**文本节点**进行：跨段落的短语不命中（章内查找的常规语义），
 * 但中英混排、emoji 与 HTML 实体都在同一套 UTF-16 下标上，Range 不会错位。
 */

export const HIGHLIGHT_ALL = 'inkwell-find';
export const HIGHLIGHT_CURRENT = 'inkwell-find-current';

/** 句子级查找的输入长度上限（避免把整章粘进查找框）。 */
const MAX_QUERY_LENGTH = 200;
const MAX_PREFILL_LENGTH = 80;

function escapeRegExp(text) {
  return String(text).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * 纯函数：在文本里找全部命中（不重叠）。
 *
 * @param {string} text
 * @param {string} query
 * @param {{caseSensitive?: boolean}} options
 * @returns {{start: number, end: number}[]} UTF-16 下标区间
 */
export function findMatches(text, query, { caseSensitive = false } = {}) {
  const source = String(text || '');
  const needle = String(query || '').slice(0, MAX_QUERY_LENGTH);
  if (!source || !needle) {
    return [];
  }
  const pattern = new RegExp(
    escapeRegExp(needle),
    caseSensitive ? 'g' : 'gi',
  );
  const matches = [];
  let hit = pattern.exec(source);
  while (hit !== null) {
    matches.push({ start: hit.index, end: hit.index + hit[0].length });
    // 空匹配理论上不会出现（query 非空且已转义），防御性前进一步
    if (hit[0].length === 0) {
      pattern.lastIndex += 1;
    }
    hit = pattern.exec(source);
  }
  return matches;
}

function canUseHighlightApi() {
  return (
    typeof CSS !== 'undefined' &&
    Boolean(CSS.highlights) &&
    typeof Highlight === 'function'
  );
}

function collectMatches(root, query, caseSensitive) {
  const doc = root.ownerDocument || document;
  // NodeFilter.SHOW_TEXT === 4（不引用 NodeFilter，便于无 DOM 环境加载模块）
  const walker = doc.createTreeWalker(root, 4);
  const found = [];
  let node = walker.nextNode();
  while (node !== null) {
    const text = node.nodeValue || '';
    for (const hit of findMatches(text, query, { caseSensitive })) {
      found.push({ node, start: hit.start, end: hit.end });
    }
    node = walker.nextNode();
  }
  return found;
}

function rangeOf(match) {
  const range = document.createRange();
  range.setStart(match.node, match.start);
  range.setEnd(match.node, match.end);
  return range;
}

/**
 * @param {object} options
 * @param {() => Element | null} options.getRoot 取当前编辑器根节点（未打开章节返回 null）
 * @param {() => void} [options.onClose] 关闭后回调（把焦点还给正文）
 */
export function createFind({ getRoot, onClose } = {}) {
  const bar = document.getElementById('find-bar');
  const input = document.getElementById('find-input');
  const count = document.getElementById('find-count');
  const prev = document.getElementById('find-prev');
  const next = document.getElementById('find-next');
  const caseBox = document.getElementById('find-case');
  const closeButton = document.getElementById('find-close');

  let opened = false;
  let matches = [];
  let current = 0;

  if (!bar || !input || !count) {
    // 页面没有查找条（例如未来复用本模块的轻量页面）：所有操作退化为 no-op
    return {
      open: () => false,
      close: () => {},
      refresh: () => {},
      next: () => {},
      prev: () => {},
      isOpen: () => false,
      matchCount: () => 0,
      currentIndex: () => 0,
      usesHighlightApi: canUseHighlightApi,
    };
  }

  function clearHighlights() {
    if (canUseHighlightApi()) {
      CSS.highlights.delete(HIGHLIGHT_ALL);
      CSS.highlights.delete(HIGHLIGHT_CURRENT);
    }
  }

  function paintCurrent() {
    const match = matches[current];
    if (!match) {
      return;
    }
    if (canUseHighlightApi()) {
      CSS.highlights.set(HIGHLIGHT_CURRENT, new Highlight(rangeOf(match)));
      return;
    }
    // 降级：把当前命中放进选区（不写入正文，也不触发 text-change）
    const selection = window.getSelection();
    if (!selection) {
      return;
    }
    selection.removeAllRanges();
    selection.addRange(rangeOf(match));
  }

  function scrollToCurrent() {
    const match = matches[current];
    const node = match && match.node.parentElement;
    if (node && typeof node.scrollIntoView === 'function') {
      node.scrollIntoView({ block: 'center', inline: 'nearest' });
    }
  }

  function syncCount() {
    count.textContent = matches.length
      ? `${current + 1}/${matches.length}`
      : '0/0';
    count.dataset.kind = matches.length ? '' : input.value ? 'empty' : '';
  }

  /** 重新扫描正文并渲染；`reset` 时回到第一条。 */
  function render({ reset = false } = {}) {
    const root = getRoot ? getRoot() : null;
    clearHighlights();
    if (!root || !input.value.trim()) {
      matches = [];
      current = 0;
      syncCount();
      return;
    }
    matches = collectMatches(
      root,
      input.value.trim(),
      Boolean(caseBox && caseBox.checked),
    );
    if (reset || current >= matches.length) {
      current = 0;
    }
    if (matches.length === 0) {
      syncCount();
      return;
    }
    if (canUseHighlightApi()) {
      const ranges = matches.map(rangeOf);
      CSS.highlights.set(HIGHLIGHT_ALL, new Highlight(...ranges));
    }
    paintCurrent();
    syncCount();
    scrollToCurrent();
  }

  function go(delta) {
    if (!opened || matches.length === 0) {
      return;
    }
    current = (current + delta + matches.length) % matches.length;
    paintCurrent();
    syncCount();
    scrollToCurrent();
  }

  function prefillFromSelection(root) {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
      return;
    }
    const range = selection.getRangeAt(0);
    if (!root.contains(range.commonAncestorContainer)) {
      return;
    }
    const text = selection.toString().replace(/\s+/g, ' ').trim();
    if (text && text.length <= MAX_PREFILL_LENGTH) {
      input.value = text;
    }
  }

  function open() {
    const root = getRoot ? getRoot() : null;
    if (!root || !root.isConnected) {
      return false;
    }
    bar.hidden = false;
    opened = true;
    prefillFromSelection(root);
    input.focus();
    input.select();
    render({ reset: false });
    return true;
  }

  function close() {
    if (!opened && bar.hidden) {
      return;
    }
    opened = false;
    clearHighlights();
    matches = [];
    current = 0;
    bar.hidden = true;
    syncCount();
    if (document.activeElement === input) {
      input.blur();
    }
    if (onClose) {
      onClose();
    }
  }

  function refresh() {
    if (opened) {
      render({ reset: false });
    }
  }

  input.addEventListener('input', () => {
    current = 0;
    render({ reset: true });
  });
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      go(event.shiftKey ? -1 : 1);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      close();
    }
  });
  caseBox?.addEventListener('change', () => render({ reset: true }));
  prev?.addEventListener('click', () => go(-1));
  next?.addEventListener('click', () => go(1));
  closeButton?.addEventListener('click', close);

  return {
    open,
    close,
    refresh,
    next: () => go(1),
    prev: () => go(-1),
    isOpen: () => opened,
    matchCount: () => matches.length,
    currentIndex: () => current,
    usesHighlightApi: canUseHighlightApi,
  };
}
