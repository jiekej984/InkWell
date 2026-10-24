/** 角色卡右侧：关系面板 + 组织身份（V2.0 / 5.6 / FR-8.12~8.16）。
 *
 * 交互：
 *   · 关系按「师承 / 血亲 / 友 / 敌 / 其他」分组；单向带箭头，隐秘带锁，失效灰显
 *   · 添加/编辑共用一张表单；对方角色与「生效章」都是**可搜索下拉**（C-20）
 *   · 「在图中查看」在 5.7 关系图落地前保持禁用
 *
 * 本模块不 import `characters.js`（避免循环），所需数据由调用方传入：
 *   `showRelations(detail, { onOpenCharacter })`
 */

import { request } from './api.js';
import { createLogger } from './logger.js';
import { el } from './view.js';

const log = createLogger('relations');

const FAMILY_ORDER = ['master', 'kin', 'friend', 'enemy', 'other'];
const FAMILY_LABELS = {
  master: '师承',
  kin: '血亲 / 姻缘',
  friend: '友',
  enemy: '敌',
  other: '其他',
};

const state = {
  projectId: null,
  meta: null,
  characters: [],
  chapters: [],
  relations: [],
  detail: null,
  editingId: null,
  onOpenCharacter: null,
};

const pickers = {
  target: null,
  from: null,
  to: null,
};

// --------------------------------------------------------------------------
// 可搜索下拉
// --------------------------------------------------------------------------

function makePicker({ input, list, onPick = null }) {
  let items = [];
  let selectedId = null;

  const close = () => {
    list.hidden = true;
  };

  const choose = (item) => {
    selectedId = item.id;
    input.value = item.label;
    close();
    if (onPick) {
      onPick(item.id);
    }
  };

  const render = (keyword) => {
    const text = keyword.trim().toLowerCase();
    const matches = items
      .filter((item) => !text || item.label.toLowerCase().includes(text))
      .slice(0, 30);
    list.textContent = '';
    if (!matches.length) {
      const empty = document.createElement('p');
      empty.className = 'picker__empty';
      empty.textContent = '没有匹配项';
      list.append(empty);
    }
    for (const item of matches) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'picker__item';
      button.textContent = item.label;
      // mousedown 先于 blur，避免下拉还没点就被收起
      button.addEventListener('mousedown', (event) => {
        event.preventDefault();
        choose(item);
      });
      list.append(button);
    }
    list.hidden = false;
  };

  input.addEventListener('focus', () => render(''));
  input.addEventListener('input', () => {
    selectedId = null;
    render(input.value);
  });
  input.addEventListener('blur', () => window.setTimeout(close, 120));
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      close();
    }
  });

  return {
    setItems(next) {
      items = next;
    },
    get value() {
      if (selectedId !== null) {
        return selectedId;
      }
      const text = input.value.trim();
      const exact = items.find((item) => item.label === text);
      return exact ? exact.id : null;
    },
    set(id, label) {
      selectedId = id === null || id === undefined ? null : id;
      input.value = label || '';
    },
    clear() {
      selectedId = null;
      input.value = '';
    },
    setDisabled(disabled) {
      input.disabled = disabled;
    },
  };
}

// --------------------------------------------------------------------------
// 支持数据
// --------------------------------------------------------------------------

function flattenChapters(tree) {
  const result = [];
  const push = (volume) => {
    for (const chapter of volume.chapters || []) {
      result.push({
        id: chapter.id,
        label: `${volume.title} · ${chapter.title}`,
      });
    }
  };
  if (tree && tree.default_volume) {
    push(tree.default_volume);
  }
  for (const volume of (tree && tree.volumes) || []) {
    push(volume);
  }
  return result;
}

async function loadSupport(projectId) {
  if (state.projectId === projectId) {
    return;
  }
  const [meta, characters, volumes] = await Promise.all([
    request(`/api/projects/${projectId}/characters/meta`),
    request(`/api/projects/${projectId}/characters?page_size=200`),
    request(`/api/projects/${projectId}/volumes`).catch(() => ({})),
  ]);
  state.projectId = projectId;
  state.meta = meta;
  state.characters = characters.items || [];
  state.chapters = flattenChapters(volumes || {});

  fillTypeSelect();
  pickers.from.setItems([{ id: '', label: '不限' }, ...state.chapters]);
  pickers.to.setItems([{ id: '', label: '不限' }, ...state.chapters]);
}

function fillTypeSelect() {
  const select = el('relation-type');
  select.textContent = '';
  for (const item of state.meta.relation_types) {
    const option = document.createElement('option');
    option.value = item.value;
    option.textContent = item.label;
    select.append(option);
  }
}

function relationMeta(item) {
  const parts = [];
  if (item.from_chapter_id || item.to_chapter_id) {
    if (item.from_chapter_id && item.to_chapter_id) {
      const from = chapterLabel(item.from_chapter_id);
      const to = chapterLabel(item.to_chapter_id);
      parts.push(`第 ${from} → ${to} 章`);
    } else if (item.from_chapter_id) {
      parts.push(`第 ${chapterLabel(item.from_chapter_id)} 章起`);
    } else {
      parts.push(`至第 ${chapterLabel(item.to_chapter_id)} 章`);
    }
  }
  if (item.active === false) {
    parts.push('已失效');
  }
  if (item.custom_label) {
    parts.push(item.custom_label);
  }
  return parts.join(' · ');
}

