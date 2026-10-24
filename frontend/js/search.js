/** 页面 P6（全局搜索）控制器（任务 2.11 / FR-7；阶段三 3.6 补分页）。
 *
 * - 搜索范围：全部 / 仅章节 / 仅设定文档；可限定项目
 * - 结果片段由服务端生成并做 HTML 转义，仅 <mark> 为受信标签
 * - **分页（FR-7.4）**：每页 20 条，「加载更多」按 `page/page_size/total` 追加；
 *   `page_limited`（单侧窗口 1000 条）时不再继续请求，并显示后端 hint
 * - 加载 / 空 / 出错三态；出错有「重试」，加载更多失败保留已显示结果
 * - 点击章节结果 → 写作页定位；点击设定文档结果 → 设定页定位
 * - 「重建全文索引」调用 #42 长任务
 */

import { request } from './api.js';
import { openDocumentsAt } from './documents.js';
import { createLogger } from './logger.js';
import { clearBusy, showEmpty, showError, showLoading } from './state.js';
import { runTask } from './tasks.js';
import { el, showView } from './view.js';
import { openWriterAt } from './writer.js';

const log = createLogger('search');

const PAGE_SIZE = 20;
// 后端单侧分页窗口上限（S2-17：page*page_size ≤ 1000）
const MAX_WINDOW = 1000;

const state = {
  query: '',
  scope: 'all',
  projectId: '',
  page: 0,
  total: 0,
  loaded: 0,
  pageLimited: false,
  fuzzy: false,
  busy: false,
};

function setStatus(text, kind = '') {
  const node = el('search-status');
  if (!node) {
    return;
  }
  node.textContent = text;
  node.className = `backup__status${kind ? ` is-${kind}` : ''}`;
}

function setHint(text) {
  const node = el('search-hint');
  if (node) {
    node.textContent = text || '';
  }
}

function canLoadMore() {
  if (state.busy || state.loaded === 0 || state.loaded >= state.total) {
    return false;
  }
  if (state.pageLimited && state.page * PAGE_SIZE >= MAX_WINDOW) {
    return false;
  }
  return true;
}

function syncMoreButton() {
  const more = el('search-more');
  if (more) {
    more.hidden = !canLoadMore();
  }
}

async function loadProjectOptions() {
  const select = el('search-project');
  if (!select) {
    return;
  }
  const previous = select.value;
  select.textContent = '';
  const all = document.createElement('option');
  all.value = '';
  all.textContent = '全部项目';
  select.append(all);
  try {
    const data = await request('/api/projects');
    for (const project of data.items) {
      const option = document.createElement('option');
      option.value = String(project.id);
      option.textContent = project.title;
      select.append(option);
    }
    if (previous && [...select.options].some((o) => o.value === previous)) {
      select.value = previous;
    }
  } catch (error) {
    log.warn('读取项目列表失败', error.message);
  }
}

function buildHit(item) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'search-hit';

  const title = document.createElement('span');
  title.className = 'search-hit__title';
  title.textContent = item.title;

  const meta = document.createElement('span');
  meta.className = 'search-hit__meta';
  meta.textContent =
    item.type === 'chapter'
      ? `${item.project_title} · ${item.volume_title} · 章节`
      : `${item.project_title} · 设定 · ${item.category_label}`;

  const snippet = document.createElement('span');
  snippet.className = 'search-hit__snippet';
  snippet.innerHTML = item.snippet || '（无正文片段）';

  button.append(title, meta, snippet);
  button.addEventListener('click', () => openHit(item));
  return button;
}

async function openHit(item) {
  try {
    if (item.type === 'chapter') {
      await openWriterAt(item.project_id, item.id);
      return;
    }
    const project = await request(`/api/projects/${item.project_id}`);
    await openDocumentsAt(project, item.id);
  } catch (error) {
    log.error(error);
    setStatus(`打开失败：${error.message}`, 'error');
  }
}

async function fetchPage(page) {
  const params = new URLSearchParams({
    q: state.query,
    scope: state.scope,
    page: String(page),
    page_size: String(PAGE_SIZE),
  });
  if (state.projectId) {
    params.set('project_id', state.projectId);
  }
  return request(`/api/search?${params.toString()}`);
}

/** 搜索（reset）或加载下一页（append）。 */
async function runSearch({ reset = true } = {}) {
  if (state.busy) {
    return;
  }
  const results = el('search-results');

  if (reset) {
    const query = (el('search-input').value || '').trim();
    if (!query) {
      setStatus('请输入搜索词', 'error');
      return;
    }
    state.query = query;
    state.scope = el('search-scope').value;
    state.projectId = el('search-project').value;
    state.page = 0;
    state.total = 0;
    state.loaded = 0;
    state.pageLimited = false;
    state.fuzzy = false;
    setHint('');
    setStatus('搜索中…');
    showLoading(results, '搜索中…');
  } else {
    setStatus(`加载更多…（已显示 ${state.loaded}/${state.total}）`);
  }
  state.busy = true;
  syncMoreButton();

  try {
    const data = await fetchPage(state.page + 1);
    state.page = data.page;
    state.total = data.total;
    state.pageLimited = Boolean(data.page_limited);
    state.fuzzy = Boolean(data.fuzzy);
    clearBusy(results);
    if (reset) {
      results.textContent = '';
    }
    setHint(data.hint || '');

    if (!data.items.length && state.loaded === 0) {
      showEmpty(results, '没有找到匹配内容。');
      setStatus('共 0 条');
      return;
    }
    for (const item of data.items) {
      results.append(buildHit(item));
    }
    state.loaded += data.items.length;
    setStatus(
      `共 ${state.total} 条${state.fuzzy ? '（模糊匹配）' : ''} · 已显示 ${state.loaded}`,
    );
  } catch (error) {
    log.error(error);
    if (reset) {
      showError(results, `搜索失败：${error.message}`, () => runSearch({ reset: true }));
      setStatus('搜索失败', 'error');
    } else {
      // 加载更多失败：保留已显示结果，按钮仍可再点一次重试
      setStatus(`加载更多失败：${error.message}`, 'error');
    }
  } finally {
    state.busy = false;
    syncMoreButton();
  }
}

async function rebuildIndex() {
  const button = el('rebuild-fts');
  button.disabled = true;
  setStatus('正在重建全文索引…');
  try {
    const body = await request('/api/maintenance/rebuild-fts', {
      method: 'POST',
    });
    const task = await runTask(body.tid, {
      onProgress: (data) => setStatus(data.message || '重建中…'),
    });
    setStatus(
      `索引已重建：${task.result.chapters} 章 / ${task.result.documents} 份设定`,
      'ok',
    );
    if ((el('search-input').value || '').trim()) {
      await runSearch({ reset: true });
    }
  } catch (error) {
    log.error(error);
    setStatus(`重建失败：${error.message}`, 'error');
  } finally {
    button.disabled = false;
  }
}

export function initSearch() {
  el('search-go').addEventListener('click', () => runSearch({ reset: true }));
  el('search-more').addEventListener('click', () => runSearch({ reset: false }));
  el('search-input').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      runSearch({ reset: true });
    }
  });
  el('close-search').addEventListener('click', () => {
    showView('view-projects');
    syncMoreButton();
  });
  el('rebuild-fts').addEventListener('click', rebuildIndex);
}

export async function openSearch() {
  showView('view-search');
  setStatus('');
  setHint('');
  syncMoreButton();
  await loadProjectOptions();
  el('search-input').focus();
}
