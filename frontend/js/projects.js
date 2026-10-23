/** 页面 P1（项目列表）与 P4（项目设置）—— 任务 2.1。
 *
 * 范围：项目 CRUD、标签、封面上传、删除二次确认。
 * 视觉打磨与交互细节属于阶段三 3.1 / 3.3，这里只保证主流程可用。
 *
 * 已知待接线点（后续任务）：
 *   · 封面预览：等 2.3 实装 #36 `/files/` 与 #37 `/files/sign` 后，
 *     用签名 URL 替换占位块（当前一律显示占位，符合 FR-1.8「缺失显示默认图标」）
 *   · 「打开」按钮：等 2.2 卷章与 2.3 编辑器就绪后进入写作页
 */

import { request, requestForm } from './api.js';
import { createLogger } from './logger.js';
import { openWriter } from './writer.js';

const log = createLogger('projects');

const STATUS_LABEL = {
  writing: '连载中',
  paused: '已暂停',
  finished: '已完结',
};

/** 当前编辑的项目；null 表示新建模式。 */
let editing = null;

function element(id) {
  return document.getElementById(id);
}

function formatCount(value) {
  const number = Number(value) || 0;
  if (number >= 10000) {
    return `${(number / 10000).toFixed(1)} 万字`;
  }
  return `${number} 字`;
}

// --------------------------------------------------------------------------
// 列表渲染
// --------------------------------------------------------------------------

function buildCard(project) {
  const card = document.createElement('article');
  card.className = 'card';
  card.dataset.id = String(project.id);

  const cover = document.createElement('div');
  cover.className = 'card__cover';
  // 封面：2.3 已接线 —— 列表加载后批量请求 #37 签名，再拼 #36 URL
  if (project.cover_path) {
    const image = document.createElement('img');
    image.className = 'card__cover-img';
    image.alt = `${project.title} 封面`;
    image.hidden = true;

    const placeholder = document.createElement('span');
    placeholder.className = 'card__cover-hint';
    placeholder.textContent = '封面加载中…';

    image.addEventListener('load', () => {
      image.hidden = false;
      placeholder.hidden = true;
    });
    image.addEventListener('error', () => {
      image.hidden = true;
      placeholder.hidden = false;
      placeholder.textContent = '封面缺失';
    });

    cover.append(image, placeholder);
    cover.dataset.coverPath = project.cover_path;
  } else {
    cover.textContent = '默认封面';
  }
  card.append(cover);

  const title = document.createElement('h3');
  title.className = 'card__title';
  title.textContent = project.title; // 用 textContent，书名含 HTML 也不被执行
  card.append(title);

  const status = document.createElement('span');
  status.className = 'badge';
  status.textContent = STATUS_LABEL[project.status] || project.status;
  card.append(status);

  const meta = document.createElement('p');
  meta.className = 'card__meta';
  meta.textContent = project.description || '暂无简介';
  card.append(meta);

  const words = document.createElement('p');
  words.className = 'card__meta';
  words.dataset.role = 'words';
  words.textContent = formatCount(project.total_word_count);
  card.append(words);

  const progress = document.createElement('div');
  progress.className = 'card__progress';
  progress.dataset.role = 'progress';
  progress.hidden = true;
  const bar = document.createElement('div');
  bar.className = 'card__progress-bar';
  bar.style.width = '0%';
  progress.append(bar);
  card.append(progress);

  if (project.tags && project.tags.length > 0) {
    const tags = document.createElement('div');
    tags.className = 'tags';
    for (const tag of project.tags) {
      const chip = document.createElement('span');
      chip.className = 'tag';
      chip.textContent = tag.name;
      tags.append(chip);
    }
    card.append(tags);
  }

  const actions = document.createElement('div');
  actions.className = 'card__actions';

  const openButton = document.createElement('button');
  openButton.className = 'btn';
  openButton.type = 'button';
  openButton.textContent = '打开';
  openButton.addEventListener('click', () => {
    openWriter(project.id);
  });

  const settingsButton = document.createElement('button');
  settingsButton.className = 'btn';
  settingsButton.type = 'button';
  settingsButton.textContent = '设置';
  settingsButton.addEventListener('click', () => openDialog(project));

  actions.append(openButton, settingsButton);
  card.append(actions);
  return card;
}

async function refreshStats(project) {
  try {
    const stats = await request(`/api/projects/${project.id}/stats`);
    const card = document.querySelector(`.card[data-id="${project.id}"]`);
    if (!card) {
      return;
    }
    const words = card.querySelector('[data-role="words"]');
    if (words) {
      words.textContent = formatCount(stats.word_count);
    }
    const progress = card.querySelector('[data-role="progress"]');
    // FR-1.3：未设目标字数则不显示进度
    if (progress && stats.progress !== null) {
      progress.hidden = false;
      progress.firstElementChild.style.width = `${Math.min(100, stats.progress * 100).toFixed(1)}%`;
    }
  } catch (error) {
    log.warn('读取统计失败', project.id, error.message);
  }
}

