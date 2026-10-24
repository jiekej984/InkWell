/** 页面 P1（项目列表）与 P4（项目设置）—— 任务 2.1 + 阶段三 3.3 打磨。
 *
 * 2.1 交付的是「能用」：列表、卡片、新建/设置对话框、封面上传、删除二次确认。
 * 3.3 补的是「首屏体验」：
 *   · 卡片：封面缺失时的默认图标（FR-1.8）、状态徽标、进度百分比、
 *     最近打开时间（FR-1.3）、整卡可点击 + 悬停/**键盘聚焦**时露出的操作按钮
 *   · 骨架态与错误态：加载有占位，出错有重试入口（不静默空白）
 *   · 空态：文案 + 主 CTA
 *   · 首启引导（C-09）：新建项目 → 自动建「第一章」→ 直达写作页 → 聚焦正文
 *   · 暂存横幅可点击直达对应作品（依赖 #47 返回的 `project_id`）
 *
 * 时间与计数的格式化是纯函数，放在 `format.js`（由 `tests/js/format.test.js` 覆盖）。
 */

import { request, requestForm } from './api.js';
import { createLogger } from './logger.js';
import { formatCount, initialOf, percentLabel, progressPercent, relativeTime } from './format.js';
import { focusEditor, openWriter } from './writer.js';

const log = createLogger('projects');

/** 首启引导自动创建的章节标题（C-09）。 */
const FIRST_CHAPTER_TITLE = '第一章';
const SKELETON_COUNT = 3;

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

function cardOf(projectId) {
  return document.querySelector(`.card[data-id="${projectId}"]`);
}

// --------------------------------------------------------------------------
// 卡片渲染
// --------------------------------------------------------------------------

/** 封面：有图走签名 URL，缺失或加载失败时回退到「书名首字」默认封面（FR-1.8）。 */
function buildCover(project) {
  const cover = document.createElement('div');
  cover.className = 'card__cover';

  const fallback = document.createElement('div');
  fallback.className = 'card__cover-fallback';
  const initial = document.createElement('span');
  initial.className = 'card__cover-initial';
  initial.textContent = initialOf(project.title);
  const hint = document.createElement('span');
  hint.className = 'card__cover-hint';
  hint.textContent = project.cover_path ? '封面加载中…' : '默认封面';
  fallback.append(initial, hint);
  fallback.dataset.role = 'cover-fallback';
  cover.append(fallback);

  if (project.cover_path) {
    const image = document.createElement('img');
    image.className = 'card__cover-img';
    image.alt = `${project.title} 封面`;
    image.hidden = true;
    image.addEventListener('load', () => {
      image.hidden = false;
      fallback.hidden = true;
    });
    image.addEventListener('error', () => {
      // FR-1.8：封面文件缺失不报错、不阻断，退回默认封面
      image.hidden = true;
      fallback.hidden = false;
      hint.textContent = '封面缺失';
    });
    cover.append(image);
  }
  return cover;
}

function buildBadge(status) {
  const badge = document.createElement('span');
  badge.className = `badge badge--${status || 'writing'}`;
  badge.textContent = STATUS_LABEL[status] || status || '连载中';
  return badge;
}

/** 进度条 + 百分比；FR-1.3 规定未设目标字数时整块不显示。 */
function buildProgress() {
  const wrap = document.createElement('div');
  wrap.className = 'card__progress';
  wrap.dataset.role = 'progress';
  wrap.hidden = true;

  const track = document.createElement('div');
  track.className = 'card__progress-track';
  const bar = document.createElement('div');
  bar.className = 'card__progress-bar';
  bar.dataset.role = 'progress-bar';
  bar.style.width = '0%';
  track.append(bar);

  const label = document.createElement('span');
  label.className = 'card__progress-label';
  label.dataset.role = 'progress-label';
  label.textContent = '0%';

  wrap.append(track, label);
  return wrap;
}

