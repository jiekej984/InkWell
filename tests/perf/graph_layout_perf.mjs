/** 前端力导向布局性能（V2.0 / 5.9）：80 节点 / 200 边 / 300 轮。 */

import { runForceLayout } from '../../frontend/js/graph-layout.js';

const NODES = 80;
const EDGES = 200;
const ITERATIONS = 300;

const nodes = Array.from({ length: NODES }, (_, index) => ({ id: index + 1 }));
const edges = [];
for (let offset = 1; offset < NODES && edges.length < EDGES; offset += 1) {
  for (let i = 0; i < NODES && edges.length < EDGES; i += 1) {
    const from = i + 1;
    const to = ((i + offset) % NODES) + 1;
    if (from !== to) {
      edges.push({ from, to });
    }
  }
}

// 预热一次，避免把 JIT 编译算进正式计时
runForceLayout(nodes, edges, {
  iterations: 60,
  width: 1200,
  height: 800,
});

const start = performance.now();
const positions = runForceLayout(nodes, edges, {
  iterations: ITERATIONS,
  width: 1200,
  height: 800,
});
const ms = performance.now() - start;

const finite = positions.every(
  (item) => Number.isFinite(item.x) && Number.isFinite(item.y),
);
console.log(
  JSON.stringify({
    nodes: NODES,
    edges: edges.length,
    iterations: ITERATIONS,
    ms: Number(ms.toFixed(1)),
    finite,
  }),
);
process.exit(finite ? 0 : 1);
