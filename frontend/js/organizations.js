/** 组织 / 阵营面板（V2.0 / 5.5 / FR-8.7~8.11）。
 *
 * 数据形状（接口见 5.3）：
 *   · `GET /projects/{pid}/organizations?tree=1` → 嵌套树（含 effective_faction_id / 成员数）
 *   · `GET /projects/{pid}/factions` → 立场（含组织数）
 *   · `GET/POST/PATCH/DELETE /organizations...`、`/organizations/{oid}/members...`
 *
 * 约定：
 *   · 组织详情与阵营详情用**显式保存**（多字段表单），成员行是**就地保存**
 *   · 删组织必须选策略：`cascade` 一并删 / `promote` 上移一级；根组织只剩「一并删」
 *   · Tab 切换由 `characters.js` 派发 `inkwell:character-tab`，本模块只监听
 */

import { request } from './api.js';
import { getCurrentProject } from './characters.js';
import { createLogger } from './logger.js';
import { askText, el } from './view.js';

const log = createLogger('organizations');

const state = {
  loadedFor: null,
  meta: null,
  characters: [],
  documents: [],
  chapters: [],
  factions: [],
  factionRelations: [],
  tree: [],
  flat: [],
  byId: new Map(),
  collapsed: new Set(),
  currentOrg: null,
  members: [],
  currentFaction: null,
};

// --------------------------------------------------------------------------
// 基础工具
// --------------------------------------------------------------------------

function errorMessage(error) {
  const text = (error && error.message) || String(error);
  const match = text.match(/code=\d+\s+(.*)$/s);
  return match ? match[1].trim() : text;
}

function setStatus(id, text, kind = '') {
  const node = el(id);
  if (!node) {
    return;
  }
  node.textContent = text;
  node.className = `writer__status${kind ? ` is-${kind}` : ''}`;
}

function setError(id, message) {
  const node = el(id);
  if (!node) {
    return;
  }
  node.textContent = message || '';
  node.hidden = !message;
}

function fillSelect(select, items, { allLabel = null, value = '' } = {}) {
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
  for (const item of items || []) {
    const option = document.createElement('option');
    option.value = String(item.value);
    option.textContent = item.label;
    select.append(option);
  }
  select.value = value === null || value === undefined ? '' : String(value);
}

function flattenTree(nodes, out = []) {
  for (const node of nodes || []) {
    out.push(node);
    flattenTree(node.children, out);
  }
  return out;
}

function flattenChapters(tree) {
  const list = [];
  const push = (volume) => {
    for (const chapter of volume.chapters || []) {
      list.push(chapter);
    }
  };
  if (tree.default_volume) {
    push(tree.default_volume);
  }
  for (const volume of tree.volumes || []) {
    push(volume);
  }
  return list;
}

function chapterOptions() {
  return [{ value: '', label: '不限' }].concat(
    state.chapters.map((chapter) => ({
      value: chapter.id,
      label: chapter.title,
    })),
  );
}

function projectId() {
  const project = getCurrentProject();
  return project ? project.id : null;
}

// --------------------------------------------------------------------------
// 共享数据
// --------------------------------------------------------------------------

async function loadShared() {
  const pid = projectId();
  if (!pid) {
    return;
  }
  if (state.loadedFor === pid) {
    return;
  }
  const [meta, characters, documents, volumes] = await Promise.all([
    request(`/api/projects/${pid}/characters/meta`),
    request(`/api/projects/${pid}/characters?page_size=200`),
    request(`/api/projects/${pid}/documents`).catch(() => ({ items: [] })),
    request(`/api/projects/${pid}/volumes`).catch(() => ({})),
  ]);
  state.meta = meta;
  state.characters = characters.items || [];
  state.documents = documents.items || [];
  state.chapters = flattenChapters(volumes || {});
  state.loadedFor = pid;

  fillSelect(
    el('org-kind'),
    meta.organization_kinds,
    { value: 'sect' },
  );
  fillSelect(
    el('faction-rel-type'),
    meta.faction_relation_types,
    { value: 'enemy' },
  );
  fillSelect(el('org-faction'), [], { allLabel: '无阵营' });
  fillSelect(el('org-parent'), [], { allLabel: '无（顶级）' });
  fillSelect(
    el('org-leader'),
    state.characters.map((item) => ({ value: item.id, label: item.name })),
    { allLabel: '暂无首领' },
  );
  fillSelect(
    el('org-document'),
    state.documents.map((item) => ({
      value: item.id,
      label: `${item.title}（${item.category_label || item.category}）`,
    })),
    { allLabel: '不关联' },
  );
  fillSelect(el('member-from'), chapterOptions(), { value: '' });
  fillSelect(el('member-to'), chapterOptions(), { value: '' });
}

