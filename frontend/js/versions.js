/** 版本历史面板（任务 2.6 / 页面 P5）。
 *
 * 列表（新→旧，含字数差异）→ 选中预览 → 回滚（先存回滚前快照）。
 * 手动快照入口在写作页顶栏（也支持 Ctrl+S：保存后立即存版本，FR-5.5）。
 */

import { request } from './api.js';
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
 * @param {() => Promise<boolean>} options.ensureSaved 保存当前正文
 * @param {(event: {kind: string, data: object}) => Promise<void>} options.onChanged
 * @param {(text: string, kind?: string) => void} options.setStatus
 */
export function initVersions({ getChapter, ensureSaved, onChanged, setStatus }) {
  let selected = null;

  const dialog = el('versions-dialog');
  const list = el('version-list');
  const preview = el('version-preview');
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
    preview.textContent = '选择一个版本查看内容';
    restoreButton.disabled = true;
    selected = null;
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
      preview.innerHTML = data.content || '<p class="versions__empty">（空章节）</p>';
      restoreButton.disabled = false;
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
    const confirmed = window.confirm(
      `回滚到版本 #${selected.version_no}？当前正文会先存为回滚快照。`,
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
        setStatus(`已回滚至 #${data.restored_from}，生成 #${data.version_no}`, 'ok');
      }
      if (onChanged) {
        await onChanged({ kind: 'restore', data });
      }
    } catch (err) {
      log.error(err);
      showError(`回滚失败：${err.message}`);
    }
  }

  el('open-versions').addEventListener('click', open);
  el('manual-snapshot').addEventListener('click', snapshot);
  el('close-versions').addEventListener('click', () => dialog.close());
  restoreButton.addEventListener('click', restore);

  return { open, snapshot, refresh: loadList };
}
