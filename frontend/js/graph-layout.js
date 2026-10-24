/** 关系图布局的纯函数（V2.0 / 5.7）。
 *
 * 简化版 Fruchterman-Reingold：斥力 k²/d、引力 d²/k、温度逐轮下降。
 * 与 DOM 无关，`tests/js/graph-layout.test.js` 直接测。
 */

/** 圆周初始位置（确定性；同样的输入永远得到同样的开局）。 */
export function circlePositions(nodes, { width, height, padding = 70 } = {}) {
  const count = nodes.length || 1;
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.max(40, Math.min(width, height) / 2 - padding);
  return nodes.map((node, index) => {
    const angle = (2 * Math.PI * index) / count - Math.PI / 2;
    return {
      id: node.id,
      x: cx + Math.cos(angle) * radius,
      y: cy + Math.sin(angle) * radius,
      pinned: Boolean(node.pinned),
    };
  });
}

/** 一轮迭代（原地修改 positions，返回同一个数组）。 */
export function forceIteration(positions, edges, options = {}) {
  const {
    width = 1200,
    height = 800,
    iteration = 0,
    total = 300,
    padding = 60,
  } = options;
  const count = positions.length;
  if (count < 2) {
    return positions;
  }

  const byId = new Map(positions.map((item) => [item.id, item]));
  const area = width * height;
  const k = Math.sqrt(area / count);
  const disp = new Map(positions.map((item) => [item.id, { x: 0, y: 0 }]));

  for (let i = 0; i < count; i += 1) {
    for (let j = i + 1; j < count; j += 1) {
      const a = positions[i];
      const b = positions[j];
      let dx = a.x - b.x;
      let dy = a.y - b.y;
      let distance = Math.hypot(dx, dy);
      if (distance < 0.01) {
        dx = (i % 2 ? 1 : -1) * 0.01;
        dy = (j % 2 ? 1 : -1) * 0.01;
        distance = 0.014;
      }
      const force = (k * k) / distance;
      const ux = dx / distance;
      const uy = dy / distance;
      const da = disp.get(a.id);
      const db = disp.get(b.id);
      da.x += ux * force;
      da.y += uy * force;
      db.x -= ux * force;
      db.y -= uy * force;
    }
  }

  for (const edge of edges) {
    const a = byId.get(edge.from);
    const b = byId.get(edge.to);
    if (!a || !b || a === b) {
      continue;
    }
    const dx = a.x - b.x;
    const dy = a.y - b.y;
    const distance = Math.max(0.01, Math.hypot(dx, dy));
    const force = (distance * distance) / k;
    const ux = dx / distance;
    const uy = dy / distance;
    const da = disp.get(a.id);
    const db = disp.get(b.id);
    da.x -= ux * force;
    da.y -= uy * force;
    db.x += ux * force;
    db.y += uy * force;
  }

  const temperature = Math.max(
    1,
    (width / 8) * (1 - Math.min(1, iteration / Math.max(1, total))),
  );
  for (const item of positions) {
    if (item.pinned) {
      continue;
    }
    const delta = disp.get(item.id);
    const length = Math.hypot(delta.x, delta.y) || 1;
    const step = Math.min(length, temperature);
    item.x += (delta.x / length) * step;
    item.y += (delta.y / length) * step;
    item.x = Math.min(width - padding, Math.max(padding, item.x));
    item.y = Math.min(height - padding, Math.max(padding, item.y));
  }
  return positions;
}

/** 同步跑完全部迭代（测试与小图用；界面走分帧版本）。 */
export function runForceLayout(nodes, edges, options = {}) {
  const { iterations = 300, width = 1200, height = 800 } = options;
  const positions = circlePositions(nodes, { width, height });
  for (let iteration = 0; iteration < iterations; iteration += 1) {
    forceIteration(positions, edges, {
      width,
      height,
      iteration,
      total: iterations,
    });
  }
  return positions;
}