// --------------------------------------------------------------------------
// 组织树
// --------------------------------------------------------------------------

async function loadOrgTree() {
  const pid = projectId();
  const data = await request(`/api/projects/${pid}/organizations?tree=1`);
  state.tree = data.items || [];
  state.flat = flattenTree(state.tree);
  state.byId = new Map(state.flat.map((item) => [item.id, item]));
  renderOrgTree();
}

function descendantIds(orgId) {
  const result = new Set([orgId]);
  const walk = (nodes) => {
    for (const node of nodes || []) {
      if (result.has(node.id)) {
        for (const child of node.children || []) {
          result.add(child.id);
        }
      }
      walk(node.children);
    }
  };
  walk(state.tree);
  return result;
}

function renderOrgTree() {
  const root = el('organization-tree');
  if (!root) {
    return;
  }
  root.textContent = '';
  if (!state.tree.length) {
    const empty = document.createElement('p');
    empty.className = 'tree__empty';
    empty.textContent = '还没有组织';
    root.append(empty);
    return;
  }

  const build = (nodes, container) => {
    for (const node of nodes) {
      const row = document.createElement('div');
      row.className = 'org-tree__row';
      row.dataset.orgId = String(node.id);
      row.draggable = true;
      if (state.currentOrg && state.currentOrg.id === node.id) {
        row.classList.add('is-active');
      }

      const toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'org-tree__toggle';
      const hasChildren = (node.children || []).length > 0;
      if (!hasChildren) {
        toggle.classList.add('is-hidden');
      }
      toggle.textContent = state.collapsed.has(node.id) ? '▸' : '▾';
      toggle.setAttribute('aria-label', '折叠 / 展开子组织');
      toggle.addEventListener('click', (event) => {
        event.stopPropagation();
        if (state.collapsed.has(node.id)) {
          state.collapsed.delete(node.id);
        } else {
          state.collapsed.add(node.id);
        }
        renderOrgTree();
      });

      const name = document.createElement('button');
      name.type = 'button';
      name.className = 'org-tree__name';
      name.textContent = node.name;
      name.title = `${node.kind_label}${node.faction_id ? '' : ' · 未归阵营'}`;
      name.addEventListener('click', () => {
        selectOrg(node.id).catch((error) => log.error(error));
      });

      const count = document.createElement('span');
      count.className = 'org-tree__count';
      count.textContent = node.member_count ? String(node.member_count) : '';

      row.append(toggle, name, count);
      row.addEventListener('dragstart', (event) => {
        event.dataTransfer.setData('text/plain', String(node.id));
        event.dataTransfer.effectAllowed = 'move';
      });
      row.addEventListener('dragover', (event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';
      });
      row.addEventListener('drop', (event) => {
        event.preventDefault();
        event.stopPropagation();
        const dragged = Number(event.dataTransfer.getData('text/plain'));
        if (!dragged || dragged === node.id) {
          return;
        }
        reparent(dragged, node.id).catch((error) =>
          setStatus('org-status', errorMessage(error), 'error'),
        );
      });

      container.append(row);
      if (hasChildren && !state.collapsed.has(node.id)) {
        const children = document.createElement('div');
        children.className = 'org-tree__children';
        build(node.children, children);
        container.append(children);
      }
    }
  };

  build(state.tree, root);
}

async function reparent(orgId, parentId) {
  await request(`/api/organizations/${orgId}`, {
    method: 'PATCH',
    body: { parent_id: parentId },
  });
  await loadOrgTree();
  if (state.currentOrg) {
    const fresh = state.byId.get(state.currentOrg.id);
    if (fresh) {
      state.currentOrg = fresh;
      renderOrgTree();
    }
  }
  setStatus('org-status', parentId ? '已挂到上级' : '已移到顶级', 'ok');
}

// --------------------------------------------------------------------------
// 组织详情
// --------------------------------------------------------------------------

