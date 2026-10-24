/** 页面 P3（设定文档页）控制器（任务 2.7 / FR-4）。
 *
 * - 项目级、五类分类、分类筛选、多文档列表
 * - 复用 Quill 编辑器与图片上传（图片落 media/documents/{did}/）
 * - 文档字数**不进入**项目总字数（由后端保证）
 * - 手工保存 + 切换/离开前强制保存；自动保存与版本历史按范围不在本任务
 */

import { request, requestForm } from './api.js';
import {
  applyImageUrls,
  collectImagePaths,
  countWords,
  createEditor,
  normalizeCodeBlocks,
} from './editor.js';
import { createLogger } from './logger.js';
import { askText, el, setContext, showView } from './view.js';

const log = createLogger('documents');
const SIGN_REFRESH_MS = 20 * 60 * 1000;

const state = {
  project: null,
  documents: [],
  document: null,
  filter: null,
  dirty: false,
};

let quill = null;

function setStatus(text, kind = '') {
  const node = el('document-status');
  if (!node) {
    return;
  }
  node.textContent = text;
  node.className = `writer__status${kind ? ` is-${kind}` : ''}`;
}

function timeLabel() {
  return new Date().toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  });
}

function updateStats() {
  if (!quill) {
    return;
  }
  const words = countWords(quill.getText());
  el('stat-document').textContent = `本文 ${words.toLocaleString('zh-CN')} 字`;
}

function clearEditor() {
  state.document = null;
  state.dirty = false;
  el('document-title').value = '';
  el('document-category').value = 'other';
  if (quill) {
    quill.setContents([], 'silent');
    quill.enable(false);
  }
  updateStats();
  renderList();
  setStatus('还没有文档，点「＋文档」新建');
}

// --------------------------------------------------------------------------
// 列表与分类筛选
// --------------------------------------------------------------------------

function renderFilter(categories) {
  const root = el('doc-filter');
  root.textContent = '';

  const makeButton = (label, value) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'doc-filter__btn';
    if (state.filter === value) {
      button.classList.add('is-active');
    }
    button.textContent = label;
    button.addEventListener('click', () => setFilter(value));
    root.append(button);
  };

  makeButton('全部', null);
  for (const category of categories || []) {
    makeButton(category.label, category.value);
  }
}

function renderList() {
  const root = el('document-list');
  if (!root) {
    return;
  }
  root.textContent = '';
  if (!state.documents.length) {
    const empty = document.createElement('p');
    empty.className = 'tree__empty';
    empty.textContent = state.filter ? '该分类下暂无文档' : '还没有设定文档';
    root.append(empty);
    return;
  }

  for (const item of state.documents) {
    // 行 = 打开按钮 + 删除按钮（兄弟节点，不嵌套交互元素；B2 补删除入口）
    const row = document.createElement('div');
    row.className = 'tree__row';

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'tree__chapter';
    button.dataset.documentId = String(item.id);
    if (state.document && item.id === state.document.id) {
      button.classList.add('is-active');
    }

    const name = document.createElement('span');
    name.className = 'tree__name';
    name.textContent = item.title;

    const count = document.createElement('span');
    count.className = 'tree__count';
    count.textContent = `${item.word_count} 字`;

    button.append(name, count);
    button.addEventListener('click', () => openDocument(item.id));

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'tree__delete';
    remove.dataset.documentDelete = String(item.id);
    remove.title = `删除「${item.title}」`;
    remove.setAttribute('aria-label', `删除设定文档「${item.title}」`);
    remove.textContent = '✕';
    remove.addEventListener('click', () => deleteDocument(item));

    row.append(button, remove);
    root.append(row);
  }
}

async function loadList() {
  const query = state.filter
    ? `?category=${encodeURIComponent(state.filter)}`
    : '';
  const data = await request(
    `/api/projects/${state.project.id}/documents${query}`,
  );
  state.documents = data.items;
  renderFilter(data.categories);
  renderList();
}

async function setFilter(value) {
  if (state.dirty) {
    const saved = await saveDocument({ silent: true });
    if (!saved) {
      return;
    }
  }
  state.filter = value;
  try {
    await loadList();
  } catch (error) {
    log.error(error);
    setStatus(`筛选失败：${error.message}`, 'error');
  }
}

// --------------------------------------------------------------------------
// 编辑器
// --------------------------------------------------------------------------

async function openDocument(documentId) {
  if (state.dirty) {
    const saved = await saveDocument({ silent: true });
    if (!saved) {
      return;
    }
  }
  try {
    const detail = await request(`/api/documents/${documentId}`);
    state.document = detail;
    state.dirty = false;
    el('document-title').value = detail.title;
    el('document-category').value = detail.category;
    quill.enable(true);
    quill.clipboard.dangerouslyPasteHTML(detail.content || '', 'silent');
    quill.history.clear();
    updateStats();
    renderList();
    setStatus('已加载');
  } catch (error) {
    log.error(error);
    setStatus(`打开文档失败：${error.message}`, 'error');
  }
}

