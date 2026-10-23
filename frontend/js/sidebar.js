/** 大纲树（任务 3.2 / FR-2.1~2.5 / BR-3 / BR-6）。
 *
 * 由 writer.js 拆分而来，负责：
 *   · 卷折叠/展开（按项目记忆到 localStorage）
 *   · 右键菜单：卷/章重命名、新建章节、删除、标记定稿、章节信息
 *   · 拖拽排序（卷内 / 跨卷）；卷本身也可拖动排序
 *   · 键盘操作：↑↓ 选章、←→ 折叠/展开、F2 重命名、Delete 删除、Enter 打开
 *   · 非空卷二选一删除（移入默认卷 / 一并删除）
 *   · C-04：创建首个命名卷时，确认后把默认卷章节一次性迁入
 */

import { request } from './api.js';
import { createLogger } from './logger.js';
import { askText, el } from './view.js';

const log = createLogger('sidebar');
const COLLAPSE_KEY = 'inkwell:tree:collapsed:';
const STATUS_LABELS = { draft: '草稿', first: '初稿', final: '定稿' };

function isFiniteId(value) {
  return Number.isInteger(Number(value)) && Number(value) > 0;
}

/**
 * @param {object} options
 * @param {() => object | null} options.getTree
 * @param {() => number} options.getProjectId
 * @param {() => number | null} options.getChapterId
 * @param {(id: number) => Promise<void>} options.onOpenChapter
 * @param {() => Promise<object>} options.onReload
 * @param {(chapter: object) => Promise<object | null>} options.onMarkFinal
 * @param {(id: number, patch: object) => void} options.onChapterUpdated
 * @param {() => void} options.onDeletedCurrent
 * @param {(text: string, kind?: string) => void} options.setStatus
 */