/** 组织层级树布局：根在上、子在下，叶子按顺序横向铺开，父节点居中于子节点。 */
export function treeLayout(
  nodes,
  edges,
  { width = 1200, paddingX = 90, paddingY = 80, levelHeight = 120 } = {},
) {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const children = new Map(nodes.map((node) => [node.id, []]));
  const hasParent = new Set();
  for (const edge of edges) {
    if (edge.kind !== 'org_parent') {
      continue;
    }
    const parent = children.get(edge.from);
    if (parent && byId.has(edge.to)) {
      parent.push(edge.to);
      hasParent.add(edge.to);
    }
  }
  const orderOf = (id) => {
    const node = byId.get(id);
    return node ? Number(node.order) || 0 : 0;
  };
  for (const list of children.values()) {
    list.sort((a, b) => orderOf(a) - orderOf(b) || a - b);
  }

  const roots = nodes
    .filter((node) => !hasParent.has(node.id))
    .map((node) => node.id)
    .sort((a, b) => orderOf(a) - orderOf(b) || a - b);

  let leafCursor = 0;
  const positions = new Map();
  const depths = new Map();
  const leafCount = new Map();

  const measure = (id, depth) => {
    depths.set(id, depth);
    const kids = children.get(id) || [];
    if (!kids.length) {
      leafCount.set(id, 1);
      return 1;
    }
    const total = kids.reduce((sum, child) => sum + measure(child, depth + 1), 0);
    leafCount.set(id, total);
    return total;
  };
  for (const root of roots) {
    measure(root, 0);
  }

  const xStep =
    (width - paddingX * 2) / Math.max(1, leafCursor + sumLeaves(roots));
  function sumLeaves(list) {
    return list.reduce((sum, id) => sum + (leafCount.get(id) || 1), 0);
  }
  function placeLeaves(list) {
    const xs = [];
    for (const id of list) {
      const kids = children.get(id) || [];
      if (!kids.length) {
        const x = paddingX + (leafCursor + 0.5) * xStep;
        leafCursor += 1;
        xs.push(x);
        positions.set(id, { x, y: paddingY + (depths.get(id) || 0) * levelHeight });
      } else {
        const childXs = placeLeaves(kids);
        const x = (Math.min(...childXs) + Math.max(...childXs)) / 2;
        xs.push(x);
        positions.set(id, { x, y: paddingY + (depths.get(id) || 0) * levelHeight });
      }
    }
    return xs;
  }
  placeLeaves(roots);

  for (const node of nodes) {
    if (!positions.has(node.id)) {
      positions.set(node.id, { x: width / 2, y: paddingY });
    }
  }
  return positions;
}

/** 阵营簇布局：立场围成一圈，各自的组织绕在本阵营周围，未归属组织排在底部。 */
export function clusterLayout(
  factions,
  organizations,
  { width = 1200, height = 800, radius = 260, innerRadius = 120 } = {},
) {
  const positions = new Map();
  const center = { x: width / 2, y: height / 2 };
  const people = factions.length;
  factions.forEach((faction, index) => {
    const angle = people === 1 ? 0 : (2 * Math.PI * index) / people;
    positions.set(faction.id, {
      x: center.x + Math.cos(angle) * radius,
      y: center.y + Math.sin(angle) * radius,
    });
  });

  const ungrouped = [];
  for (const org of organizations) {
    if (org.faction_id === null || org.faction_id === undefined) {
      ungrouped.push(org);
      continue;
    }
    const factionPos = positions.get(Number(org.faction_id));
    if (!factionPos) {
      ungrouped.push(org);
      continue;
    }
    const siblings = organizations.filter(
      (item) => Number(item.faction_id) === Number(org.faction_id),
    );
    const index = siblings.findIndex((item) => item.id === org.id);
    const angle =
      (2 * Math.PI * index) / Math.max(1, siblings.length) + Math.PI / 2;
    positions.set(org.id, {
      x: factionPos.x + Math.cos(angle) * innerRadius,
      y: factionPos.y + Math.sin(angle) * innerRadius,
    });
  }

  ungrouped.forEach((org, index) => {
    positions.set(org.id, {
      x: 160 + index * 170,
      y: height - 90,
    });
  });
  return positions;
}

/** 节点半径：主角最大，龙套最小。 */
export function nodeRadius(role) {
  switch (role) {
    case 'protagonist':
      return 17;
    case 'heroine':
      return 15;
    case 'antagonist':
      return 14;
    case 'supporting':
      return 12;
    case 'extra':
      return 9;
    default:
      return 10;
  }
}

/** 组织填充色：优先用组织自定义颜色，否则按组织 id 取 8 色板。 */
export function orgFill(orgColor, orgId) {
  if (orgColor) {
    return orgColor;
  }
  if (orgId === null || orgId === undefined) {
    return 'var(--text-2)';
  }
  const index = (Math.abs(Number(orgId)) % 8) + 1;
  return `var(--org-fill-${index})`;
}
