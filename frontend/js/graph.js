/** 关系图大画布：人物 / 组织 / 阵营三种模式（V2.0 / 5.7 + 5.8）。
 *
 * 布局：
 *   · 人物——简化 FR 力导向（300 轮分帧）
 *   · 组织——层级树（根上子下，父居中，从属折线）
 *   · 阵营——立场围圈，组织绕各自阵营
 *
 * 入口由 `inkwell:open-graph` 事件触发（characters / relations 派发），
 * 图模块单向依赖 `characters.js` 的 `openCharacterCard`。
 */

import { request } from './api.js';
import { getCurrentProject, openCharacterCard } from './characters.js';
import {
  circlePositions,
  clusterLayout,
  forceIteration,
  nodeRadius,
  orgFill,
  treeLayout,
} from './graph-layout.js';
import { createLogger } from './logger.js';
import { el, setContext, showView } from './view.js';

const log = createLogger('graph');

const WORLD = { width: 1200, height: 800 };
const SIMULATION_ITERATIONS = 300;
const SIMULATION_CHUNK = 15;
const SAVE_DEBOUNCE_MS = 600;

const MODE_TITLES = {
  character: '人物关系图',
  organization: '组织层级树',
  faction: '阵营全景',
};

const ROLE_COLORS = {
  protagonist: '#6b5b49',
  heroine: '#a04e5c',
  supporting: '#4a6473',
  antagonist: '#b84f36',
  extra: '#6b6b6b',
  other: '#7a6e5e',
};

const FAMILY_COLORS = {
  master: '#8a6d1f',
  kin: '#b87333',
  friend: '#4f7a5b',
  enemy: '#b84f36',
  other: '#8a8378',
};

const ORG_REL_COLORS = {
  vassal: '#8a8378',
  ally: '#3b6ea5',
  enemy: '#b84f36',
  war: '#7a2f22',
  neutral: '#6e6e6e',
};

const FACTION_REL_COLORS = {
  ally: '#4f7a5b',
  enemy: '#b84f36',
  neutral: '#6e6e6e',
  vassal: '#8a8378',
};

const state = {
  project: null,
  mode: 'character',
  centerId: null,
  meta: null,
  nodes: [],
  edges: [],
  groups: [],
  positions: new Map(),
  edgeStyles: new Map(),
  hidden: new Set(),
  selectedId: null,
  zoom: { k: 1, x: 0, y: 0 },
  views: {
    character: { k: 1, x: 0, y: 0 },
    organization: { k: 1, x: 0, y: 0 },
    faction: { k: 1, x: 0, y: 0 },
  },
  truncated: false,
  total: 0,
  layoutStamp: null,
  simFrame: 0,
  simIteration: 0,
  simPositions: [],
  simEdges: [],
  saveTimer: 0,
  menuNodeId: null,
  drag: null,
  panning: null,
  loaded: false,
  loadToken: 0,
  showLabels: true,
  labelOffsets: new Map(),
};

const dom = {};

// --------------------------------------------------------------------------
// 基础
// --------------------------------------------------------------------------

function setStatus(text, kind = '') {
  if (!dom.status) {
    return;
  }
  dom.status.textContent = text;
  dom.status.className = `writer__status${kind ? ` is-${kind}` : ''}`;
}

function visibleNodes() {
  return state.nodes.filter((node) => !state.hidden.has(node.id));
}

function visibleEdges() {
  const ids = new Set(visibleNodes().map((node) => node.id));
  return state.edges.filter(
    (edge) => ids.has(Number(edge.from)) && ids.has(Number(edge.to)),
  );
}

function createSvg(name, attrs = {}) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', name);
  for (const [key, value] of Object.entries(attrs)) {
    node.setAttribute(key, String(value));
  }
  return node;
}

function familyOf(relationType) {
  if (!state.meta) {
    return 'other';
  }
  const hit = state.meta.relation_types.find(
    (item) => item.value === relationType,
  );
  return hit ? hit.family : 'other';
}

function roleLabel(role) {
  if (!state.meta) {
    return role;
  }
  const hit = state.meta.roles.find((item) => item.value === role);
  return hit ? hit.label : role;
}

function orgKindLabel(kind) {
  if (!state.meta) {
    return kind;
  }
  const hit = state.meta.organization_kinds.find((item) => item.value === kind);
  return hit ? hit.label : kind;
}

function nodeLabel(node) {
  if (node.kind === 'character') {
    return roleLabel(node.role);
  }
  if (node.kind === 'faction') {
    return '阵营';
  }
  return orgKindLabel(node.kind_label || node.kind);
}

function clip(text, max) {
  const chars = Array.from(String(text || ''));
  return chars.length > max ? `${chars.slice(0, max).join('')}…` : text;
}

function markerId(color) {
  return `graph-arrow-${String(color).replace('#', '')}`;
}

