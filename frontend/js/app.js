/** 阶段一骨架自检页面。
 *
 * 验证三件事：
 *   1. pywebview 桥接可用，token 能从窗口对象注入到前端（不走 URL）
 *   2. 本地后端可访问，/api/system/health 鉴权生效
 *   3. 连续多次请求不出现 404（R-17 回归）
 *
 * 正式 UI 属于阶段三，本文件不实现任何业务功能。
 */

import { isDev, request } from './api.js';
import { HOTKEY_SCOPES, hotkeys, installHotkeys } from './hotkeys.js';
import { createLogger, installGlobalHandlers } from './logger.js';
import { initProjects, loadProjects } from './projects.js';
import { initBackup, openBackup } from './backup.js';
import { initDocuments, leaveDocuments } from './documents.js';
import { initSearch, openSearch } from './search.js';
import { initSettings } from './settings.js';
import { initTrash, openTrash } from './trash.js';
import { showView } from './view.js';
import { initWriter, leaveWriter } from './writer.js';

const log = createLogger('bootstrap');
const CHECK_ROUNDS = 20;

function element(id) {
  return document.getElementById(id);
}

function setStatus(id, text, state = '') {
  const node = element(id);
  if (!node) {
    return;
  }
  node.textContent = text;
  node.className = `status__value${state ? ` is-${state}` : ''}`;
}

function appendLog(line) {
  const node = element('log');
  if (node) {
    node.textContent += `${line}\n`;
  }
}

async function runChecks() {
  await request('/api/system/health');
  setStatus('bridge', '已就绪，token 注入成功', 'ok');
  setStatus('health', '200 · code=0', 'ok');
  appendLog('健康检查通过');

  for (let round = 1; round <= CHECK_ROUNDS; round += 1) {
    // eslint-disable-next-line no-await-in-loop
    await request('/api/system/health');
    setStatus('loop', `${round}/${CHECK_ROUNDS}`, '');
  }
  setStatus('loop', `${CHECK_ROUNDS}/${CHECK_ROUNDS} 全部 200`, 'ok');
  appendLog(`连续 ${CHECK_ROUNDS} 次请求全部成功（R-17 回归）`);

  if (!(await isDev())) {
    lockDownProduction();
    appendLog('生产模式：已禁用 DevTools 与右键菜单');
  } else {
    appendLog('开发模式：调试入口保持可用');
  }
}

/** 生产环境纵深防御：拦截 F12 / 常用开发者工具快捷键与右键菜单。
 *
 * 注意：pywebview 在 debug=False 时已通过 WebView2 设置关闭了
 * AreDevToolsEnabled / AreDefaultContextMenusEnabled（见
 * webview/platforms/edgechromium.py 第 287、288、290 行）。
 * 此处的前端拦截是第二层防护，用于在快捷键路径上兜底。
 */
function lockDownProduction() {
  document.addEventListener('contextmenu', (event) => event.preventDefault());
  document.addEventListener('keydown', (event) => {
    const key = (event.key || '').toLowerCase();
    const blocked =
      key === 'f12' ||
      (event.ctrlKey && event.shiftKey && key === 'i') ||
      (event.ctrlKey && event.shiftKey && key === 'j') ||
      (event.ctrlKey && key === 'u');
    if (blocked) {
      event.preventDefault();
    }
  });
}

/** 对话框「取消」统一关闭（B1）。
 *
 * 取消按钮一律 `type="button"` + `data-dialog-cancel`，由这里统一 `close()`。
 * 原因：取消按钮若写成 `type="submit"`，会先经过表单必填校验（书名/章节标题为空时
 * 连 submit 事件都不发），即使发了也可能被 submit 回调里的 preventDefault 拦下，
 * 结果是「取消关不掉、只能保存」。
 */
function setupDialogs() {
  document.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    const button = target.closest('[data-dialog-cancel]');
    if (!button) {
      return;
    }
    const dialog = button.closest('dialog');
    if (dialog) {
      dialog.close(button.dataset.dialogCancel || 'cancel');
    }
  });
}

/** 当前可见视图（`view-writer` → `writer`），供快捷键作用域判断。 */
function currentView() {
  const view = document.querySelector('.view:not([hidden])');
  return view ? view.id.replace(/^view-/, '') : '';
}

/** 3.7：全局键位（报告 §7.5）。切页类动作与顶栏按钮等价。
 *
 * 2026-10-24 真机缺陷：微软拼音中文态会把 Ctrl+Shift+F 当「简/繁切换」系统热键吞掉
 * keydown，`hotkeys.js` 因此加了 keyup 兜底（见该文件头 §5）。
 * 这里同时收口失败路径：`openSearch()` 的异常不再只 `log.error`，还要落到搜索页状态栏，
 * 否则用户在界面上「按了没反应」（该缺陷的第一版排查就吃过这个亏）。
 */
function runGlobalSearch() {
  openSearch().catch((error) => {
    const message = (error && error.message) || String(error);
    log.error('打开全局搜索失败：', message);
    const status = element('search-status');
    if (status) {
      status.textContent = `打开全局搜索失败：${message}`;
      status.className = 'backup__status is-error';
    }
  });
}

function registerGlobalHotkeys() {
  hotkeys.add({
    id: 'global-search',
    combo: 'ctrl+shift+f',
    scope: HOTKEY_SCOPES.GLOBAL,
    label: '全局搜索',
    run: () => {
      runGlobalSearch();
    },
  });
  hotkeys.add({
    id: 'global-backup',
    combo: 'ctrl+shift+e',
    scope: HOTKEY_SCOPES.GLOBAL,
    label: '备份与导出',
    run: () => {
      openBackup().catch((error) => log.error(error));
    },
  });
}

/** 顶栏「返回作品」：先尝试保存当前章节，再回到项目列表（2.4 会补强制保存兜底）。 */
function setupNavigation() {
  const home = document.getElementById('nav-home');
  if (home) {
    home.addEventListener('click', async () => {
      try {
        await leaveWriter();
        await leaveDocuments();
      } catch (error) {
        log.error(error);
      }
      showView('view-projects');
      loadProjects().catch((error) => log.error(error));
    });
  }

  const trash = document.getElementById('open-trash');
  if (trash) {
    trash.addEventListener('click', () => {
      openTrash().catch((error) => log.error(error));
    });
  }

  const backup = document.getElementById('open-backup');
  if (backup) {
    backup.addEventListener('click', () => {
      openBackup().catch((error) => log.error(error));
    });
  }

  const search = document.getElementById('nav-search');
  if (search) {
    search.addEventListener('click', () => {
      runGlobalSearch();
    });
  }

  window.addEventListener('inkwell:projects-refresh', () => {
    loadProjects().catch((error) => log.error(error));
  });
}

installGlobalHandlers();

runChecks()
  .then(() => {
    // 桥接与后端确认可用后再加载业务页面（P1 项目列表 / P2 写作页 / P3 设定文档）
    initWriter();
    initDocuments();
    initTrash();
    initBackup();
    initSearch();
    initSettings();
    registerGlobalHotkeys();
    installHotkeys(hotkeys, { getView: currentView });
    setupDialogs();
    setupNavigation();
    return initProjects();
  })
  .catch((error) => {
    log.error(error);
    setStatus('bridge', '失败', 'error');
    setStatus('health', error.message, 'error');
    appendLog(`自检失败：${error.message}`);
  });
