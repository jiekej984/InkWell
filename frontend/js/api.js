/** 统一 API 客户端。
 *
 * 约定（§6.1）：
 *   · 业务接口经头 X-Inkwell-Token 鉴权，token 不入 URL（NFR-S2）
 *   · 统一响应 { code, message, data }，code=0 视为成功
 *   · 页面由后端同源提供，因此使用相对路径
 *
 * token 通过 pywebview 的 js_api 桥接获取，不出现在地址栏或任何日志里。
 */

const TOKEN_HEADER = 'X-Inkwell-Token';
const DEFAULT_TIMEOUT_MS = 10000;

let cachedToken = null;

/** 带 10 秒超时的 fetch（§6.1 普通接口超时假设；超时明确报错不静默挂起）。 */
async function fetchWithTimeout(path, options = {}, timeoutMs = DEFAULT_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(path, { ...options, signal: controller.signal });
  } catch (error) {
    if (error && error.name === 'AbortError') {
      throw new Error(
        `${options.method || 'GET'} ${path} 请求超时（${timeoutMs / 1000} 秒）`,
      );
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

/** 等待 pywebview 桥接就绪。
 *
 * pywebview 官方说明：window.pywebview.api 不保证在 window.onload 时可用，
 * 必须订阅 window 的 pywebviewready 事件。
 */
export function waitForBridge(timeoutMs = 5000) {
  if (window.pywebview && window.pywebview.api) {
    return Promise.resolve(window.pywebview.api);
  }
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(new Error('pywebview 桥接超时'));
    }, timeoutMs);
    window.addEventListener(
      'pywebviewready',
      () => {
        clearTimeout(timer);
        resolve(window.pywebview.api);
      },
      { once: true },
    );
  });
}

/** 获取一次性 token（带缓存）。 */
export async function getToken() {
  if (cachedToken) {
    return cachedToken;
  }
  const api = await waitForBridge();
  cachedToken = await api.get_token();
  return cachedToken;
}

/** 是否为开发模式（决定前端是否放开调试入口）。 */
export async function isDev() {
  const api = await waitForBridge();
  return api.is_dev();
}

/** 打开数据目录（P9 / C-07，3.6）。
 *
 * 桥接方法只接受「打开固定数据目录」，前端不传路径（避免任意路径打开）。
 */
export async function openDataDir() {
  const api = await waitForBridge();
  if (typeof api.open_data_dir !== 'function') {
    throw new Error('当前环境不支持打开数据目录（缺少桥接方法 open_data_dir）');
  }
  return api.open_data_dir();
}

/** 上传文件（multipart/form-data）。
 *
 * 注意：不要手动设置 Content-Type，必须让浏览器自动带上 boundary，
 * 否则服务端无法解析分段，python-multipart 会直接拒绝。
 */
export async function requestForm(path, formData, method = 'POST') {
  const token = await getToken();
  const response = await fetchWithTimeout(path, {
    method,
    headers: { [TOKEN_HEADER]: token },
    body: formData,
  });

  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload || payload.code !== 0) {
    const reason = payload
      ? `code=${payload.code} ${payload.message}`
      : `HTTP ${response.status}`;
    throw new Error(`${method} ${path} 失败：${reason}`);
  }
  return payload.data;
}

/** 发起一次统一响应格式的请求；非 0 时抛错。 */
export async function request(path, { method = 'GET', body } = {}) {
  const token = await getToken();
  const headers = { [TOKEN_HEADER]: token };
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }

  const response = await fetchWithTimeout(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload || payload.code !== 0) {
    const reason = payload ? `code=${payload.code} ${payload.message}` : `HTTP ${response.status}`;
    throw new Error(`${method} ${path} 失败：${reason}`);
  }
  return payload.data;
}

/** 下载二进制响应（诊断包）。 */
export async function requestBlob(path, timeoutMs = DEFAULT_TIMEOUT_MS) {
  const token = await getToken();
  const response = await fetchWithTimeout(
    path,
    { headers: { [TOKEN_HEADER]: token } },
    timeoutMs,
  );
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const reason = payload
      ? `code=${payload.code} ${payload.message}`
      : `HTTP ${response.status}`;
    throw new Error(`GET ${path} 失败：${reason}`);
  }
  return response.blob();
}
