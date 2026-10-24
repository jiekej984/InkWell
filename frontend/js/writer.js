/** 页面 P2（项目写作页）控制器。
 *
 * 任务 2.3：卷章树、章节加载/切换、标题保存、正文保存、实时字数。
 * 任务 2.4：自动保存（停输 3s / 最长 30s）、失败重试 1s/3s/9s、
 *           localStorage + drafts/ 双份暂存、3002 先暂存、重启恢复提示。
 * 阶段三 3.5：状态栏三态（保存中… → ✓ 已保存 HH:MM → ⚠ 保存失败，已本地暂存）、
 *           失败态「重试 / 导出本章」（#50）、3002 冲突「刷新并恢复」、
 *           BR-2 失焦 / 页面隐藏强制保存、项目页暂存横幅联动。
 *
 * 大纲树拖拽与快捷键归阶段三 3.2 / 3.7。
 */

import { request, requestForm } from './api.js';
import { createAutosave } from './autosave.js';
import { chapterCapacity } from './capacity.js';
import {
  applyImageUrls,
  collectImagePaths,
  countWords,
  createEditor,
  normalizeCodeBlocks,
} from './editor.js';
import { createDraftStore, isConflictError } from './fallback.js';
import { createLogger } from './logger.js';
import { listServerDrafts, saveLocalDraft } from './pending.js';
import { createSaveBar } from './savebar.js';
import { SAVE_STATES, clockLabel } from './savestate.js';
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
  // 3.5：保存期间又有输入时，用序号判断「这次保存的正文是否已过期」
  editSeq: 0,
};

let quill = null;
let autosave = null;
let versions = null;
let sidebar = null;
let saveBar = null;

// --------------------------------------------------------------------------
// 状态栏 / 统计
// --------------------------------------------------------------------------

/** 与保存三态无关的临时提示（标题已保存、已回滚、导出结果…）。 */
function notifyStatus(text, kind = '', options = {}) {
  if (saveBar) {
    saveBar.notify(text, kind, options);
  }
}

/** 保存三态（idle / editing / saving / saved / failed / conflict）。 */
function setSaveState(next, options = {}) {
  if (saveBar) {
    saveBar.set(next, options);
  }
}

function currentSaveState() {
  return saveBar ? saveBar.getState() : SAVE_STATES.IDLE;
}