function parentOptions(orgId) {
  const blocked = descendantIds(orgId);
  return state.flat
    .filter((item) => !blocked.has(item.id))
    .map((item) => ({ value: item.id, label: item.name }));
}

function factionOptions() {
  return state.factions.map((item) => ({
    value: item.id,
    label: item.name,
  }));
}

async function selectOrg(orgId) {
  const org = state.byId.get(orgId);
  if (!org) {
    return;
  }
  state.currentOrg = org;
  el('organization-empty').hidden = true;
  el('organization-detail').hidden = false;
  el('org-detail-title').textContent = org.name;
  el('org-name').value = org.name;
  el('org-kind').value = org.kind;
  fillSelect(el('org-faction'), factionOptions(), { allLabel: '无阵营', value: org.faction_id });
  fillSelect(el('org-parent'), parentOptions(orgId), {
    allLabel: '无（顶级）',
    value: org.parent_id,
  });
  fillSelect(el('org-leader'), state.characters.map((item) => ({
    value: item.id,
    label: item.name,
  })), { allLabel: '暂无首领', value: org.leader_id });
  fillSelect(el('org-document'), state.documents.map((item) => ({
    value: item.id,
    label: `${item.title}（${item.category_label || item.category}）`,
  })), { allLabel: '不关联', value: org.document_id });
  el('org-color').value = org.color || '#7a6a58';
  el('org-description').value = org.description || '';
  el('move-org-up').disabled = org.parent_id === null;
  setError('org-error', '');
  renderOrgTree();
  await loadMembers(orgId);
}

async function saveOrg() {
  if (!state.currentOrg) {
    return;
  }
  const body = {
    name: el('org-name').value.trim(),
    kind: el('org-kind').value,
    faction_id: el('org-faction').value ? Number(el('org-faction').value) : null,
    parent_id: el('org-parent').value ? Number(el('org-parent').value) : null,
    leader_id: el('org-leader').value ? Number(el('org-leader').value) : null,
    document_id: el('org-document').value
      ? Number(el('org-document').value)
      : null,
    color: el('org-color').value,
    description: el('org-description').value.trim() || null,
  };
  setStatus('org-status', '保存中…');
  try {
    await request(`/api/organizations/${state.currentOrg.id}`, {
      method: 'PATCH',
      body,
    });
    await loadFactions();
    await loadOrgTree();
    await selectOrg(state.currentOrg.id);
    setStatus('org-status', '已保存', 'ok');
  } catch (error) {
    setStatus('org-status', errorMessage(error), 'error');
  }
}

async function createOrg(asChild) {
  const name = await askText({
    title: asChild ? '新建子组织' : '新建组织',
    label: '组织名称',
  });
  if (!name) {
    return;
  }
  const body = { name };
  if (asChild && state.currentOrg) {
    body.parent_id = state.currentOrg.id;
    if (state.currentOrg.faction_id) {
      body.faction_id = state.currentOrg.faction_id;
    }
  }
  try {
    const created = await request(`/api/projects/${projectId()}/organizations`, {
      method: 'POST',
      body,
    });
    await loadFactions();
    await loadOrgTree();
    await selectOrg(created.id);
    setStatus('org-status', '已创建', 'ok');
  } catch (error) {
    setStatus('org-status', errorMessage(error), 'error');
  }
}

async function moveOrgUp() {
  if (!state.currentOrg || state.currentOrg.parent_id === null) {
    return;
  }
  const parent = state.byId.get(state.currentOrg.parent_id);
  const grandParentId = parent && parent.parent_id ? parent.parent_id : null;
  try {
    await request(`/api/organizations/${state.currentOrg.id}`, {
      method: 'PATCH',
      body: { parent_id: grandParentId },
    });
    await loadOrgTree();
    await selectOrg(state.currentOrg.id);
    setStatus('org-status', '已上移一级', 'ok');
  } catch (error) {
    setStatus('org-status', errorMessage(error), 'error');
  }
}

function openDeleteDialog() {
  if (!state.currentOrg) {
    return;
  }
  const org = state.currentOrg;
  el('org-delete-title').textContent = `删除组织「${org.name}」`;
  el('org-delete-summary').textContent = org.child_count
    ? `它有 ${org.child_count} 个子组织、${org.member_count} 位成员。`
    : `它有 ${org.member_count} 位成员。`;
  const promoteLabel = el('org-delete-promote-label');
  const promoteInput = promoteLabel.querySelector('input');
  const canPromote = org.parent_id !== null;
  promoteInput.disabled = !canPromote;
  promoteInput.checked = false;
  promoteLabel.title = canPromote
    ? '子组织与成员挂到上一级'
    : '顶层组织没有上级可挂';
  el('org-delete-form').reset();
  el('org-delete-dialog').showModal();
}

