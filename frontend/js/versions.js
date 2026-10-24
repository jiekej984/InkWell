/** 版本历史面板（任务 2.6 / 页面 P5；阶段三 3.6 补差异对比）。
 *
 * 流程：列表（新→旧，含字数差异）→ 选中 → **差异对比 / 内容预览** 切换 →
 * 回滚（先存回滚前快照，文案「由 #13 回滚至 #7，生成 #14」）。
 *
 * 差异对比的算法与上限保护在 `diff.js`（纯函数，Node 单测覆盖）；
 * 这里只负责取「旧版本正文」与「当前编辑器正文」并渲染。
 */

import { request } from './api.js';
import { diffLines, htmlToText } from './diff.js';
import { createLogger } from './logger.js';
import { el } from './view.js';

const log = createLogger('versions');

const CHANGE_LABELS = {
  auto: '自动',
  manual: '手动',
  milestone: '里程碑',
  restore: '回滚',
};

function formatTime(value) {
  if (!value) {
    return '';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * @param {object} options
 * @param {() => object | null} options.getChapter 当前章节
 * @param {() => string} options.getCurrentText 当前编辑器纯文本（差异右栏）
 * @param {() => Promise<boolean>} options.ensureSaved 保存当前正文
 * @param {(event: {kind: string, data: object}) => Promise<void>} options.onChanged
 * @param {(text: string, kind?: string, options?: object) => void} options.setStatus
 */
export function initVersions({
  getChapter,
  getCurrentText,
  ensureSaved,
  onChanged,
  setStatus,
}) {
  let selected = null;
  let mode = 'diff';

  const dialog = el('versions-dialog');
  const list = el('version-list');
  const content = el('version-content');
  const tabs = el('version-tabs');
  const restoreButton = el('restore-version');
  const error = el('version-error');

  function showError(message) {
    error.textContent = message;
    error.hidden = false;
  }

  function clearError() {
    error.hidden = true;
  }

  function resetPreview() {
    selected = null;
    content.textContent = '选择一个版本查看内容';
    if (tabs) {
      tabs.hidden = true;
    }
    restoreButton.disabled = true;
  }

  function syncTabs() {
    if (!tabs) {
      return;
    }
    tabs.hidden = !selected;
    for (const button of tabs.querySelectorAll('.versions__tab')) {
      const active = button.dataset.mode === mode;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-selected', active ? 'true' : 'false');
    }
  }

  /** 差异对比：版本 #N → 当前正文；超 5 万字/段落过多时只提示、不渲染。 */
  function renderDiff(version) {
    const before = htmlToText(version.content || '');
    const after = getCurrentText ? getCurrentText() : '';
    const diff = diffLines(before, after);

    const summary = document.createElement('p');
    summary.className = 'diff__summary';
    if (diff.tooLarge) {
      summary.classList.add('is-warn');
      summary.textContent = `${diff.reason}：差异对比已省略，可切到「内容预览」。`;
      content.replaceChildren(summary);
      return;
    }

    const head = document.createElement('div');
    head.className = 'diff__head';
    const title = document.createElement('span');
    title.textContent = `版本 #${version.version_no} → 当前正文`;
    const stats = document.createElement('span');
    stats.className = 'diff__stats';
    stats.textContent = `+${diff.stats.added} −${diff.stats.removed}`;
    head.append(title, stats);
    content.replaceChildren(head);

    if (diff.rows.length === 0) {
      summary.textContent = '版本正文与当前正文一致，没有差异。';
      content.append(summary);
      return;
    }

    const box = document.createElement('div');
    box.className = 'diff';
    for (const row of diff.rows) {
      if (row.type === 'skip') {
        const skip = document.createElement('div');
        skip.className = 'diff__row diff__row--skip';
        skip.textContent = `⋯ 相同的 ${row.count} 行 ⋯`;
        box.append(skip);
        continue;
      }
      const line = document.createElement('div');
      line.className = `diff__row diff__row--${row.type}`;
      const sign = document.createElement('span');
      sign.className = 'diff__sign';
      sign.textContent = row.type === 'add' ? '+' : row.type === 'del' ? '−' : ' ';
      const text = document.createElement('span');
      text.className = 'diff__text';
      text.textContent = row.text;
      line.append(sign, text);
      box.append(line);
    }
    content.append(box);
  }

  function renderPreview(version) {
    const box = document.createElement('div');
    box.className = 'versions__preview-body';
    box.innerHTML = version.content || '<p class="versions__empty">（空章节）</p>';
    content.replaceChildren(box);
  }

  function renderSelected() {
    if (!selected) {
      return;
    }
    syncTabs();
    if (mode === 'diff') {
      renderDiff(selected);
    } else {
      renderPreview(selected);
    }
  }

  async function loadList() {
    const chapter = getChapter();
    if (!chapter) {
      return;
    }
    list.textContent = '';
    resetPreview();

    const data = await request(`/api/chapters/${chapter.id}/versions`);
    if (!data.items.length) {
      const empty = document.createElement('p');
      empty.className = 'versions__empty';
      empty.textContent = '还没有版本快照。点「存为版本」创建第一条。';
      list.append(empty);
      return;
    }

    for (const item of data.items) {
      const row = document.createElement('div');
      row.className = 'version';

      const main = document.createElement('button');
      main.type = 'button';
      main.className = 'version__main';

      const head = document.createElement('span');
      head.className = 'version__head';
      head.textContent = `#${item.version_no} · ${
        CHANGE_LABELS[item.change_type] || item.change_type
      }`;

      const meta = document.createElement('span');
      meta.className = 'version__meta';
      const diff =
        item.diff_word_count >= 0
          ? `+${item.diff_word_count}`
          : String(item.diff_word_count);
      meta.textContent = `${item.word_count} 字（${diff}）`;

      const time = document.createElement('span');
      time.className = 'version__time';
      time.textContent = formatTime(item.created_at);

      main.append(head, meta, time);
      main.addEventListener('click', () => selectVersion(item, row, main));

      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'version__delete';
      remove.textContent = '删除';
      remove.title = '删除该快照（物理删除，不可恢复）';
      remove.addEventListener('click', () => removeVersion(item));

      row.append(main, remove);
      list.append(row);
    }
  }

  async function selectVersion(item, row, main) {
    clearError();
    for (const active of list.querySelectorAll('.version.is-active')) {
      active.classList.remove('is-active');
    }
    row.classList.add('is-active');
    main.blur();
    try {
      const data = await request(`/api/versions/${item.id}`);
      selected = data;
      restoreButton.disabled = false;
      renderSelected();
    } catch (err) {
      log.error(err);
      showError(`读取版本失败：${err.message}`);
    }
  }

  async function removeVersion(item) {
    if (!window.confirm(`删除版本 #${item.version_no}？（物理删除，不可恢复）`)) {
      return;
    }
    try {
      await request(`/api/versions/${item.id}`, { method: 'DELETE' });
      await loadList();
      if (setStatus) {
        setStatus(`已删除版本 #${item.version_no}`, 'ok');
      }
    } catch (err) {
      log.error(err);
      showError(`删除失败：${err.message}`);
    }
  }

  /** 手动快照；返回快照对象或 null。 */
  async function snapshot() {
    const chapter = getChapter();
    if (!chapter) {
      if (setStatus) {
        setStatus('请先选择章节', 'error');
      }
      return null;
    }
    if (ensureSaved && !(await ensureSaved())) {
      if (setStatus) {
        setStatus('当前正文保存失败（已暂存），请稍后再存版本', 'error');
      }
      return null;
    }
    try {
      const data = await request(`/api/chapters/${chapter.id}/versions`, {
        method: 'POST',
        body: { change_type: 'manual' },
      });
      if (setStatus) {
        setStatus(`已存为版本 #${data.version_no}`, 'ok');
      }
      if (onChanged) {
        await onChanged({ kind: 'snapshot', data });
      }
      return data;
    } catch (err) {
      log.error(err);
      if (setStatus) {
        setStatus(`存版本失败：${err.message}`, 'error');
      }
      return null;
    }
  }

  async function open() {
    if (!getChapter()) {
      if (setStatus) {
        setStatus('请先选择章节', 'error');
      }
      return;
    }
    clearError();
    try {
      await loadList();
      dialog.showModal();
    } catch (err) {
      log.error(err);
      if (setStatus) {
        setStatus(`加载版本失败：${err.message}`, 'error');
      }
    }
  }

  async function restore() {
    const chapter = getChapter();
    if (!selected || !chapter) {
      return;
    }
    // BR-9 文案：由 #当前 回滚至 #目标，生成 #下一号（回滚前正文会先存快照）
    const confirmed = window.confirm(
      `由 #${chapter.version_no} 回滚至 #${selected.version_no}，生成 #${
        chapter.version_no + 1
      }。\n当前正文会先存为回滚快照（永久保留），确定回滚？`,
    );
    if (!confirmed) {
      return;
    }
    if (ensureSaved && !(await ensureSaved())) {
      showError('当前正文保存失败（已暂存），请稍后重试');
      return;
    }
    try {
      const data = await request(
        `/api/chapters/${chapter.id}/versions/${selected.id}/restore`,
        { method: 'POST' },
      );
      dialog.close();
      if (setStatus) {
        setStatus(
          `由 #${chapter.version_no} 回滚至 #${data.restored_from}，生成 #${data.version_no}`,
          'ok',
        );
      }
      if (onChanged) {
        await onChanged({ kind: 'restore', data });
      }
    } catch (err) {
      log.error(err);
      showError(`回滚失败：${err.message}`);
    }
  }

  if (tabs) {
    tabs.addEventListener('click', (event) => {
      const button = event.target.closest('.versions__tab');
      if (!button) {
        return;
      }
      mode = button.dataset.mode === 'preview' ? 'preview' : 'diff';
      renderSelected();
    });
  }

  el('open-versions').addEventListener('click', open);
  el('manual-snapshot').addEventListener('click', snapshot);
  el('close-versions').addEventListener('click', () => dialog.close());
  restoreButton.addEventListener('click', restore);

  return { open, snapshot, refresh: loadList };
}
