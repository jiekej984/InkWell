/** 页面 P2（项目写作页）控制器。
 *
 * 任务 2.3：卷章树、章节加载/切换、标题保存、正文保存、实时字数。
 * 任务 2.4：自动保存（停输 3s / 最长 30s）、失败重试 1s/3s/9s、
 *           localStorage + drafts/ 双份暂存、3002 先暂存、重启恢复提示。
 *
 * 大纲树拖拽与快捷键归阶段三 3.2 / 3.7。
 */

import { request, requestForm } from './api.js';
import { createAutosave } from './autosave.js';
import {
  applyImageUrls,
  collectImagePaths,
  countWords,
  createEditor,
} from './editor.js';
import { createDraftStore, isConflictError } from './fallback.js';
import { createLogger } from './logger.js';
import { listServerDrafts, saveLocalDraft } from './pending.js';
import { el, setContext, showView } from './view.js';
import { initVersions } from './versions.js';
import { openDocuments } from './documents.js';
import { initSidebar } from './sidebar.js';

const log = createLogger('writer');
const drafts = createDraftStore({ log });
const SIGN_REFRESH_MS = 20 * 60 * 1000; // V-03：签名 30 分钟，提前 10 分钟续签
const LOCAL_DRAFT_INTERVAL_MS = 10 * 1000; // AC-4：强杀丢失 ≤10 秒

const state = {
  project: null,
  tree: null,
  chapter: null,
  savedWords: 0,
  projectWords: 0,
  dirty: false,
  localDraftTimer: null,
};

let quill = null;
let autosave = null;
let versions = null;
let sidebar = null;

// --------------------------------------------------------------------------
// 状态栏 / 统计
// --------------------------------------------------------------------------

function setStatus(text, kind = '') {
  const node = el('save-status');
  if (!node) {
    return;
  }
  node.textContent = text;
  node.className = `writer__status${kind ? ` is-${kind}` : ''}`;
}

function setRetryVisible(visible) {
  const button = el('retry-save');
  if (button) {
    button.hidden = !visible;
  }
}

