/** 本地暂存读写（任务 2.4 / BR-2）。
 *
 * 双份兜底：
 *   · localStorage —— 编辑器每次改动后短时间内写入，强杀/断电也能留住
 *   · 服务端 drafts/ —— 保存失败或版本冲突时落盘，重启后可恢复
 *
 * 任何一份失败都不阻断写作主路径（正文保存始终优先）。
 */

import { request } from './api.js';

const KEY_PREFIX = 'inkwell:draft:';

function key(chapterId) {
  return `${KEY_PREFIX}${chapterId}`;
}

export function saveLocalDraft(chapterId, contentHtml, reason = '') {
  try {
    window.localStorage.setItem(
      key(chapterId),
      JSON.stringify({
        content: contentHtml,
        saved_at: new Date().toISOString(),
        reason,
      }),
    );
  } catch {
    // 隐私模式或超配额：忽略，服务端暂存仍可兜底
  }
}

export function readLocalDraft(chapterId) {
  try {
    const raw = window.localStorage.getItem(key(chapterId));
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function clearLocalDraft(chapterId) {
  try {
    window.localStorage.removeItem(key(chapterId));
  } catch {
    // 忽略
  }
}

export function saveServerDraft({ chapterId, contentHtml, reason }) {
  return request('/api/drafts', {
    method: 'POST',
    body: {
      chapter_id: chapterId,
      content_html: contentHtml,
      client_saved_at: new Date().toISOString(),
      reason,
    },
  });
}

export function listServerDrafts() {
  return request('/api/drafts');
}

export function fetchServerDraft(chapterId) {
  return request(`/api/drafts/${chapterId}`);
}

export function deleteServerDraft(chapterId) {
  return request(`/api/drafts/${chapterId}`, { method: 'DELETE' });
}
