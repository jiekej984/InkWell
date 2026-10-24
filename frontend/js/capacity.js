/** 单章容量提示（阶段三 3.4 / FR-3.9「超容量单章提示不阻断」）。
 *
 * 报告把「单章 ≤5 万字」定为 V1 的承诺范围（§2.4 NFR-P2、AC-1、AC-3），
 * 回归 20 则要求「打开 8 万字超长章节给出拆分提示且不崩溃」。
 * 两档阈值 → 一条纯提示：**不限制输入、不拦截保存、不弹窗阻断**。
 *
 * 单独成文件的原因：等级判定与文案是「输入 → 输出」的纯计算，不碰 DOM，
 * 因此可以直接在 `tests/js/capacity.test.js` 里用 Node 断言（阶段三 DoD 第 1 条）。
 * 前端字数与后端 BR-1 同口径（`editor.countWords`），所以这里的值可以直接和
 * 状态栏「本章 N 字」对齐。
 */

/** 承诺范围上限：达到即提示「已超建议上限」（NFR-P2 / AC-1）。 */
export const CAPACITY_WARN = 50000;

/** 超长章节：达到即给拆章建议（回归 20 的 8 万字场景）。 */
export const CAPACITY_SPLIT = 80000;

/** 字数归一化：非数字 / 负数 / NaN 一律当 0，且不抛异常（状态栏随时可能在算）。 */
function normalizeWords(words) {
  const value = Number(words);
  if (!Number.isFinite(value) || value <= 0) {
    return 0;
  }
  return Math.trunc(value);
}

/** 「50000 → 5 万字」「82000 → 8.2 万字」；不足 1 万按字给，避免出现「0.5 万字」。 */
export function formatWan(words) {
  const value = normalizeWords(words);
  if (value < 10000) {
    return `${value.toLocaleString('zh-CN')} 字`;
  }
  const wan = (value / 10000).toFixed(1).replace(/\.0$/, '');
  return `${wan} 万字`;
}

/**
 * 单章容量判定。
 *
 * @param {number} words 本章字数（与 BR-1 同口径）
 * @returns {{level: 'ok'|'warn'|'split', words: number, label: string, detail: string}}
 *   `level === 'ok'` 时 `label` 为空串，调用方据此隐藏提示。
 */
export function chapterCapacity(words) {
  const value = normalizeWords(words);
  if (value >= CAPACITY_SPLIT) {
    return {
      level: 'split',
      words: value,
      label: `本章 ${formatWan(value)} · 建议拆章（不影响保存）`,
      detail:
        `单章已超 ${formatWan(CAPACITY_SPLIT)}（超长章节场景）：建议拆成两三章。` +
        '编辑、自动保存与版本快照都不受影响，内容不会因为字数多而丢失。',
    };
  }
  if (value >= CAPACITY_WARN) {
    return {
      level: 'warn',
      words: value,
      label: `本章 ${formatWan(value)} · 已超 5 万字建议上限`,
      detail:
        `单章 ${formatWan(CAPACITY_WARN)}是 V1 的承诺范围（NFR-P2 / AC-1）：` +
        '超出后仍可正常编辑与保存（功能不受影响），只是打开和重绘可能变慢，' +
        '建议后续按情节拆章。',
    };
  }
  return { level: 'ok', words: value, label: '', detail: '' };
}