function timeLabel() {
  return new Date().toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatDraftTime(value) {
  if (!value) {
    return '未知时间';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function currentWords() {
  return quill ? countWords(quill.getText()) : 0;
}

function updateStats() {
  if (!quill) {
    return;
  }
  const words = currentWords();
  const projectTotal = Math.max(
    0,
    state.projectWords - state.savedWords + words,
  );
  el('stat-chapter').textContent = `本章 ${words.toLocaleString('zh-CN')} 字`;
  el('stat-version').textContent = `版本 #${state.chapter ? state.chapter.version_no : 0}`;
  el('stat-project').textContent = `全书 ${projectTotal.toLocaleString('zh-CN')} 字`;
}

// --------------------------------------------------------------------------
// 大纲树
// --------------------------------------------------------------------------

function allVolumes() {
  if (!state.tree) {
    return [];
  }
  return state.tree.volumes.length > 0
    ? state.tree.volumes
    : [state.tree.default_volume];
}

function findChapter(chapterId) {
  if (!chapterId || !state.tree) {
    return null;
  }
  for (const volume of [...state.tree.volumes, state.tree.default_volume]) {
    const chapter = volume.chapters.find((item) => item.id === chapterId);
    if (chapter) {
      return { volume, chapter };
    }
  }
  return null;
}

function firstChapter() {
  for (const volume of allVolumes()) {
    if (volume.chapters.length > 0) {
      return { volume, chapter: volume.chapters[0] };
    }
  }
  return null;
}

function patchTreeChapter(chapterId, patch) {
  const found = findChapter(chapterId);
  if (found) {
    Object.assign(found.chapter, patch);
  }
  if (sidebar) {
    sidebar.updateChapter(chapterId, patch);
  }
}

function renderTree() {
  if (sidebar && state.tree) {
    sidebar.render(state.tree);
  }
}

async function loadTree() {
  state.tree = await request(`/api/projects/${state.project.id}/volumes`);
  renderTree();
}

// --------------------------------------------------------------------------
// 暂存（BR-2 双份兜底）
// --------------------------------------------------------------------------

function clearLocalDraftTimer() {
  if (state.localDraftTimer !== null) {
    window.clearTimeout(state.localDraftTimer);
    state.localDraftTimer = null;
  }
}

async function persistDraft(reason) {
  if (!state.chapter || !quill) {
    return;
  }
  await drafts.persist(state.chapter.id, quill.root.innerHTML, reason);
}

/** 打开章节后检查暂存并恢复；返回是否恢复过内容。 */
async function maybeRestoreDraft(chapterId, autoRestore) {
  const draft = await drafts.recover(chapterId);
  if (!draft) {
    return false;
  }

  const confirmed =
    autoRestore ||
    window.confirm(
      `发现未保存的暂存（${formatDraftTime(draft.saved_at)}），是否恢复并补写？`,
    );
  if (!confirmed) {
    return false;
  }

  quill.enable(true);
  quill.clipboard.dangerouslyPasteHTML(draft.content_html || '', 'silent');
  quill.history.clear();
  state.dirty = true;
  setStatus('已恢复暂存，正在补写…');
  updateStats();

  const result = await saveContent();
  if (result.ok) {
    setStatus('暂存已恢复并自动补写', 'ok');
    return true;
  }
  setStatus('暂存已恢复，补写失败，已再次落盘', 'error');
  return true;
}

// --------------------------------------------------------------------------
// 章节
// --------------------------------------------------------------------------

function clearEditor() {
  state.chapter = null;
  state.savedWords = 0;
  state.dirty = false;
  clearLocalDraftTimer();
  el('chapter-title').value = '';
  if (quill) {
    quill.setContents([], 'silent');
    quill.enable(false);
  }
  updateStats();
  renderTree();
  if (sidebar) {
    sidebar.setActive(null);
  }
}

async function openChapter(chapterId, { autoRestore = false } = {}) {
  if (state.dirty && autosave) {
    const saved = await autosave.flush('switch');
    if (!saved) {
      setStatus('本章保存失败，内容已暂存；已取消切换', 'error');
      return;
    }
  }
  try {
    const detail = await request(`/api/chapters/${chapterId}`);
    state.chapter = detail;
    state.savedWords = detail.word_count;
    state.projectWords = detail.project_word_count;
    state.dirty = false;

    el('chapter-title').value = detail.title;
    quill.enable(true);
    quill.clipboard.dangerouslyPasteHTML(detail.content || '', 'silent');
    quill.history.clear();
    updateStats();
    renderTree();
    setStatus('已加载');
    setRetryVisible(false);

    request(`/api/projects/${state.project.id}`, {
      method: 'PATCH',
      body: { last_chapter_id: chapterId },
    }).catch((error) => log.warn('记录上次章节失败', error.message));

    await maybeRestoreDraft(chapterId, autoRestore);
  } catch (error) {
    log.error(error);
    setStatus(`打开章节失败：${error.message}`, 'error');
  }
}

/** 正文保存；返回 ``{ok, conflict, message}``（供 autosave 调度）。 */
async function saveContent() {
  if (!state.chapter || !quill) {
    return { ok: true, skipped: true };
  }
  if (!state.dirty) {
    setRetryVisible(false);
    return { ok: true, skipped: true };
  }

  const chapterId = state.chapter.id;
  try {
    const data = await request(`/api/chapters/${chapterId}/content`, {
      method: 'PUT',
      body: {
        content_html: quill.root.innerHTML,
        client_saved_at: new Date().toISOString(),
        expect_version: state.chapter.version_no,
      },
    });
    state.chapter.version_no = data.version_no;
    state.savedWords = data.word_count;
    state.projectWords = data.project_word_count;
    state.dirty = false;
    clearLocalDraftTimer();
    await drafts.clear(chapterId);

    setRetryVisible(false);
    setStatus(`已保存 ${timeLabel()}`, 'ok');
    el('stat-saved').textContent = `保存于 ${timeLabel()}`;
    updateStats();
    patchTreeChapter(chapterId, {
      title: state.chapter.title,
      word_count: data.word_count,
      version_no: data.version_no,
    });
    return { ok: true };
  } catch (error) {
    log.error(error);
    const conflict = isConflictError(error);
    await persistDraft(conflict ? 'version_conflict' : 'save_failed');
    setRetryVisible(true);
    setStatus(
      conflict ? '版本冲突：内容已本地暂存，请刷新后恢复' : '保存失败，已本地暂存',
      'error',
    );
    return { ok: false, conflict, message: error.message };
  }
}

function handleTextChange() {
  state.dirty = true;
  setStatus('未保存');
  updateStats();
  if (autosave) {
    autosave.schedule();
  }
  // AC-4：首轮改动后 2 秒写一次 localStorage；之后由 10 秒轮询兜底
  if (state.localDraftTimer === null) {
    state.localDraftTimer = window.setTimeout(() => {
      state.localDraftTimer = null;
      if (state.chapter && state.dirty) {
        saveLocalDraft(state.chapter.id, quill.root.innerHTML, 'editing');
      }
    }, 2000);
  }
}

async function saveTitle() {
  if (!state.chapter) {
    return;
  }
  const title = el('chapter-title').value.trim();
  if (!title || title === state.chapter.title) {
    el('chapter-title').value = state.chapter.title;
    return;
  }
  try {
    const data = await request(`/api/chapters/${state.chapter.id}`, {
      method: 'PATCH',
      body: { title },
    });
    state.chapter.title = data.title;
    patchTreeChapter(state.chapter.id, { title: data.title });
    setStatus('标题已保存', 'ok');
  } catch (error) {
    log.error(error);
    setStatus(`标题保存失败：${error.message}`, 'error');
  }
}

// --------------------------------------------------------------------------
// 定稿（FR-5.6：里程碑快照）
// --------------------------------------------------------------------------

/** 标记定稿：当前章节先保存，再生成 milestone 快照；返回快照或 null。 */
async function markChapterFinal(chapter) {
  const isCurrent = state.chapter && state.chapter.id === chapter.id;
  if (isCurrent && state.dirty) {
    const saved = await autosave.flush('milestone');
    if (!saved) {
      return null;
    }
  }
  const data = await request(`/api/chapters/${chapter.id}/versions`, {
    method: 'POST',
    body: { change_type: 'milestone' },
  });
  if (isCurrent) {
    state.chapter.version_no = data.version_no;
    updateStats();
    patchTreeChapter(chapter.id, { version_no: data.version_no });
  }
  return data;
}

// --------------------------------------------------------------------------
// 图片签名续签（V-03）
// --------------------------------------------------------------------------

async function refreshImageSignatures() {
  if (!state.chapter || !quill) {
    return;
  }
  const paths = collectImagePaths(quill);
  if (paths.length === 0) {
    return;
  }
  const data = await request('/api/files/sign', {
    method: 'POST',
    body: { paths },
  });
  applyImageUrls(quill, data.items);
}

/** 版本面板回调：手动快照 / 回滚后的页面状态同步。 */
async function handleVersionChanged({ kind, data }) {
  if (!state.chapter) {
    return;
  }
  if (kind === 'snapshot') {
    state.chapter.version_no = data.version_no;
    updateStats();
    patchTreeChapter(state.chapter.id, { version_no: data.version_no });
    return;
  }
  if (kind === 'restore') {
    await openChapter(state.chapter.id);
    setStatus(`已回滚至 #${data.restored_from}，生成 #${data.version_no}`, 'ok');
  }
}

// --------------------------------------------------------------------------
// 对外接口
// --------------------------------------------------------------------------

export function initWriter() {
  try {
    quill = createEditor({
      container: el('editor'),
      uploadImage: async (file) => {
        if (!state.chapter) {
          throw new Error('请先选择章节');
        }
        const form = new FormData();
        form.append('file', file);
        return requestForm(`/api/chapters/${state.chapter.id}/images`, form);
      },
      onTextChange: handleTextChange,
    });
  } catch (error) {
    log.error(error);
    setStatus('编辑器初始化失败', 'error');
    return;
  }

  autosave = createAutosave({ save: saveContent, onStatus: setStatus });
  versions = initVersions({
    getChapter: () => state.chapter,
    ensureSaved: async () => {
      if (!state.dirty) {
        return true;
      }
      return autosave.flush('snapshot');
    },
    setStatus,
    onChanged: handleVersionChanged,
  });

  sidebar = initSidebar({
    getTree: () => state.tree,
    getProjectId: () => (state.project ? state.project.id : 0),
    getChapterId: () => (state.chapter ? state.chapter.id : null),
    onOpenChapter: (chapterId) => openChapter(chapterId),
    onReload: async () => {
      await loadTree();
      return state.tree;
    },
    onMarkFinal: (chapter) => markChapterFinal(chapter),
    onChapterUpdated: (chapterId, patch) => {
      if (state.chapter && state.chapter.id === chapterId) {
        Object.assign(state.chapter, patch);
        if (patch.title) {
          const input = el('chapter-title');
          if (input) {
            input.value = patch.title;
          }
        }
        updateStats();
      }
      patchTreeChapter(chapterId, patch);
    },
    onDeletedCurrent: () => clearEditor(),
    setStatus,
  });

  el('open-documents').addEventListener('click', () => {
    if (state.project) {
      openDocuments(state.project);
    }
  });
  el('save-chapter').addEventListener('click', () => {
    if (!state.dirty) {
      setStatus('没有需要保存的修改');
      return;
    }
    setRetryVisible(false);
    autosave.flush('manual');
  });
  el('retry-save').addEventListener('click', () => {
    setRetryVisible(false);
    autosave.flush('retry-manual');
  });

  const title = el('chapter-title');
  title.addEventListener('change', saveTitle);
  title.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      title.blur();
    }
  });

  document.addEventListener('keydown', async (event) => {
    // V-03：IME 组合期间（isComposing / keyCode 229）不得触发全局快捷键
    if (event.isComposing || event.keyCode === 229) {
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
      event.preventDefault();
      setRetryVisible(false);
      // FR-5.5：Ctrl+S = 保存 + 手动快照（永久保留）
      const saved = await autosave.flush('hotkey');
      if (saved && versions) {
        await versions.snapshot();
      }
    }
  });

  // AC-4：写作过程中每 10 秒把编辑器内容写进 localStorage（强杀兜底）
  window.setInterval(() => {
    if (state.chapter && state.dirty && quill) {
      saveLocalDraft(state.chapter.id, quill.root.innerHTML, 'editing');
    }
  }, LOCAL_DRAFT_INTERVAL_MS);

  window.setInterval(() => {
    refreshImageSignatures().catch((error) =>
      log.warn('图片签名续签失败', error.message),
    );
  }, SIGN_REFRESH_MS);

  // 正常关闭窗口前：同步写本地暂存并提示未保存
  window.addEventListener('beforeunload', (event) => {
    if (!state.chapter || !state.dirty || !quill) {
      return;
    }
    saveLocalDraft(state.chapter.id, quill.root.innerHTML, 'beforeunload');
    event.preventDefault();
    event.returnValue = '';
  });
}

