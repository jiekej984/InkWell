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