async function refreshCovers(items) {
  const paths = items
    .map((project) => project.cover_path)
    .filter((path) => Boolean(path));
  if (paths.length === 0) {
    return;
  }
  try {
    const data = await request('/api/files/sign', {
      method: 'POST',
      body: { paths },
    });
    const urls = new Map(data.items.map((item) => [item.path, item.url]));
    for (const project of items) {
      if (!project.cover_path) {
        continue;
      }
      const url = urls.get(project.cover_path);
      const card = document.querySelector(`.card[data-id="${project.id}"]`);
      const image = card && card.querySelector('.card__cover-img');
      if (image && url) {
        image.src = url;
      }
    }
  } catch (error) {
    log.warn('封面签名失败', error.message);
  }
}

async function refreshDraftBanner() {
  const banner = element('draft-banner');
  if (!banner) {
    return;
  }
  try {
    const { items } = await request('/api/drafts');
    if (items && items.length > 0) {
      banner.textContent = `有 ${items.length} 条未保存的暂存，打开对应作品可恢复。`;
      banner.hidden = false;
    } else {
      banner.hidden = true;
    }
  } catch (error) {
    log.warn('读取暂存列表失败', error.message);
  }
}

export async function loadProjects() {
  const grid = element('project-grid');
  const empty = element('project-empty');
  const { items } = await request('/api/projects');

  grid.textContent = '';
  for (const project of items) {
    grid.append(buildCard(project));
  }
  empty.hidden = items.length > 0;

  await refreshCovers(items);
  await refreshDraftBanner();

  // 列表接口不带统计（避免 N+1 拖慢首屏），渲染后再逐个补齐
  await Promise.all(items.map(refreshStats));
}

// --------------------------------------------------------------------------
// 新建 / 设置对话框
// --------------------------------------------------------------------------

export function openDialog(project = null) {
  editing = project;
  const dialog = element('project-dialog');
  element('project-dialog-title').textContent = project ? '项目设置' : '新建项目';
  element('project-title').value = project ? project.title : '';
  element('project-description').value = project ? project.description || '' : '';
  element('project-status').value = project ? project.status : 'writing';
  element('project-target').value = project ? project.target_word_count || 0 : 0;
  element('project-tags').value = project
    ? (project.tags || []).map((tag) => tag.name).join(', ')
    : '';

  const coverField = element('cover-field');
  coverField.hidden = !project;
  element('delete-project').hidden = !project;
  element('cover-hint').textContent = project && project.cover_path
    ? `当前封面：${project.cover_path}`
    : '未设置封面（不选择文件则不改动）';
  element('project-error').hidden = true;
  dialog.showModal();
}

function parseTags(raw) {
  return raw
    .split(/[,，]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

async function saveProject() {
  const payload = {
    title: element('project-title').value.trim(),
    description: element('project-description').value,
    status: element('project-status').value,
    target_word_count: Number(element('project-target').value) || 0,
    tags: parseTags(element('project-tags').value),
  };

  if (editing) {
    await request(`/api/projects/${editing.id}`, { method: 'PATCH', body: payload });
    const cover = element('project-cover').files[0];
    if (cover) {
      const form = new FormData();
      form.append('file', cover);
      await requestForm(`/api/projects/${editing.id}/cover`, form);
    }
  } else {
    await request('/api/projects', { method: 'POST', body: payload });
  }
}

async function deleteProject() {
  if (!editing) {
    return;
  }
  // NFR-U3：破坏性操作必须二次确认
  const confirmed = window.confirm(
    `删除《${editing.title}》？其卷、章节与设定文档会一并进入回收站，可在 30 天内恢复。`,
  );
  if (!confirmed) {
    return;
  }
  await request(`/api/projects/${editing.id}`, { method: 'DELETE' });
}

export function initProjects() {
  element('new-project').addEventListener('click', () => openDialog(null));
  element('delete-project').addEventListener('click', () => {
    deleteProject()
      .then(() => {
        element('project-dialog').close();
        return loadProjects();
      })
      .catch((error) => showError(error));
  });

  element('project-form').addEventListener('submit', (event) => {
    event.preventDefault();
    // 取消按钮也会触发 submit（method="dialog"），这里只处理保存
    if (event.submitter && event.submitter.id !== 'save-project') {
      return;
    }
    saveProject()
      .then(() => {
        element('project-dialog').close();
        return loadProjects();
      })
      .catch((error) => showError(error));
  });

  return loadProjects().catch((error) => log.error(error));
}

function showError(error) {
  log.error(error);
  const node = element('project-error');
  node.textContent = error.message;
  node.hidden = false;
}