async function confirmDeleteOrg(event) {
  if (event.target.returnValue !== 'ok' || !state.currentOrg) {
    return;
  }
  const mode = new FormData(el('org-delete-form')).get('org-delete-mode') || 'cascade';
  const org = state.currentOrg;
  try {
    await request(`/api/organizations/${org.id}?strategy=${mode}`, {
      method: 'DELETE',
    });
    state.currentOrg = null;
    el('organization-detail').hidden = true;
    el('organization-empty').hidden = false;
    await loadFactions();
    await loadOrgTree();
    if (state.tree.length) {
      await selectOrg(state.tree[0].id);
    }
    setStatus('org-status', '已删除', 'ok');
  } catch (error) {
    setStatus('org-status', errorMessage(error), 'error');
  }
}

// --------------------------------------------------------------------------
// 成员
// --------------------------------------------------------------------------

async function loadMembers(orgId) {
  const data = await request(`/api/organizations/${orgId}/members`);
  // 连续切换组织时只接受当前组织的响应，避免 A 的成员列表覆盖 B
  if (!state.currentOrg || state.currentOrg.id !== orgId) {
    return;
  }
  state.members = data.items || [];
  renderMembers();
}

function renderMembers() {
  const root = el('org-member-list');
  if (!root) {
    return;
  }
  root.textContent = '';
  if (!state.members.length) {
    const empty = document.createElement('p');
    empty.className = 'field__hint';
    empty.textContent = '还没有成员';
    root.append(empty);
  }

  for (const member of state.members) {
    const row = document.createElement('div');
    row.className = 'member-row';

    const name = document.createElement('span');
    name.className = 'member-row__name';
    name.textContent = member.character_name;
    name.title = member.is_secret ? '隐蔽身份' : '';

    const position = document.createElement('input');
    position.className = 'field__input';
    position.value = member.position || '';
    position.placeholder = '职位';
    position.maxLength = 50;
    position.setAttribute('aria-label', `${member.character_name} 的职位`);
    position.addEventListener('blur', () => {
      patchMember(member, { position: position.value.trim() || null }).catch(
        (error) => log.error(error),
      );
    });

    const from = document.createElement('select');
    from.className = 'field__input';
    fillSelect(from, chapterOptions(), { value: member.from_chapter_id || '' });
    from.setAttribute('aria-label', `${member.character_name} 起始章`);
    from.addEventListener('change', () => {
      patchMember(member, {
        from_chapter_id: from.value ? Number(from.value) : null,
      }).catch((error) => log.error(error));
    });

    const to = document.createElement('select');
    to.className = 'field__input';
    fillSelect(to, chapterOptions(), { value: member.to_chapter_id || '' });
    to.setAttribute('aria-label', `${member.character_name} 结束章`);
    to.addEventListener('change', () => {
      patchMember(member, {
        to_chapter_id: to.value ? Number(to.value) : null,
      }).catch((error) => log.error(error));
    });

    const primary = document.createElement('label');
    primary.className = 'check';
    const primaryInput = document.createElement('input');
    primaryInput.type = 'checkbox';
    primaryInput.checked = member.is_primary;
    primaryInput.addEventListener('change', () => {
      patchMember(member, { is_primary: primaryInput.checked }).catch(
        (error) => log.error(error),
      );
    });
    primary.append(primaryInput, document.createTextNode(' 主组织'));

    const secret = document.createElement('label');
    secret.className = 'check';
    const secretInput = document.createElement('input');
    secretInput.type = 'checkbox';
    secretInput.checked = member.is_secret;
    secretInput.addEventListener('change', () => {
      patchMember(member, { is_secret: secretInput.checked }).catch((error) =>
        log.error(error),
      );
    });
    secret.append(secretInput, document.createTextNode(' 隐蔽'));

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'tree__delete';
    remove.textContent = '✕';
    remove.title = `移除「${member.character_name}」`;
    remove.setAttribute('aria-label', `移除成员「${member.character_name}」`);
    remove.addEventListener('click', () => {
      removeMember(member).catch((error) => log.error(error));
    });

    row.append(name, position, from, to, primary, secret, remove);
    root.append(row);
  }

  const existing = new Set(state.members.map((item) => item.character_id));
  fillSelect(
    el('member-character'),
    state.characters
      .filter((item) => !existing.has(item.id))
      .map((item) => ({ value: item.id, label: item.name })),
    { allLabel: '选择角色' },
  );
}

