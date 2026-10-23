/** 展示层格式化纯函数（阶段三 3.3）。
 *
 * 单独成文件的原因：这些规则全部是「输入 → 输出」的纯计算，不碰 DOM，
 * 因此可以直接在 `tests/js/format.test.js` 里用 Node 断言（阶段三 DoD 第 1 条：
 * 新增交互逻辑优先抽纯函数）。
 *
 * 时间口径：服务端一律返回 ISO 8601 UTC（§6.1），这里只负责按**本地时区**
 * 折算成人能读的相对时间。`now` 参数显式传入，便于测试固定时钟。
 */

const MINUTE_MS = 60 * 1000;
const HOUR_MS = 60 * MINUTE_MS;

/** 把 ISO 字符串 / Date / 毫秒数转成毫秒时间戳；无法解析返回 null。 */
function toMillis(value) {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  if (value instanceof Date) {
    const time = value.getTime();
    return Number.isFinite(time) ? time : null;
  }
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : null;
  }
  const time = new Date(String(value)).getTime();
  return Number.isFinite(time) ? time : null;
}

function pad2(value) {
  return String(value).padStart(2, '0');
}

/** 本地日期键（YYYY-MM-DD），用于判断「今天 / 昨天」。 */
function dayKey(date) {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
}

function hourMinute(date) {
  return `${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
}

/**
 * 相对时间：刚刚 / N 分钟前 / 今天 HH:MM / 昨天 HH:MM / MM-DD / YYYY-MM-DD。
 *
 * @param {string|number|Date|null} value ISO 时间
 * @param {string|number|Date} [now] 当前时间（默认取系统时钟，测试可固定）
 * @returns {string} 空字符串表示时间未知/不可解析
 */
export function relativeTime(value, now = Date.now()) {
  const time = toMillis(value);
  if (time === null) {
    return '';
  }
  const current = toMillis(now);
  if (current === null) {
    return '';
  }

  const diff = current - time;
  // 一分钟以内（含系统时间回拨造成的「未来时间」）一律当作刚刚
  if (Math.abs(diff) < MINUTE_MS) {
    return '刚刚';
  }
  if (diff > 0 && diff < HOUR_MS) {
    return `${Math.floor(diff / MINUTE_MS)} 分钟前`;
  }

  const date = new Date(time);
  const today = new Date(current);
  const yesterday = new Date(current);
  yesterday.setDate(yesterday.getDate() - 1);

  const key = dayKey(date);
  if (key === dayKey(today)) {
    return `今天 ${hourMinute(date)}`;
  }
  if (key === dayKey(yesterday)) {
    return `昨天 ${hourMinute(date)}`;
  }
  if (date.getFullYear() === today.getFullYear()) {
    return `${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
  }
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
}

/** 封面缺失时的占位字：书名首字（跳过书名号与前导空白），书名空则回退「书」。 */
export function initialOf(title) {
  const text = String(title ?? '')
    .replace(/^[\s《「『]+/, '')
    .trim();
  if (!text) {
    return '书';
  }
  // Array.from 按码点切分，避免把 emoji / 生僻字拆成半个代理对
  return Array.from(text)[0];
}

function ratio(value) {
  // null / undefined / 空串表示「没有进度」（未设目标字数），与 0 区分
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return null;
  }
  return Math.min(1, Math.max(0, number));
}

/** 进度条宽度（0~100 的数值，直接给 CSS width 用）；未知返回 0。 */
export function progressPercent(progress) {
  const value = ratio(progress);
  return value === null ? 0 : value * 100;
}

/**
 * 进度文案：FR-1.3 规定未设目标字数则不显示进度条，因此 `null` 返回空串。
 * 有进度但不足 1% 时显示「<1%」，避免四舍五入成 0% 看起来像没开始。
 */
export function percentLabel(progress) {
  const value = ratio(progress);
  if (value === null) {
    return '';
  }
  const percent = value * 100;
  if (percent > 0 && percent < 1) {
    return '<1%';
  }
  return `${Math.round(percent)}%`;
}

/** 字数：低于一万按字计，超过按万字并保留一位小数。 */
export function formatCount(value) {
  const number = Number(value) || 0;
  if (number >= 10000) {
    return `${(number / 10000).toFixed(1)} 万字`;
  }
  return `${number} 字`;
}

/** 时长（秒）→ 「1 分 20 秒」；用于导入/导出的进度提示。 */
export function formatDuration(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  if (total < 60) {
    return `${total} 秒`;
  }
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return rest === 0 ? `${minutes} 分钟` : `${minutes} 分 ${rest} 秒`;
}
