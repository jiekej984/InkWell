"""阶段四 4.4 性能打点（只在 `INKWELL_PERF_TRACE=1` 时才被 main.py 惰性导入）。

为什么不把打点写进 `main.py`：正常启动不该为「测量」付任何代价。`launch_window()`
只有在环境变量开启时才 `import perf_probe`，生产路径连模块都不会加载。

打点全部写进 `inkwell` 日志（`[perf]` 前缀），由 `tools/perf_probe.py` 读取汇总：

    驱动就绪     —— pywebview 驱动线程已跑起来
    首屏就绪     —— 项目列表（卡片 / 空态 / 出错态）已可见，即「窗口可交互」
    大纲树渲染   —— 打开项目后 `.tree__chapter` 数量不再变化（AC-1 的「不卡」）
    打开五万字章 —— 章节标题就绪且正文长度稳定（AC-3）
    检索首命中   —— 结果列表出现第一条命中（AC-10 的 UI 端）

场景步骤（`INKWELL_PERF_SCENARIO=1`）依赖 `tools/perf_probe.py` 的种子数据：
一个项目、2001 章（含一篇「五万字章」）、10 份设定文档、正文含「性能关键词」。
"""

from __future__ import annotations

import logging
import os
import time

PERF_TRACE_ENV = "INKWELL_PERF_TRACE"
PERF_SCENARIO_ENV = "INKWELL_PERF_SCENARIO"
FIVE_WAN_TITLE = "五万字章"
SEARCH_QUERY = "性能关键词"

# 首屏「可交互」= 项目列表三态里任意一个已经渲染出来
_READY_SELECTOR = """(function () {
  var cards = document.querySelectorAll('.card').length;
  var empty = document.getElementById('project-empty');
  var error = document.getElementById('projects-error');
  return cards > 0 || (empty && !empty.hidden) || (error && !error.hidden);
})()"""

_TREE_COUNT = "document.querySelectorAll('.tree__chapter').length"

_OPEN_FIVE_WAN = """(function () {
  var nodes = document.querySelectorAll('.tree__chapter');
  for (var i = 0; i < nodes.length; i += 1) {
    if (nodes[i].textContent.indexOf('%s') >= 0) { nodes[i].click(); return true; }
  }
  return false;
})()""" % FIVE_WAN_TITLE

_FIVE_WAN_READY = """(function () {
  var title = document.getElementById('chapter-title');
  var editor = document.querySelector('#editor .ql-editor');
  return !!title && title.value.indexOf('%s') >= 0 &&
    !!editor && editor.isContentEditable && editor.textContent.length > 40000;
})()""" % FIVE_WAN_TITLE

_SEARCH = """(function () {
  var input = document.getElementById('search-input');
  input.value = '%s';
  input.dispatchEvent(new Event('input', { bubbles: true }));
  document.getElementById('search-go').click();
  return true;
})()""" % SEARCH_QUERY

_HITS = "document.querySelectorAll('.search-hit').length"


def attach(window, started_at: float):
    """按环境变量决定是否返回 pywebview 的驱动函数（None = 不测量）。"""
    if os.environ.get(PERF_TRACE_ENV) != "1":
        return None
    log = logging.getLogger("inkwell")
    scenario = os.environ.get(PERF_SCENARIO_ENV) == "1"

    def elapsed_ms() -> int:
        return int((time.perf_counter() - started_at) * 1000)

    def evaluate(script: str):
        try:
            return window.evaluate_js(script)
        except Exception:  # 页面还没起来时 evaluate_js 会抛
            return None

    def wait_for(script: str, timeout: float, interval: float = 0.05) -> bool:
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            if evaluate(script):
                return True
            time.sleep(interval)
        return False

    def wait_tree_stable(timeout: float = 60.0) -> tuple[int, int]:
        """等大纲树节点数不再变化；返回 (本步耗时毫秒, 节点数)。"""
        started = time.perf_counter()
        last = -1
        stable_since: float | None = None
        while time.perf_counter() - started < timeout:
            count = evaluate(_TREE_COUNT) or 0
            if count >= 1 and count == last:
                if stable_since is None:
                    stable_since = time.perf_counter()
                elif time.perf_counter() - stable_since >= 0.2:
                    return _step_ms(started), int(count)
            else:
                stable_since = None
                last = count
            time.sleep(0.05)
        return _step_ms(started), int(last or 0)

    def _step_ms(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)

    def driver() -> None:
        log.info("[perf] 驱动就绪=%d ms", elapsed_ms())
        if not wait_for(_READY_SELECTOR, timeout=90.0):
            log.error("[perf] 首屏未就绪（90s 超时）")
            return
        log.info("[perf] 首屏就绪=%d ms", elapsed_ms())
        if not scenario:
            return

        clicked_at = time.perf_counter()
        # 注意：整卡可点的是 `.card__open`（role=button）；点 `.card` 不会打开项目
        clicked = evaluate(
            "(function(){var c=document.querySelector('.card__open')"
            "||document.querySelector('.card');"
            "if(c){c.click();}return !!c;})()"
        )
        cards = evaluate("document.querySelectorAll('.card').length") or 0
        log.info(
            "[perf] 项目卡点击=%d ms（卡片 %s 张，命中=%s）",
            _step_ms(clicked_at),
            cards,
            bool(clicked),
        )

        tree_ms, tree_count = wait_tree_stable()
        log.info("[perf] 大纲树渲染=%d ms（%d 章）", tree_ms, tree_count)

        opened_at = time.perf_counter()
        if evaluate(_OPEN_FIVE_WAN) and wait_for(_FIVE_WAN_READY, timeout=60.0):
            log.info("[perf] 打开五万字章=%d ms", _step_ms(opened_at))
        else:
            log.error("[perf] 五万字章没能打开（场景数据不对？）")

        search_at = time.perf_counter()
        evaluate(_SEARCH)
        if wait_for(f"{_HITS} > 0", timeout=30.0):
            hits = evaluate(_HITS) or 0
            log.info("[perf] 检索首命中=%d ms（%d 条）", _step_ms(search_at), int(hits))
        else:
            log.error("[perf] 检索没有命中（场景数据不对？）")

    return driver