/** 边 id 只在各自表内自增，跨类型会撞号；DOM 映射统一用「类型:id」。 */
function edgeKey(edge) {
  return `${edge.kind}:${edge.id}`;
}

function optionLabel(list, value) {
  if (!state.meta || !list) {
    return value;
  }
  const hit = list.find((item) => item.value === value);
  return hit ? hit.label : value;
}

/** 线上的关系名：只给「语义关系」加字，结构线（从属 / 归属）不加。 */
function edgeLabel(edge) {
  if (state.mode === 'character') {
    return (
      edge.label || optionLabel(state.meta.relation_types, edge.type)
    );
  }
  if (state.mode === 'organization') {
    if (edge.kind !== 'org_relation') {
      return null;
    }
    return optionLabel(state.meta.organization_relation_types, edge.type);
  }
  if (edge.kind === 'faction_relation') {
    return optionLabel(state.meta.faction_relation_types, edge.type);
  }
  if (edge.kind === 'org_relation') {
    return optionLabel(state.meta.organization_relation_types, edge.type);
  }
  return null;
}

/** 同一对节点之间可能有多条线：给文字加垂直偏移，避免叠在一起。 */
function labelOffsetsFor(edges) {
  const groups = new Map();
  for (const edge of edges) {
    if (!edgeLabel(edge)) {
      continue;
    }
    const pair = [Number(edge.from), Number(edge.to)]
      .sort((a, b) => a - b)
      .join('-');
    if (!groups.has(pair)) {
      groups.set(pair, []);
    }
    groups.get(pair).push(edge);
  }
  const offsets = new Map();
  for (const list of groups.values()) {
    list.forEach((edge, index) => {
      offsets.set(edgeKey(edge), (index - (list.length - 1) / 2) * 14);
    });
  }
  return offsets;
}

function applyLabelVisibility() {
  if (dom.labelsLayer) {
    dom.labelsLayer.style.display = state.showLabels ? '' : 'none';
  }
  if (dom.labelsButton) {
    dom.labelsButton.setAttribute(
      'aria-pressed',
      state.showLabels ? 'true' : 'false',
    );
  }
}

// --------------------------------------------------------------------------
// 边样式
// --------------------------------------------------------------------------

function edgeStyle(edge) {
  if (state.mode === 'character') {
    const family = familyOf(edge.type);
    return {
      color: FAMILY_COLORS[family] || FAMILY_COLORS.other,
      dash: Boolean(edge.secret),
      arrow: !edge.bidirectional,
      elbow: false,
    };
  }
  if (state.mode === 'organization') {
    if (edge.kind === 'org_parent') {
      return { color: '#9a9388', dash: false, arrow: true, elbow: true };
    }
    return {
      color: ORG_REL_COLORS[edge.type] || ORG_REL_COLORS.vassal,
      dash: edge.type === 'neutral',
      arrow: !edge.bidirectional,
      elbow: false,
    };
  }
  // 阵营模式
  if (edge.kind === 'membership') {
    return { color: '#cfc9bf', dash: false, arrow: false, elbow: false };
  }
  if (edge.kind === 'faction_relation') {
    return {
      color: FACTION_REL_COLORS[edge.type] || FACTION_REL_COLORS.vassal,
      dash: edge.type === 'enemy' || edge.type === 'neutral',
      arrow: edge.type === 'vassal',
      elbow: false,
    };
  }
  return {
    color: ORG_REL_COLORS[edge.type] || ORG_REL_COLORS.vassal,
    dash: edge.type === 'neutral',
    arrow: !edge.bidirectional,
    elbow: false,
  };
}

// --------------------------------------------------------------------------
// 渲染
// --------------------------------------------------------------------------