export async function openWriter(projectId) {
  try {
    const project = await request(`/api/projects/${projectId}`);
    state.project = project;
    state.projectWords = project.total_word_count;
    state.chapter = null;
    state.savedWords = 0;
    state.dirty = false;
    if (autosave) {
      autosave.reset();
    }

    el('writer-project-title').textContent = project.title;
    setContext(project.title);
    showView('view-writer');

    await loadTree();

    // 重启后：先看服务端暂存列表，是否有本项目章节的待恢复内容
    let restoreChapterId = null;
    try {
      const listing = await listServerDrafts();
      const recoverable = (listing.items || []).filter((item) =>
        findChapter(item.chapter_id),
      );
      if (recoverable.length > 0) {
        const latest = recoverable[0];
        const confirmed = window.confirm(
          `发现 ${recoverable.length} 条未保存的暂存（最近：${formatDraftTime(latest.saved_at)}）。` +
            '是否打开并恢复最近一条？',
        );
        if (confirmed) {
          restoreChapterId = latest.chapter_id;
        }
      }
    } catch (error) {
      log.warn('读取暂存列表失败', error.message);
    }

    const target =
      (restoreChapterId && findChapter(restoreChapterId)) ||
      findChapter(project.last_chapter_id) ||
      firstChapter();
    if (target) {
      await openChapter(target.chapter.id, {
        autoRestore: target.chapter.id === restoreChapterId,
      });
    } else {
      clearEditor();
      setStatus('还没有章节，点上方「＋卷 / ＋章」开始');
    }
  } catch (error) {
    log.error(error);
    setStatus(`打开项目失败：${error.message}`, 'error');
  }
}

