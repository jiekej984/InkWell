/** 列表三态（加载 / 空 / 出错）的统一渲染（阶段三 3.6：P6 / P7 / P8）。

 * 只负责把状态画进容器，不关心业务；「重试」回调由调用方提供。
 * 容器在加载期间带 `aria-busy="true"`，读屏不会把它当成空列表。
 */
function mount(container, className) {
  container.textContent = '';
  container.removeAttribute('aria-busy');
  const box = document.createElement('div');
  box.className = `list-state ${className}`;
  container.append(box);
  return box;
}

export function showLoading(container, text = '加载中…') {
  const box = mount(container, 'list-state--loading');
  container.setAttribute('aria-busy', 'true');
  box.textContent = text;
  return box;
}

export function showEmpty(container, text) {
  const box = mount(container, 'list-state--empty');
  box.textContent = text;
  return box;
}

export function showError(container, message, onRetry = null) {
  const box = mount(container, 'list-state--error');
  const text = document.createElement('p');
  text.className = 'list-state__message';
  text.textContent = message;
  box.append(text);
  if (onRetry) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn btn--small';
    button.textContent = '重试';
    button.addEventListener('click', onRetry);
    box.append(button);
  }
  return box;
}

/** 请求结束后清掉 loading 标记（成功/失败都要调用）。 */
export function clearBusy(container) {
  if (container) {
    container.removeAttribute('aria-busy');
  }
}
