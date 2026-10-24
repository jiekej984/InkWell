/** 页面 P10（角色库）控制器（V2.0 / 5.4 / FR-8.1~8.6）。
 *
 * 交互原则（报告 §7.2）：
 *   · **字段失焦即保存**（debounce 800ms），不设整卡「保存」按钮，避免漏点
 *   · 别名冲突就地提示，可「仍要添加」（走 `force`）
 *   · 自定义字段 4 种类型，值就地编辑
 *   · 组织 / 阵营两个 Tab 在 5.5 / 5.8 接入，这里先给占位页
 */

import { request, requestForm } from './api.js';
import {
  appendAlias,
  characterInitial,
  characterSummary,
  formatTags,
  parseTags,
  saveStateText,
} from './character-format.js';
import { createLogger } from './logger.js';
import {
  hideRelations,
  initCharacterRelations,
  invalidateRelationSupport,
  showRelations,
} from './relations.js';
import { askText, el, setContext, showView } from './view.js';

const log = createLogger('characters');
const SEARCH_DEBOUNCE_MS = 250;

const state = {
  project: null,
  meta: null,
  organizations: [],
  characters: [],
  detail: null,
  keyword: '',
  role: '',
  orgId: '',
  sort: 'order',
  pendingAlias: '',
  pendingForce: false,
  loading: false,
};

let searchTimer = 0;

// --------------------------------------------------------------------------
// 小工具
// --------------------------------------------------------------------------

function timeLabel() {
  return new Date().toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  });
}

function errorMessage(error) {
  const text = (error && error.message) || String(error);
  const match = text.match(/code=\d+\s+(.*)$/s);
  return match ? match[1].trim() : text;
}

function setSaveState(kind, message = '') {
  const node = el('character-save-state');
  if (!node) {
    return;
  }
  node.textContent = saveStateText(kind, timeLabel(), message);
  node.className = `writer__status${kind === 'saved' ? ' is-ok' : ''}${
    kind === 'error' ? ' is-error' : ''
  }`;
  if (kind === 'saved') {
    el('character-saved').textContent = `保存于 ${timeLabel()}`;
  }
}

function setStat(text) {
  const node = el('stat-character');
  if (node) {
    node.textContent = text;
  }
}

function fillSelect(select, options, { allLabel = null, value = '' } = {}) {
  if (!select) {
    return;
  }
  select.textContent = '';
  if (allLabel !== null) {
    const option = document.createElement('option');
    option.value = '';
    option.textContent = allLabel;
    select.append(option);
  }
  for (const item of options || []) {
    const option = document.createElement('option');
    option.value = item.value;
    option.textContent = item.label;
    select.append(option);
  }
  select.value = value;
}

function currentQuery() {
  const params = new URLSearchParams();
  if (state.keyword) {
    params.set('keyword', state.keyword);
  }
  if (state.role) {
    params.set('role', state.role);
  }
  if (state.orgId) {
    params.set('org_id', state.orgId);
  }
  params.set('sort', state.sort);
  params.set('page', '1');
  params.set('page_size', '200');
  return params.toString();
}

// --------------------------------------------------------------------------
// 列表
// --------------------------------------------------------------------------

function renderList() {
  const root = el('character-list');
  if (!root) {
    return;
  }
  root.textContent = '';

  if (!state.characters.length) {
    const empty = document.createElement('p');
    empty.className = 'tree__empty';
    empty.textContent = state.loading
      ? '加载中…'
      : state.keyword || state.role || state.orgId
        ? '没有匹配的角色'
        : '还没有角色';
    root.append(empty);
    el('character-count').textContent = '共 0 个角色';
    return;
  }

  for (const item of state.characters) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'character-row';
    button.dataset.characterId = String(item.id);
    if (state.detail && item.id === state.detail.id) {
      button.classList.add('is-active');
    }
    button.setAttribute('aria-current', state.detail?.id === item.id ? 'true' : 'false');

    const dot = document.createElement('span');
    dot.className = 'character-row__dot';
    dot.style.background = `var(--role-${item.role}, var(--text-2))`;

    const name = document.createElement('span');
    name.className = 'character-row__name';
    name.textContent = item.name;

    const role = document.createElement('span');
    role.className = 'character-row__role';
    role.textContent = item.role_label;

    button.append(dot, name, role);
    button.addEventListener('click', () => {
      selectCharacter(item.id).catch((error) => log.error(error));
    });
    root.append(button);
  }

  el('character-count').textContent = `共 ${state.characters.length} 个角色${
    state.characters.length >= 200 ? '（仅显示前 200）' : ''
  }`;
}