function renderGraph() {
  const svg = dom.svg;
  if (!svg) {
    return;
  }
  svg.textContent = '';

  const styles = new Map();
  const colors = new Set();
  for (const edge of visibleEdges()) {
    const style = edgeStyle(edge);
    styles.set(edgeKey(edge), style);
    if (style.arrow) {
      colors.add(style.color);
    }
  }
  state.edgeStyles = styles;

  const defs = createSvg('defs');
  for (const color of colors) {
    const marker = createSvg('marker', {
      id: markerId(color),
      viewBox: '0 0 10 10',
      refX: 9,
      refY: 5,
      markerWidth: 8,
      markerHeight: 8,
      orient: 'auto',
    });
    const path = createSvg('path', { d: 'M0,0 L10,5 L0,10 z' });
    path.style.fill = color;
    marker.append(path);
    defs.append(marker);
  }
  svg.append(defs);

  const viewport = createSvg('g', { class: 'graph-viewport' });
  svg.append(viewport);
  dom.viewport = viewport;

  dom.edgeEls = new Map();
  for (const edge of visibleEdges()) {
    const style = styles.get(edgeKey(edge));
    const path = createSvg('path', { class: 'graph-edge' });
    path.style.stroke = style.color;
    if (style.dash) {
      path.style.strokeDasharray = '6 4';
    }
    if (style.arrow) {
      path.setAttribute('marker-end', `url(#${markerId(style.color)})`);
    }
    if (edge.secret) {
      path.classList.add('is-secret');
    }
    viewport.append(path);
    dom.edgeEls.set(edgeKey(edge), path);
  }

  // 关系名直接标在线的中间：不依赖颜色，色觉障碍用户也能读
  state.labelOffsets = labelOffsetsFor(visibleEdges());
  const labelsLayer = createSvg('g', { class: 'graph-edge-labels' });
  dom.labelsLayer = labelsLayer;
  dom.edgeLabelEls = new Map();
  for (const edge of visibleEdges()) {
    const label = edgeLabel(edge);
    if (!label) {
      continue;
    }
    const text = createSvg('text', {
      class: 'graph-edge-label',
      'text-anchor': 'middle',
    });
    text.textContent = edge.secret ? `${clip(label, 8)} · 秘` : clip(label, 8);
    labelsLayer.append(text);
    dom.edgeLabelEls.set(edgeKey(edge), text);
  }
  viewport.append(labelsLayer);

  const nodesLayer = createSvg('g', { class: 'graph-nodes' });
  viewport.append(nodesLayer);
  dom.nodeEls = new Map();
  dom.nodeLayer = nodesLayer;
  for (const node of visibleNodes()) {
    const group = renderNode(node);
    nodesLayer.append(group);
    dom.nodeEls.set(String(node.id), group);
  }

  updatePositions();
  applyZoom();
  updateEmpty();
  renderLegend();
  applyLabelVisibility();
}

function renderNode(node) {
  const group = createSvg('g', {
    class: 'graph-node',
    'data-id': String(node.id),
    role: 'button',
    tabindex: 0,
    'aria-label': `${node.name}（${nodeLabel(node)}）`,
  });

  const title = createSvg('title');
  title.textContent =
    node.kind === 'organization'
      ? `${node.name} · ${orgKindLabel(node.kind_label || node.kind)} · ${node.member_count || 0} 人`
      : `${node.name} · ${nodeLabel(node)}`;
  group.append(title);

  if (node.kind === 'character') {
    const circle = createSvg('circle', { r: nodeRadius(node.role) });
    circle.style.fill = orgFill(node.org_color, node.org_id);
    circle.style.stroke = ROLE_COLORS[node.role] || ROLE_COLORS.other;
    const text = createSvg('text', { 'text-anchor': 'middle', dy: '0.35em' });
    text.textContent = Array.from(node.name || '?')[0];
    group.append(circle, text);
  } else if (node.kind === 'faction') {
    const rect = createSvg('rect', {
      x: -92,
      y: -38,
      width: 184,
      height: 76,
      rx: 14,
    });
    rect.style.fill = node.color || '#b8b0a4';
    rect.style.fillOpacity = '0.16';
    rect.style.stroke = node.color || '#8a8378';
    const name = createSvg('text', { 'text-anchor': 'middle', y: -4 });
    name.classList.add('graph-node__title');
    name.textContent = clip(node.name, 8);
    const sub = createSvg('text', { 'text-anchor': 'middle', y: 20 });
    sub.classList.add('graph-node__sub');
    sub.textContent = `${(node.member_ids || []).length} 个组织`;
    group.append(rect, name, sub);
  } else {
    const rect = createSvg('rect', {
      x: -78,
      y: -24,
      width: 156,
      height: 48,
      rx: 10,
    });
    rect.style.fill = orgFill(node.color, node.id);
    const factionColor = factionColorOf(node.faction_id);
    rect.style.stroke = factionColor || '#9a9388';
    const name = createSvg('text', { 'text-anchor': 'middle', y: -2 });
    name.classList.add('graph-node__title');
    name.textContent = clip(node.name, 7);
    const sub = createSvg('text', { 'text-anchor': 'middle', y: 16 });
    sub.classList.add('graph-node__sub');
    sub.textContent = `${orgKindLabel(node.kind_label || node.kind)} · ${node.member_count || 0} 人`;
    group.append(rect, name, sub);
  }

  if (state.selectedId === node.id) {
    group.classList.add('is-selected');
  }
  return group;
}

function factionColorOf(factionId) {
  if (factionId === null || factionId === undefined) {
    return null;
  }
  const hit = (state.groups || []).find(
    (group) => Number(group.id) === Number(factionId),
  );
  return hit && hit.color ? hit.color : null;
}

function nodeBoundary(node, ux, uy) {
  if (!node || node.kind === 'character') {
    return nodeRadius(node ? node.role : 'other') + 2;
  }
  const halfWidth = node.kind === 'faction' ? 92 : 78;
  const halfHeight = node.kind === 'faction' ? 38 : 24;
  const tx = Math.abs(ux) < 1e-6 ? Infinity : halfWidth / Math.abs(ux);
  const ty = Math.abs(uy) < 1e-6 ? Infinity : halfHeight / Math.abs(uy);
  return Math.min(tx, ty) + 2;
}

