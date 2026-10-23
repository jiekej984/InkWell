/** 页面 P7（备份与恢复）控制器（任务 2.9 / FR-6.1~6.3）。
 *
 * - 立即备份、备份列表（手动/每日/迁移前/恢复前）、磁盘余量
 * - 恢复前二次确认；后端先校验，前端轮询长任务，成功后刷新页面
 */

import { request, requestBlob } from './api.js';
import { createLogger } from './logger.js';
import { runTask } from './tasks.js';
import { el, showView } from './view.js';

const log = createLogger('backup');

const KIND_LABELS = {
  manual: '手动',
  daily: '每日',
  premigrate: '迁移前',
  prerestore: '恢复前',
};

let busy = false;
let dataDir = '';

function formatBytes(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) {
    return '未知';
  }
  if (number >= 1024 ** 3) {
    return `${(number / 1024 ** 3).toFixed(1)} GB`;
  }
  if (number >= 1024 ** 2) {
    return `${(number / 1024 ** 2).toFixed(1)} MB`;
  }
  if (number >= 1024) {
    return `${(number / 1024).toFixed(1)} KB`;
  }
  return `${number} B`;
}

function formatTime(value) {
  if (!value) {
    return '';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function setTaskStatus(text, kind = '') {
  const node = el('backup-status');
  if (!node) {
    return;
  }
  node.textContent = text;
  node.className = `backup__status${kind ? ` is-${kind}` : ''}`;
}

function setExportStatus(text, kind = '') {
  const node = el('export-status');
  if (!node) {
    return;
  }
  node.textContent = text;
  node.className = `backup__status${kind ? ` is-${kind}` : ''}`;
}

function buildRow(item) {
  const row = document.createElement('div');
  row.className = 'trash__row';

  const info = document.createElement('div');
  info.className = 'trash__info';

  const title = document.createElement('span');
  title.className = 'trash__title';
  title.textContent = item.name;

  const meta = document.createElement('span');
  meta.className = 'trash__meta';
  meta.textContent = `${KIND_LABELS[item.kind] || item.kind} · ${formatBytes(
    item.size,
  )} · ${formatTime(item.created_at)}`;

  info.append(title, meta);

  const restore = document.createElement('button');
  restore.type = 'button';
  restore.className = 'btn btn--small';
  restore.textContent = '恢复';
  restore.addEventListener('click', () => restoreBackup(item));

  row.append(info, restore);
  return row;
}

export async function loadBackups() {
  const list = el('backup-list');
  if (!list) {
    return;
  }
  list.textContent = '';
  try {
    const data = await request('/api/backups');
    el('backup-disk').textContent = `磁盘余量：${formatBytes(
      data.disk_free_bytes,
    )}`;
    if (!data.items.length) {
      const empty = document.createElement('p');
      empty.className = 'trash__empty';
      empty.textContent = '还没有备份，点「立即备份」创建第一份。';
      list.append(empty);
      return;
    }
    for (const item of data.items) {
      list.append(buildRow(item));
    }
  } catch (error) {
    log.error(error);
    const failed = document.createElement('p');
    failed.className = 'trash__empty';
    failed.textContent = `读取备份列表失败：${error.message}`;
    list.append(failed);
  }
}

async function createBackup() {
  if (busy) {
    return;
  }
  busy = true;
  setTaskStatus('正在备份…');
  try {
    const body = await request('/api/backup', { method: 'POST' });
    await runTask(body.tid, {
      onProgress: (data) => {
        setTaskStatus(data.message || '备份中…');
      },
    });
    setTaskStatus('备份完成', 'ok');
    await loadBackups();
  } catch (error) {
    log.error(error);
    setTaskStatus(`备份失败：${error.message}`, 'error');
  } finally {
    busy = false;
  }
}

async function restoreBackup(item) {
  if (busy) {
    return;
  }
  const confirmed = window.confirm(
    `从备份「${item.name}」恢复？\n` +
      '恢复前会自动备份当前数据；完成后页面将重新加载。',
  );
  if (!confirmed) {
    return;
  }
  busy = true;
  setTaskStatus('正在校验并恢复…');
  try {
    const body = await request(
      `/api/backups/${encodeURIComponent(item.name)}/restore`,
      { method: 'POST' },
    );
    await runTask(body.tid, {
      onProgress: (data) => {
        setTaskStatus(data.message || '恢复中…');
      },
    });
    setTaskStatus('恢复完成，正在刷新…', 'ok');
    window.setTimeout(() => window.location.reload(), 600);
  } catch (error) {
    log.error(error);
    setTaskStatus(`恢复失败：${error.message}`, 'error');
  } finally {
    busy = false;
  }
}

async function loadExportProjects() {
  const select = el('export-project');
  if (!select) {
    return;
  }
  const previous = select.value;
  select.textContent = '';
  try {
    const data = await request('/api/projects');
    if (!data.items.length) {
      const option = document.createElement('option');
      option.value = '';
      option.textContent = '（还没有项目）';
      select.append(option);
      return;
    }
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

async function exportProject() {
  if (busy) {
    return;
  }
  const select = el('export-project');
  const projectId = select ? select.value : '';
  if (!projectId) {
    setExportStatus('请先选择项目', 'error');
    return;
  }
  const format = el('export-format').value;
  busy = true;
  setExportStatus('正在导出…');
  try {
    const body = await request(`/api/projects/${projectId}/export`, {
      method: 'POST',
      body: { format },
    });
    const task = await runTask(body.tid, {
      onProgress: (data) => {
        setExportStatus(data.message || '导出中…');
      },
    });
    const result = task.result;
    const location = dataDir
      ? `${dataDir}/${result.relpath}`
      : result.relpath;
    setExportStatus(
      `导出完成：${result.chapters} 章 / ${result.word_count} 字\n${location}`,
      'ok',
    );
  } catch (error) {
    log.error(error);
    setExportStatus(`导出失败：${error.message}`, 'error');
  } finally {
    busy = false;
  }
}

async function downloadDiagnostics() {
  try {
    setTaskStatus('正在生成诊断包…');
    const blob = await requestBlob('/api/system/diagnostics');
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'inkwell-diagnostics.zip';
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    setTaskStatus('诊断包已导出（仅含日志与库结构摘要）', 'ok');
  } catch (error) {
    log.error(error);
    setTaskStatus(`诊断包生成失败：${error.message}`, 'error');
  }
}

export async function openBackup() {
  showView('view-backup');
  setTaskStatus('');
  setExportStatus('');
  if (!dataDir) {
    try {
      const meta = await request('/api/system/meta');
      dataDir = meta.data_dir || '';
    } catch (error) {
      log.warn('读取数据目录失败', error.message);
    }
  }
  await Promise.all([loadBackups(), loadExportProjects()]);
}

export function initBackup() {
  el('backup-now').addEventListener('click', createBackup);
  el('refresh-backups').addEventListener('click', loadBackups);
  el('export-now').addEventListener('click', exportProject);
  el('download-diagnostics').addEventListener('click', downloadDiagnostics);
  el('close-backup').addEventListener('click', () => {
    showView('view-projects');
    window.dispatchEvent(new CustomEvent('inkwell:projects-refresh'));
  });
}