async function loadList() {
  if (!state.project) {
    return;
  }
  state.loading = true;
  renderList();
  try {
    const data = await request(
      `/api/projects/${state.project.id}/characters?${currentQuery()}`,
    );
    state.characters = data.items;
  } catch (error) {
    log.error(error);
    state.characters = [];
    setSaveState('error', errorMessage(error));
  } finally {
    state.loading = false;
    renderList();
  }
}

async function loadOrganizations() {
  if (!state.project) {
    return;
  }
  try {
    const data = await request(
      `/api/projects/${state.project.id}/organizations`,
    );
    state.organizations = data.items || [];
  } catch (error) {
    // 组织还没建过属正常情况，不打断角色页
    log.warn('加载组织失败', errorMessage(error));
    state.organizations = [];
  }
  fillSelect(
    el('character-org-filter'),
    state.organizations.map((item) => ({ value: String(item.id), label: item.name })),
    { allLabel: '全部组织', value: state.orgId },
  );
}

async function loadMeta() {
  if (state.meta) {
    return state.meta;
  }
  const data = await request(
    `/api/projects/${state.project.id}/characters/meta`,
  );
  state.meta = data;

  fillSelect(el('character-role-filter'), data.roles, {
    allLabel: '全部定位',
    value: state.role,
  });
  fillSelect(el('character-sort'), data.sorts, { value: state.sort });
  fillSelect(el('character-role'), data.roles, { value: '' });
  fillSelect(el('character-status'), data.statuses, { value: '' });
  fillSelect(el('field-type'), data.field_types, { value: 'text' });
  return data;
}

// --------------------------------------------------------------------------
// 卡片
// --------------------------------------------------------------------------

function setHeaderEnabled(enabled) {
  for (const id of ['character-name', 'character-role', 'character-status']) {
    const node = el(id);
    if (node) {
      node.disabled = !enabled;
    }
  }
  el('character-role').hidden = !enabled;
  el('character-status').hidden = !enabled;
  el('delete-character').hidden = !enabled;
  el('character-name').placeholder = enabled ? '角色姓名' : '还没有角色';
}

function setEmpty() {
  state.detail = null;
  el('character-form').hidden = true;
  el('character-empty').hidden = false;
  el('character-name').value = '';
  el('character-role').value = '';
  el('character-status').value = '';
  setHeaderEnabled(false);
  hideRelations();
  setSaveState('idle');
  setStat('未选择角色');
  renderList();
}

function resetAliasInput() {
  state.pendingAlias = '';
  state.pendingForce = false;
  el('character-alias-input').value = '';
  el('character-alias-error').hidden = true;
  el('force-alias').hidden = true;
}

function renderAliases() {
  const root = el('character-aliases');
  root.textContent = '';
  const aliases = state.detail?.aliases || [];
  if (!aliases.length) {
    const empty = document.createElement('p');
    empty.className = 'field__hint';
    empty.textContent = '暂无别名';
    root.append(empty);
    el('character-aliases-hint').textContent = '别名：暂无';
    return;
  }
  el('character-aliases-hint').textContent = `别名：${aliases.join('、')}`;
  for (const alias of aliases) {
    const chip = document.createElement('span');
    chip.className = 'character-alias';
    const text = document.createElement('span');
    text.textContent = alias;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'character-alias__remove';
    remove.textContent = '×';
    remove.title = `移除别名「${alias}」`;
    remove.setAttribute('aria-label', `移除别名「${alias}」`);
    remove.addEventListener('click', () => {
      removeAlias(alias).catch((error) => log.error(error));
    });
    chip.append(text, remove);
    root.append(chip);
  }
}