/** 离开写作页前的强制保存（失败时内容已落暂存，不阻断返回）。 */
export async function leaveWriter() {
  if (state.dirty && autosave) {
    await autosave.flush('leave');
  }
  setContext('');
}

/** 以下供 2.6 / 阶段三复用。 */
export function currentChapter() {
  return state.chapter;
}

export function isDirty() {
  return state.dirty;
}

export function editorHtml() {
  return quill ? quill.root.innerHTML : '';
}

export function saveNow() {
  return saveContent();
}

export function enableEditing(enabled) {
  if (quill) {
    quill.enable(enabled);
  }
}

/** 聚焦正文并把光标放到末尾（首启引导 C-09 用）。
 *
 * 返回 ``false`` 表示编辑器尚未就绪（没有章节 / 仍是只读），调用方跳过即可。
 * **必须等章节加载完成、`contenteditable=true` 之后再聚焦**，否则首次输入的
 * 组合串会被丢弃 —— 复现与结论见 `docs/版本更新/阶段三_IME验证记录.md` §二。
 */
export function focusEditor({ atEnd = true } = {}) {
  if (!quill || !state.chapter) {
    return false;
  }
  const root = quill.root;
  if (!root || !root.isContentEditable) {
    return false;
  }
  quill.focus();
  if (atEnd) {
    quill.setSelection(Math.max(0, quill.getLength() - 1), 0, 'silent');
  }
  return true;
}

/** 搜索结果跳转：打开项目并定位到指定章节。 */
export async function openWriterAt(projectId, chapterId) {
  await openWriter(projectId);
  if (chapterId && findChapter(chapterId)) {
    await openChapter(chapterId);
  }
}