function updatePositions() {
  if (!dom.nodeEls) {
    return;
  }
  for (const [id, group] of dom.nodeEls) {
    const position = state.positions.get(Number(id));
    if (!position) {
      continue;
    }
    group.setAttribute(
      'transform',
      `translate(${position.x.toFixed(2)} ${position.y.toFixed(2)})`,
    );
  }

  const nodeById = new Map(state.nodes.map((node) => [node.id, node]));
  for (const edge of visibleEdges()) {
    const path = dom.edgeEls.get(edgeKey(edge));
    const style = state.edgeStyles.get(edgeKey(edge));
    const from = state.positions.get(Number(edge.from));
    const to = state.positions.get(Number(edge.to));
    if (!path || !from || !to) {
      continue;
    }
    const fromNode = nodeById.get(Number(edge.from));
    const toNode = nodeById.get(Number(edge.to));
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const distance = Math.hypot(dx, dy) || 1;
    const ux = dx / distance;
    const uy = dy / distance;
    const x1 = from.x + ux * nodeBoundary(fromNode, ux, uy);
    const y1 = from.y + uy * nodeBoundary(fromNode, ux, uy);
    const x2 = to.x - ux * nodeBoundary(toNode, ux, uy);
    const y2 = to.y - uy * nodeBoundary(toNode, ux, uy);

    const label = dom.edgeLabelEls
      ? dom.edgeLabelEls.get(edgeKey(edge))
      : null;
    if (label) {
      const shift = state.labelOffsets.get(edgeKey(edge)) || 0;
      label.setAttribute(
        'x',
        ((x1 + x2) / 2 - uy * shift).toFixed(2),
      );
      label.setAttribute(
        'y',
        ((y1 + y2) / 2 + ux * shift + 3).toFixed(2),
      );
    }

    if (style && style.elbow && to.y > from.y + 30) {
      const midY = (y1 + y2) / 2;
      path.setAttribute(
        'd',
        `M ${x1.toFixed(2)} ${y1.toFixed(2)} L ${x1.toFixed(2)} ${midY.toFixed(
          2,
        )} L ${x2.toFixed(2)} ${midY.toFixed(2)} L ${x2.toFixed(2)} ${y2.toFixed(
          2,
        )}`,
      );
    } else {
      path.setAttribute(
        'd',
        `M ${x1.toFixed(2)} ${y1.toFixed(2)} L ${x2.toFixed(2)} ${y2.toFixed(2)}`,
      );
    }
  }
}

function applyZoom() {
  if (!dom.viewport) {
    return;
  }
  const { k, x, y } = state.zoom;
  dom.viewport.setAttribute(
    'transform',
    `translate(${x.toFixed(2)} ${y.toFixed(2)}) scale(${k.toFixed(3)})`,
  );
}

function updateEmpty() {
  const empty = state.nodes.length === 0;
  dom.empty.hidden = !empty;
  dom.svg.style.visibility = empty ? 'hidden' : 'visible';
  if (empty) {
    dom.empty.textContent =
      state.mode === 'character'
        ? '这本书还没有角色关系。先回角色库建几个角色、加两条关系。'
        : state.mode === 'organization'
          ? '还没有组织。先回角色库的「组织」页建一个。'
          : '还没有阵营。先回角色库的「阵营」页建一个。';
  }
}

function renderLegend() {
  if (!dom.legend) {
    return;
  }
  const items = [];
  const add = (color, label, dashed = false) => {
    items.push({ color, label, dashed });
  };
  if (state.mode === 'character') {
    add(FAMILY_COLORS.master, '师承');
    add(FAMILY_COLORS.kin, '血亲');
    add(FAMILY_COLORS.friend, '友');
    add(FAMILY_COLORS.enemy, '敌');
    add(FAMILY_COLORS.other, '其他');
    add(null, '隐秘', true);
    items.push({ text: '→ 单向 · — 双向' });
  } else if (state.mode === 'organization') {
    add('#9a9388', '从属');
    add(ORG_REL_COLORS.vassal, '附庸');
    add(ORG_REL_COLORS.ally, '结盟');
    add(ORG_REL_COLORS.enemy, '敌对');
    add(ORG_REL_COLORS.war, '战争');
    add(ORG_REL_COLORS.neutral, '中立', true);
  } else {
    add(FACTION_REL_COLORS.ally, '结盟');
    add(FACTION_REL_COLORS.enemy, '敌对', true);
    add(FACTION_REL_COLORS.neutral, '中立', true);
    add(FACTION_REL_COLORS.vassal, '从属');
    add('#cfc9bf', '组织归属');
  }
  dom.legend.textContent = '';
  for (const item of items) {
    const span = document.createElement('span');
    span.className = 'graph-legend__item';
    if (item.text) {
      span.textContent = item.text;
    } else {
      const swatch = document.createElement('i');
      if (item.dashed) {
        swatch.className = 'is-dash';
        swatch.style.borderColor = item.color || 'var(--text-2)';
      } else {
        swatch.style.background = item.color;
      }
      span.append(swatch, document.createTextNode(item.label));
    }
    dom.legend.append(span);
  }
}