export function initSidebar({
  getTree,
  getProjectId,
  getChapterId,
  onOpenChapter,
  onReload,
  onMarkFinal,
  onChapterUpdated,
  onDeletedCurrent,
  setStatus,
}) {
  const root = el('chapter-tree');
  const menu = el('tree-menu');
  const infoDialog = el('chapter-info-dialog');
  const infoForm = el('chapter-info-form');
  const infoName = el('chapter-info-name');
  const infoStatus = el('chapter-info-status');
  const infoTarget = el('chapter-info-target');
  const infoSummary = el('chapter-info-summary');
  const infoError = el('chapter-info-error');

  const deleteDialog = el('volume-delete-dialog');
  const deleteForm = el('volume-delete-form');
  const deleteText = el('volume-delete-text');

  let currentTree = null;
  let editingChapter = null;
  let deletingVolume = null;
  let collapsed = new Set();
  let drag = null;

  // --------------------------------------------------------------------------
  // 数据辅助
  // --------------------------------------------------------------------------

  function volumes() {
    if (!currentTree) {
      return [];
    }
    return currentTree.volumes.length > 0
      ? currentTree.volumes
      : [currentTree.default_volume];
  }

  function findChapter(chapterId) {
    for (const volume of volumes()) {
      const chapter = volume.chapters.find((item) => item.id === chapterId);
      if (chapter) {
        return { volume, chapter };
      }
    }
    return null;
  }

  function findVolume(volumeId) {
    return volumes().find((volume) => volume.id === volumeId) || null;
  }

  function collapseKey() {
    return `${COLLAPSE_KEY}${getProjectId() || 'unknown'}`;
  }

  function loadCollapsed() {
    try {
      const raw = window.localStorage.getItem(collapseKey());
      const ids = raw ? JSON.parse(raw) : [];
      return new Set((Array.isArray(ids) ? ids : []).filter(isFiniteId).map(Number));
    } catch {
      return new Set();
    }
  }

  function saveCollapsed() {
    try {
      window.localStorage.setItem(
        collapseKey(),
        JSON.stringify([...collapsed]),
      );
    } catch {
      // 隐私模式/超配额：折叠状态不持久化，不影响使用
    }
  }

  function setCollapsed(volumeId, value) {
    if (value) {
      collapsed.add(volumeId);
    } else {
      collapsed.delete(volumeId);
    }
    saveCollapsed();
    const section = root?.querySelector(
      `.volume[data-volume-id="${volumeId}"]`,
    );
    if (section) {
      section.classList.toggle('is-collapsed', value);
      const toggle = section.querySelector('.volume__toggle');
      if (toggle) {
        toggle.setAttribute('aria-expanded', String(!value));
      }
    }
  }

  function activeSection(volumeId) {
    return root?.querySelector(`.volume[data-volume-id="${volumeId}"]`);
  }

  // --------------------------------------------------------------------------
  // 渲染
  // --------------------------------------------------------------------------

  function buildChapter(chapter, volume) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'tree__chapter';
    button.dataset.chapterId = String(chapter.id);
    button.draggable = true;
    button.title = `${STATUS_LABELS[chapter.status] || chapter.status} · ${chapter.word_count} 字`;

    const name = document.createElement('span');
    name.className = 'tree__name';
    name.textContent = chapter.title;

    const count = document.createElement('span');
    count.className = 'tree__count';
    count.textContent = `${chapter.word_count} 字`;

    button.append(name, count);
    if (chapter.status === 'final') {
      const flag = document.createElement('span');
      flag.className = 'tree__flag';
      flag.textContent = '定稿';
      button.append(flag);
    }

    button.addEventListener('click', () => onOpenChapter(chapter.id));
    button.addEventListener('contextmenu', (event) => {
      event.preventDefault();
      openChapterMenu(event.clientX, event.clientY, chapter, volume);
    });
    button.addEventListener('keydown', (event) =>
      handleChapterKey(event, chapter, volume, button),
    );

    button.addEventListener('dragstart', (event) => {
      drag = { kind: 'chapter', id: chapter.id };
      button.classList.add('is-dragging');
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', String(chapter.id));
    });
    button.addEventListener('dragend', () => {
      drag = null;
      button.classList.remove('is-dragging');
      clearDropMarks();
    });
    button.addEventListener('dragover', (event) => {
      if (!drag || drag.kind !== 'chapter' || drag.id === chapter.id) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      const rect = button.getBoundingClientRect();
      const before = event.clientY < rect.top + rect.height / 2;
      clearDropMarks();
      button.classList.add(before ? 'is-drop-before' : 'is-drop-after');
      drag.target = { volume, chapter, before };
      event.dataTransfer.dropEffect = 'move';
    });
    button.addEventListener('drop', (event) => {
      if (!drag || drag.kind !== 'chapter' || drag.id === chapter.id) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      const target = drag.target;
      const dragged = drag.id;
      clearDropMarks();
      if (target) {
        moveChapter(dragged, target.volume.id, target.chapter.id, target.before);
      }
    });

    return button;
  }

  function buildVolume(volume) {
    const section = document.createElement('section');
    section.className = 'volume';
    section.dataset.volumeId = String(volume.id);
    if (collapsed.has(volume.id)) {
      section.classList.add('is-collapsed');
    }

    const header = document.createElement('div');
    header.className = 'volume__header';
    header.dataset.volumeId = String(volume.id);

    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'volume__toggle';
    toggle.textContent = '▾';
    toggle.setAttribute('aria-expanded', String(!collapsed.has(volume.id)));
    toggle.setAttribute('aria-label', `折叠或展开「${volume.title}」`);
    toggle.addEventListener('click', (event) => {
      event.stopPropagation();
      setCollapsed(volume.id, !collapsed.has(volume.id));
    });
    toggle.addEventListener('keydown', (event) => {
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        section.querySelector('.tree__chapter')?.focus();
      }
    });

    const title = document.createElement('span');
    title.className = 'volume__title';
    title.textContent = volume.title;
    title.title = `${volume.chapter_count || 0} 章 · ${volume.word_count || 0} 字`;
    title.addEventListener('click', () =>
      setCollapsed(volume.id, !collapsed.has(volume.id)),
    );

    const add = document.createElement('button');
    add.type = 'button';
    add.className = 'tree__add';
    add.textContent = '＋章';
    add.title = `在「${volume.title}」新建章节`;
    add.addEventListener('click', (event) => {
      event.stopPropagation();
      createChapter(volume);
    });

    header.append(toggle, title, add);
    header.addEventListener('contextmenu', (event) => {
      event.preventDefault();
      openVolumeMenu(event.clientX, event.clientY, volume);
    });

    if (!volume.is_default && currentTree.volumes.length > 1) {
      header.draggable = true;
      header.addEventListener('dragstart', (event) => {
        drag = { kind: 'volume', id: volume.id };
        section.classList.add('is-dragging');
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', `volume:${volume.id}`);
      });
      header.addEventListener('dragend', () => {
        drag = null;
        section.classList.remove('is-dragging');
        clearDropMarks();
      });
      header.addEventListener('dragover', (event) => {
        if (!drag || drag.kind !== 'volume' || drag.id === volume.id) {
          return;
        }
        event.preventDefault();
        const rect = header.getBoundingClientRect();
        const before = event.clientY < rect.top + rect.height / 2;
        clearDropMarks();
        header.classList.add(before ? 'is-drop-before' : 'is-drop-after');
        drag.target = { volume, before };
        event.dataTransfer.dropEffect = 'move';
      });
      header.addEventListener('drop', (event) => {
        if (!drag || drag.kind !== 'volume' || drag.id === volume.id) {
          return;
        }
        event.preventDefault();
        const target = drag.target;
        const dragged = drag.id;
        clearDropMarks();
        if (target) {
          moveVolume(dragged, target.volume.id, target.before);
        }
      });
    }

    const list = document.createElement('div');
    list.className = 'volume__chapters';

    if (volume.chapters.length === 0) {
      const empty = document.createElement('p');
      empty.className = 'tree__empty';
      empty.textContent = '暂无章节';
      list.append(empty);
    } else {
      for (const chapter of volume.chapters) {
        list.append(buildChapter(chapter, volume));
      }
    }

    // 拖到卷标题/空白处 = 追加到该卷末尾
    header.addEventListener('dragover', (event) => {
      if (!drag || drag.kind !== 'chapter') {
        return;
      }
      event.preventDefault();
      section.classList.add('is-drop-target');
      drag.target = null;
      drag.appendTo = { volume };
      event.dataTransfer.dropEffect = 'move';
    });
    header.addEventListener('dragleave', () => {
      section.classList.remove('is-drop-target');
    });
    header.addEventListener('drop', (event) => {
      if (!drag || drag.kind !== 'chapter' || !drag.appendTo) {
        return;
      }
      event.preventDefault();
      section.classList.remove('is-drop-target');
      const dragged = drag.id;
      const volumeTarget = drag.appendTo.volume;
      drag.appendTo = null;
      moveChapter(dragged, volumeTarget.id, null, false);
    });

    section.append(header, list);
    return section;
  }

  function render(tree) {
    currentTree = tree;
    if (!root) {
      return;
    }
    collapsed = loadCollapsed();
    const focusedChapter = Number(
      document.activeElement?.dataset?.chapterId || 0,
    );
    const focusedVolume = Number(
      document.activeElement?.dataset?.volumeId || 0,
    );

    root.textContent = '';
    for (const volume of volumes()) {
      root.append(buildVolume(volume));
    }
    setActive(getChapterId());

    if (focusedChapter) {
      root
        .querySelector(`.tree__chapter[data-chapter-id="${focusedChapter}"]`)
        ?.focus();
    } else if (focusedVolume) {
      activeSection(focusedVolume)?.querySelector('.volume__toggle')?.focus();
    }
  }

  function setActive(chapterId) {
    if (!root) {
      return;
    }
    for (const node of root.querySelectorAll('.tree__chapter')) {
      node.classList.toggle(
        'is-active',
        Number(node.dataset.chapterId) === chapterId,
      );
    }
  }

  /** 保存后增量更新（避免每次自动保存都全量重绘）。 */
  function updateChapter(chapterId, patch) {
    const button = root?.querySelector(
      `.tree__chapter[data-chapter-id="${chapterId}"]`,
    );
    if (!button) {
      return;
    }
    if ('title' in patch && patch.title) {
      const name = button.querySelector('.tree__name');
      if (name) {
        name.textContent = patch.title;
      }
    }
    if ('word_count' in patch) {
      const count = button.querySelector('.tree__count');
      if (count) {
        count.textContent = `${patch.word_count} 字`;
      }
    }
    if ('status' in patch) {
      const existing = button.querySelector('.tree__flag');
      if (patch.status === 'final' && !existing) {
        const flag = document.createElement('span');
        flag.className = 'tree__flag';
        flag.textContent = '定稿';
        button.append(flag);
      } else if (patch.status !== 'final' && existing) {
        existing.remove();
      }
    }
  }

  function clearDropMarks() {
    if (!root) {
      return;
    }
    for (const node of root.querySelectorAll(
      '.is-drop-before, .is-drop-after, .is-drop-target',
    )) {
      node.classList.remove('is-drop-before', 'is-drop-after', 'is-drop-target');
    }
  }

  // --------------------------------------------------------------------------
  // 右键菜单
  // --------------------------------------------------------------------------

  function closeMenu() {
    if (!menu || menu.hidden) {
      return;
    }
    menu.hidden = true;
    menu.textContent = '';
  }

  function openMenu(x, y, items) {
    if (!menu) {
      return;
    }
    menu.textContent = '';
    for (const item of items) {
      if (item.separator) {
        const separator = document.createElement('div');
        separator.className = 'menu__separator';
        menu.append(separator);
        continue;
      }
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `menu__item${item.danger ? ' menu__item--danger' : ''}`;
      button.textContent = item.label;
      button.disabled = Boolean(item.disabled);
      button.setAttribute('role', 'menuitem');
      button.addEventListener('click', () => {
        closeMenu();
        if (item.action) {
          Promise.resolve(item.action()).catch((error) => {
            log.error(error);
            setStatus(`操作失败：${error.message}`, 'error');
          });
        }
      });
      menu.append(button);
    }

    menu.hidden = false;
    menu.style.left = `${x}px`;
    menu.style.top = `${y}px`;
    const rect = menu.getBoundingClientRect();
    menu.style.left = `${Math.max(8, Math.min(x, window.innerWidth - rect.width - 8))}px`;
    menu.style.top = `${Math.max(8, Math.min(y, window.innerHeight - rect.height - 8))}px`;
    menu.querySelector('.menu__item:not(:disabled)')?.focus();
  }

  function openChapterMenu(x, y, chapter, volume) {
    openMenu(x, y, [
      { label: '打开', action: () => onOpenChapter(chapter.id) },
      {
        label: '重命名…',
        action: () => openChapterInfo(chapter, { focusTitle: true }),
      },
      { label: '章节信息…', action: () => openChapterInfo(chapter) },
      {
        label: chapter.status === 'final' ? '已定稿' : '标记定稿',
        disabled: chapter.status === 'final',
        action: () => markFinal(chapter),
      },
      { separator: true },
      {
        label: '删除章节…',
        danger: true,
        action: () => deleteChapter(chapter),
      },
    ]);
    void volume;
  }

  function openVolumeMenu(x, y, volume) {
    const items = [
      {
        label: '在此卷新建章节',
        action: () => createChapter(volume),
      },
      {
        label: collapsed.has(volume.id) ? '展开' : '折叠',
        action: () => setCollapsed(volume.id, !collapsed.has(volume.id)),
      },
    ];
    if (!volume.is_default) {
      items.unshift(
        {
          label: '重命名卷…',
          action: () => renameVolume(volume),
        },
        { separator: true },
      );
      items.push(
        { separator: true },
        {
          label: '删除卷…',
          danger: true,
          action: () => deleteVolume(volume),
        },
      );
    }
    openMenu(x, y, items);
  }

  // --------------------------------------------------------------------------
  // 章节信息对话框
  // --------------------------------------------------------------------------

  function openChapterInfo(chapter, { focusTitle = false } = {}) {
    editingChapter = chapter;
    infoName.value = chapter.title;
    infoStatus.value = chapter.status || 'draft';
    infoTarget.value = String(chapter.target_word_count || 0);
    infoSummary.value = chapter.summary || '';
    infoError.hidden = true;
    infoDialog.showModal();
    if (focusTitle) {
      infoName.focus();
      infoName.select();
    } else {
      infoStatus.focus();
    }
  }

  async function saveChapterInfo() {
    if (!editingChapter) {
      return;
    }
    const title = infoName.value.trim();
    if (!title) {
      infoError.textContent = '标题不能为空';
      infoError.hidden = false;
      return;
    }
    const payload = {
      title,
      status: infoStatus.value,
      summary: infoSummary.value,
      target_word_count: Number(infoTarget.value) || 0,
    };
    try {
      await request(`/api/chapters/${editingChapter.id}`, {
        method: 'PATCH',
        body: payload,
      });
      onChapterUpdated(editingChapter.id, payload);
      infoDialog.close('ok');
      await onReload();
      setStatus('章节信息已保存', 'ok');
    } catch (error) {
      infoError.textContent = error.message;
      infoError.hidden = false;
    }
  }

  // --------------------------------------------------------------------------
  // 动作
  // --------------------------------------------------------------------------

  async function createChapter(volume) {
    const title = await askText({
      title: '新建章节',
      label: '章节标题',
      value: `第${volume.chapters.length + 1}章`,
    });
    if (!title) {
      return;
    }
    try {
      const chapter = await request(`/api/volumes/${volume.id}/chapters`, {
        method: 'POST',
        body: { title },
      });
      setCollapsed(volume.id, false);
      await onReload();
      setStatus('已新建章节', 'ok');
      await onOpenChapter(chapter.id);
    } catch (error) {
      log.error(error);
      setStatus(`新建章节失败：${error.message}`, 'error');
    }
  }

  async function renameVolume(volume) {
    const title = await askText({
      title: '重命名卷',
      label: '卷名',
      value: volume.title,
    });
    if (!title || title === volume.title) {
      return;
    }
    try {
      await request(`/api/volumes/${volume.id}`, {
        method: 'PATCH',
        body: { title },
      });
      await onReload();
      setStatus('卷名已更新', 'ok');
    } catch (error) {
      log.error(error);
      setStatus(`重命名失败：${error.message}`, 'error');
    }
  }

  async function createVolume() {
    const title = await askText({ title: '新建卷', label: '卷名' });
    if (!title) {
      return;
    }
    const projectId = getProjectId();
    const current = getTree();
    const firstNamed = current && current.volumes.length === 0;
    const defaultCount = current ? current.default_volume.chapters.length : 0;
    let adopt = false;
    if (firstNamed && defaultCount > 0) {
      adopt = window.confirm(
        `默认卷里还有 ${defaultCount} 章。是否一并移入新卷？\n` +
          '取消则保留在默认卷（大纲树中不显示）。',
      );
    }
    try {
      const volume = await request(`/api/projects/${projectId}/volumes`, {
        method: 'POST',
        body: { title },
      });
      let message = '已新建卷';
      if (adopt) {
        const result = await request(
          `/api/volumes/${volume.id}/adopt-default`,
          { method: 'POST' },
        );
        message = `已新建卷并迁入 ${result.moved} 章`;
      }
      setCollapsed(volume.id, false);
      await onReload();
      setStatus(message, 'ok');
    } catch (error) {
      log.error(error);
      setStatus(`新建卷失败：${error.message}`, 'error');
    }
  }

  async function deleteChapter(chapter) {
    const confirmed = window.confirm(
      `删除章节「${chapter.title}」？可在回收站恢复。`,
    );
    if (!confirmed) {
      return;
    }
    try {
      await request(`/api/chapters/${chapter.id}`, { method: 'DELETE' });
      if (chapter.id === getChapterId()) {
        onDeletedCurrent();
      }
      await onReload();
      setStatus('章节已移入回收站', 'ok');
    } catch (error) {
      log.error(error);
      setStatus(`删除失败：${error.message}`, 'error');
    }
  }

  function deleteVolume(volume) {
    if (volume.is_default) {
      return;
    }
    if ((volume.chapter_count || 0) === 0) {
      if (!window.confirm(`删除空卷「${volume.title}」？`)) {
        return;
      }
      performDeleteVolume(volume, 'cascade');
      return;
    }
    deletingVolume = volume;
    deleteText.textContent = `「${volume.title}」还有 ${volume.chapter_count} 章，请选择处理方式：`;
    deleteDialog.showModal();
  }

  async function performDeleteVolume(volume, mode) {
    try {
      await request(`/api/volumes/${volume.id}?mode=${mode}`, {
        method: 'DELETE',
      });
      const hasCurrent = volume.chapters.some(
        (chapter) => chapter.id === getChapterId(),
      );
      if (hasCurrent) {
        onDeletedCurrent();
      }
      await onReload();
      setStatus(
        mode === 'move' ? '卷已删除，章节移入默认卷' : '卷与章节已移入回收站',
        'ok',
      );
    } catch (error) {
      log.error(error);
      setStatus(`删除卷失败：${error.message}`, 'error');
    } finally {
      deletingVolume = null;
    }
  }

  async function markFinal(chapter) {
    try {
      const data = await onMarkFinal(chapter);
      if (!data) {
        setStatus('标记定稿失败：请先确保正文保存成功', 'error');
        return;
      }
      await request(`/api/chapters/${chapter.id}`, {
        method: 'PATCH',
        body: { status: 'final' },
      });
      await onReload();
      setStatus(`已标记定稿，生成里程碑版本 #${data.version_no}`, 'ok');
    } catch (error) {
      log.error(error);
      setStatus(`标记定稿失败：${error.message}`, 'error');
    }
  }

  async function moveChapter(chapterId, targetVolumeId, targetChapterId, before) {
    const found = findChapter(chapterId);
    const targetVolume = findVolume(targetVolumeId);
    if (!found || !targetVolume) {
      return;
    }
    const siblings = targetVolume.chapters.filter(
      (chapter) => chapter.id !== chapterId,
    );
    let prevId = null;
    let nextId = null;
    if (targetChapterId) {
      const index = siblings.findIndex(
        (chapter) => chapter.id === targetChapterId,
      );
      if (index < 0) {
        return;
      }
      if (before) {
        nextId = siblings[index].id;
        prevId = index > 0 ? siblings[index - 1].id : null;
      } else {
        prevId = siblings[index].id;
        nextId = index + 1 < siblings.length ? siblings[index + 1].id : null;
      }
    } else {
      prevId = siblings.length ? siblings[siblings.length - 1].id : null;
    }
    try {
      await request(`/api/volumes/${targetVolumeId}/chapters/reorder`, {
        method: 'POST',
        body: {
          chapter_id: chapterId,
          prev_id: prevId,
          next_id: nextId,
          target_volume_id: targetVolumeId,
        },
      });
      setCollapsed(targetVolumeId, false);
      await onReload();
      setStatus(`已移动「${found.chapter.title}」`, 'ok');
    } catch (error) {
      log.error(error);
      setStatus(`移动失败：${error.message}`, 'error');
    } finally {
      drag = null;
      clearDropMarks();
    }
  }

  async function moveVolume(volumeId, targetVolumeId, before) {
    const list = (getTree()?.volumes || []).filter(
      (volume) => volume.id !== volumeId,
    );
    const index = list.findIndex((volume) => volume.id === targetVolumeId);
    if (index < 0) {
      return;
    }
    let prevId = null;
    let nextId = null;
    if (before) {
      nextId = list[index].id;
      prevId = index > 0 ? list[index - 1].id : null;
    } else {
      prevId = list[index].id;
      nextId = index + 1 < list.length ? list[index + 1].id : null;
    }
    try {
      await request(`/api/projects/${getProjectId()}/volumes/reorder`, {
        method: 'POST',
        body: { volume_id: volumeId, prev_id: prevId, next_id: nextId },
      });
      await onReload();
      setStatus('卷顺序已更新', 'ok');
    } catch (error) {
      log.error(error);
      setStatus(`卷排序失败：${error.message}`, 'error');
    } finally {
      drag = null;
      clearDropMarks();
    }
  }

  // --------------------------------------------------------------------------
  // 键盘导航
  // --------------------------------------------------------------------------

  function visibleChapters() {
    if (!root) {
      return [];
    }
    return [...root.querySelectorAll('.tree__chapter')].filter(
      (node) => node.offsetParent !== null,
    );
  }

  function handleChapterKey(event, chapter, volume, button) {
    const key = event.key;
    if (key === 'ArrowDown' || key === 'ArrowUp') {
      event.preventDefault();
      const list = visibleChapters();
      const index = list.indexOf(button);
      const next = list[index + (key === 'ArrowDown' ? 1 : -1)];
      next?.focus();
      return;
    }
    if (key === 'Home' || key === 'End') {
      event.preventDefault();
      const list = visibleChapters();
      (key === 'Home' ? list[0] : list[list.length - 1])?.focus();
      return;
    }
    if (key === 'ArrowLeft') {
      event.preventDefault();
      if (!collapsed.has(volume.id)) {
        setCollapsed(volume.id, true);
      } else {
        activeSection(volume.id)?.querySelector('.volume__toggle')?.focus();
      }
      return;
    }
    if (key === 'ArrowRight') {
      event.preventDefault();
      setCollapsed(volume.id, false);
      return;
    }
    if (key === 'F2') {
      event.preventDefault();
      openChapterInfo(chapter, { focusTitle: true });
      return;
    }
    if (key === 'Delete') {
      event.preventDefault();
      deleteChapter(chapter);
    }
  }

  // --------------------------------------------------------------------------
  // 事件绑定
  // --------------------------------------------------------------------------

  if (infoForm) {
    infoForm.addEventListener('submit', (event) => {
      if (event.submitter && event.submitter.value !== 'ok') {
        return;
      }
      event.preventDefault();
      saveChapterInfo();
    });
  }

  if (deleteForm) {
    deleteForm.addEventListener('submit', (event) => {
      const value = event.submitter ? event.submitter.value : 'cancel';
      if (!deletingVolume) {
        return;
      }
      if (value === 'cancel') {
        return;
      }
      event.preventDefault();
      const volume = deletingVolume;
      deleteDialog.close();
      performDeleteVolume(volume, value === 'move' ? 'move' : 'cascade');
    });
  }

  document.addEventListener('click', (event) => {
    if (menu && !menu.hidden && !menu.contains(event.target)) {
      closeMenu();
    }
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && menu && !menu.hidden) {
      closeMenu();
    }
  });
  window.addEventListener('blur', closeMenu);
  window.addEventListener('resize', closeMenu);
  document.addEventListener('scroll', closeMenu, true);
  menu?.addEventListener('keydown', (event) => {
    const items = [...menu.querySelectorAll('.menu__item:not(:disabled)')];
    const index = items.indexOf(document.activeElement);
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      items[(index + 1) % items.length]?.focus();
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      items[(index - 1 + items.length) % items.length]?.focus();
    } else if (event.key === 'Tab') {
      closeMenu();
    }
  });

  el('add-volume')?.addEventListener('click', createVolume);
  el('add-chapter')?.addEventListener('click', () => {
    const list = volumes();
    const current = list.find((volume) =>
      volume.chapters.some((chapter) => chapter.id === getChapterId()),
    );
    const target = current || list[0];
    if (target) {
      createChapter(target);
    }
  });

  return { render, setActive, updateChapter, createVolume, createChapter };
}
