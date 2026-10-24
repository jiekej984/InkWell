/** 行级差异对比（阶段三 3.6 / P5 / FR-5.4）。
 *
 * 纯函数：输入两段正文（纯文本，段落用换行分隔），输出可直接渲染的差异行。
 *
 * 口径：
 *   · 行 = 非空段落（服务端 ``extract_text`` 已是「段落用换行分隔」的纯文本口径）
 *   · 算法 = LCS 动态规划（O(n·m)），回溯生成 equal / add / del 序列
 *   · **双重上限保护**：任一侧 > 5 万字符，或行数乘积 > 400 万（病态输入）时，
 *     直接返回 ``tooLarge``，由 UI 提示「差异对比已省略」——绝不把界面卡死
 *   · 长段相同内容折叠为 ``skip``（上下文各留 3 行），避免整篇铺满弹窗
 *
 * `add` 表示「当前正文有、旧版本没有」（新增），`del` 反之（删除）。
 */

export const MAX_DIFF_CHARS = 50000;
export const MAX_DIFF_CELLS = 4_000_000;
export const CONTEXT_LINES = 3;

/** 拆行为非空段落（保留行内空格，去掉首尾空白与空行）。 */
export function splitLines(text) {
  if (!text) {
    return [];
  }
  return String(text)
    .replace(/\r\n?/g, '\n')
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

function codePointLength(text) {
  return [...String(text || '')].length;
}

/** LCS 回溯：返回 [{type:'equal'|'add'|'del', text}]。 */
function lcsRows(before, after) {
  const n = before.length;
  const m = after.length;
  const table = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      table[i][j] =
        before[i] === after[j]
          ? table[i + 1][j + 1] + 1
          : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }

  const rows = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (before[i] === after[j]) {
      rows.push({ type: 'equal', text: before[i] });
      i += 1;
      j += 1;
    } else if (table[i + 1][j] >= table[i][j + 1]) {
      rows.push({ type: 'del', text: before[i] });
      i += 1;
    } else {
      rows.push({ type: 'add', text: after[j] });
      j += 1;
    }
  }
  while (i < n) {
    rows.push({ type: 'del', text: before[i] });
    i += 1;
  }
  while (j < m) {
    rows.push({ type: 'add', text: after[j] });
    j += 1;
  }
  return rows;
}

/** 把长串相同行折叠成 ``{type:'skip', count}``（首尾也折叠）。 */
function collapseEqualRuns(rows, context = CONTEXT_LINES) {
  const result = [];
  let index = 0;
  while (index < rows.length) {
    if (rows[index].type !== 'equal') {
      result.push(rows[index]);
      index += 1;
      continue;
    }
    let end = index;
    while (end < rows.length && rows[end].type === 'equal') {
      end += 1;
    }
    const run = rows.slice(index, end);
    if (run.length <= context * 2 + 1) {
      result.push(...run);
    } else {
      result.push(...run.slice(0, context));
      result.push({ type: 'skip', count: run.length - context * 2 });
      result.push(...run.slice(-context));
    }
    index = end;
  }
  return result;
}

/**
 * 计算行级差异。
 * @param {string} before 旧版本正文（纯文本）
 * @param {string} after 当前正文（纯文本）
 */
export function diffLines(
  before,
  after,
  { maxChars = MAX_DIFF_CHARS, maxCells = MAX_DIFF_CELLS, context = CONTEXT_LINES } = {},
) {
  const beforeLines = splitLines(before);
  const afterLines = splitLines(after);

  if (codePointLength(before) > maxChars || codePointLength(after) > maxChars) {
    return {
      tooLarge: true,
      reason: `内容超过 ${(maxChars / 10000).toFixed(0)} 万字上限`,
      rows: [],
      stats: { added: 0, removed: 0 },
      lines: { before: beforeLines.length, after: afterLines.length },
    };
  }
  if (beforeLines.length * afterLines.length > maxCells) {
    return {
      tooLarge: true,
      reason: '段落过多，差异对比已省略',
      rows: [],
      stats: { added: 0, removed: 0 },
      lines: { before: beforeLines.length, after: afterLines.length },
    };
  }

  const raw = lcsRows(beforeLines, afterLines);
  const stats = {
    added: raw.filter((row) => row.type === 'add').length,
    removed: raw.filter((row) => row.type === 'del').length,
  };
  return {
    tooLarge: false,
    rows: collapseEqualRuns(raw, context),
    stats,
    lines: { before: beforeLines.length, after: afterLines.length },
  };
}

/** HTML → 纯文本（供版本正文参与 diff；浏览器环境）。 */
export function htmlToText(html) {
  if (!html) {
    return '';
  }
  const withBreaks = String(html)
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/(p|div|h[1-6]|li|blockquote|pre|tr)>/gi, '\n')
    .replace(/<[^>]*>/g, '');
  const textarea = document.createElement('textarea');
  textarea.innerHTML = withBreaks;
  return textarea.value;
}
