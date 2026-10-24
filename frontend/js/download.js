/** 浏览器下载 Blob（诊断包等，3.6 P9 复用）。

 * 用临时 `<a download>` 触发下载：WebView2 会走系统下载行为；不打开新窗口。
 */
export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename || 'download.bin';
  anchor.rel = 'noopener';
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  // 立刻 revoke 会让部分 WebView 下载失败，下一轮事件循环再释放
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
