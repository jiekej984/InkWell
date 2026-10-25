/** 关系图布局纯函数测试（V2.0 / 5.7）。 */

import assert from 'node:assert/strict';
import test from 'node:test';

import {
  bfsPositions,
  circlePositions,
  clusterLayout,
  forceIteration,
  nodeRadius,
  orgFill,
  runForceLayout,
  separateNodes,
  separateRectNodes,
  treeLayout,
} from '../../frontend/js/graph-layout.js';

test('circlePositions：确定性、落在画布内、互不重合', () => {
  const nodes = [{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }];
  const first = circlePositions(nodes, { width: 1200, height: 800 });
  const again = circlePositions(nodes, { width: 1200, height: 800 });
  assert.deepEqual(first, again);
  assert.equal(first.length, 4);
  for (const item of first) {
    assert.ok(item.x > 0 && item.x < 1200, `x 越界: ${item.x}`);
    assert.ok(item.y > 0 && item.y < 800, `y 越界: ${item.y}`);
  }
  const keys = new Set(first.map((item) => `${Math.round(item.x)},${Math.round(item.y)}`));
  assert.equal(keys.size, 4);
});

test('forceIteration：两点重合会被斥力推开', () => {
  const positions = [
    { id: 1, x: 600, y: 400 },
    { id: 2, x: 600, y: 400 },
  ];
  forceIteration(positions, [], { width: 1200, height: 800, iteration: 0, total: 300 });
  const distance = Math.hypot(
    positions[0].x - positions[1].x,
    positions[0].y - positions[1].y,
  );
  assert.ok(distance > 0, '两点不应再完全重合');
});

test('forceIteration：pinned 节点不动', () => {
  const positions = [
    { id: 1, x: 100, y: 100, pinned: true },
    { id: 2, x: 900, y: 700 },
  ];
  forceIteration(positions, [], { width: 1200, height: 800, iteration: 0, total: 300 });
  assert.equal(positions[0].x, 100);
  assert.equal(positions[0].y, 100);
});

test('runForceLayout：位置有限且不越界', () => {
  const nodes = Array.from({ length: 12 }, (_, i) => ({ id: i + 1 }));
  const edges = [
    { from: 1, to: 2 },
    { from: 2, to: 3 },
    { from: 3, to: 4 },
    { from: 4, to: 1 },
  ];
  const positions = runForceLayout(nodes, edges, {
    iterations: 120,
    width: 1200,
    height: 800,
  });
  assert.equal(positions.length, 12);
  for (const item of positions) {
    assert.ok(Number.isFinite(item.x) && Number.isFinite(item.y));
    assert.ok(item.x >= 60 && item.x <= 1140, `x 越界: ${item.x}`);
    assert.ok(item.y >= 60 && item.y <= 740, `y 越界: ${item.y}`);
  }
});

test('runForceLayout：相连节点不塌缩到一点', () => {
  const nodes = [{ id: 1 }, { id: 2 }, { id: 3 }, { id: 99 }];
  const positions = runForceLayout(
    nodes,
    [
      { from: 1, to: 2 },
      { from: 2, to: 3 },
    ],
    { iterations: 300, width: 1200, height: 800 },
  );
  for (let i = 0; i < positions.length; i += 1) {
    for (let j = i + 1; j < positions.length; j += 1) {
      const distance = Math.hypot(
        positions[i].x - positions[j].x,
        positions[i].y - positions[j].y,
      );
      assert.ok(distance > 1, `节点 ${positions[i].id}/${positions[j].id} 重合`);
    }
  }
});

test('nodeRadius / orgFill：角色半径与组织配色', () => {
  assert.ok(nodeRadius('protagonist') > nodeRadius('extra'));
  assert.equal(nodeRadius('unknown'), 10);
  assert.equal(orgFill('#123456', 3), '#123456');
  assert.equal(orgFill(null, 3), 'var(--org-fill-4)');
  assert.equal(orgFill(null, null), 'var(--text-2)');
  assert.equal(orgFill(null, 9), 'var(--org-fill-2)');
});

test('treeLayout：根在上、子在下、父节点居中于子节点', () => {
  const nodes = [
    { id: 1, order: 0 },
    { id: 2, order: 0 },
    { id: 3, order: 1 },
    { id: 10, order: 0 },
  ];
  const edges = [
    { from: 1, to: 2, kind: 'org_parent' },
    { from: 1, to: 3, kind: 'org_parent' },
    { from: 10, to: 4, kind: 'org_relation' },
  ];
  const positions = treeLayout(nodes, edges, { width: 1200 });
  assert.ok(positions.get(1).y < positions.get(2).y, '子节点应在根下方');
  assert.ok(positions.get(2).x < positions.get(3).x, '兄弟按 order 排开');
  const parentX = positions.get(1).x;
  const midX = (positions.get(2).x + positions.get(3).x) / 2;
  assert.ok(Math.abs(parentX - midX) < 0.001, '父节点应居中');
  for (const node of nodes) {
    const pos = positions.get(node.id);
    assert.ok(Number.isFinite(pos.x) && Number.isFinite(pos.y));
  }
});

test('treeLayout：三棵独立树不会叠在一起', () => {
  const nodes = [
    { id: 1 },
    { id: 2 },
    { id: 3 },
  ];
  const positions = treeLayout(nodes, [], { width: 1200 });
  const xs = [1, 2, 3].map((id) => positions.get(id).x);
  assert.equal(new Set(xs.map((x) => Math.round(x))).size, 3);
});