function renderFields() {
  const root = el('character-fields');
  root.textContent = '';
  const fields = state.detail?.fields || [];
  if (!fields.length) {
    const empty = document.createElement('p');
    empty.className = 'field__hint';
    empty.textContent = '还没有自定义字段（灵根、血型、口音…都行）';
    root.append(empty);
    return;
  }
  for (const field of fields) {
    const row = document.createElement('div');
    row.className = 'character-field-row';

    const key = document.createElement('span');
    key.className = 'character-field-row__key';
    key.textContent = field.key;

    const type = document.createElement('span');
    type.className = 'character-field-row__type';
    type.textContent = field.field_type_label || field.field_type;

    const input = document.createElement('input');
    input.className = 'field__input';
    input.value = field.value ?? '';
    input.dataset.fieldId = String(field.id);
    input.setAttribute('aria-label', `${field.key} 的值`);
    input.addEventListener('blur', () => {
      saveFieldValue(field, input.value).catch((error) => log.error(error));
    });
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        input.blur();
      }
    });

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'tree__delete';
    remove.textContent = '✕';
    remove.title = `删除字段「${field.key}」`;
    remove.setAttribute('aria-label', `删除字段「${field.key}」`);
    remove.addEventListener('click', () => {
      deleteField(field).catch((error) => log.error(error));
    });

    row.append(key, type, input, remove);
    root.append(row);
  }
}

function fillForm(detail) {
  state.detail = detail;
  el('character-empty').hidden = true;
  el('character-form').hidden = false;
  setHeaderEnabled(true);

  el('character-name').value = detail.name || '';
  el('character-role').value = detail.role || 'other';
  el('character-status').value = detail.status || 'alive';
  for (const input of document.querySelectorAll('#character-form [data-field]')) {
    const key = input.dataset.field;
    input.value = detail[key] ?? '';
  }
  el('character-tags').value = formatTags(detail.tags);
  el('character-summary').textContent = characterSummary(detail);
  el('character-avatar-initial').textContent = characterInitial(detail.name);
  updateAvatar(detail);
  renderAliases();
  renderFields();
  resetAliasInput();
  renderList();
  showRelations(detail, {
    onOpenCharacter: (characterId) => {
      selectCharacter(characterId).catch((error) => log.error(error));
    },
  }).catch((error) => log.error(error));
  setStat(
    `第 ${state.characters.findIndex((item) => item.id === detail.id) + 1} 个 / 共 ${
      state.characters.length
    } 个`,
  );
}

function updateAvatar(detail) {
  const img = el('character-avatar-img');
  const initial = el('character-avatar-initial');
  if (!detail || !detail.avatar_path) {
    img.hidden = true;
    img.removeAttribute('src');
    initial.hidden = false;
    return;
  }
  // 先显示首字，拿到签名 URL 再换成图片，避免 src 里带非法签名导致破图
  img.hidden = true;
  img.removeAttribute('src');
  initial.hidden = false;
  request('/api/files/sign', {
    method: 'POST',
    body: { paths: [detail.avatar_path] },
  })
    .then((data) => {
      const item = (data.items || [])[0];
      if (!item || !state.detail || state.detail.id !== detail.id) {
        return;
      }
      img.src = item.url;
      img.alt = `${detail.name} 的立绘`;
      img.hidden = false;
      initial.hidden = true;
    })
    .catch((error) => log.warn('立绘签名失败', errorMessage(error)));
}

async function selectCharacter(characterId) {
  if (!characterId) {
    return;
  }
  if (state.detail && state.detail.id === characterId) {
    renderList();
    return;
  }
  try {
    const detail = await request(`/api/characters/${characterId}`);
    fillForm(detail);
    setSaveState('idle');
    el('character-save-state').textContent = '就绪';
  } catch (error) {
    log.error(error);
    setSaveState('error', errorMessage(error));
  }
}

/** 从组织/阵营页切回来时重拉当前角色（组织身份可能刚改过）。 */
async function refreshDetail() {
  if (!state.detail) {
    return;
  }
  const detail = await request(`/api/characters/${state.detail.id}`);
  fillForm(detail);
}

// --------------------------------------------------------------------------
// 保存
// --------------------------------------------------------------------------