// --------------------------------------------------------------------------
// 布局
// --------------------------------------------------------------------------

function startSimulation({ save = true } = {}) {
  window.cancelAnimationFrame(state.simFrame);
  const nodes = visibleNodes();
  const ids = new Set(nodes.map((node) => node.id));
  state.simPositions = nodes.map((node) => {
    const position = state.positions.get(node.id) || {
      x: WORLD.width / 2,
      y: WORLD.height / 2,
    };
    return {
      id: node.id,
      x: position.x,
      y: position.y,
      pinned: Boolean(position.pinned),
    };
  });
  state.simEdges = state.edges
    .filter(
      (edge) => ids.has(Number(edge.from)) && ids.has(Number(edge.to)),
    )
    .map((edge) => ({ from: Number(edge.from), to: Number(edge.to) }));
  state.simIteration = 0;
  setStatus('布局计算中…');

  const tick = () => {
    const limit = Math.min(
      SIMULATION_ITERATIONS,
      state.simIteration + SIMULATION_CHUNK,
    );
    while (state.simIteration < limit) {
      forceIteration(state.simPositions, state.simEdges, {
        width: WORLD.width,
        height: WORLD.height,
        iteration: state.simIteration,
        total: SIMULATION_ITERATIONS,
        padding: 70,
      });
      state.simIteration += 1;
    }
    for (const item of state.simPositions) {
      state.positions.set(item.id, {
        x: item.x,
        y: item.y,
        pinned: item.pinned,
      });
    }
    updatePositions();
    if (state.simIteration < SIMULATION_ITERATIONS) {
      state.simFrame = window.requestAnimationFrame(tick);
      return;
    }
    fit();
    updateStatus();
    if (save) {
      scheduleSave(0);
    }
  };
  tick();
}

function computeStaticLayout() {
  if (state.mode === 'organization') {
    return treeLayout(state.nodes, state.edges, {
      width: WORLD.width,
      paddingY: 90,
      levelHeight: 130,
    });
  }
  const factions = state.nodes.filter((node) => node.kind === 'faction');
  const organizations = state.nodes.filter(
    (node) => node.kind === 'organization',
  );
  // 阵营节点 id 带偏移（与组织消歧），组织身上的 faction_id 仍是原始库 id
  const factionIdByRaw = new Map(
    factions.map((node) => [
      Number(String(node.key).split(':')[1]),
      node.id,
    ]),
  );
  const resolvedOrganizations = organizations.map((node) => ({
    ...node,
    faction_id:
      factionIdByRaw.get(Number(node.faction_id)) ?? null,
  }));
  return clusterLayout(factions, resolvedOrganizations, {
    width: WORLD.width,
    height: WORLD.height,
    radius: 250,
    innerRadius: 130,
  });
}

function fit() {
  const nodes = visibleNodes()
    .map((node) => state.positions.get(node.id))
    .filter(Boolean);
  if (!nodes.length || !dom.canvas) {
    return;
  }
  const xs = nodes.map((item) => item.x);
  const ys = nodes.map((item) => item.y);
  const minX = Math.min(...xs) - 80;
  const maxX = Math.max(...xs) + 80;
  const minY = Math.min(...ys) - 80;
  const maxY = Math.max(...ys) + 120;
  const canvas = dom.canvas.getBoundingClientRect();
  const k = Math.max(
    0.25,
    Math.min(canvas.width / (maxX - minX), canvas.height / (maxY - minY), 1.8),
  );
  state.zoom.k = k;
  state.zoom.x = canvas.width / 2 - ((minX + maxX) / 2) * k;
  state.zoom.y = canvas.height / 2 - ((minY + maxY) / 2) * k;
  applyZoom();
}

function restoreView() {
  const saved = state.views[state.mode];
  if (saved && (saved.k !== 1 || saved.x !== 0 || saved.y !== 0)) {
    state.zoom = { ...saved };
    applyZoom();
  } else {
    fit();
  }
}

function updateStatus() {
  const nodes = visibleNodes();
  const edges = visibleEdges().length;
  if (state.mode === 'character') {
    setStatus(`${nodes.length} 个角色 · ${edges} 条关系`);
  } else if (state.mode === 'organization') {
    setStatus(`${nodes.length} 个组织 · ${edges} 条连线`);
  } else {
    const factions = nodes.filter((node) => node.kind === 'faction').length;
    const organizations = nodes.length - factions;
    setStatus(`${factions} 个阵营 / ${organizations} 个组织 · ${edges} 条连线`);
  }
  if (state.truncated) {
    dom.banner.hidden = false;
    dom.banner.textContent = `只显示前 ${state.nodes.length} 个节点（共 ${state.total} 个）。想看清局部，先在角色卡里点「在图中查看」。`;
  } else {
    dom.banner.hidden = true;
  }
}