async function patchMember(member, fields) {
  try {
    await request(`/api/org-members/${member.id}`, {
      method: 'PATCH',
      body: fields,
    });
    await loadMembers(state.currentOrg.id);
    await loadOrgTree();
    // 只刷新成员与树，不重填组织详情表单：描述等字段是显式保存的，
    // 成员操作不能把用户正在编辑的内容冲掉。
    setStatus('org-status', '已保存', 'ok');
  } catch (error) {
    setStatus('org-status', errorMessage(error), 'error');
    throw error;
  }
}

async function addMember() {
  if (!state.currentOrg) {
    return;
  }
  const characterId = el('member-character').value;
  if (!characterId) {
    setError('org-error', '先选一个角色');
    return;
  }
  try {
    await request(`/api/organizations/${state.currentOrg.id}/members`, {
      method: 'POST',
      body: {
        character_id: Number(characterId),
        position: el('member-position').value.trim() || null,
        is_primary: el('member-primary').checked,
        is_secret: el('member-secret').checked,
        from_chapter_id: el('member-from').value
          ? Number(el('member-from').value)
          : null,
        to_chapter_id: el('member-to').value
          ? Number(el('member-to').value)
          : null,
      },
    });
    el('member-position').value = '';
    el('member-primary').checked = false;
    el('member-secret').checked = false;
    setError('org-error', '');
    await loadMembers(state.currentOrg.id);
    await loadOrgTree();
    setStatus('org-status', '已添加成员', 'ok');
  } catch (error) {
    setError('org-error', errorMessage(error));
    setStatus('org-status', errorMessage(error), 'error');
  }
}

async function removeMember(member) {
  const confirmed = window.confirm(
    `移除「${member.character_name}」在「${state.currentOrg.name}」的身份？`,
  );
  if (!confirmed) {
    return;
  }
  try {
    await request(`/api/org-members/${member.id}`, { method: 'DELETE' });
    await loadMembers(state.currentOrg.id);
    await loadOrgTree();
    setStatus('org-status', '已移除', 'ok');
  } catch (error) {
    setStatus('org-status', errorMessage(error), 'error');
  }
}

// --------------------------------------------------------------------------
// 阵营
// --------------------------------------------------------------------------

async function loadFactions() {
  const pid = projectId();
  const [factions, relations] = await Promise.all([
    request(`/api/projects/${pid}/factions`),
    request(`/api/projects/${pid}/faction-relations`),
  ]);
  state.factions = factions.items || [];
  state.factionRelations = relations.items || [];
  renderFactionList();
  // 重填阵营下拉时保留用户当前选择：增删阵营不应清掉组织详情里未保存的编辑
  const factionSelect = el('org-faction');
  const previousFaction = factionSelect ? factionSelect.value : '';
  fillSelect(factionSelect, factionOptions(), { allLabel: '无阵营' });
  if (previousFaction) {
    factionSelect.value = previousFaction;
  }
  if (state.currentFaction) {
    const fresh = state.factions.find((item) => item.id === state.currentFaction.id);
    state.currentFaction = fresh || null;
  }
  if (!state.currentFaction && state.factions.length) {
    state.currentFaction = state.factions[0];
  }
  renderFactionDetail();
}

function renderFactionList() {
  const root = el('faction-list');
  if (!root) {
    return;
  }
  root.textContent = '';
  if (!state.factions.length) {
    const empty = document.createElement('p');
    empty.className = 'tree__empty';
    empty.textContent = '还没有阵营';
    root.append(empty);
    return;
  }
  for (const faction of state.factions) {
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'faction-card';
    if (state.currentFaction && state.currentFaction.id === faction.id) {
      card.classList.add('is-active');
    }

    const dot = document.createElement('span');
    dot.className = 'faction-card__dot';
    dot.style.background = faction.color || '#b8b0a4';

    const name = document.createElement('span');
    name.className = 'faction-card__name';
    name.textContent = faction.name;

    const count = document.createElement('span');
    count.className = 'faction-card__count';
    count.textContent = `${faction.organization_count} 组织`;

    card.append(dot, name, count);
    card.addEventListener('click', () => {
      state.currentFaction = faction;
      renderFactionList();
      renderFactionDetail();
    });
    root.append(card);
  }
}

