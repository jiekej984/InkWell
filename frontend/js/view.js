/** 单页视图切换与共享 DOM 小工具。
 *
 * 阶段二只做「同一文档内 section 显隐」，无路由与历史记录；
 * 正式页面组织与交互打磨归阶段三 3.x。
 */

/** 显示指定视图（唯一一个），并同步顶栏「返回作品」按钮。 */
export function showView(id) {
  for (const view of document.querySelectorAll('.view')) {
    view.hidden = view.id !== id;
  }
  const home = document.getElementById('nav-home');
  if (home) {
    home.hidden = id === 'view-projects';
  }
  if (id === 'view-projects') {
    setContext('');
  }
}

/** 设置顶栏右侧上下文（如当前项目名）。 */
export function setContext(text) {
  const node = document.getElementById('topbar-context');
  if (node) {
    node.textContent = text || '';
  }
}

/** 按 id 取元素（找不到返回 null，调用方负责判空）。 */
export function el(id) {
  return document.getElementById(id);
}

/** 通用文本输入对话框；确认返回字符串，取消返回 null。 */
export function askText({ title, label, value = '' }) {
  const dialog = el('prompt-dialog');
  if (dialog && dialog.open) {
    // 已有输入框在等用户：第二次调用直接返回 null，避免 showModal 抛
    // InvalidStateError 并留下旧的 submit 监听器
    return Promise.resolve(null);
  }
  return new Promise((resolve) => {
    const form = el('prompt-form');
    const input = el('prompt-input');
    const error = el('prompt-error');

    el('prompt-title').textContent = title;
    el('prompt-label').textContent = label;
    input.value = value;
    error.hidden = true;

    const onSubmit = (event) => {
      if (event.submitter && event.submitter.value === 'cancel') {
        return; // 交给 method="dialog" 关闭，returnValue=cancel
      }
      event.preventDefault();
      const text = input.value.trim();
      if (!text) {
        error.textContent = '不能为空';
        error.hidden = false;
        return;
      }
      dialog.close('ok');
    };

    const onClose = () => {
      form.removeEventListener('submit', onSubmit);
      resolve(dialog.returnValue === 'ok' ? input.value.trim() : null);
    };

    form.addEventListener('submit', onSubmit);
    dialog.addEventListener('close', onClose, { once: true });
    dialog.showModal();
    input.focus();
  });
}