// --------------------------------------------------------------------------
// 交互
// --------------------------------------------------------------------------

function screenToWorld(clientX, clientY) {
  const rect = dom.canvas.getBoundingClientRect();
  return {
    x: (clientX - rect.left - state.zoom.x) / state.zoom.k,
    y: (clientY - rect.top - state.zoom.y) / state.zoom.k,
  };
}

function nodeIdFromEvent(event) {
  const group = event.target.closest
    ? event.target.closest('.graph-node')
    : null;
  return group ? Number(group.dataset.id) : null;
}

function onPointerDown(event) {
  if (event.button !== 0) {
    return;
  }
  hideMenu();
  const nodeId = nodeIdFromEvent(event);
  if (nodeId !== null) {
    const position = state.positions.get(nodeId);
    if (!position) {
      return;
    }
    const world = screenToWorld(event.clientX, event.clientY);
    state.drag = {
      id: nodeId,
      offsetX: position.x - world.x,
      offsetY: position.y - world.y,
      moved: false,
    };
    window.cancelAnimationFrame(state.simFrame);
    event.preventDefault();
    dom.svg.setPointerCapture?.(event.pointerId);
    return;
  }
  state.panning = {
    startX: event.clientX,
    startY: event.clientY,
    originX: state.zoom.x,
    originY: state.zoom.y,
  };
  dom.svg.classList.add('is-panning');
}

function onPointerMove(event) {
  if (state.drag) {
    const world = screenToWorld(event.clientX, event.clientY);
    const position = state.positions.get(state.drag.id);
    if (!position) {
      return;
    }
    position.x = Math.min(
      WORLD.width - 20,
      Math.max(20, world.x + state.drag.offsetX),
    );
    position.y = Math.min(
      WORLD.height - 20,
      Math.max(20, world.y + state.drag.offsetY),
    );
    position.pinned = true;
    state.drag.moved = true;
    updatePositions();
    return;
  }
  if (state.panning) {
    state.zoom.x =
      state.panning.originX + (event.clientX - state.panning.startX);
    state.zoom.y =
      state.panning.originY + (event.clientY - state.panning.startY);
    applyZoom();
  }
}

function onPointerUp() {
  if (state.drag) {
    if (state.drag.moved) {
      scheduleSave();
    } else {
      selectNode(state.drag.id);
    }
    state.drag = null;
  }
  if (state.panning) {
    state.panning = null;
    dom.svg.classList.remove('is-panning');
  }
}

function onWheel(event) {
  event.preventDefault();
  const rect = dom.canvas.getBoundingClientRect();
  const px = event.clientX - rect.left;
  const py = event.clientY - rect.top;
  const previous = state.zoom.k;
  const factor = event.deltaY < 0 ? 1.12 : 0.9;
  const next = Math.min(3, Math.max(0.25, previous * factor));
  state.zoom.x = px - ((px - state.zoom.x) / previous) * next;
  state.zoom.y = py - ((py - state.zoom.y) / previous) * next;
  state.zoom.k = next;
  applyZoom();
}

function selectNode(nodeId) {
  state.selectedId = nodeId;
  for (const [id, group] of dom.nodeEls || []) {
    group.classList.toggle('is-selected', Number(id) === nodeId);
  }
  const node = state.nodes.find((item) => item.id === nodeId);
  if (node) {
    setStatus(`已选：${node.name} · ${nodeLabel(node)}`);
  }
}

function showMenu(event, nodeId) {
  state.menuNodeId = nodeId;
  const isCharacter = state.mode === 'character';
  for (const button of dom.menu.querySelectorAll('button')) {
    if (button.dataset.action === 'center' || button.dataset.action === 'open') {
      button.hidden = !isCharacter;
    }
  }
  dom.menu.hidden = false;
  const rect = dom.canvas.getBoundingClientRect();
  const menuRect = dom.menu.getBoundingClientRect();
  const left = Math.min(
    event.clientX - rect.left,
    rect.width - menuRect.width - 8,
  );
  const top = Math.min(
    event.clientY - rect.top,
    rect.height - menuRect.height - 8,
  );
  dom.menu.style.left = `${Math.max(8, left)}px`;
  dom.menu.style.top = `${Math.max(8, top)}px`;
}

function hideMenu() {
  dom.menu.hidden = true;
  state.menuNodeId = null;
}

function onContextMenu(event) {
  const nodeId = nodeIdFromEvent(event);
  if (nodeId === null) {
    return;
  }
  event.preventDefault();
  selectNode(nodeId);
  showMenu(event, nodeId);
}