function renderFactionDetail() {
  const faction = state.currentFaction;
  const empty = el('faction-empty');
  const detail = el('faction-detail');
  if (!faction) {
    empty.hidden = false;
    detail.hidden = true;
    return;
  }
  empty.hidden = true;
  detail.hidden = false;
  el('faction-detail-title').textContent = faction.name;
  el('faction-name').value = faction.name;
  el('faction-color').value = faction.color || '#7a6a58';
  el('faction-description').value = faction.description || '';
  setError('faction-error', '');
  renderFactionRelations();
}

function renderFactionRelations() {
  const root = el('faction-relation-list');
  if (!root) {
    return;
  }
  root.textContent = '';
  const related = state.factionRelations.filter(
    (item) =>
      state.currentFaction &&
      (item.from_id === state.currentFaction.id ||
        item.to_id === state.currentFaction.id),
  );
  if (!related.length) {
    const empty = document.createElement('p');
    empty.className = 'field__hint';
    empty.textContent = '还没有阵营关系';
    root.append(empty);
  }
  for (const relation of related) {
    const row = document.createElement('div');
    row.className = 'faction-relation-row';

    const text = document.createElement('span');
    text.className = 'faction-relation-row__text';
    const direction = relation.is_bidirectional ? '⇄' : '→';
    text.textContent = `${relation.from_name} ${direction} ${relation.to_name} · ${relation.relation_label}${
      relation.description ? `（${relation.description}）` : ''
    }`;

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'tree__delete';
    remove.textContent = '✕';
    remove.title = '删除这条关系';
    remove.setAttribute('aria-label', '删除阵营关系');
    remove.addEventListener('click', () => {
      deleteFactionRelation(relation).catch((error) => log.error(error));
    });

    row.append(text, remove);
    root.append(row);
  }

  fillSelect(
    el('faction-rel-from'),
    state.factions.map((item) => ({ value: item.id, label: item.name })),
    { value: state.currentFaction ? state.currentFaction.id : '' },
  );
  fillSelect(
    el('faction-rel-to'),
    state.factions
      .filter(
        (item) => !state.currentFaction || item.id !== state.currentFaction.id,
      )
      .map((item) => ({ value: item.id, label: item.name })),
    { allLabel: '选择阵营', value: '' },
  );
}

async function saveFaction() {
  if (!state.currentFaction) {
    return;
  }
  setStatus('faction-status', '保存中…');
  try {
    await request(`/api/factions/${state.currentFaction.id}`, {
      method: 'PATCH',
      body: {
        name: el('faction-name').value.trim(),
        color: el('faction-color').value,
        description: el('faction-description').value.trim() || null,
      },
    });
    await loadFactions();
    setStatus('faction-status', '已保存', 'ok');
  } catch (error) {
    setStatus('faction-status', errorMessage(error), 'error');
  }
}

async function createFaction() {
  const name = await askText({ title: '新建阵营', label: '阵营名称' });
  if (!name) {
    return;
  }
  try {
    await request(`/api/projects/${projectId()}/factions`, {
      method: 'POST',
      body: { name },
    });
    state.currentFaction = null;
    await loadFactions();
    setStatus('faction-status', '已创建', 'ok');
  } catch (error) {
    setStatus('faction-status', errorMessage(error), 'error');
  }
}

async function deleteFaction() {
  if (!state.currentFaction) {
    return;
  }
  const confirmed = window.confirm(
    `删除阵营「${state.currentFaction.name}」？\n若下面还有组织，需要先迁移或改为中立。`,
  );
  if (!confirmed) {
    return;
  }
  try {
    await request(`/api/factions/${state.currentFaction.id}`, {
      method: 'DELETE',
    });
    state.currentFaction = null;
    await loadFactions();
    setStatus('faction-status', '已删除', 'ok');
  } catch (error) {
    setStatus('faction-status', errorMessage(error), 'error');
  }
}

