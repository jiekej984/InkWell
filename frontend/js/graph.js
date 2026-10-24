/** 人物关系图大画布（V2.0 / 5.7 / FR-8.17~8.21）。
 *
 * 结构：
 *   · SVG 画布（世界坐标 1200×800）+「缩放/平移」变换组
 *   · 布局用 `graph-layout.js` 的简化 FR，分帧跑 300 轮，不阻塞输入
 *   · 节点：圆点 + 姓名首字；填充=主组织色，描边=定位色，半径=定位
 *   · 边：五大色系、单/双向箭头、隐秘虚线
 *   · 拖拽摆位后写回 `#81` 布局接口（按模式合并）
 *
 * 入口由 `inkwell:open-graph` 事件触发（`characters.js` / `relations.js` 派发），
 * 避免图模块反过来 import 页面模块造成循环。
 */

import { request } from './api.js';
import { getCurrentProject, openCharacterCard } from './characters.js';
import {
  circlePositions,
  forceIteration,
  nodeRadius,
  orgFill,
} from './graph-layout.js';
import { createLogger } from './logger.js';
import { el, setContext, showView } from './view.js';

const log = createLogger('graph');

const WORLD = { width: 1200, height: 800 };
const SIMULATION_ITERATIONS = 300;
const SIMULATION_CHUNK = 15;
const SAVE_DEBOUNCE_MS = 600;

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