/** 标签行；没有标签时不渲染（不留空行）。 */
function buildTags(project) {
  if (!project.tags || project.tags.length === 0) {
    return null;
  }
  const tags = document.createElement('div');
  tags.className = 'tags';
  for (const tag of project.tags) {
    const chip = document.createElement('span');
    chip.className = 'tag';
    chip.textContent = tag.name;
    tags.append(chip);
  }
  return tags;
}

function buildCard(project) {
  const card = document.createElement('article');
  card.className = 'card';
  card.dataset.id = String(project.id);

  // 卡片主体整块可点（比只点按钮更好按）；内部全是非交互内容，因此用 role=button
  const body = document.createElement('div');
  body.className = 'card__open';
  body.setAttribute('role', 'button');
  body.setAttribute('aria-label', `打开《${project.title}》`);
  body.tabIndex = 0;
  body.addEventListener('click', () => {
    openWriter(project.id);
  });
  body.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      openWriter(project.id);
    }
  });

  body.append(buildCover(project));

  const head = document.createElement('div');
  head.className = 'card__head';
  const title = document.createElement('h3');
  title.className = 'card__title';
  title.textContent = project.title; // 用 textContent，书名含 HTML 也不被执行
  head.append(title, buildBadge(project.status));
  body.append(head);

  const meta = document.createElement('p');
  meta.className = 'card__meta card__meta--desc';
  meta.textContent = project.description || '暂无简介';
  body.append(meta);

  const facts = document.createElement('p');
  facts.className = 'card__meta card__facts';
  const words = document.createElement('span');
  words.dataset.role = 'words';
  words.textContent = formatCount(project.total_word_count);
  const opened = document.createElement('span');
  opened.dataset.role = 'opened';
  opened.textContent = `最近打开 ${relativeTime(project.last_opened_at || project.updated_at) || '未知'}`;
  facts.append(words, opened);
  body.append(facts);

  body.append(buildProgress());

  const tags = buildTags(project);
  if (tags) {
    body.append(tags);
  }

  const actions = document.createElement('div');
  actions.className = 'card__actions';

  const openButton = document.createElement('button');
  openButton.className = 'btn btn--small';
  openButton.type = 'button';
  openButton.textContent = '打开';
  openButton.addEventListener('click', () => {
    openWriter(project.id);
  });

  const settingsButton = document.createElement('button');
  settingsButton.className = 'btn btn--small';
  settingsButton.type = 'button';
  settingsButton.textContent = '设置';
  settingsButton.addEventListener('click', () => openDialog(project));

  actions.append(openButton, settingsButton);
  card.append(body, actions);
  return card;
}

/** 骨架态：首屏请求返回前占位，避免「空列表闪一下」。 */
function renderSkeleton(grid) {
  grid.textContent = '';
  grid.classList.add('is-loading');
  grid.setAttribute('aria-busy', 'true');
  for (let index = 0; index < SKELETON_COUNT; index += 1) {
    const skeleton = document.createElement('article');
    skeleton.className = 'card card--skeleton';
    skeleton.setAttribute('aria-hidden', 'true');
    for (const height of ['cover', 'title', 'line', 'line-short']) {
      const block = document.createElement('div');
      block.className = `skeleton skeleton--${height}`;
      skeleton.append(block);
    }
    grid.append(skeleton);
  }
}

function clearGrid(grid) {
  grid.textContent = '';
  grid.classList.remove('is-loading');
  grid.removeAttribute('aria-busy');
}

function showError(error) {
  log.error(error);
  const node = element('project-error');
  if (node) {
    node.textContent = error.message;
    node.hidden = false;
  }
}

// --------------------------------------------------------------------------
// 统计与封面补拉
// --------------------------------------------------------------------------