async function addFactionRelation() {
  const fromId = el('faction-rel-from').value;
  const toId = el('faction-rel-to').value;
  if (!fromId || !toId) {
    setError('faction-error', '请选择两个阵营');
    return;
  }
  if (fromId === toId) {
    setError('faction-error', '不能和自己建立关系');
    return;
  }
  try {
    await request(`/api/projects/${projectId()}/faction-relations`, {
      method: 'POST',
      body: {
        from_id: Number(fromId),
        to_id: Number(toId),
        relation_type: el('faction-rel-type').value,
        description: el('faction-rel-description').value.trim() || null,
      },
    });
    el('faction-rel-description').value = '';
    setError('faction-error', '');
    await loadFactions();
    setStatus('faction-status', '已添加关系', 'ok');
  } catch (error) {
    setError('faction-error', errorMessage(error));
    setStatus('faction-status', errorMessage(error), 'error');
  }
}

async function deleteFactionRelation(relation) {
  try {
    await request(`/api/faction-relations/${relation.id}`, {
      method: 'DELETE',
    });
    await loadFactions();
    setStatus('faction-status', '已删除关系', 'ok');
  } catch (error) {
    setStatus('faction-status', errorMessage(error), 'error');
  }
}

// --------------------------------------------------------------------------
// 对外
// --------------------------------------------------------------------------

async function openOrganizations() {
  const pid = projectId();
  if (!pid) {
    return;
  }
  try {
    await loadShared();
    await loadFactions();
    await loadOrgTree();
    if (state.currentOrg && state.byId.has(state.currentOrg.id)) {
      await selectOrg(state.currentOrg.id);
    } else if (state.flat.length) {
      await selectOrg(state.flat[0].id);
    } else {
      state.currentOrg = null;
      el('organization-detail').hidden = true;
      el('organization-empty').hidden = false;
    }
  } catch (error) {
    log.error(error);
    setStatus('org-status', errorMessage(error), 'error');
  }
}

async function openFactions() {
  if (!projectId()) {
    return;
  }
  try {
    await loadShared();
    await loadFactions();
  } catch (error) {
    log.error(error);
    setStatus('faction-status', errorMessage(error), 'error');
  }
}

export function initOrganizations() {
  el('add-root-org').addEventListener('click', () => {
    createOrg(false).catch((error) => log.error(error));
  });
  el('add-child-org').addEventListener('click', () => {
    createOrg(true).catch((error) => log.error(error));
  });
  el('save-org').addEventListener('click', () => {
    saveOrg().catch((error) => log.error(error));
  });
  el('move-org-up').addEventListener('click', () => {
    moveOrgUp().catch((error) => log.error(error));
  });
  el('delete-org').addEventListener('click', () => openDeleteDialog());
  el('org-delete-dialog').addEventListener('close', (event) => {
    confirmDeleteOrg(event).catch((error) => log.error(error));
  });
  el('add-member').addEventListener('click', () => {
    addMember().catch((error) => log.error(error));
  });

  // 拖到树空白处 = 变顶级
  const tree = el('organization-tree');
  tree.addEventListener('dragover', (event) => {
    event.preventDefault();
    tree.classList.add('is-drop-root');
  });
  tree.addEventListener('dragleave', () => tree.classList.remove('is-drop-root'));
  tree.addEventListener('drop', (event) => {
    tree.classList.remove('is-drop-root');
    const dragged = Number(event.dataTransfer.getData('text/plain'));
    if (!dragged) {
      return;
    }
    event.preventDefault();
    reparent(dragged, null).catch((error) =>
      setStatus('org-status', errorMessage(error), 'error'),
    );
  });

  el('add-faction').addEventListener('click', () => {
    createFaction().catch((error) => log.error(error));
  });
  el('save-faction').addEventListener('click', () => {
    saveFaction().catch((error) => log.error(error));
  });
  el('delete-faction').addEventListener('click', () => {
    deleteFaction().catch((error) => log.error(error));
  });
  el('add-faction-relation').addEventListener('click', () => {
    addFactionRelation().catch((error) => log.error(error));
  });

  window.addEventListener('inkwell:character-tab', (event) => {
    const tab = event.detail ? event.detail.tab : '';
    if (tab === 'organizations') {
      openOrganizations().catch((error) => log.error(error));
    } else if (tab === 'factions') {
      openFactions().catch((error) => log.error(error));
    }
  });
}
