/** 页面 P9（应用设置）控制器（阶段三 3.6 / C-07 / FR-5.3）。
 *
 * 覆盖 C-07 确定的范围：
 *   · 只读：数据目录 / schema / 数据库体积 / 磁盘余量 / 内容计数 / 字数口径说明
 *   · 修复：重建全文索引（#42）、重算字数（#43）—— 长任务走 `tasks.js` 轮询
 *   · 维护：清理过期自动快照（#51，同步；D-04 保留策略）
 *   · 自检：数据库自检（#52，快速 / 完整两种模式）
 *   · 诊断：下载诊断包（#49）、打开数据目录（桥接 `open_data_dir()`）
 *
 * 不提供：字数口径开关（V1.1，需 app_meta 存储 + 全量重算）、深色模式（FR-3.8）。
 */

import { openDataDir, request, requestBlob } from './api.js';
import { downloadBlob } from './download.js';
import { createLogger } from './logger.js';
import { runTask } from './tasks.js';
import { el, showView } from './view.js';

const log = createLogger('settings');

const MAINTENANCE_BUTTONS = [
  'settings-rebuild-fts',
  'settings-rebuild-wordcount',
  'settings-cleanup-snapshots',
  'settings-integrity',
];

let busy = false;

function setStatus(text, kind = '') {
  const node = el('settings-status');
  if (!node) {
    return;
  }
  node.textContent = text;
  node.className = `backup__status${kind ? ` is-${kind}` : ''}`;
}

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
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  });
}

function setMaintenanceDisabled(disabled) {
  for (const id of MAINTENANCE_BUTTONS) {
    const node = el(id);
    if (node) {
      node.disabled = disabled;
    }
  }
}

function renderInfo(data) {
  const list = el('settings-info');
  if (!list) {
    return;
  }
  const counts = data.counts || {};
  const rows = [
    ['数据目录', data.data_dir],
    [
      '数据库',
      `${data.db_path}（${formatBytes(data.db_size)}${
        data.wal_size ? ` + WAL ${formatBytes(data.wal_size)}` : ''
      }）`,
    ],
    [
      'schema 版本',
      `${data.schema_version}（期望 ${data.expected_schema_version}）`,
    ],
    [
      '磁盘余量',
      `${formatBytes(data.disk.free)} 可用 / 共 ${formatBytes(data.disk.total)}`,
    ],
    [
      '内容统计',
      `项目 ${counts.projects ?? 0} · 卷 ${counts.volumes ?? 0} · 章节 ${
        counts.chapters ?? 0
      } · 设定 ${counts.documents ?? 0}`,
    ],
    [
      '快照 / 暂存 / 备份',
      `${counts.versions ?? 0} 条快照 · ${counts.drafts ?? 0} 份暂存 · ${
        counts.backups ?? 0
      } 份备份`,
    ],
    [
      '自检',
      `${data.quick_check}（${data.mode === 'full' ? '完整' : '快速'}）· ${formatTime(
        data.checked_at,
      )}`,
    ],
  ];

  list.textContent = '';
  for (const [label, value] of rows) {
    const row = document.createElement('div');
    row.className = 'settings__row';
    const term = document.createElement('dt');
    term.textContent = label;
    const detail = document.createElement('dd');
    detail.textContent = value;
    detail.title = value;
    row.append(term, detail);
    list.append(row);
  }
}

async function refreshIntegrity({ full = false, silent = false } = {}) {
  if (!silent) {
    setStatus(full ? '正在执行完整自检（大库可能要几秒）…' : '正在自检…');
  }
  const data = await request(`/api/system/integrity${full ? '?full=1' : ''}`);
  renderInfo(data);
  if (silent) {
    // 维护动作刚给出结果文案，静默刷新信息区，不要把它顶掉
    return data;
  }
  if (data.ok) {
    setStatus(
      `自检通过（${data.mode === 'full' ? '完整' : '快速'}，${formatTime(
        data.checked_at,
      )}）`,
      'ok',
    );
  } else {
    setStatus(`自检发现问题：${data.quick_check}`, 'error');
  }
  return data;
}