test('treeLayout：叶子步长不小于卡片宽（多叶子不重叠）', () => {
  const nodes = [{ id: 1 }, ...Array.from({ length: 12 }, (_, i) => ({ id: i + 2 }))];
  const edges = nodes
    .slice(1)
    .map((node) => ({ from: 1, to: node.id, kind: 'org_parent' }));
  const positions = treeLayout(nodes, edges, { width: 1200 });
  const xs = nodes
    .slice(1)
    .map((node) => positions.get(node.id).x)
    .sort((a, b) => a - b);
  for (let index = 1; index < xs.length; index += 1) {
    assert.ok(
      xs[index] - xs[index - 1] >= 156,
      `叶子间距 ${xs[index] - xs[index - 1]} 小于卡片宽 156`,
    );
  }
});


test('clusterLayout：阵营围成圈，组织靠近自己的阵营', () => {  const factions = [
    { id: 1 },
    { id: 2 },
  ];
  const orgs = [
    { id: 11, faction_id: 1 },
    { id: 12, faction_id: 1 },
    { id: 21, faction_id: 2 },
    { id: 99, faction_id: null },
  ];
  const positions = clusterLayout(factions, orgs, {
    width: 1200,
    height: 800,
    radius: 260,
    innerRadius: 120,
  });
  const distance = (a, b) =>
    Math.hypot(a.x - b.x, a.y - b.y);
  assert.ok(
    distance(positions.get(11), positions.get(1)) <
      distance(positions.get(11), positions.get(2)),
    '组织应更靠近自己的阵营',
  );
  assert.ok(positions.get(99).y > 700, '未归属组织排在底部');
});

test('separateNodes：压在连线中点的节点会被挪开', () => {
  const positions = [
    { id: 1, x: 100, y: 100, pinned: true },
    { id: 2, x: 500, y: 100, pinned: true },
    { id: 3, x: 300, y: 100 },
  ];
  separateNodes(
    positions,
    [{ from: 1, to: 2 }],
    { edgeClearance: 34, iterations: 20 },
  );
  const node = positions.find((item) => item.id === 3);
  assert.ok(Math.abs(node.y - 100) >= 25, `仍贴在线上: ${node.y}`);
  assert.equal(positions.find((item) => item.id === 1).y, 100);
});

test('separateNodes：重叠节点会被推开且 pinned 不动', () => {
  const positions = [
    { id: 1, x: 200, y: 200, pinned: true },
    { id: 2, x: 205, y: 200 },
  ];
  separateNodes(positions, [], { nodeGap: 48, iterations: 20 });
  const other = positions.find((item) => item.id === 2);
  const distance = Math.hypot(other.x - 200, other.y - 200);
  assert.ok(distance >= 40, `推开距离不足: ${distance}`);
  assert.equal(positions.find((item) => item.id === 1).x, 200);
});

test('bfsPositions：度数最高的节点居中，邻居在近圈', () => {  const nodes = Array.from({ length: 8 }, (_, index) => ({ id: index + 1 }));
  const edges = [
    { from: 1, to: 2 },
    { from: 1, to: 3 },
    { from: 1, to: 4 },
    { from: 2, to: 5 },
    { from: 5, to: 6 },
  ];
  const positions = bfsPositions(nodes, edges, {
    width: 1200,
    height: 800,
  });
  const byId = new Map(positions.map((item) => [item.id, item]));
  assert.equal(byId.get(1).x, 600);
  assert.equal(byId.get(1).y, 400);
  const distance = (id) =>
    Math.hypot(byId.get(id).x - 600, byId.get(id).y - 400);
  assert.ok(distance(2) < distance(6), '二跳节点应比三跳更近中心');
  assert.equal(positions.length, 8);
  for (const item of positions) {
    assert.ok(Number.isFinite(item.x) && Number.isFinite(item.y));
  }
});

test('separateRectNodes：组织卡压在连线上会被推开', () => {
  const positions = [
    { id: 1, x: 100, y: 200, pinned: true },
    { id: 2, x: 900, y: 200, pinned: true },
    { id: 3, x: 500, y: 200 },
  ];
  separateRectNodes(positions, [{ from: 1, to: 2 }], {
    halfWidth: 78,
    halfHeight: 24,
    edgeClearance: 20,
    iterations: 30,
  });
  const card = positions.find((item) => item.id === 3);
  const distance = Math.abs(card.y - 200);
  assert.ok(distance > 40, `卡片仍压在线上: ${distance}`);
  assert.equal(positions.find((item) => item.id === 1).y, 200);
});

test('separateRectNodes：两张重叠的组织卡沿短轴分开', () => {
  const positions = [
    { id: 1, x: 300, y: 300 },
    { id: 2, x: 310, y: 305 },
  ];
  separateRectNodes(positions, [], {
    halfWidth: 78,
    halfHeight: 24,
    nodeGap: 18,
    iterations: 30,
  });
  const a = positions[0];
  const b = positions[1];
  const apart =
    Math.abs(b.x - a.x) > 150 || Math.abs(b.y - a.y) > 60;
  assert.ok(apart, `卡片仍重叠: ${b.x - a.x}, ${b.y - a.y}`);
});
