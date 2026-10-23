/** 双份暂存与恢复（任务 2.4 / BR-2 / 回归 15）。
 *
 * 保存失败或版本冲突时把当前正文同时落两份：
 *   · localStorage —— 编辑器改动后短时间写入，强杀/断电也能留住
 *   · 服务端 ``drafts/`` —— 保存失败或冲突时落盘，重启后仍可恢复
 *
 * 恢复顺序与服务端一致：服务端暂存优先，localStorage 兜底。
 * 依赖通过参数注入，便于在无 DOM 环境（Node 单测）验证
 * 「重试耗尽 → 双份暂存 → 重启恢复 → 补写清理」整条链路。
 */

import {
  clearLocalDraft,
  deleteServerDraft,
  fetchServerDraft,
  readLocalDraft,
  saveLocalDraft,
  saveServerDraft,
} from './pending.js';

const CODE_NOT_FOUND = 'code=2001';
const CODE_VERSION_CONFLICT = 'code=3002';

function messageOf(error) {
  if (!error) {
    return '';
  }
  return String(error.message || error);
}

/** 是否为版本冲突（3002）；冲突不重试，必须先恢复/刷新。 */
export function isConflictError(error) {
  return messageOf(error).includes(CODE_VERSION_CONFLICT);
}

/** 创建双份暂存读写器（默认走真实 API，测试可注入替身）。 */
export function createDraftStore({ log = null, deps = {} } = {}) {
  const api = {
    saveLocalDraft,
    readLocalDraft,
    clearLocalDraft,
    saveServerDraft,
    fetchServerDraft,
    deleteServerDraft,
    ...deps,
  };

  function warn(text, detail) {
    if (log && typeof log.warn === 'function') {
      log.warn(text, detail);
    }
  }

  /** 落双份暂存：localStorage 先行，服务端失败不阻断写作主路径。 */
  async function persist(chapterId, contentHtml, reason = '') {
    api.saveLocalDraft(chapterId, contentHtml, reason);
    try {
      await api.saveServerDraft({ chapterId, contentHtml, reason });
      return { local: true, remote: true };
    } catch (error) {
      warn('服务端暂存失败', messageOf(error));
      return { local: true, remote: false };
    }
  }

  /** 读取待恢复内容：服务端优先，localStorage 兜底；都没有返回 null。 */
  async function recover(chapterId) {
    let draft = null;
    try {
      draft = await api.fetchServerDraft(chapterId);
    } catch (error) {
      if (!messageOf(error).includes(CODE_NOT_FOUND)) {
        warn('读取服务端暂存失败', messageOf(error));
      }
    }
    if (draft) {
      return draft;
    }
    const local = api.readLocalDraft(chapterId);
    if (!local) {
      return null;
    }
    return {
      content_html: local.content,
      saved_at: local.saved_at,
      reason: local.reason,
    };
  }

  /** 补写成功后清理双份暂存；暂存不存在（2001）不算错误。 */
  async function clear(chapterId) {
    api.clearLocalDraft(chapterId);
    try {
      await api.deleteServerDraft(chapterId);
    } catch (error) {
      if (!messageOf(error).includes(CODE_NOT_FOUND)) {
        warn('清理暂存失败', messageOf(error));
      }
    }
  }

  return { persist, recover, clear };
}
