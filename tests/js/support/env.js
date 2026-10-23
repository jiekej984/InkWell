/** Node 单测用的最小浏览器环境替身（不引入 jsdom，保持零依赖）。
 *
 * 提供三样东西：
 *   · FakeClock —— 可手动推进的 setTimeout/clearTimeout，让 3s/1s/3s/9s 等时序可断言
 *   · createFakeStorage —— localStorage 替身
 *   · createDraftBackend / installFetch —— 与后端 drafts、章节正文接口同构的内存实现
 */

export class FakeClock {
  constructor() {
    this.now = 0;
    this._seq = 0;
    this._timers = new Map();
    this.setTimeout = this.setTimeout.bind(this);
    this.clearTimeout = this.clearTimeout.bind(this);
  }

  setTimeout(callback, delay = 0) {
    const id = ++this._seq;
    this._timers.set(id, {
      id,
      at: this.now + Math.max(0, delay),
      callback,
    });
    return id;
  }

  clearTimeout(id) {
    this._timers.delete(id);
  }

  get pending() {
    return this._timers.size;
  }

  /** 推进时间并执行到期回调（执行完等待微任务与事件循环排空）。 */
  async advance(ms) {
    const target = this.now + ms;
    for (;;) {
      const due = [...this._timers.values()]
        .filter((timer) => timer.at <= target)
        .sort((a, b) => a.at - b.at || a.id - b.id)[0];
      if (!due) {
        break;
      }
      this._timers.delete(due.id);
      this.now = due.at;
      due.callback();
      await flushTasks();
    }
    this.now = target;
    await flushTasks();
  }
}

/** 等待 Promise 链与计时器回调都排空。 */
export async function flushTasks() {
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
}

export function createFakeStorage() {
  const data = new Map();
  return {
    getItem(key) {
      return data.has(key) ? data.get(key) : null;
    },
    setItem(key, value) {
      data.set(key, String(value));
    },
    removeItem(key) {
      data.delete(key);
    },
    clear() {
      data.clear();
    },
    get size() {
      return data.size;
    },
    keys() {
      return [...data.keys()];
    },
  };
}

/** 安装 window 替身（含 pywebview 桥接与 localStorage），返回时钟与存储。 */
export function installWindow({ clock = new FakeClock(), storage = createFakeStorage() } = {}) {
  globalThis.window = {
    setTimeout: clock.setTimeout,
    clearTimeout: clock.clearTimeout,
    localStorage: storage,
    pywebview: { api: { get_token: async () => 'test-token' } },
  };
  return { clock, storage };
}

/** 安装 fetch 替身：handler 收到 {path, method, body, headers}，需返回 Response 形状。 */
export function installFetch(handler) {
  globalThis.fetch = async (path, options = {}) =>
    handler({
      path: String(path).split('?')[0],
      query: String(path).includes('?') ? String(path).split('?')[1] : '',
      method: String(options.method || 'GET').toUpperCase(),
      body: options.body ? JSON.parse(options.body) : undefined,
      headers: options.headers || {},
    });
}

function reply(payload, status = 200) {
  return {
    ok: status < 400,
    status,
    json: async () => payload,
  };
}

const okBody = (data) => reply({ code: 0, message: 'ok', data });
const failBody = (code, message) => reply({ code, message, data: {} });

/** 与后端 drafts / 章节正文接口同构的内存实现（只覆盖本工具用到的路径）。 */
export function createDraftBackend() {
  const drafts = new Map();
  const chapters = new Map([[1, '']]);
  const calls = [];

  return {
    drafts,
    chapters,
    calls,
    handle({ path, method, body }) {
      calls.push({ path, method, body });

      if (path === '/api/drafts' && method === 'POST') {
        if (!chapters.has(body.chapter_id)) {
          return failBody(2001, '章节不存在');
        }
        const record = {
          chapter_id: body.chapter_id,
          title: '第一章',
          content_html: body.content_html,
          client_saved_at: body.client_saved_at,
          reason: body.reason,
          saved_at: new Date().toISOString(),
        };
        drafts.set(body.chapter_id, record);
        return okBody({
          chapter_id: body.chapter_id,
          title: '第一章',
          saved_at: record.saved_at,
          reason: record.reason,
          size: JSON.stringify(record).length,
        });
      }

      if (path === '/api/drafts' && method === 'GET') {
        const items = [...drafts.values()].map(({ content_html, ...rest }) => rest);
        return okBody({ items, total: items.length });
      }

      const single = path.match(/^\/api\/drafts\/(\d+)$/);
      if (single) {
        const chapterId = Number(single[1]);
        if (method === 'DELETE') {
          if (!drafts.delete(chapterId)) {
            return failBody(2001, '暂存不存在');
          }
          return okBody({ chapter_id: chapterId, deleted: true });
        }
        const record = drafts.get(chapterId);
        return record ? okBody(record) : failBody(2001, '暂存不存在');
      }

      const content = path.match(/^\/api\/chapters\/(\d+)\/content$/);
      if (content && method === 'PUT') {
        const chapterId = Number(content[1]);
        if (!chapters.has(chapterId)) {
          return failBody(2001, '章节不存在');
        }
        chapters.set(chapterId, body.content_html);
        return okBody({
          version_no: 2,
          word_count: 0,
          project_word_count: 0,
        });
      }

      return failBody(1001, `未模拟的请求 ${method} ${path}`);
    },
  };
}

/** 静默 logger（测试不关心控制台噪音）。 */
export const silentLog = { info() {}, warn() {}, error() {} };