async function refreshStats(project) {
  try {
    const stats = await request(`/api/projects/${project.id}/stats`);
    const card = cardOf(project.id);
    if (!card) {
      return;
    }
    const words = card.querySelector('[data-role="words"]');
    if (words) {
      words.textContent = formatCount(stats.word_count);
    }
    const progress = card.querySelector('[data-role="progress"]');
    // FR-1.3：未设目标字数则不显示进度
    if (progress && stats.progress !== null && stats.progress !== undefined) {
      progress.hidden = false;
      const bar = progress.querySelector('[data-role="progress-bar"]');
      if (bar) {
        bar.style.width = `${progressPercent(stats.progress).toFixed(1)}%`;
      }
      const label = progress.querySelector('[data-role="progress-label"]');
      if (label) {
        label.textContent = percentLabel(stats.progress);
      }
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
      const card = cardOf(project.id);
      const image = card && card.querySelector('.card__cover-img');
      if (image && url) {
        image.src = url;
      }
    }
  } catch (error) {
    log.warn('封面签名失败', error.message);
  }
}

// --------------------------------------------------------------------------
// 暂存横幅（可直达对应作品）
// --------------------------------------------------------------------------

async function refreshDraftBanner() {
  const banner = element('draft-banner');
  if (!banner) {
    return;
  }
  banner.textContent = '';
  try {
    const { items } = await request('/api/drafts');
    if (!items || items.length === 0) {
      banner.hidden = true;
      return;
    }

    const label = document.createElement('span');
    label.className = 'projects__drafts-label';
    label.textContent = `有 ${items.length} 条未保存的暂存：`;
    banner.append(label);

    for (const item of items) {
      const button = document.createElement('button');
      button.className = 'btn btn--small';
      button.type = 'button';
      // 章节所属项目已删除时没有 project_id，只能提示不可直达
      const reachable = Boolean(item.project_id);
      const title = item.title || '未命名章节';
      const project = item.project_title ? `《${item.project_title}》` : '';
      button.textContent = `${project}${title}`;
      button.disabled = !reachable;
      button.title = reachable ? '打开该作品并恢复暂存' : '所属项目已删除，暂无法直达';
      if (reachable) {
        button.addEventListener('click', () => {
          openWriter(item.project_id);
        });
      }
      banner.append(button);
    }
    banner.hidden = false;
  } catch (error) {
    banner.hidden = true;
    log.warn('读取暂存列表失败', error.message);
  }
}

// --------------------------------------------------------------------------
// 列表加载
// --------------------------------------------------------------------------

export async function loadProjects() {
  const grid = element('project-grid');
  const empty = element('project-empty');
  const errorState = element('projects-error');
  if (!grid) {
    return;
  }

  renderSkeleton(grid);
  empty.hidden = true;
  errorState.hidden = true;

  try {
    const { items } = await request('/api/projects');
    clearGrid(grid);
    for (const project of items) {
      grid.append(buildCard(project));
    }
    empty.hidden = items.length > 0;

    await refreshCovers(items);
    await refreshDraftBanner();

    // 列表接口不带统计（避免 N+1 拖慢首屏），渲染后再逐个补齐
    await Promise.all(items.map(refreshStats));
  } catch (error) {
    clearGrid(grid);
    empty.hidden = true;
    const message = errorState.querySelector('[data-role="projects-error-message"]');
    if (message) {
      message.textContent = `读取作品列表失败：${error.message}`;
    }
    errorState.hidden = false;
    const banner = element('draft-banner');
    if (banner) {
      banner.hidden = true;
    }
    log.error(error);
  }
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
  element('project-target').value = project
    ? project.target_word_count || 0
    : 0;
  element('project-tags').value = project
    ? (project.tags || []).map((tag) => tag.name).join(', ')
    : '';

  const coverField = element('cover-field');
  coverField.hidden = !project;
  element('delete-project').hidden = !project;
  element('cover-hint').textContent =
    project && project.cover_path
      ? `当前封面：${project.cover_path}`
      : '未设置封面（不选择文件则不改动）';
  element('project-error').hidden = true;
  // 取消时不应把上一次选的封面文件留给下一次保存（B1 相关：取消=彻底放弃本次编辑）
  element('project-cover').value = '';
  dialog.showModal();
  element('project-title').focus();
}