function chapterLabel(chapterId) {
  const hit = state.chapters.find((item) => item.id === chapterId);
  return hit ? hit.label : `#${chapterId}`;
}

// --------------------------------------------------------------------------
// 渲染
// --------------------------------------------------------------------------

function familyOf(relationType) {
  const hit = state.meta.relation_types.find(
    (item) => item.value === relationType,
  );
  return hit ? hit.family : 'other';
}

function renderRelations() {
  const root = el('relation-list');
  root.textContent = '';
  el('relations-count').textContent = String(state.relations.length);
  el('relation-empty').hidden = state.relations.length > 0;
  if (!state.relations.length) {
    return;
  }

  const grouped = new Map(FAMILY_ORDER.map((key) => [key, []]));
  for (const item of state.relations) {
    const family = familyOf(item.relation_type);
    if (!grouped.has(family)) {
      grouped.set(family, []);
    }
    grouped.get(family).push(item);
  }

  for (const family of FAMILY_ORDER) {
    const items = grouped.get(family) || [];
    if (!items.length) {
      continue;
    }
    const title = document.createElement('p');
    title.className = 'relation-group-title';
    title.textContent = FAMILY_LABELS[family] || family;
    root.append(title);

    for (const item of items) {
      root.append(relationRow(item));
    }
  }
}

function relationRow(item) {
  const row = document.createElement('div');
  row.className = 'relation-row';
  if (item.active === false) {
    row.classList.add('is-expired');
  }

  const main = document.createElement('button');
  main.type = 'button';
  main.className = 'relation-row__main';
  main.title = `查看「${item.other_name}」`;

  const direction = item.is_bidirectional ? '⇄' : item.outgoing ? '→' : '←';
  const title = document.createElement('span');
  title.className = 'relation-row__title';
  title.textContent = `${direction} ${item.other_name} · ${item.relation_label}`;
  main.append(title);

  const meta = document.createElement('span');
  meta.className = 'relation-row__meta';
  meta.textContent = relationMeta(item);
  if (meta.textContent) {
    main.append(meta);
  }
  main.addEventListener('click', () => {
    if (state.onOpenCharacter && item.other_id) {
      state.onOpenCharacter(item.other_id);
    }
  });

  row.append(main);

  if (item.is_secret) {
    const lock = document.createElement('span');
    lock.className = 'relation-row__lock';
    lock.textContent = '🔒';
    lock.title = '不为人知的关系';
    row.append(lock);
  }

  const edit = document.createElement('button');
  edit.type = 'button';
  edit.className = 'relation-row__action';
  edit.textContent = '✎';
  edit.title = '编辑这条关系';
  edit.setAttribute('aria-label', `编辑与${item.other_name}的关系`);
  edit.addEventListener('click', () => startEdit(item));
  row.append(edit);

  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'relation-row__action';
  remove.textContent = '✕';
  remove.title = '删除这条关系';
  remove.setAttribute('aria-label', `删除与${item.other_name}的关系`);
  remove.addEventListener('click', () => {
    deleteRelation(item).catch((error) => log.error(error));
  });
  row.append(remove);

  return row;
}

function renderMemberships(detail) {
  const root = el('character-memberships');
  root.textContent = '';
  const items = detail.memberships || [];
  if (!items.length) {
    const empty = document.createElement('p');
    empty.className = 'field__hint';
    empty.textContent = '还没有组织身份（去「组织」页添加）';
    root.append(empty);
    return;
  }
  for (const item of items) {
    const row = document.createElement('div');
    row.className = 'membership-row';

    const title = document.createElement('span');
    const flags = [];
    if (item.is_primary) {
      flags.push('主组织');
    }
    if (item.is_secret) {
      flags.push('隐蔽');
    }
    title.textContent = `${item.org_name}${flags.length ? `（${flags.join(' · ')}）` : ''}`;

    const meta = document.createElement('span');
    meta.className = 'membership-row__meta';
    const parts = [];
    if (item.position) {
      parts.push(item.position);
    }
    if (item.from_chapter_id) {
      parts.push(`第 ${chapterLabel(item.from_chapter_id)} 章起`);
    }
    if (item.to_chapter_id) {
      parts.push(`至第 ${chapterLabel(item.to_chapter_id)} 章`);
    }
    meta.textContent = parts.join(' · ');

    row.append(title, meta);
    root.append(row);
  }
}

// --------------------------------------------------------------------------
// 表单
// --------------------------------------------------------------------------

function resetForm() {
  state.editingId = null;
  el('relation-form-title').textContent = '添加关系';
  el('relation-save').textContent = '添加';
  el('relation-cancel').hidden = true;
  el('relation-type').value = 'master';
  el('relation-direction').value = 'single';
  el('relation-label').value = '';
  el('relation-secret').checked = false;
  el('relation-description').value = '';
  el('relation-error').hidden = true;
  pickers.target.clear();
  pickers.target.setDisabled(false);
  pickers.from.clear();
  pickers.to.clear();
  syncDirectionDefault();
}

