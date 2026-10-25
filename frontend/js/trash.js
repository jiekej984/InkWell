/** 页面 P8（回收站）控制器（任务 2.8 / BR-4）。
 *
 * - 按类型分组展示：项目 / 卷 / 章节 / 文档 / 角色 / 组织 / 阵营，含父级与剩余天数
 * - 恢复时若父资源也在回收站，二次确认后带 `with_parent=true` 一并恢复
 * - 清空为物理删除，连续两次确认（NFR-U3）
 */

import { request } from './api.js';
import { createLogger } from './logger.js';
import { clearBusy, showEmpty, showError, showLoading } from './state.js';
import { el, showView } from './view.js';

const log = createLogger('trash');

const TYPE_LABELS = {
  project: '项目',
  volume: '卷',
  chapter: '章节',
  document: '设定文档',
  character: '角色',
  organization: '组织',
  faction: '阵营',
};

const GROUPS = [
  ['projects', '项目'],
  ['volumes', '卷'],
  ['chapters', '章节'],
  ['documents', '设定文档'],
  ['characters', '角色'],
  ['organizations', '组织'],
  ['factions', '阵营'],
];

function notifyProjectsRefresh() {
  window.dispatchEvent(new CustomEvent('inkwell:projects-refresh'));
}

function buildRow(item) {
  const row = document.createElement('div');
  row.className = 'trash__row';

  const info = document.createElement('div');
  info.className = 'trash__info';

  const title = document.createElement('span');
  title.className = 'trash__title';
  title.textContent = item.title;

  const meta = document.createElement('span');
  meta.className = 'trash__meta';
  const parts = [];
  if (item.project_title) {
    parts.push(`项目：${item.project_title}`);
  }
  if (item.volume_title) {
    parts.push(`卷：${item.volume_title}`);
  }
  if (item.parent_title) {
    parts.push(`父组织：${item.parent_title}`);
  }
  if (item.faction_title) {
    parts.push(`阵营：${item.faction_title}`);
  }
  if (item.word_count) {
    parts.push(`${item.word_count} 字`);
  }
  parts.push(`剩余 ${item.days_left} 天`);
  meta.textContent = parts.join(' · ');

  info.append(title, meta);

  const restore = document.createElement('button');
  restore.type = 'button';
  restore.className = 'btn btn--small';
  restore.textContent = '恢复';
  restore.addEventListener('click', () => restoreItem(item));

  row.append(info, restore);
  return row;
}

async function restoreItem(item) {
  try {
    let data = await request(`/api/trash/${item.type}/${item.id}/restore`, {
      method: 'POST',
    });
    if (data.requires_parent) {
      const parentLabel =
        TYPE_LABELS[data.parent.type] || data.parent.type;
      const confirmed = window.confirm(
        `父${parentLabel}「${data.parent.title}」也在回收站，是否一并恢复？`,
      );
      if (!confirmed) {
        return;
      }
      data = await request(
        `/api/trash/${item.type}/${item.id}/restore?with_parent=true`,
        { method: 'POST' },
      );
    }
    if (data.restored) {
      await loadTrash();
      notifyProjectsRefresh();
    }
  } catch (error) {
    log.error(error);
    window.alert(`恢复失败：${error.message}`);
  }
}

export async function loadTrash() {
  const list = el('trash-list');
  if (!list) {
    return;
  }
  showLoading(list, '正在读取回收站…');
  try {
    const data = await request('/api/trash');
    clearBusy(list);
    el('trash-hint').textContent =
      `回收站保留 ${data.retention_days} 天；恢复时若父资源也在回收站，会提示一并恢复。`;

    if (!data.total) {
      showEmpty(list, '回收站是空的。');
      return;
    }

    list.textContent = '';
    for (const [key, label] of GROUPS) {
      const items = data[key] || [];
      if (!items.length) {
        continue;
      }
      const section = document.createElement('section');
      section.className = 'trash__group';
      const heading = document.createElement('h3');
      heading.className = 'trash__group-title';
      heading.textContent = `${label}（${items.length}）`;
      section.append(heading);
      for (const item of items) {
        section.append(buildRow(item));
      }
      list.append(section);
    }
  } catch (error) {
    log.error(error);
    showError(list, `读取回收站失败：${error.message}`, () => {
      loadTrash().catch((err) => log.error(err));
    });
  }
}

async function emptyTrash() {
  const first = window.confirm(
    '清空回收站？其中所有项目、卷、章节、文档、角色、组织与阵营将被物理删除，无法恢复。',
  );
  if (!first) {
    return;
  }
  const second = window.confirm('再次确认：此操作不可恢复。');
  if (!second) {
    return;
  }
  try {
    await request('/api/trash/empty', { method: 'DELETE' });
    await loadTrash();
    notifyProjectsRefresh();
  } catch (error) {
    log.error(error);
    window.alert(`清空失败：${error.message}`);
  }
}

export async function openTrash() {
  showView('view-trash');
  await loadTrash();
}

export function initTrash() {
  el('close-trash').addEventListener('click', () => {
    showView('view-projects');
    notifyProjectsRefresh();
  });
  el('empty-trash').addEventListener('click', emptyTrash);
}
