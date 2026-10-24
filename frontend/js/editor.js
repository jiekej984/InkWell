/** Quill 2.x 编辑器封装（任务 2.3 / FR-3；阶段三 3.4 排版与中文适配）。
 *
 * - toolbar 只放 V1 必需格式（FR-3.1）：标题 / 加粗 / 斜体 / 下划线 / 删除线 /
 *   有序与无序列表 / 引用 / 代码块 / 链接 / 图片
 * - 图片由调用方提供 `uploadImage(file)` 上传（章节走
 *   `/chapters/{cid}/images`，设定文档走 `/documents/{did}/images`），
 *   插入的是签名 URL；保存时服务端会把签名 URL 还原为相对路径
 * - 字数统计与后端 BR-1 同口径（CJK 逐字、西文按词、标点 emoji 计入）
 * - 图片缺失（被删或签名过期）加 `is-missing` 类，由 style.css 显示占位
 * - 3.4：`spellcheck=false` 等输入行为在创建时统一关掉（中文写作不要红色波浪线），
 *   空文档占位文案由调用方按页面给（章节 / 设定文档）
 */

import { createLogger } from './logger.js';

const log = createLogger('editor');

const TOOLBAR = [
  [{ header: [1, 2, 3, false] }],
  ['bold', 'italic', 'underline', 'strike'],
  [{ list: 'ordered' }, { list: 'bullet' }],
  ['blockquote', 'code-block'],
  ['link', 'image'],
  ['clean'],
];

const DEFAULT_PLACEHOLDER = '开始写作…';
const DEFAULT_ARIA_LABEL = '正文编辑区';

