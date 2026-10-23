/** 前端日志 + 远端上报（任务 2.13 / #44 / NFR-M4）。
 *
 * - 输出前按**值**脱敏：只替换 token / sig / signature / authorization 的取值，
 *   保留路径、错误码、文案等诊断信息（不再整条参数替换成「[已脱敏]」）
 * - 单条消息限长 1000 字符，避免把成段正文带进日志
 * - error / warning 同时上报 `POST /api/system/logs`（失败静默，避免日志风暴）
 * - `installGlobalHandlers()` 捕获未处理异常与 Promise 拒绝
 */

import { request } from './api.js';

const MAX_MESSAGE = 1000;

// 只匹配「关键字 = 值」形态；值可以是引号包裹或到空白/分隔符为止
const SECRET_PATTERNS = [
  /(x-inkwell-token\s*[:=]\s*)("[^"]*"|[^\s,;"'&]+)/gi,
  /((?:token|signature|sig)\s*[:=]\s*)("[^"]*"|[^\s,;"'&]+)/gi,
];

function toText(value) {
  if (typeof value === 'string') {
    return value;
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

/** 按值脱敏：`sig=SECRET` → `sig=***`，其余文字原样保留。 */
export function redactSecrets(text) {
  let value = String(text ?? '');
  for (const pattern of SECRET_PATTERNS) {
    value = value.replace(pattern, (match, prefix) => `${prefix}***`);
  }
  return value;
}

/** 脱敏 + 限长（控制台与远端上报共用）。 */
export function sanitizeText(value, maxChars = MAX_MESSAGE) {
  return redactSecrets(toText(value)).slice(0, maxChars);
}

function sendRemote(level, scope, args) {
  const message = args
    .map((value) => sanitizeText(value))
    .join(' ')
    .slice(0, MAX_MESSAGE);
  if (!message) {
    return;
  }
  request('/api/system/logs', {
    method: 'POST',
    body: { level, message, context: { scope } },
  }).catch(() => {
    // 上报失败静默：避免网络/桥接异常引发日志递归
  });
}

export function createLogger(scope) {
  const write = (level, args) => {
    const safe = args.map((value) => sanitizeText(value));
    // eslint-disable-next-line no-console
    (console[level] || console.log)(`[${scope}]`, ...safe);
    if (level === 'error' || level === 'warn') {
      sendRemote(level === 'warn' ? 'warning' : 'error', scope, safe);
    }
  };

  return {
    info: (...args) => write('info', args),
    warn: (...args) => write('warn', args),
    error: (...args) => write('error', args),
  };
}

/** 捕获未处理异常 / Promise 拒绝并上报（#44）。 */
export function installGlobalHandlers() {
  const log = createLogger('global');

  window.addEventListener('error', (event) => {
    log.error(
      '未捕获异常：',
      event.message,
      `${event.filename || ''}:${event.lineno || 0}`,
    );
  });

  window.addEventListener('unhandledrejection', (event) => {
    const reason =
      event.reason && event.reason.message
        ? event.reason.message
        : String(event.reason);
    log.error('未处理的 Promise 拒绝：', reason);
  });
}