async function saveDocument({ silent = false } = {}) {
  if (!state.document) {
    return false;
  }
  if (!state.dirty) {
    if (!silent) {
      setStatus('没有需要保存的修改');
    }
    return true;
  }

  const title = el('document-title').value.trim() || state.document.title;
  const category = el('document-category').value;
  try {
    const data = await request(`/api/documents/${state.document.id}`, {
      method: 'PATCH',
      // D-3.4-1：代码块存成 <pre><code>，重开才能还原
      body: { title, category, content_html: normalizeCodeBlocks(quill.root.innerHTML) },
    });
    state.document = data;
    state.dirty = false;
    setStatus(`已保存 ${timeLabel()}`, 'ok');
    el('doc-saved').textContent = `保存于 ${timeLabel()}`;
    updateStats();
    await loadList();
    return true;
  } catch (error) {
    log.error(error);
    setStatus(`保存失败：${error.message}`, 'error');
    return false;
  }
}

/** 删除设定文档（B2）：软删除进回收站（BR-4），破坏性操作二次确认（NFR-U3）。 */
async function deleteDocument(item) {
  const confirmed = window.confirm(
    `删除设定文档「${item.title}」？\n未保存的修改会一起丢弃；删除后可在回收站恢复（30 天内）。`,
  );
  if (!confirmed) {
    return;
  }
  const wasCurrent = Boolean(state.document && state.document.id === item.id);
  try {
    await request(`/api/documents/${item.id}`, { method: 'DELETE' });
    if (wasCurrent) {
      state.document = null;
      state.dirty = false;
      el('document-title').value = '';
      if (quill) {
        quill.setContents([], 'silent');
        quill.enable(false);
      }
    }
    await loadList();
    if (wasCurrent) {
      if (state.documents.length > 0) {
        await openDocument(state.documents[0].id);
      } else {
        clearEditor();
      }
    }
    setStatus(`已删除「${item.title}」，可在回收站恢复`, 'ok');
  } catch (error) {
    log.error(error);
    setStatus(`删除失败：${error.message}`, 'error');
  }
}

async function createDocument() {
  if (!state.project) {
    return;
  }
  const title = await askText({ title: '新建设定文档', label: '文档标题' });
  if (!title) {
    return;
  }
  try {
    const created = await request(
      `/api/projects/${state.project.id}/documents`,
      {
        method: 'POST',
        body: { title, category: state.filter || 'other' },
      },
    );
    await loadList();
    await openDocument(created.id);
  } catch (error) {
    log.error(error);
    setStatus(`新建文档失败：${error.message}`, 'error');
  }
}

// --------------------------------------------------------------------------
// 图片签名续签
// --------------------------------------------------------------------------

async function refreshImageSignatures() {
  if (!state.document || !quill) {
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

// --------------------------------------------------------------------------
// 对外接口
// --------------------------------------------------------------------------

export function initDocuments() {
  try {
    quill = createEditor({
      container: el('doc-editor'),
      placeholder: '记录设定、人物或时间线…',
      ariaLabel: '设定文档正文',
      uploadImage: async (file) => {
        if (!state.document) {
          throw new Error('请先选择文档');
        }
        const form = new FormData();
        form.append('file', file);
        return requestForm(`/api/documents/${state.document.id}/images`, form);
      },
      onTextChange: () => {
        state.dirty = true;
        setStatus('未保存');
        updateStats();
      },
    });
  } catch (error) {
    log.error(error);
    setStatus('编辑器初始化失败', 'error');
    return;
  }

  el('add-document').addEventListener('click', createDocument);
  el('save-document').addEventListener('click', () => {
    saveDocument();
  });
  el('back-to-writer').addEventListener('click', async () => {
    if (state.dirty) {
      const saved = await saveDocument({ silent: true });
      if (!saved) {
        setStatus('保存失败，已取消返回', 'error');
        return;
      }
    }
    showView('view-writer');
    setContext(state.project ? state.project.title : '');
  });

  el('document-title').addEventListener('input', () => {
    state.dirty = true;
    setStatus('未保存');
  });
  el('document-category').addEventListener('change', () => {
    state.dirty = true;
    setStatus('未保存');
  });

  window.setInterval(() => {
    refreshImageSignatures().catch((error) =>
      log.warn('文档图片续签失败', error.message),
    );
  }, SIGN_REFRESH_MS);
}

export async function openDocuments(project) {
  state.project = project;
  state.filter = null;
  state.document = null;
  state.dirty = false;
  el('documents-project-title').textContent = `${project.title} · 设定`;
  setContext(`${project.title} · 设定文档`);
  showView('view-documents');

  try {
    await loadList();
    if (state.documents.length > 0) {
      await openDocument(state.documents[0].id);
    } else {
      clearEditor();
    }
  } catch (error) {
    log.error(error);
    setStatus(`加载设定文档失败：${error.message}`, 'error');
  }
}

/** 离开设定文档页（返回作品列表前由 app.js 调用）。 */
export async function leaveDocuments() {
  if (state.dirty) {
    await saveDocument({ silent: true });
  }
  setContext('');
}

/** 搜索结果跳转：打开项目设定页并定位到指定文档。 */
export async function openDocumentsAt(project, documentId) {
  await openDocuments(project);
  await openDocument(documentId);
}