const state = {
  project: null,
  meta: null,
  nodes: [],
  edges: [],
  positions: new Map(),
  hidden: new Set(),
  selectedId: null,
  zoom: { k: 1, x: 0, y: 0 },
  mode: 'character',
  centerId: null,
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

function template() {
  const ns = 'http://www.w3.org/2000/svg';
  return {
    ns,
    create(name, attrs = {}) {
      const node = document.createElementNS(ns, name);
      for (const [key, value] of Object.entries(attrs)) {
        node.setAttribute(key, String(value));
      }
      return node;
    },
  };
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

// --------------------------------------------------------------------------
// 渲染
// --------------------------------------------------------------------------

function renderGraph() {
  const svg = dom.svg;
  if (!svg) {
    return;
  }
  const { create } = template();
  svg.textContent = '';

  const defs = create('defs');
  for (const [family, color] of Object.entries(FAMILY_COLORS)) {
    const marker = create('marker', {
      id: `graph-arrow-${family}`,
      viewBox: '0 0 10 10',
      refX: 9,
      refY: 5,
      markerWidth: 8,
      markerHeight: 8,
      orient: 'auto-start-reverse',
    });
    const path = create('path', { d: 'M0,0 L10,5 L0,10 z' });
    path.style.fill = color;
    marker.append(path);
    defs.append(marker);
  }
  svg.append(defs);

  const viewport = create('g', { class: 'graph-viewport' });
  svg.append(viewport);
  dom.viewport = viewport;

  dom.edgeEls = new Map();
  for (const edge of visibleEdges()) {
    const line = create('line', { class: 'graph-edge' });
    const family = familyOf(edge.type);
    line.style.stroke = FAMILY_COLORS[family] || FAMILY_COLORS.other;
    line.dataset.edgeId = String(edge.id);
    if (edge.secret) {
      line.classList.add('is-secret');
    }
    if (!edge.bidirectional) {
      line.setAttribute('marker-end', `url(#graph-arrow-${family})`);
    }
    viewport.append(line);
    dom.edgeEls.set(String(edge.id), line);
  }

  dom.nodeEls = new Map();
  const nodesLayer = create('g', { class: 'graph-nodes' });
  viewport.append(nodesLayer);
  for (const node of visibleNodes()) {
    const radius = nodeRadius(node.role);
    const group = create('g', {
      class: 'graph-node',
      'data-id': String(node.id),
      role: 'button',
      tabindex: 0,
      'aria-label': `${node.name}（${roleLabel(node.role)}）`,
    });
    const circle = create('circle', { r: radius });
    circle.style.fill = orgFill(node.org_color, node.org_id);
    circle.style.stroke =
      ROLE_COLORS[node.role] || ROLE_COLORS.other || '#7a6e5e';

    const text = create('text', {
      'text-anchor': 'middle',
      dy: '0.35em',
    });
    text.textContent = Array.from(node.name || '?')[0];

    const title = create('title');
    title.textContent = `${node.name} · ${roleLabel(node.role)}`;
    group.append(circle, text, title);
    nodesLayer.append(group);
    dom.nodeEls.set(String(node.id), group);
    if (state.selectedId === node.id) {
      group.classList.add('is-selected');
    }
  }

  dom.nodeLayer = nodesLayer;
  updatePositions();
  applyZoom();
  updateEmpty();
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
  for (const edge of visibleEdges()) {
    const line = dom.edgeEls.get(String(edge.id));
    const from = state.positions.get(Number(edge.from));
    const to = state.positions.get(Number(edge.to));
    if (!line || !from || !to) {
      continue;
    }
    const fromNode = state.nodes.find((node) => node.id === Number(edge.from));
    const toNode = state.nodes.find((node) => node.id === Number(edge.to));
    const fromRadius = nodeRadius(fromNode ? fromNode.role : 'other') + 2;
    const toRadius = nodeRadius(toNode ? toNode.role : 'other') + 2;
    let dx = to.x - from.x;
    let dy = to.y - from.y;
    const distance = Math.hypot(dx, dy) || 1;
    const ux = dx / distance;
    const uy = dy / distance;
    const x1 = from.x + ux * fromRadius;
    const y1 = from.y + uy * fromRadius;
    const x2 = to.x - ux * toRadius;
    const y2 = to.y - uy * toRadius;
    line.setAttribute('x1', x1.toFixed(2));
    line.setAttribute('y1', y1.toFixed(2));
    line.setAttribute('x2', x2.toFixed(2));
    line.setAttribute('y2', y2.toFixed(2));
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
}

// --------------------------------------------------------------------------
// 布局与视图
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
    .map((edge) => ({
      from: Number(edge.from),
      to: Number(edge.to),
    }));
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

function fit() {
  const nodes = visibleNodes()
    .map((node) => state.positions.get(node.id))
    .filter(Boolean);
  if (!nodes.length || !dom.canvas) {
    return;
  }
  const xs = nodes.map((item) => item.x);
  const ys = nodes.map((item) => item.y);
  // 左右上留 80，底部多留一点给图例与操作提示
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

function updateStatus() {
  const nodes = visibleNodes().length;
  const edges = visibleEdges().length;
  setStatus(`${nodes} 个角色 · ${edges} 条关系`);
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
    // 拖动时停掉正在跑的布局，避免和用户抢位置
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
  // 以鼠标位置为锚点缩放
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
    setStatus(`已选：${node.name} · ${roleLabel(node.role)}`);
  }
}

function showMenu(event, nodeId) {
  state.menuNodeId = nodeId;
  const rect = dom.canvas.getBoundingClientRect();
  dom.menu.hidden = false;
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
  const action = event.target.dataset
    ? event.target.dataset.action
    : null;
  if (!action || state.menuNodeId === null) {
    return;
  }
  const nodeId = state.menuNodeId;
  hideMenu();
  if (action === 'center') {
    openGraph({ centerId: nodeId }).catch((error) => log.error(error));
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
  const payload = { character: {} };
  for (const node of state.nodes) {
    const position = state.positions.get(node.id);
    if (!position) {
      continue;
    }
    payload.character[node.key] = {
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
        body: { payload, expected_updated_at: state.layoutStamp },
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
// 打开
// --------------------------------------------------------------------------

async function loadMeta() {
  const project = state.project;
  if (state.meta && state.meta.__project === project.id) {
    return;
  }
  const meta = await request(
    `/api/projects/${project.id}/characters/meta`,
  );
  meta.__project = project.id;
  state.meta = meta;
}

/** 打开人物关系图；`centerId` 存在时只展开该角色 N 跳以内的人。 */
export async function openGraph({ centerId = null } = {}) {
  const project = getCurrentProject();
  if (!project) {
    return;
  }
  state.project = project;
  state.centerId = centerId || null;
  state.selectedId = null;
  state.hidden.clear();
  hideMenu();
  showView('view-graph');
  setContext(`${project.title} · 关系图`);
  dom.title.textContent = centerId ? '人物关系图（以某人为中心）' : '人物关系图';
  setStatus('加载中…');

  try {
    await loadMeta();
    const params = new URLSearchParams({
      mode: 'character',
      limit: '80',
      depth: '2',
    });
    if (centerId) {
      params.set('center_id', String(centerId));
    }
    const [data, layout] = await Promise.all([
      request(`/api/projects/${project.id}/graph?${params.toString()}`),
      request(`/api/projects/${project.id}/graph/layout`),
    ]);
    state.nodes = data.nodes.map((node) => ({
      ...node,
      id: Number(node.id),
    }));
    state.edges = data.edges.map((edge) => ({
      ...edge,
      from: Number(edge.from),
      to: Number(edge.to),
      id: String(edge.id),
    }));
    state.truncated = Boolean(data.truncated);
    state.total = Number(data.total_nodes) || state.nodes.length;
    state.layoutStamp = layout.updated_at || null;

    const saved = (layout.payload && layout.payload.character) || {};
    state.positions = new Map();
    const missing = [];
    for (const node of state.nodes) {
      const position = saved[node.key];
      if (
        position &&
        Number.isFinite(position.x) &&
        Number.isFinite(position.y)
      ) {
        state.positions.set(node.id, {
          x: position.x,
          y: position.y,
          pinned: Boolean(position.pinned),
        });
      } else {
        missing.push(node);
      }
    }
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
    }

    renderGraph();
    if (missing.length) {
      startSimulation();
    } else {
      fit();
      updateStatus();
    }
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

  if (!dom.svg) {
    return;
  }

  el('graph-back').addEventListener('click', () => {
    showView('view-characters');
    if (state.project) {
      setContext(`${state.project.title} · 角色`);
    }
  });
  el('graph-fit').addEventListener('click', () => fit());
  el('graph-relayout').addEventListener('click', () => {
    for (const node of visibleNodes()) {
      const position = state.positions.get(node.id);
      if (position) {
        position.pinned = false;
      }
    }
    renderGraph();
    startSimulation();
  });

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
    const centerId = event.detail ? event.detail.centerId : null;
    openGraph({ centerId }).catch((error) => log.error(error));
  });
}
