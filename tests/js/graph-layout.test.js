/** 关系图布局纯函数测试（V2.0 / 5.7）。 */

import assert from 'node:assert/strict';
import test from 'node:test';

import {
  circlePositions,
  forceIteration,
  nodeRadius,
  orgFill,
  runForceLayout,
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