/** 暂存落盘 / 清理后通知项目页刷新横幅（3.5：两页提示联动）。 */
function notifyDraftsChanged() {
  window.dispatchEvent(new CustomEvent('inkwell:drafts-changed'));
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

/** 当前正文的「存档形态」：代码块序列化为 `<pre><code>`（D-3.4-1），保存与暂存都走这里。 */
function currentHtml() {
  return quill ? normalizeCodeBlocks(quill.root.innerHTML) : '';
}

/** FR-3.9：单章容量提示（5 万提示 / 8 万建议拆章），只提示，不阻断编辑与保存。 */
function updateCapacity(words) {
  const node = el('chapter-capacity');
  if (!node) {
    return;
  }
  const info = chapterCapacity(words);
  node.hidden = info.level === 'ok';
  node.textContent = info.label;
  node.className = `statusbar__chip${
    info.level === 'ok' ? '' : ` is-${info.level}`
  }`;
  node.title = info.detail;
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
  updateCapacity(words);
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
  await drafts.persist(state.chapter.id, currentHtml(), reason);
  notifyDraftsChanged();
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
  notifyStatus('已恢复暂存，正在补写…');
  updateStats();

  const result = await saveContent();
  if (result.ok) {
    notifyStatus('暂存已恢复并自动补写', 'ok');
    return true;
  }
  notifyStatus('暂存已恢复，补写失败，已再次落盘', 'error');
  return true;
}

// --------------------------------------------------------------------------
// 保存三态动作（3.5 / §7.4）
// --------------------------------------------------------------------------

/** 失败态「导出本章」：把**编辑器当前正文**发给 #50，保存失败的稿子也能落到文件。 */
async function exportChapter() {
  if (!state.chapter || !quill) {
    notifyStatus('请先打开章节', 'error');
    return;
  }
  const title = (el('chapter-title').value || '').trim() || state.chapter.title;
  notifyStatus('正在导出本章…');
  try {
    const data = await request(`/api/chapters/${state.chapter.id}/export`, {
      method: 'POST',
      body: { format: 'txt', title, content_html: currentHtml() },
    });
    notifyStatus(`已导出 ${data.filename}（${data.relpath}）`, 'ok', {
      timeoutMs: 12000,
      title: data.path,
    });
  } catch (error) {
    log.error(error);
    notifyStatus(`导出失败：${error.message}`, 'error', { timeoutMs: 8000 });
  }
}

/** 冲突态「刷新并恢复」：先保暂存，再重新载入库内正文并自动补写。 */
async function reloadAfterConflict() {
  if (!state.chapter) {
    return;
  }
  const chapterId = state.chapter.id;
  notifyStatus('正在刷新并恢复暂存…');
  await persistDraft('version_conflict');
  // force：跳过切换前的 flush（再提交只会顶着同一个旧版本号继续 3002）
  await openChapter(chapterId, { autoRestore: true, force: true });
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
  setSaveState(SAVE_STATES.IDLE);
}

async function openChapter(chapterId, { autoRestore = false, force = false } = {}) {
  if (!force && state.dirty && autosave) {
    const saved = await autosave.flush('switch');
    if (!saved) {
      setSaveState(SAVE_STATES.FAILED);
      notifyStatus('本章保存失败，内容已暂存；已取消切换', 'error');
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
    notifyStatus('');
    // 打开即视为「已保存」：时间取库内最后保存时间，不是「就绪」这种含糊态
    setSaveState(SAVE_STATES.SAVED, { at: clockLabel(detail.updated_at) });

    request(`/api/projects/${state.project.id}`, {
      method: 'PATCH',
      body: { last_chapter_id: chapterId },
    }).catch((error) => log.warn('记录上次章节失败', error.message));

    await maybeRestoreDraft(chapterId, autoRestore);
  } catch (error) {
    log.error(error);
    notifyStatus(`打开章节失败：${error.message}`, 'error');
  }
}

/** 正文保存；返回 ``{ok, conflict, message}``（供 autosave 调度）。 */
async function saveContent() {
  if (!state.chapter || !quill) {
    return { ok: true, skipped: true };
  }
  if (!state.dirty) {
    return { ok: true, skipped: true };
  }

  const chapterId = state.chapter.id;
  // 保存期间用户继续输入时，这次保存的正文会「过期」：成功后不能把 dirty 清掉，
  // 否则这段输入会静默丢失（3.5「无静默失败」）
  const seq = state.editSeq;
  setSaveState(SAVE_STATES.SAVING);

  try {
    const data = await request(`/api/chapters/${chapterId}/content`, {
      method: 'PUT',
      body: {
        content_html: currentHtml(),
        client_saved_at: new Date().toISOString(),
        expect_version: state.chapter.version_no,
      },
    });
    state.chapter.version_no = data.version_no;
    state.savedWords = data.word_count;
    state.projectWords = data.project_word_count;
    state.dirty = state.editSeq !== seq;
    if (!state.dirty) {
      clearLocalDraftTimer();
    }
    await drafts.clear(chapterId);
    notifyDraftsChanged();

    updateStats();
    patchTreeChapter(chapterId, {
      title: state.chapter.title,
      word_count: data.word_count,
      version_no: data.version_no,
    });

    if (state.dirty) {
      setSaveState(SAVE_STATES.EDITING);
      notifyStatus('保存期间又有修改，稍后继续保存');
      // 等 autosave.flush 的 finally 把 inFlight 放掉，再排下一次
      window.setTimeout(() => {
        if (autosave) {
          autosave.schedule();
        }
      }, 0);
    } else {
      setSaveState(SAVE_STATES.SAVED, { at: clockLabel() });
    }
    return { ok: true };
  } catch (error) {
    log.error(error);
    const conflict = isConflictError(error);
    await persistDraft(conflict ? 'version_conflict' : 'save_failed');
    if (conflict) {
      setSaveState(SAVE_STATES.CONFLICT);
      notifyStatus('请点「刷新并恢复」重新载入后自动补写', 'error');
    } else {
      setSaveState(SAVE_STATES.FAILED);
    }
    return { ok: false, conflict, message: error.message };
  }
}

/** autosave 的结构化状态 → 状态栏三态（重试倒计时 / 耗尽 / 冲突）。 */
function handleAutosaveStatus(message, kind, meta = {}) {
  switch (meta.phase) {
    case 'retry':
      setSaveState(SAVE_STATES.FAILED, { message });
      break;
    case 'exhausted':
      setSaveState(SAVE_STATES.FAILED);
      break;
    case 'conflict':
      setSaveState(SAVE_STATES.CONFLICT);
      break;
    default:
      notifyStatus(message, kind);
  }
}

function handleTextChange() {
  state.editSeq += 1;
  state.dirty = true;
  const current = currentSaveState();
  // 失败 / 冲突态下继续输入不把状态改成「未保存」，否则问题被掩盖、动作按钮也消失
  if (
    current !== SAVE_STATES.FAILED &&
    current !== SAVE_STATES.CONFLICT &&
    current !== SAVE_STATES.SAVING
  ) {
    setSaveState(SAVE_STATES.EDITING);
  }
  updateStats();
  if (autosave) {
    autosave.schedule();
  }
  // AC-4：首轮改动后 2 秒写一次 localStorage；之后由 10 秒轮询兜底
  if (state.localDraftTimer === null) {
    state.localDraftTimer = window.setTimeout(() => {
      state.localDraftTimer = null;
      if (state.chapter && state.dirty) {
        saveLocalDraft(state.chapter.id, currentHtml(), 'editing');
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
    notifyStatus('标题已保存', 'ok');
  } catch (error) {
    log.error(error);
    notifyStatus(`标题保存失败：${error.message}`, 'error');
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
    notifyStatus(`已回滚至 #${data.restored_from}，生成 #${data.version_no}`, 'ok');
  }
}

// --------------------------------------------------------------------------
// BR-2：失焦 / 页面隐藏强制保存
// --------------------------------------------------------------------------

/** 窗口失焦、页面隐藏时：先同步写本地暂存，再尝试保存（失败会走正常三态）。 */
function saveOnHide(reason) {
  if (!state.chapter || !state.dirty || !quill) {
    return;
  }
  saveLocalDraft(state.chapter.id, currentHtml(), reason);
  if (autosave) {
    autosave
      .flush(reason)
      .catch((error) => log.warn('隐藏时保存失败', error.message));
  }
}

// --------------------------------------------------------------------------
// 对外接口
// --------------------------------------------------------------------------

export function initWriter() {
  saveBar = createSaveBar({
    root: el('save-state'),
    icon: el('save-state-icon'),
    text: el('save-status'),
    note: el('status-note'),
    actions: {
      retry: el('retry-save'),
      export: el('export-chapter'),
      reload: el('reload-chapter'),
    },
  });

  try {
    quill = createEditor({
      container: el('editor'),
      placeholder: '开始写这一章…',
      ariaLabel: '章节正文',
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
    notifyStatus('编辑器初始化失败', 'error');
    return;
  }

  autosave = createAutosave({ save: saveContent, onStatus: handleAutosaveStatus });
  versions = initVersions({
    getChapter: () => state.chapter,
    ensureSaved: async () => {
      if (!state.dirty) {
        return true;
      }
      return autosave.flush('snapshot');
    },
    setStatus: notifyStatus,
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
    setStatus: notifyStatus,
  });

  el('open-documents').addEventListener('click', () => {
    if (state.project) {
      openDocuments(state.project);
    }
  });
  el('save-chapter').addEventListener('click', () => {
    if (!state.dirty) {
      notifyStatus('没有需要保存的修改');
      return;
    }
    autosave.flush('manual');
  });
  el('retry-save').addEventListener('click', () => {
    if (!autosave) {
      return;
    }
    notifyStatus('正在重试保存…');
    autosave.retryNow().catch((error) => log.error(error));
  });
  el('export-chapter').addEventListener('click', () => {
    exportChapter().catch((error) => log.error(error));
  });
  el('reload-chapter').addEventListener('click', () => {
    reloadAfterConflict().catch((error) => log.error(error));
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
      // FR-5.5：Ctrl+S = 保存 + 手动快照（永久保留）
      const saved = await autosave.flush('hotkey');
      if (saved && versions) {
        await versions.snapshot();
      }
    }
  });

  // BR-2：失焦 / 页面隐藏 / 关闭 三条路径都要强制保存（切换章节由 openChapter 负责）
  window.addEventListener('blur', () => saveOnHide('blur'));
  window.addEventListener('pagehide', () => saveOnHide('pagehide'));
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      saveOnHide('hidden');
    }
  });

  // AC-4：写作过程中每 10 秒把编辑器内容写进 localStorage（强杀兜底）
  window.setInterval(() => {
    if (state.chapter && state.dirty && quill) {
      saveLocalDraft(state.chapter.id, currentHtml(), 'editing');
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
    saveLocalDraft(state.chapter.id, currentHtml(), 'beforeunload');
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
    setSaveState(SAVE_STATES.IDLE);
    notifyStatus('');

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
      notifyStatus('还没有章节，点上方「＋卷 / ＋章」开始');
    }
  } catch (error) {
    log.error(error);
    notifyStatus(`打开项目失败：${error.message}`, 'error');
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
  return quill ? currentHtml() : '';
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