function parseTags(raw) {
  return raw
    .split(/[,，]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

/** 保存项目；新建时返回服务端新建出的项目对象（首启引导需要 id）。 */
async function saveProject() {
  const payload = {
    title: element('project-title').value.trim(),
    description: element('project-description').value,
    status: element('project-status').value,
    target_word_count: Number(element('project-target').value) || 0,
    tags: parseTags(element('project-tags').value),
  };

  if (editing) {
    const updated = await request(`/api/projects/${editing.id}`, {
      method: 'PATCH',
      body: payload,
    });
    const cover = element('project-cover').files[0];
    if (cover) {
      const form = new FormData();
      form.append('file', cover);
      await requestForm(`/api/projects/${editing.id}/cover`, form);
    }
    return updated;
  }
  return request('/api/projects', { method: 'POST', body: payload });
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

// --------------------------------------------------------------------------
// 首启引导（C-09）
// --------------------------------------------------------------------------

/** 在默认卷里建「第一章」，然后直达写作页并聚焦正文。
 *
 * 聚焦时机：必须等章节加载完成、编辑器 `contenteditable=true` 之后，
 * 否则首次组合输入会被丢弃（见 `docs/版本更新/阶段三_IME验证记录.md` §二）。
 * 这里 `openWriter` 内部已 await 完章节加载，`focusEditor()` 再判一次就绪。
 */
async function startFirstWrite(project) {
  try {
    const tree = await request(`/api/projects/${project.id}/volumes`);
    const volumeId = tree.default_volume && tree.default_volume.id;
    if (volumeId) {
      await request(`/api/volumes/${volumeId}/chapters`, {
        method: 'POST',
        body: { title: FIRST_CHAPTER_TITLE },
      });
    }
  } catch (error) {
    // 建章失败不阻断：写作页仍可进入，用户可手动新建
    log.warn('首启引导建章失败', error.message);
  }

  await openWriter(project.id);
  if (!focusEditor()) {
    log.warn('编辑器尚未就绪，跳过首启聚焦');
  }
}

// --------------------------------------------------------------------------
// 初始化
// --------------------------------------------------------------------------

export function initProjects() {
  element('new-project').addEventListener('click', () => openDialog(null));
  element('empty-new-project').addEventListener('click', () => openDialog(null));
  element('projects-retry').addEventListener('click', () => {
    loadProjects().catch((error) => log.error(error));
  });

  // 阶段三 3.5：写作页落/清暂存后，若项目列表正开着，横幅即时跟随（两页提示联动）
  window.addEventListener('inkwell:drafts-changed', () => {
    const view = element('view-projects');
    if (!view || view.hidden) {
      return;
    }
    refreshDraftBanner().catch((error) =>
      log.warn('刷新暂存横幅失败', error.message),
    );
  });

  element('delete-project').addEventListener('click', () => {
    deleteProject()
      .then(() => {
        element('project-dialog').close();
        return loadProjects();
      })
      .catch((error) => showError(error));
  });

  element('project-form').addEventListener('submit', (event) => {
    // 只有「保存」走提交流程；取消按钮已改为 type="button"，由 app.js 统一 close（B1）。
    // 注意顺序：非保存的 submitter 必须**先返回再 preventDefault**，否则会把
    // <dialog method="dialog"> 的原生关闭一起拦掉。
    if (event.submitter && event.submitter.id !== 'save-project') {
      return;
    }
    event.preventDefault();
    const isCreate = !editing;
    saveProject()
      .then((project) => {
        element('project-dialog').close();
        if (isCreate && project) {
          return startFirstWrite(project);
        }
        return loadProjects();
      })
      .catch((error) => showError(error));
  });

  return loadProjects().catch((error) => log.error(error));
}
