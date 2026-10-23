/** 页面 P6（全局搜索）控制器（任务 2.11 / FR-7）。
 *
 * - 搜索范围：全部 / 仅章节 / 仅设定文档；可限定项目
 * - 结果片段由服务端生成并做 HTML 转义，仅 <mark> 为受信标签
 * - 点击章节结果 → 写作页定位；点击设定文档结果 → 设定页定位
 * - 「重建全文索引」调用 #42 长任务
 */

import { request } from './api.js';
import { openDocumentsAt } from './documents.js';
import { createLogger } from './logger.js';
import { runTask } from './tasks.js';
import { el, showView } from './view.js';
import { openWriterAt } from './writer.js';

const log = createLogger('search');

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

async function runSearch() {
  const input = el('search-input');
  const query = (input.value || '').trim();
  if (!query) {
    setStatus('请输入搜索词', 'error');
    return;
  }

  const params = new URLSearchParams({
    q: query,
    scope: el('search-scope').value,
    page: '1',
    page_size: '20',
  });
  const projectId = el('search-project').value;
  if (projectId) {
    params.set('project_id', projectId);
  }

  const results = el('search-results');
  setStatus('搜索中…');
  setHint('');
  try {
    const data = await request(`/api/search?${params.toString()}`);
    results.textContent = '';
    setHint(data.hint || '');
    if (!data.items.length) {
      const empty = document.createElement('p');
      empty.className = 'trash__empty';
      empty.textContent = '没有找到匹配内容。';
      results.append(empty);
      setStatus('共 0 条');
      return;
    }
    for (const item of data.items) {
      results.append(buildHit(item));
    }
    setStatus(`共 ${data.total} 条${data.fuzzy ? '（模糊匹配）' : ''}`);
  } catch (error) {
    log.error(error);
    setStatus(`搜索失败：${error.message}`, 'error');
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
      await runSearch();
    }
  } catch (error) {
    log.error(error);
    setStatus(`重建失败：${error.message}`, 'error');
  } finally {
    button.disabled = false;
  }
}

export function initSearch() {
  el('search-go').addEventListener('click', runSearch);
  el('search-input').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      runSearch();
    }
  });
  el('close-search').addEventListener('click', () => {
    showView('view-projects');
  });
  el('rebuild-fts').addEventListener('click', rebuildIndex);
}

export async function openSearch() {
  showView('view-search');
  setStatus('');
  setHint('');
  await loadProjectOptions();
  el('search-input').focus();
}
