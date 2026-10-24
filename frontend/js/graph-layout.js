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
  { width = 1200, height = 800, radius = 260, innerRadius = 190 } = {},
) {
  const positions = new Map();
  const center = { x: width / 2, y: height / 2 };
  const people = factions.length;
  factions.forEach((faction, index) => {
    const angle = people === 1 ? 0 : (2 * Math.PI * index) / people;
    const factionX = center.x + Math.cos(angle) * radius;
    const factionY = center.y + Math.sin(angle) * radius;
    positions.set(faction.id, { x: factionX, y: factionY });

    // 组织朝「远离图心」的方向扇形展开，避免不同阵营的簇互相插进去
    const siblings = organizations.filter(
      (item) => Number(item.faction_id) === Number(faction.id),
    );
    const spread = Math.PI / 2.4;
    siblings.forEach((org, siblingIndex) => {
      const offset =
        siblings.length === 1
          ? 0
          : ((siblingIndex - (siblings.length - 1) / 2) * spread) /
            Math.max(1, siblings.length - 1);
      const orgAngle = angle + offset;
      positions.set(org.id, {
        x: factionX + Math.cos(orgAngle) * innerRadius,
        y: factionY + Math.sin(orgAngle) * innerRadius,
      });
    });
  });

  const factionIds = new Set(factions.map((faction) => Number(faction.id)));
  const ungrouped = organizations.filter(
    (org) =>
      org.faction_id === null ||
      org.faction_id === undefined ||
      !factionIds.has(Number(org.faction_id)),
  );
  ungrouped.forEach((org, index) => {
    positions.set(org.id, {
      x: 160 + index * 170,
      y: height - 90,
    });
  });
  return positions;
}

/** BFS 同心环初始布局：度数最高的角色放中心，邻居一圈圈向外。
 *
 * 比随机圆周更接近「主角居中、关系外扩」的直觉，力导向也更容易收敛。
 */
export function bfsPositions(
  nodes,
  edges,
  { width = 1200, height = 800, padding = 90, ring = 170 } = {},
) {
  const adjacency = new Map(nodes.map((node) => [node.id, []]));
  for (const edge of edges) {
    const from = adjacency.get(edge.from);
    const to = adjacency.get(edge.to);
    if (from && to) {
      from.push(edge.to);
      to.push(edge.from);
    }
  }
  const degree = (id) => (adjacency.get(id) || []).length;
  const root = [...nodes].sort(
    (a, b) => degree(b.id) - degree(a.id) || a.id - b.id,
  )[0];
  if (!root) {
    return [];
  }

  const cx = width / 2;
  const cy = height / 2;
  const positions = new Map();
  positions.set(root.id, { id: root.id, x: cx, y: cy, pinned: false });

  const visited = new Set([root.id]);
  let frontier = [root.id];
  let level = 1;
  while (frontier.length > 0) {
    const next = [];
    for (const id of frontier) {
      for (const neighbor of adjacency.get(id) || []) {
        if (!visited.has(neighbor)) {
          visited.add(neighbor);
          next.push(neighbor);
        }
      }
    }
    if (!next.length) {
      break;
    }
    const radius = Math.min(
      ring * level,
      Math.min(width, height) / 2 - padding,
    );
    const offset = level * 0.4;
    next.forEach((id, index) => {
      const angle = (2 * Math.PI * index) / next.length - Math.PI / 2 + offset;
      positions.set(id, {
        id,
        x: cx + Math.cos(angle) * radius,
        y: cy + Math.sin(angle) * radius,
        pinned: false,
      });
    });
    frontier = next;
    level += 1;
  }

  // 与主连通分量断开的角色：排到外圈，避免被硬拉进中心
  const rest = nodes.filter((node) => !visited.has(node.id));
  const radius = Math.min(width, height) / 2 - padding;
  rest.forEach((node, index) => {
    const angle = (2 * Math.PI * index) / Math.max(1, rest.length);
    positions.set(node.id, {
      id: node.id,
      x: cx + Math.cos(angle) * radius,
      y: cy + Math.sin(angle) * radius,
      pinned: false,
    });
  });

  return [...positions.values()];
}

/** 节点-连线分离与节点防重叠（V2.0 5.9 优化）。
 *
 * 力导向只保证「大致疏密」，不保证节点不压在别的连线上。这里在布局结束后
 * 做一轮轻量松弛：节点互相推开、节点从无关连线上挪开，pinned 节点不动。
 */