function onMenuClick(event) {
  const action = event.target.dataset ? event.target.dataset.action : null;
  if (!action || state.menuNodeId === null) {
    return;
  }
  const nodeId = state.menuNodeId;
  hideMenu();
  if (action === 'center') {
    enterMode('character', { centerId: nodeId }).catch((error) =>
      log.error(error),
    );
  } else if (action === 'open') {
    openCharacterCard(nodeId).catch((error) => log.error(error));
  } else if (action === 'hide') {
    state.hidden.add(nodeId);
    renderGraph();
    fit();
    updateStatus();
  }
}

function onDoubleClick(event) {
  if (state.mode !== 'character') {
    return;
  }
  const nodeId = nodeIdFromEvent(event);
  if (nodeId !== null) {
    openCharacterCard(nodeId).catch((error) => log.error(error));
  }
}

// --------------------------------------------------------------------------
// 布局保存
// --------------------------------------------------------------------------

function scheduleSave(delay = SAVE_DEBOUNCE_MS) {
  window.clearTimeout(state.saveTimer);
  state.saveTimer = window.setTimeout(() => {
    saveLayout().catch((error) => log.error(error));
  }, delay);
}

async function saveLayout() {
  if (!state.project) {
    return;
  }
  const positions = {};
  for (const node of state.nodes) {
    const position = state.positions.get(node.id);
    if (!position) {
      continue;
    }
    positions[node.key] = {
      x: Math.round(position.x * 100) / 100,
      y: Math.round(position.y * 100) / 100,
      pinned: Boolean(position.pinned),
    };
  }
  try {
    const saved = await request(
      `/api/projects/${state.project.id}/graph/layout`,
      {
        method: 'PUT',
        body: {
          payload: { [state.mode]: positions },
          expected_updated_at: state.layoutStamp,
        },
      },
    );
    state.layoutStamp = saved.updated_at;
  } catch (error) {
    const text = (error && error.message) || '';
    if (text.includes('3002')) {
      setStatus('布局已在别处更新，本次改动未保存', 'error');
      return;
    }
    throw error;
  }
}

// --------------------------------------------------------------------------
// 加载与模式
// --------------------------------------------------------------------------

async function loadMeta() {
  if (!state.project) {
    return;
  }
  if (state.meta && state.meta.__project === state.project.id) {
    return;
  }
  const meta = await request(
    `/api/projects/${state.project.id}/characters/meta`,
  );
  meta.__project = state.project.id;
  state.meta = meta;
}

async function loadGraph() {
  const project = state.project;
  if (!project) {
    return;
  }
  const token = (state.loadToken += 1);
  setStatus('加载中…');
  window.cancelAnimationFrame(state.simFrame);
  await loadMeta();

  const params = new URLSearchParams({
    mode: state.mode,
    limit: '80',
  });
  if (state.mode === 'character' && state.centerId) {
    params.set('center_id', String(state.centerId));
    params.set('depth', '2');
  }
  const [data, layout] = await Promise.all([
    request(`/api/projects/${project.id}/graph?${params.toString()}`),
    request(`/api/projects/${project.id}/graph/layout`),
  ]);
  if (token !== state.loadToken) {
    return;
  }

  state.nodes = (data.nodes || []).map((node) => ({
    ...node,
    id: Number(node.id),
  }));
  state.edges = (data.edges || []).map((edge) => ({
    ...edge,
    from: Number(edge.from),
    to: Number(edge.to),
    id: String(edge.id),
  }));
  state.groups = data.groups || [];
  state.truncated = Boolean(data.truncated);
  state.total = Number(data.total_nodes) || state.nodes.length;
  state.layoutStamp = layout.updated_at || null;
  state.selectedId = null;
  state.hidden.clear();

  const saved = (layout.payload && layout.payload[state.mode]) || {};
  state.positions = new Map();
  for (const node of state.nodes) {
    const position = saved[node.key];
    if (position && Number.isFinite(position.x) && Number.isFinite(position.y)) {
      state.positions.set(node.id, {
        x: position.x,
        y: position.y,
        pinned: Boolean(position.pinned),
      });
    }
  }

  let needsSimulation = false;
  if (state.mode === 'character') {
    const missing = state.nodes.filter(
      (node) => !state.positions.has(node.id),
    );
    if (missing.length) {
      const initial = circlePositions(missing, {
        width: WORLD.width,
        height: WORLD.height,
      });
      for (const item of initial) {
        state.positions.set(item.id, {
          x: item.x,
          y: item.y,
          pinned: false,
        });
      }
      needsSimulation = state.positions.size > 1;
    }
  } else {
    const computed = computeStaticLayout();
    for (const [id, position] of computed) {
      if (!state.positions.has(id)) {
        state.positions.set(id, { ...position, pinned: false });
      }
    }
  }

  state.loaded = true;
  renderGraph();
  if (needsSimulation) {
    startSimulation();
  } else {
    restoreView();
    updateStatus();
  }
}

