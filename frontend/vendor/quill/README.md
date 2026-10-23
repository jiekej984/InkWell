# Quill 2.0.3（离线本地副本）

- **来源**：<https://cdn.jsdelivr.net/npm/quill@2.0.3/dist/>（npm registry 校验最新稳定版 = `2.0.3`）
- **构建类型**：**UMD**（**不是** ESM），直接 `<script src>` 引入即可，挂载全局 `window.Quill`
- **引入方式**：

  ```html
  <link rel="stylesheet" href="/vendor/quill/quill.snow.css">
  <script src="/vendor/quill/quill.js"></script>
  ```

  `quill.js` 已包含 snow 与 bubble 主题及全部内置模块，**无需再引 `quill.core.js`**。

## 为什么不需要 ESM / importmap

`dist/quill.js` 头部为 UMD 包装器：

```js
!function(t,e){"object"==typeof exports&&"object"==typeof module?module.exports=e()
 :"function"==typeof define&&define.amd?define([],e)
 :"object"==typeof exports?exports.Quill=e()
 :t.Quill=e()}(self,(function(){ ... }));
```

浏览器环境下 `self === window`，因此走最后一条分支 `window.Quill = e()`。

**实测证据**（Node 22 以脚本方式执行本文件）：

| 若为 ESM 的预期 | 实际结果 |
|---|---|
| `SyntaxError: Cannot use import statement outside a module` | `ReferenceError: document is not defined` |

第二条说明文件被当作普通脚本解析执行、只是在等待 DOM，不存在 ESM 语法。
（注：`quill.global.js` / `quill.browser.js` 在 2.0.3 的 dist 中**不存在**，无需寻找。）

## 文件与校验（sha256）

| 文件 | 大小 | sha256 |
|---|---|---|
| `quill.js` | 209,274 B | `f6157c72ac9b3f51cdead426335688a027b12405d9d6a4daadd38a676b2d7ff2` |
| `quill.snow.css` | 24,606 B | `1c7948cd13aa92fac6390319bc1e5e461823da171519d3a768db56164f871636` |
| `LICENSE.txt` | 159 B | `7b1938804d68d96764233d0a148a7501f39e547e6ae2dead4b16836e9b8d123c` |

验证：`sha256sum frontend/vendor/quill/*`

## 许可

Quill 为 **BSD-3-Clause**（Copyright Slab / Jason Chen / salesforce.com），原文见 `LICENSE.txt`。
本项目自身许可为 MIT（D-02），第三方许可随本目录一并分发，打包时不得剔除。

## 维护约定

- 版本锁定：**2.0.3**，升级须走变更评审并同步更新 `DECISIONS.md` 与本文件
- 不使用 CDN：V1 要求离线运行（R-1 打包资源丢失风险）
- 本目录随项目一起备份，**不在** `.venv` 排除范围内（备份脚本已排除 `.venv`，未排除 `frontend/vendor`）
- `quill.js` 末尾含 `//# sourceMappingURL=quill.js.map`，未下载 `.map`；仅 DevTools 打开时会 404，生产无影响