const WORD_GLOBAL_RE = /[A-Za-z0-9]+(?:[._'’\-][A-Za-z0-9]+)*/gu;
const CJK_RE = /[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]|[\u{20000}-\u{2FA1F}]/u;
const SIGNED_SRC_RE = /^\/files\/(media\/[^?]+)/;

/** 与 BR-1 同口径的纯文本字数统计（编辑器实时显示用）。 */
export function countWords(text) {
  if (!text) {
    return 0;
  }
  let cjk = 0;
  let rest = '';
  for (const char of text) {
    if (CJK_RE.test(char)) {
      cjk += 1;
      rest += ' ';
    } else {
      rest += char;
    }
  }
  const words = rest.match(WORD_GLOBAL_RE) || [];
  const punctuationMatches = rest
    .replace(WORD_GLOBAL_RE, ' ')
    .match(/[^\sA-Za-z0-9]/gu);
  return cjk + words.length + (punctuationMatches ? punctuationMatches.length : 0);
}

/** 收集正文中图片的库内相对路径（用于续签）。 */
export function collectImagePaths(quill) {
  const paths = new Set();
  for (const image of quill.root.querySelectorAll('img')) {
    const match = (image.getAttribute('src') || '').match(SIGNED_SRC_RE);
    if (match) {
      paths.add(match[1]);
    }
  }
  return [...paths];
}

/** 用新签发的 URL 替换编辑器中的图片地址（V-03 长会话续签）。 */
export function applyImageUrls(quill, items) {
  const mapping = new Map((items || []).map((item) => [item.path, item.url]));
  for (const image of quill.root.querySelectorAll('img')) {
    const match = (image.getAttribute('src') || '').match(SIGNED_SRC_RE);
    if (!match || !mapping.has(match[1])) {
      continue;
    }
    image.src = mapping.get(match[1]);
    image.classList.remove('is-missing');
  }
}

function markMissingImage(event) {
  const target = event.target;
  if (!(target instanceof HTMLImageElement)) {
    return;
  }
  target.classList.add('is-missing');
  target.alt = target.alt || '图片缺失';
  target.title = '图片缺失（文件已删除或签名已过期）';
}

async function insertImage(quill, file, uploadImage, onTextChange) {
  if (!uploadImage) {
    window.alert('当前编辑器未接入图片上传');
    return;
  }
  try {
    const data = await uploadImage(file);
    const range = quill.getSelection(true) || { index: quill.getLength() };
    quill.insertEmbed(range.index, 'image', data.url, 'user');
    quill.setSelection(range.index + 1, 'silent');
    if (onTextChange) {
      onTextChange();
    }
  } catch (error) {
    log.error(error);
    window.alert(`图片上传失败：${error.message}`);
  }
}

function pickImage(quill, uploadImage, onTextChange) {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/jpeg,image/png,image/webp';
  input.addEventListener('change', () => {
    const file = input.files && input.files[0];
    if (file) {
      insertImage(quill, file, uploadImage, onTextChange);
    }
  });
  input.click();
}

/** 中文写作的输入行为：关掉拼写检查 / 自动纠正 / 自动大写。
 *
 * 理由（3.4）：中文正文里拼写检查只会画满红色波浪线；输入法与自动纠正/自动大写
 * 抢输入会打乱组合串（阶段三_IME验证记录 §二 的同一类问题）。
 * `role` + `aria-label` 让读屏软件把正文区当成多行文本框朗读。
 */
function configureRoot(root, ariaLabel) {
  root.setAttribute('spellcheck', 'false');
  root.setAttribute('autocorrect', 'off');
  root.setAttribute('autocapitalize', 'off');
  root.setAttribute('data-gramm', 'false');
  root.setAttribute('role', 'textbox');
  root.setAttribute('aria-multiline', 'true');
  root.setAttribute('aria-label', ariaLabel);
}

/** 把 Quill 2 的代码块容器序列化成 ``<pre><code>``（D-3.4-1）。
 *
 * Quill 2 的代码块 DOM 是
 * ``<div class="ql-code-block-container"><div class="ql-code-block">…</div></div>``，
 * 而服务端消毒白名单不含 ``div``、Quill 载入端也只认 ``<pre>``（clipboard matcher「pre」），
 * 所以直接存 ``root.innerHTML`` 会让代码块在「保存 → 重开」之后变成纯文本。
 * 保存前把容器改写成 ``<pre><code>``：服务端原样保留，重开时 Quill 再据此重建代码块。
 *
 * 只在真出现代码块时才走 DOM 解析，普通章节零开销。
 */
export function normalizeCodeBlocks(html) {
  if (!html || !html.includes('ql-code-block-container')) {
    return html;
  }
  const template = document.createElement('template');
  template.innerHTML = html;
  let changed = false;
  const containers = template.content.querySelectorAll(
    '.ql-code-block-container',
  );
  for (const container of containers) {
    const lines = Array.from(container.querySelectorAll('.ql-code-block')).map(
      (line) => line.textContent,
    );
    const pre = document.createElement('pre');
    const code = document.createElement('code');
    code.textContent = lines.join('\n');
    pre.append(code);
    container.replaceWith(pre);
    changed = true;
  }
  return changed ? template.innerHTML : html;
}

/** 创建编辑器实例；``uploadImage(file)`` 由调用方提供（章节 / 文档各自的接口）。 */
export function createEditor({
  container,
  uploadImage,
  onTextChange,
  placeholder = DEFAULT_PLACEHOLDER,
  ariaLabel = DEFAULT_ARIA_LABEL,
}) {
  if (!window.Quill) {
    throw new Error('Quill 未加载（检查 /vendor/quill/quill.js）');
  }
  let quill = null;
  quill = new window.Quill(container, {
    theme: 'snow',
    placeholder,
    modules: {
      toolbar: {
        container: TOOLBAR,
        handlers: {
          image: () => pickImage(quill, uploadImage, onTextChange),
        },
      },
    },
  });

  configureRoot(quill.root, ariaLabel);
  // B5：组合输入期间 Quill 还没收到 text-change、ql-blank 仍在，占位会跟候选窗叠在一起。
  // 用 is-composing 让 CSS 暂时藏起占位，组合结束（compositionend）后恢复由 Quill 接管。
  const root = quill.root;
  root.addEventListener('compositionstart', () =>
    root.classList.add('is-composing'),
  );
  root.addEventListener('compositionend', () =>
    root.classList.remove('is-composing'),
  );
  root.addEventListener('error', markMissingImage, true);
  quill.on('text-change', (delta, oldDelta, source) => {
    if (source !== 'user') {
      return;
    }
    if (onTextChange) {
      onTextChange();
    }
  });
  return quill;
}