function updateModeTabs() {
  for (const button of dom.modes.querySelectorAll('.graph-mode')) {
    const active = button.dataset.mode === state.mode;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-selected', active ? 'true' : 'false');
  }
}

async function enterMode(mode, { centerId = null } = {}) {
  if (state.loaded) {
    state.views[state.mode] = { ...state.zoom };
  }
  state.mode = mode;
  state.centerId = centerId || null;
  state.selectedId = null;
  state.hidden.clear();
  updateModeTabs();
  dom.title.textContent = centerId
    ? `${MODE_TITLES[mode]}（以某人为中心）`
    : MODE_TITLES[mode];
  hideMenu();
  await loadGraph();
}

/** 打开关系图；`mode` 指定模式，`centerId` 仅人物模式有效。 */
export async function openGraph({ centerId = null, mode = 'character' } = {}) {
  const project = getCurrentProject();
  if (!project) {
    return;
  }
  const sameProject = state.project && state.project.id === project.id;
  if (!sameProject) {
    state.meta = null;
    state.loaded = false;
    state.views = {
      character: { k: 1, x: 0, y: 0 },
      organization: { k: 1, x: 0, y: 0 },
      faction: { k: 1, x: 0, y: 0 },
    };
    state.mode = 'character';
  }
  state.project = project;
  showView('view-graph');
  setContext(`${project.title} · 关系图`);
  try {
    await enterMode(mode, { centerId });
  } catch (error) {
    log.error(error);
    setStatus(`打开关系图失败：${(error && error.message) || error}`, 'error');
  }
}

// --------------------------------------------------------------------------
// 初始化
// --------------------------------------------------------------------------

export function initGraph() {
  dom.svg = el('graph-svg');
  dom.canvas = el('graph-canvas');
  dom.viewport = null;
  dom.nodeEls = null;
  dom.edgeEls = null;
  dom.status = el('graph-status');
  dom.banner = el('graph-banner');
  dom.menu = el('graph-menu');
  dom.empty = el('graph-empty');
  dom.title = el('graph-title');
  dom.legend = el('graph-legend');
  dom.modes = el('graph-modes');
  dom.labelsButton = el('graph-labels');

  if (!dom.svg) {
    return;
  }

  try {
    state.showLabels =
      window.localStorage.getItem('inkwell.graph.labels') !== '0';
  } catch {
    state.showLabels = true;
  }
  applyLabelVisibility();
  if (dom.labelsButton) {
    dom.labelsButton.addEventListener('click', () => {
      state.showLabels = !state.showLabels;
      try {
        window.localStorage.setItem(
          'inkwell.graph.labels',
          state.showLabels ? '1' : '0',
        );
      } catch {
        // 忽略隐私模式下的存储失败
      }
      applyLabelVisibility();
    });
  }

  el('graph-back').addEventListener('click', () => {
    showView('view-characters');
    if (state.project) {
      setContext(`${state.project.title} · 角色`);
    }
  });
  el('graph-fit').addEventListener('click', () => fit());
  el('graph-relayout').addEventListener('click', () => {
    state.positions = new Map();
    state.hidden.clear();
    if (state.mode === 'character') {
      const initial = circlePositions(visibleNodes(), {
        width: WORLD.width,
        height: WORLD.height,
      });
      for (const item of initial) {
        state.positions.set(item.id, {
          x: item.x,
          y: item.y,
          pinned: false,
        });
      }
      renderGraph();
      startSimulation();
    } else {
      const computed = computeStaticLayout();
      for (const [id, position] of computed) {
        state.positions.set(id, { ...position, pinned: false });
      }
      renderGraph();
      fit();
      updateStatus();
      scheduleSave(0);
    }
  });

  if (dom.modes) {
    dom.modes.addEventListener('click', (event) => {
      const button = event.target.closest('.graph-mode');
      if (!button || button.dataset.mode === state.mode) {
        return;
      }
      enterMode(button.dataset.mode).catch((error) => log.error(error));
    });
  }

  dom.svg.addEventListener('pointerdown', onPointerDown);
  dom.svg.addEventListener('pointermove', onPointerMove);
  dom.svg.addEventListener('pointerup', onPointerUp);
  dom.svg.addEventListener('pointercancel', onPointerUp);
  dom.svg.addEventListener('wheel', onWheel, { passive: false });
  dom.svg.addEventListener('contextmenu', onContextMenu);
  dom.svg.addEventListener('dblclick', onDoubleClick);
  dom.menu.addEventListener('click', onMenuClick);

  document.addEventListener('click', (event) => {
    if (!dom.menu.hidden && !dom.menu.contains(event.target)) {
      hideMenu();
    }
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      hideMenu();
    }
  });

  window.addEventListener('inkwell:open-graph', (event) => {
    const detail = event.detail || {};
    openGraph({ centerId: detail.centerId || null }).catch((error) =>
      log.error(error),
    );
  });
}