function syncDirectionDefault() {
  const type = el('relation-type').value;
  const hit = (state.meta ? state.meta.relation_types : []).find(
    (item) => item.value === type,
  );
  if (hit && state.editingId === null) {
    el('relation-direction').value = hit.default_bidirectional ? 'double' : 'single';
  }
}

function startEdit(item) {
  state.editingId = item.id;
  el('relation-form-title').textContent = '编辑关系';
  el('relation-save').textContent = '保存修改';
  el('relation-cancel').hidden = false;
  el('relation-type').value = item.relation_type;
  el('relation-direction').value = item.is_bidirectional ? 'double' : 'single';
  el('relation-label').value = item.custom_label || '';
  el('relation-secret').checked = Boolean(item.is_secret);
  el('relation-description').value = item.description || '';
  pickers.target.set(item.other_id, item.other_name || '');
  pickers.target.setDisabled(true);
  pickers.from.set(item.from_chapter_id, chapterDisplay(item.from_chapter_id));
  pickers.to.set(item.to_chapter_id, chapterDisplay(item.to_chapter_id));
  el('relation-error').hidden = true;
  el('relation-form').scrollIntoView({ block: 'nearest' });
}

function chapterDisplay(chapterId) {
  if (!chapterId) {
    return '';
  }
  return chapterLabel(chapterId);
}

async function submitForm(event) {
  event.preventDefault();
  if (!state.detail) {
    return;
  }
  const type = el('relation-type').value;
  const body = {
    relation_type: type,
    custom_label: el('relation-label').value.trim() || null,
    is_bidirectional: el('relation-direction').value === 'double',
    is_secret: el('relation-secret').checked,
    description: el('relation-description').value.trim() || null,
    from_chapter_id: pickers.from.value || null,
    to_chapter_id: pickers.to.value || null,
  };

  try {
    if (state.editingId) {
      await request(`/api/relations/${state.editingId}`, {
        method: 'PATCH',
        body,
      });
    } else {
      const target = pickers.target.value;
      if (!target) {
        showError('先选择对方角色');
        return;
      }
      await request(`/api/characters/${state.detail.id}/relations`, {
        method: 'POST',
        body: { to_id: target, ...body },
      });
    }
    resetForm();
    await loadRelations();
  } catch (error) {
    showError(error);
  }
}

function showError(error) {
  const node = el('relation-error');
  node.textContent =
    typeof error === 'string' ? error : errorMessageOf(error);
  node.hidden = false;
}

function errorMessageOf(error) {
  const text = (error && error.message) || String(error);
  const match = text.match(/code=\d+\s+(.*)$/s);
  return match ? match[1].trim() : text;
}

async function deleteRelation(item) {
  const confirmed = window.confirm(`删除与「${item.other_name}」的「${item.relation_label}」关系？`);
  if (!confirmed) {
    return;
  }
  await request(`/api/relations/${item.id}`, { method: 'DELETE' });
  await loadRelations();
}

async function loadRelations() {
  const data = await request(`/api/characters/${state.detail.id}/relations`);
  state.relations = data.items || [];
  renderRelations();
}

// --------------------------------------------------------------------------
// 对外
// --------------------------------------------------------------------------

export function initCharacterRelations() {
  pickers.target = makePicker({
    input: el('relation-target'),
    list: el('relation-target-list'),
  });
  pickers.from = makePicker({
    input: el('relation-from'),
    list: el('relation-from-list'),
  });
  pickers.to = makePicker({
    input: el('relation-to'),
    list: el('relation-to-list'),
  });

  el('relation-form').addEventListener('submit', (event) => {
    submitForm(event).catch((error) => log.error(error));
  });
  el('relation-type').addEventListener('change', syncDirectionDefault);
  el('relation-cancel').addEventListener('click', () => resetForm());

  el('open-graph-character').addEventListener('click', () => {
    if (!state.detail) {
      return;
    }
    window.dispatchEvent(
      new CustomEvent('inkwell:open-graph', {
        detail: { centerId: state.detail.id },
      }),
    );
  });
}

export async function showRelations(detail, { onOpenCharacter } = {}) {
  state.detail = detail;
  state.onOpenCharacter = onOpenCharacter || null;
  el('character-side').hidden = false;
  renderMemberships(detail);

  try {
    await loadSupport(detail.project_id);
    pickers.target.setItems(
      state.characters
        .filter((item) => item.id !== detail.id)
        .map((item) => ({ id: item.id, label: item.name })),
    );
    syncDirectionDefault();
    resetForm();
    await loadRelations();
  } catch (error) {
    log.error(error);
    showError(error);
  }
}

export function hideRelations() {
  el('character-side').hidden = true;
  state.detail = null;
  state.relations = [];
}

/** 角色增删改名后调用：下次 showRelations 重新拉角色/章节列表。 */
export function invalidateRelationSupport() {
  state.projectId = null;
}