export function separateNodes(positions, edges, options = {}) {
  const {
    nodeGap = 48,
    edgeClearance = 34,
    iterations = 26,
  } = options;
  const byId = new Map(positions.map((item) => [item.id, item]));

  for (let round = 0; round < iterations; round += 1) {
    for (let i = 0; i < positions.length; i += 1) {
      for (let j = i + 1; j < positions.length; j += 1) {
        const a = positions[i];
        const b = positions[j];
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        let distance = Math.hypot(dx, dy);
        if (distance >= nodeGap) {
          continue;
        }
        if (distance < 0.01) {
          dx = 0.01;
          dy = 0.01;
          distance = 0.014;
        }
        const ux = dx / distance;
        const uy = dy / distance;
        const push = (nodeGap - distance) / 2;
        if (!a.pinned && !b.pinned) {
          a.x -= ux * push;
          a.y -= uy * push;
          b.x += ux * push;
          b.y += uy * push;
        } else if (!a.pinned) {
          a.x -= ux * push * 2;
          a.y -= uy * push * 2;
        } else if (!b.pinned) {
          b.x += ux * push * 2;
          b.y += uy * push * 2;
        }
      }
    }

    for (const edge of edges) {
      const from = byId.get(edge.from);
      const to = byId.get(edge.to);
      if (!from || !to) {
        continue;
      }
      const ex = to.x - from.x;
      const ey = to.y - from.y;
      const lengthSquared = ex * ex + ey * ey || 1;
      for (const node of positions) {
        if (
          node.pinned ||
          node.id === edge.from ||
          node.id === edge.to
        ) {
          continue;
        }
        const t =
          ((node.x - from.x) * ex + (node.y - from.y) * ey) / lengthSquared;
        if (t <= 0.12 || t >= 0.88) {
          continue;
        }
        const px = from.x + ex * t;
        const py = from.y + ey * t;
        let dx = node.x - px;
        let dy = node.y - py;
        let distance = Math.hypot(dx, dy);
        if (distance >= edgeClearance) {
          continue;
        }
        if (distance < 0.01) {
          dx = -ey;
          dy = ex;
          distance = Math.hypot(dx, dy) || 1;
        }
        const ux = dx / distance;
        const uy = dy / distance;
        const push = Math.min(edgeClearance - distance, 10);
        node.x += ux * push;
        node.y += uy * push;
      }
    }
  }
  return positions;
}

/** 矩形节点版松弛：组织 / 阵营模式用。
 *
 * 组织卡是 156×48 的大矩形，按圆点算间距会漏掉「卡片压线」。
 * 这里按矩形半宽/半高处理：卡片之间不重叠，卡片从无关连线上让开。
 */
export function separateRectNodes(positions, edges, options = {}) {
  const {
    nodeGap = 20,
    edgeClearance = 20,
    iterations = 36,
    sizeOf = null,
    halfWidth = 78,
    halfHeight = 24,
  } = options;
  const size = (node) =>
    sizeOf ? sizeOf(node) : { hw: halfWidth, hh: halfHeight };
  const byId = new Map(positions.map((item) => [item.id, item]));

  for (let round = 0; round < iterations; round += 1) {
    // 矩形 AABB 分离：沿重叠较小的轴推开
    for (let i = 0; i < positions.length; i += 1) {
      for (let j = i + 1; j < positions.length; j += 1) {
        const a = positions[i];
        const b = positions[j];
        const sizeA = size(a);
        const sizeB = size(b);
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const overlapX = sizeA.hw + sizeB.hw + nodeGap - Math.abs(dx);
        const overlapY = sizeA.hh + sizeB.hh + nodeGap - Math.abs(dy);
        if (overlapX <= 0 || overlapY <= 0) {
          continue;
        }
        if (overlapX < overlapY) {
          const sign = dx >= 0 ? 1 : -1;
          const push = overlapX / 2;
          if (!a.pinned && !b.pinned) {
            a.x -= sign * push;
            b.x += sign * push;
          } else if (!a.pinned) {
            a.x -= sign * push * 2;
          } else if (!b.pinned) {
            b.x += sign * push * 2;
          }
        } else {
          const sign = dy >= 0 ? 1 : -1;
          const push = overlapY / 2;
          if (!a.pinned && !b.pinned) {
            a.y -= sign * push;
            b.y += sign * push;
          } else if (!a.pinned) {
            a.y -= sign * push * 2;
          } else if (!b.pinned) {
            b.y += sign * push * 2;
          }
        }
      }
    }

    // 卡片压线：按「矩形在法线方向的支撑半宽」判断
    for (const edge of edges) {
      const from = byId.get(edge.from);
      const to = byId.get(edge.to);
      if (!from || !to) {
        continue;
      }
      const ex = to.x - from.x;
      const ey = to.y - from.y;
      const length = Math.hypot(ex, ey) || 1;
      const nx = -ey / length;
      const ny = ex / length;
      const lengthSquared = length * length;
      for (const node of positions) {
        if (
          node.pinned ||
          node.id === edge.from ||
          node.id === edge.to
        ) {
          continue;
        }
        const t =
          ((node.x - from.x) * ex + (node.y - from.y) * ey) / lengthSquared;
        if (t <= 0.08 || t >= 0.92) {
          continue;
        }
        const signed = (node.x - from.x) * nx + (node.y - from.y) * ny;
        const distance = Math.abs(signed);
        const nodeSize = size(node);
        const extent = Math.abs(nx) * nodeSize.hw + Math.abs(ny) * nodeSize.hh;
        if (distance >= extent + edgeClearance) {
          continue;
        }
        const sign = signed >= 0 ? 1 : -1;
        const push = Math.min(extent + edgeClearance - distance, 12);
        node.x += nx * sign * push;
        node.y += ny * sign * push;
      }
    }
  }
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