async function runMaintenance(path, label, describe) {
  if (busy) {
    return;
  }
  busy = true;
  setMaintenanceDisabled(true);
  setStatus(`正在${label}…`);
  try {
    const body = await request(path, { method: 'POST' });
    const task = await runTask(body.tid, {
      onProgress: (data) => setStatus(`${label}：${data.message || '处理中…'}`),
    });
    setStatus(describe(task.result || {}), 'ok');
    await refreshIntegrity({ silent: true });
  } catch (error) {
    log.error(error);
    setStatus(`${label}失败：${error.message}`, 'error');
  } finally {
    busy = false;
    setMaintenanceDisabled(false);
  }
}

async function cleanupSnapshots() {
  if (busy) {
    return;
  }
  const confirmed = window.confirm(
    '清理过期自动快照？\n只删除 auto 类型（保留最近 30 条 + 每日首条 30 天）；\n' +
      '手动、里程碑与回滚快照永久保留，不受影响。',
  );
  if (!confirmed) {
    return;
  }
  busy = true;
  setMaintenanceDisabled(true);
  setStatus('正在清理过期快照…');
  try {
    const data = await request('/api/maintenance/cleanup-snapshots', {
      method: 'POST',
    });
    setStatus(
      `已清理 ${data.deleted} 条过期快照（扫描 ${data.chapters} 章）`,
      'ok',
    );
    await refreshIntegrity({ silent: true });
  } catch (error) {
    log.error(error);
    setStatus(`清理失败：${error.message}`, 'error');
  } finally {
    busy = false;
    setMaintenanceDisabled(false);
  }
}

async function downloadDiagnostics() {
  setStatus('正在生成诊断包…');
  try {
    const blob = await requestBlob('/api/system/diagnostics');
    downloadBlob(blob, 'inkwell-diagnostics.zip');
    setStatus('诊断包已下载（仅含日志与库结构摘要）', 'ok');
  } catch (error) {
    log.error(error);
    setStatus(`诊断包生成失败：${error.message}`, 'error');
  }
}

async function openDirectory() {
  try {
    const result = await openDataDir();
    if (result && result.ok) {
      setStatus(`已打开数据目录：${result.path}`, 'ok');
    } else {
      setStatus(
        `打开数据目录失败：${(result && result.error) || '未知原因'}`,
        'error',
      );
    }
  } catch (error) {
    log.error(error);
    setStatus(`打开数据目录失败：${error.message}`, 'error');
  }
}

export async function openSettings() {
  showView('view-settings');
  setStatus('');
  try {
    await refreshIntegrity();
  } catch (error) {
    log.error(error);
    setStatus(`自检失败：${error.message}`, 'error');
  }
}

export function initSettings() {
  el('open-settings').addEventListener('click', () => {
    openSettings().catch((error) => log.error(error));
  });
  el('close-settings').addEventListener('click', () => {
    showView('view-projects');
    window.dispatchEvent(new CustomEvent('inkwell:projects-refresh'));
  });
  el('settings-refresh').addEventListener('click', () => {
    refreshIntegrity().catch((error) => {
      log.error(error);
      setStatus(`自检失败：${error.message}`, 'error');
    });
  });
  el('settings-integrity').addEventListener('click', () => {
    refreshIntegrity({ full: true }).catch((error) => {
      log.error(error);
      setStatus(`完整自检失败：${error.message}`, 'error');
    });
  });
  el('settings-rebuild-fts').addEventListener('click', () => {
    runMaintenance(
      '/api/maintenance/rebuild-fts',
      '重建全文索引',
      (result) =>
        `索引已重建：${result.chapters ?? 0} 章 / ${result.documents ?? 0} 份设定`,
    );
  });
  el('settings-rebuild-wordcount').addEventListener('click', () => {
    runMaintenance(
      '/api/maintenance/rebuild-wordcount',
      '重算字数',
      (result) =>
        `字数已重算：${result.chapters ?? 0} 章（修正 ${
          result.changed ?? 0
        } 章）· ${result.projects ?? 0} 个项目`,
    );
  });
  el('settings-cleanup-snapshots').addEventListener('click', () => {
    cleanupSnapshots().catch((error) => log.error(error));
  });
  el('settings-diagnostics').addEventListener('click', () => {
    downloadDiagnostics().catch((error) => log.error(error));
  });
  el('settings-open-dir').addEventListener('click', () => {
    openDirectory().catch((error) => log.error(error));
  });
}
