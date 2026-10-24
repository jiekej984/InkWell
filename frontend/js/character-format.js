/** 角色库的纯函数（V2.0 / 5.4）。
 *
 * 与 DOM 无关、与网络无关，供 `characters.js` 复用并可在 Node 里直接单测
 * （见 `tests/js/character-format.test.js`）。
 */

/** 标签输入框 → 数组：支持中英文逗号、顿号、分号、换行；去空、去重、截断 20 个。 */
export function parseTags(text) {
  if (typeof text !== 'string') {
    return [];
  }
  const parts = text.split(/[,，、;；\n]+/);
  const result = [];
  for (const part of parts) {
    const value = part.trim();
    if (!value || result.includes(value)) {
      continue;
    }
    result.push(value);
    if (result.length >= 20) {
      break;
    }
  }
  return result;
}

/** 数组 → 标签输入框文本（与 `parseTags` 互逆）。 */
export function formatTags(tags) {
  if (!Array.isArray(tags)) {
    return '';
  }
  return tags.filter((item) => typeof item === 'string' && item.trim()).join('，');
}

/** 头像占位文字：姓名首字；空名回退 `?`。 */
export function characterInitial(name) {
  const text = typeof name === 'string' ? name.trim() : '';
  return text ? Array.from(text)[0] : '?';
}

/** 追加别名：空值忽略、重复忽略；返回新数组。 */
export function appendAlias(current, value) {
  const list = Array.isArray(current) ? current.slice() : [];
  const text = typeof value === 'string' ? value.trim() : '';
  if (!text || list.includes(text)) {
    return list;
  }
  return [...list, text];
}

/** 卡片头部的一行摘要：`主角 · 存活`（缺失时用占位）。 */
export function characterSummary(detail) {
  if (!detail) {
    return '未选择角色';
  }
  const role = detail.role_label || '未分类';
  const status = detail.status_label || '状态未知';
  return `${role} · ${status}`;
}

/** 保存状态文案：`保存中…` / `已保存 14:32` / `保存失败：…`。 */
export function saveStateText(state, time = '', message = '') {
  if (state === 'saving') {
    return '保存中…';
  }
  if (state === 'saved') {
    return `已保存 ${time}`;
  }
  if (state === 'error') {
    return `保存失败：${message}`;
  }
  return '就绪';
}