async function patchCharacter(fields, { quiet = false } = {}) {
  if (!state.detail) {
    return null;
  }
  if (!quiet) {
    setSaveState('saving');
  }
  try {
    const detail = await request(`/api/characters/${state.detail.id}`, {
      method: 'PATCH',
      body: fields,
    });
    const identityChanged = 'name' in fields || 'role' in fields;
    state.detail = detail;
    if (identityChanged) {
      invalidateRelationSupport();
      await loadList();
    }
    setSaveState('saved');
    return detail;
  } catch (error) {
    log.error(error);
    setSaveState('error', errorMessage(error));
    throw error;
  }
}

async function onFieldBlur(event) {
  const input = event.currentTarget;
  const key = input.dataset.field;
  if (!state.detail || !key) {
    return;
  }
  const value = input.value.trim();
  const previous = state.detail[key] ?? '';
  if (value === previous) {
    return;
  }
  if (key === 'name' && !value) {
    input.value = previous;
    setSaveState('error', '姓名不能为空');
    return;
  }
  await patchCharacter({ [key]: value || null }).catch(() => {});
}

async function saveTags() {
  if (!state.detail) {
    return;
  }
  const tags = parseTags(el('character-tags').value);
  const before = state.detail.tags || [];
  if (tags.length === before.length && tags.every((tag, i) => tag === before[i])) {
    return;
  }
  await patchCharacter({ tags }).catch(() => {});
}

async function onSelectChange(event) {
  const select = event.currentTarget;
  if (!state.detail) {
    return;
  }
  const key = select.id === 'character-role' ? 'role' : 'status';
  await patchCharacter({ [key]: select.value }).catch(() => {});
  el('character-summary').textContent = characterSummary(state.detail);
}

// --------------------------------------------------------------------------
// 别名
// --------------------------------------------------------------------------

async function saveAliases(aliases, force = false) {
  if (!state.detail) {
    return;
  }
  setSaveState('saving');
  try {
    const data = await request(`/api/characters/${state.detail.id}/aliases`, {
      method: 'PUT',
      body: { aliases, force },
    });
    state.detail.aliases = data.aliases;
    resetAliasInput();
    renderAliases();
    renderList();
    setSaveState('saved');
  } catch (error) {
    state.pendingAlias = el('character-alias-input').value.trim();
    state.pendingForce = errorMessage(error).includes('姓名冲突');
    const node = el('character-alias-error');
    node.textContent = errorMessage(error);
    node.hidden = false;
    el('force-alias').hidden = !state.pendingForce;
    setSaveState('error', errorMessage(error));
    throw error;
  }
}

async function addAlias(force = false) {
  if (!state.detail) {
    return;
  }
  const value = el('character-alias-input').value.trim();
  if (!value) {
    return;
  }
  const next = appendAlias(state.detail.aliases || [], value);
  await saveAliases(next, force).catch(() => {});
}

async function removeAlias(alias) {
  if (!state.detail) {
    return;
  }
  const next = (state.detail.aliases || []).filter((item) => item !== alias);
  await saveAliases(next).catch(() => {});
}

// --------------------------------------------------------------------------
// 自定义字段
// --------------------------------------------------------------------------

async function addField() {
  if (!state.detail) {
    return;
  }
  const key = el('field-key').value.trim();
  if (!key) {
    el('character-field-error').textContent = '字段名不能为空';
    el('character-field-error').hidden = false;
    return;
  }
  const payload = {
    key,
    value: el('field-value').value.trim() || null,
    field_type: el('field-type').value,
  };
  try {
    await request(`/api/characters/${state.detail.id}/fields`, {
      method: 'POST',
      body: payload,
    });
    el('field-key').value = '';
    el('field-value').value = '';
    el('character-field-error').hidden = true;
    const detail = await request(`/api/characters/${state.detail.id}`);
    fillForm(detail);
    setSaveState('saved');
  } catch (error) {
    el('character-field-error').textContent = errorMessage(error);
    el('character-field-error').hidden = false;
    setSaveState('error', errorMessage(error));
  }
}

async function saveFieldValue(field, value) {
  const next = value.trim();
  if (next === (field.value ?? '')) {
    return;
  }
  setSaveState('saving');
  try {
    await request(`/api/fields/${field.id}`, {
      method: 'PATCH',
      body: { value: next || null },
    });
    field.value = next || null;
    setSaveState('saved');
  } catch (error) {
    setSaveState('error', errorMessage(error));
    throw error;
  }
}

async function deleteField(field) {
  const confirmed = window.confirm(`删除字段「${field.key}」？`);
  if (!confirmed) {
    return;
  }
  try {
    await request(`/api/fields/${field.id}`, { method: 'DELETE' });
    const detail = await request(`/api/characters/${state.detail.id}`);
    fillForm(detail);
    setSaveState('saved');
  } catch (error) {
    setSaveState('error', errorMessage(error));
  }
}

// --------------------------------------------------------------------------
// 立绘 / 新建 / 删除
// --------------------------------------------------------------------------

async function uploadAvatar() {
  const file = el('character-avatar-file').files?.[0];
  if (!file || !state.detail) {
    return;
  }
  const form = new FormData();
  form.append('file', file);
  setSaveState('saving');
  try {
    const data = await requestForm(
      `/api/characters/${state.detail.id}/avatar`,
      form,
    );
    state.detail.avatar_path = data.path;
    updateAvatar(state.detail);
    await loadList();
    setSaveState('saved');
  } catch (error) {
    setSaveState('error', errorMessage(error));
  } finally {
    el('character-avatar-file').value = '';
  }
}

async function createCharacter() {
  if (!state.project) {
    return;
  }
  const name = await askText({ title: '新建角色', label: '姓名' });
  if (!name) {
    return;
  }
  try {
    const created = await request(
      `/api/projects/${state.project.id}/characters`,
      { method: 'POST', body: { name } },
    );
    invalidateRelationSupport();
    await loadList();
    await selectCharacter(created.id);
    setSaveState('saved');
  } catch (error) {
    setSaveState('error', errorMessage(error));
  }
}

async function deleteCharacter() {
  if (!state.detail) {
    return;
  }
  const confirmed = window.confirm(
    `删除角色「${state.detail.name}」？\n可在回收站恢复（30 天内）；别名与关系会一起保留。`,
  );
  if (!confirmed) {
    return;
  }
  try {
    await request(`/api/characters/${state.detail.id}`, { method: 'DELETE' });
    invalidateRelationSupport();
    await loadList();
    if (state.characters.length) {
      await selectCharacter(state.characters[0].id);
    } else {
      setEmpty();
    }
    setSaveState('saved');
  } catch (error) {
    setSaveState('error', errorMessage(error));
  }
}

// --------------------------------------------------------------------------
// Tab / 导航
// --------------------------------------------------------------------------

function switchTab(tab) {
  const section = el('view-characters');
  const tabs = {
    characters: el('tab-characters'),
    organizations: el('tab-organizations'),
    factions: el('tab-factions'),
  };
  for (const [key, button] of Object.entries(tabs)) {
    const active = key === tab;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-selected', active ? 'true' : 'false');
  }
  section.classList.remove(
    'is-tab-characters',
    'is-tab-organizations',
    'is-tab-factions',
  );
  section.classList.add(`is-tab-${tab}`);
  // 组织 / 阵营面板由 organizations.js 监听后自行加载
  window.dispatchEvent(
    new CustomEvent('inkwell:character-tab', { detail: { tab } }),
  );
}

// --------------------------------------------------------------------------
// 对外
// --------------------------------------------------------------------------

export function initCharacters() {
  initCharacterRelations();
  el('tab-characters').addEventListener('click', () => switchTab('characters'));
  el('tab-organizations').addEventListener('click', () =>
    switchTab('organizations'),
  );
  el('tab-factions').addEventListener('click', () => switchTab('factions'));

  // 从组织/阵营页切回来：重拉当前角色（组织身份可能刚变）
  window.addEventListener('inkwell:character-tab', (event) => {
    if (event.detail && event.detail.tab === 'characters' && state.detail) {
      refreshDetail().catch((error) => log.error(error));
    }
  });

  el('add-character').addEventListener('click', () => {
    createCharacter().catch((error) => log.error(error));
  });
  el('delete-character').addEventListener('click', () => {
    deleteCharacter().catch((error) => log.error(error));
  });

  const nameInput = el('character-name');
  nameInput.addEventListener('blur', (event) => {
    onFieldBlur(event).catch((error) => log.error(error));
  });
  nameInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      nameInput.blur();
    }
  });

  for (const input of document.querySelectorAll('#character-form [data-field]')) {
    input.addEventListener('blur', (event) => {
      onFieldBlur(event).catch((error) => log.error(error));
    });
  }

  el('character-role').addEventListener('change', (event) => {
    onSelectChange(event).catch((error) => log.error(error));
  });
  el('character-status').addEventListener('change', (event) => {
    onSelectChange(event).catch((error) => log.error(error));
  });

  el('character-tags').addEventListener('blur', () => {
    saveTags().catch((error) => log.error(error));
  });

  el('add-alias').addEventListener('click', () => {
    addAlias(false).catch((error) => log.error(error));
  });
  el('force-alias').addEventListener('click', () => {
    addAlias(true).catch((error) => log.error(error));
  });
  el('character-alias-input').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      addAlias(false).catch((error) => log.error(error));
    }
  });

  el('add-field').addEventListener('click', () => {
    addField().catch((error) => log.error(error));
  });

  el('character-avatar').addEventListener('click', () => {
    el('character-avatar-file').click();
  });
  el('character-avatar-file').addEventListener('change', () => {
    uploadAvatar().catch((error) => log.error(error));
  });

  el('character-search').addEventListener('input', (event) => {
    window.clearTimeout(searchTimer);
    const value = event.currentTarget.value.trim();
    searchTimer = window.setTimeout(() => {
      state.keyword = value;
      loadList().catch((error) => log.error(error));
    }, SEARCH_DEBOUNCE_MS);
  });
  el('character-role-filter').addEventListener('change', (event) => {
    state.role = event.currentTarget.value;
    loadList().catch((error) => log.error(error));
  });
  el('character-org-filter').addEventListener('change', (event) => {
    state.orgId = event.currentTarget.value;
    loadList().catch((error) => log.error(error));
  });
  el('character-sort').addEventListener('change', (event) => {
    state.sort = event.currentTarget.value;
    loadList().catch((error) => log.error(error));
  });

  el('character-list').addEventListener('keydown', (event) => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') {
      return;
    }
    event.preventDefault();
    const index = state.characters.findIndex(
      (item) => state.detail && item.id === state.detail.id,
    );
    const next =
      event.key === 'ArrowDown'
        ? Math.min(index + 1, state.characters.length - 1)
        : Math.max(index - 1, 0);
    if (state.characters[next]) {
      selectCharacter(state.characters[next].id).catch((error) =>
        log.error(error),
      );
    }
  });

  el('back-to-writer-from-characters').addEventListener('click', () => {
    showView('view-writer');
    setContext(state.project ? state.project.title : '');
  });
}

export async function openCharacters(project) {
  state.project = project;
  state.detail = null;
  state.characters = [];
  state.keyword = '';
  state.role = '';
  state.orgId = '';
  state.sort = 'order';
  el('character-search').value = '';
  el('character-role-filter').value = '';
  el('character-org-filter').value = '';
  el('character-sort').value = 'order';
  switchTab('characters');
  el('characters-project-title').textContent = `${project.title} · 角色`;
  setContext(`${project.title} · 角色`);
  showView('view-characters');
  setSaveState('idle');
  setStat('加载中…');

  try {
    await loadMeta();
    await loadOrganizations();
    await loadList();
    if (state.characters.length) {
      await selectCharacter(state.characters[0].id);
    } else {
      setEmpty();
    }
  } catch (error) {
    log.error(error);
    setSaveState('error', errorMessage(error));
    setStat('加载失败');
  }
}

/** 当前项目（组织 / 阵营面板复用）。 */
export function getCurrentProject() {
  return state.project;
}

/** 离开角色库（返回作品列表前由 app.js 调用）。字段是即时保存的，这里只清上下文。 */
export function leaveCharacters() {
  setContext('');
  window.clearTimeout(searchTimer);
}
