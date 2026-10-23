# 项目长期约定与关键事实（Inkwell 小说辅助工具）

## 一、任务收尾流程（用户明确要求，每次开发任务结束自动执行，无需提醒）

每次完成一项开发任务（新增功能 / 修复缺陷 / 重构 / 阶段性改动）后，按序执行：

1. **备份**：把项目（至少含源码与配置文件）完整复制一份，目录名带日期时间戳
   - 位置：`D:\小说辅助\_backups\Inkwell_YYYY-MM-DD_HHmm`
   - 排除：`.venv`（可由 requirements.lock 重建）、`_backups`、`__pycache__`、`.workbuddy`、`*.pyc`
   - 用 robocopy（退出码 0-7 为成功），备份后核对文件数与大小，并告知用户位置
   - 若项目已有版本管理（git），需同时确认本次改动已被记录（提交或至少在进度中写明）
2. **进度记录**：追加更新 `D:\小说辅助\版本更新\进度记录.md`
   - **追加式，禁止覆盖或删改已有条目**；新条目一律加到文件末尾
   - 每条含：时间、已完成任务、变更的文件与模块、未完成事项与待办、完成度快照
3. **汇报**：生成 `D:\小说辅助\版本更新\YYYY-MM-DD_HHmm_进度汇报.md`
   - 内容：本次改动摘要 / 当前进度状态 / 风险与阻塞点 / 下一步建议 / 备份信息
   - 同时在对话中以结构化简明格式汇报

**原则**：所有信息基于实际改动，准确反映真实完成度，**不得夸大**；完成度要区分维度（设计 / 环境 / 代码 / 整体）。

## 二、项目关键事实

- **设计基线**：`Inkwell项目报告_v0.5.md`（已判定可进入开发）。历史版本 v0.1~v0.4 及各轮自审意见均保留，不删除。
- **技术栈**：pywebview + FastAPI(uvicorn 子线程) + SQLite/SQLAlchemy + Quill 2.x + PyInstaller onedir；V1 仅 Windows。
- **开发环境**：Python 3.11.9 @ `E:\Python311`；项目 venv @ `D:\小说辅助\.venv`；一律用 venv 绝对路径调用（`D:\小说辅助\.venv\Scripts\python.exe`）。
- **E 盘是用户的开发盘**（VScode / Git / PyCharm / IDEA / Visual Studio / SQL Server 均在此）。新装工具优先放 E 盘。
- **本机特有坑 R-17**：`http_proxy / https_proxy = http://127.0.0.1:64530`，访问本地服务的 HTTP 客户端必须 `trust_env=False`，否则请求行被改写为 absolute-form → 404。
- **已确认**：Documents 未被 OneDrive 接管；WebView2 Runtime 155.0.4283.62 已装。
- **仍待用户答复**：Q-02 是否做自动更新 / Q-03 发布渠道与版本号规则 / Q-05 磁盘满是否自动清理最老备份。
- **已纳入 git（2026-10-24）**：`main` 分支，首个基线提交 `4163afb`（181 文件）；
  `.gitignore` 排除 `.venv/`、`data/`、`_backups/`、`__pycache__/`、缓存与打包产物；
  日常改动走 commit，`_backups/` 仍按任务留存。
- **建表 DDL 的权威位置是 `backend/migrate.py`**（原始 SQL，按版本登记），阶段二的 `models.py` 需与之保持一致并由一致性测试兜底。
- **阶段二功能开发已完成（2026-10-23，14/14 项）**：2.0~2.13 全部实现，`pytest` **237 passed**
  （含 1 条 Node 入口 → 13 条前端逻辑用例），真实 pywebview 窗口冒烟通过
  （页面/导航/桥接/输入→自动保存/快照/检索/导出/备份）。
  下一步为**真机验收**（V-02 / AC-4 / AC-5 / AC-9 / AC-10 / 回归 15/17/19）与阶段三 UI。
- **阶段三进行中（2026-10-23）**：`阶段三任务清单.md`（3.0~3.9，估算 **12~14 人日**），C 组已确认：
  C-03 新增 **#50 导出本章**；C-04 建首个命名卷时迁入默认卷章节；P9 用 **#51 快照清理 / #52 数据库自检**。
  **3.0 已交付**：`版本更新/阶段三_UI走查基线.md` + 8 张截图（`版本更新/阶段三_截图/`）；
  截图脚本 `tests/e2e/capture_ui.py` 用 WebView2 CDP 抓页面（绕过窗口遮挡，`--label` 区分批次）。
  **3.1 已交付**：`tokens.css` 按 §7.2 重写（语义名 `--bg/--panel/--sidebar/--text/--text-2/--border/
  --accent/--accent-soft/--danger/--success`），`style.css` 硬编码色 18→0，补 `:focus-visible`/`::selection`/
  `dialog::backdrop`/滚动条/reduced-motion；`--danger` 由 §7.2 `#C0563C` 调为 `#B84F36`（AA），见 S3-01。
  **禁用组合**：`--accent`/`--text-2` 在 `--accent-soft` 上仅 4.39/4.49:1，其上文字用 `--text`。
  **3.2 已交付**：`frontend/js/sidebar.js`（折叠/右键菜单/章节信息/标记定稿/拖拽/卷排序/键盘/删卷三选一），
  新增 **#53 `POST /volumes/{vid}/adopt-default`**（C-04，仅首个命名卷可接收默认卷章节）；
  writer.js 改为保存后增量更新章节字数；S3-02。**不提供「章节移入默认卷」菜单**（会不可达）。
  下一步 **3.3 项目卡片与首启引导**。
- **阶段二评审补强（2026-10-23 19:45）**：回归 15 与 AC-6 已补自动化；检索深页上限 100→1000 并新增
  `page_limited`/`fuzzy` 字段；#44 日志增加正文兜底、前端 logger 改为按值脱敏（S2-17 / S2-18）。
- **前端单测约定**：`tests/js/*.test.js` 用 Node 内置 test runner（零依赖假时钟/假 localStorage/内存 drafts 后端），
  由 `tests/test_frontend_js.py` 作为 pytest 入口（Node 缺失自动 skip）；根目录 `package.json` 只为
  `type: module` 与 `npm test`，前端仍无构建步骤、浏览器不读取该文件。
  本机 PATH 上的 `node` 是 DSH 的 Electron-as-Node 包装（`ELECTRON_RUN_AS_NODE=1`），
  **不支持 `node --test <目录>`**，必须按文件显式传参。
- **阶段二实施决策**登记在 `DECISIONS.md` §六（S2-06~S2-18）；接口增补（#45~#49）与勘误差异见
  `版本更新/阶段二_接口与勘误同步清单.md`（供 v0.6 统一修订）。
- **阶段二新增工程约定**：`pyproject.toml` 配置 ruff / black，两者**必须排除 `_backups`**（否则扫历史副本持续报错）。
- **数据访问层约定（S2-04）**：同步 SQLAlchemy ORM；软删除**显式过滤**，用 `active(Model)` 查询辅助，回收站查询裸查；不用全局 `before_compile`。
- **长任务约定（S2-03）**：进程内内存任务表 + `GET /tasks/{tid}`；**互斥**，第二个任务返回 409 + 3004；不做取消、不持久化。

## 三、本机 / 依赖层面的已验证事实

- **SQLite 版本 3.45.1**（要求 ≥3.35；trigram 需 ≥3.34，实测支持）。
- **FTS5 中文分词**：`unicode61` 下中文子串检索**不可用**（连续中文被视为单个 token，实测 `MATCH '中文'` 命中 0）；`trigram` 可用（查询串需 ≥3 字符）。已据此决策采用 trigram。
- **Python 3.11 的 `sqlite3.Connection` 没有 `autocommit` 属性**，SQLAlchemy 官方文档的 PRAGMA 示例不可直接照抄。
- **pywebview 6.2.1 API**：`create_window` 默认 `text_select=False`（写作应用需显式 True）；`start` 默认 `private_mode=True`（localStorage 不保留，需显式 False）；`debug` 同时控制快捷键 / 右键菜单 / DevTools（`webview/platforms/edgechromium.py:287/288/290`）。
- **Git Bash（MSYS）会把以 `/` 开头的参数转成盘符路径**，调用 robocopy 等 Windows 命令时需 `MSYS_NO_PATHCONV=1`。
- **uvicorn 在子线程安全**：`uvicorn/server.py` 的 `capture_signals()` 在非主线程直接返回。
- 前端调用桥接必须订阅 `pywebviewready`，不能在 `window.onload` 假定 `pywebview.api` 已就绪。
- **Quill 2.0.3 的 `dist/quill.js` 是 UMD 而非 ESM**（实测：Node 以脚本执行抛 `ReferenceError: document is not defined`），可直接 `<script src>` 挂 `window.Quill`；2.0.3 的 dist **没有** `quill.global.js` / `quill.browser.js`。离线副本在 `frontend/vendor/quill/`。
- **FTS5 external content 表会生成 5 张影子表**（`<name>_data/_idx/_content/_docsize/_config`），做结构比对时必须按前缀排除。
- **DDL ↔ ORM 一致性比对**：不要解析 DDL 字符串；应建两个库（迁移产出 vs `metadata.create_all`）后比对两边 `PRAGMA table_info/index_list/foreign_key_list`。主键列的 `notnull` 有固有差异（AUTOINCREMENT=0 vs `NOT NULL`=1），语义等价，比对时归一化。
- **pywebview 窗口可自动化冒烟**：`webview.start(func=...)` 中调用 `window.evaluate_js()` 可驱动页面；
  已用该方式验证桥接 token、项目卡片、写作页、Quill、自动保存、快照、检索、导出、备份（2026-10-23）。
  注意：`execCommand('insertText')` 可注入中文，但**不等于中文输入法（IME）验证**，V-02 仍需人工走查。
- **真实窗口冒烟已固化为脚本**：`tests/e2e/window_smoke.py` —— 临时数据目录（不碰 `data/`）+ 内存桥接 token +
  后端子线程，14 步断言（列表/桥接/写作页/3s 保存/暂存清理/检索高亮/短词降级/无 JS 异常），
  `--json` 可解析、`--keep-data` 留现场、退出码 0/1；改动前端主路径后建议先跑它。
- **IME 组合与快捷键（2026-10-24 实测）**：WebView2 下用 CDP `Input.imeSetComposition` 模拟组合输入；
  组合期间 keydown 的 `isComposing=true` 可稳定读取（Ctrl+S/Ctrl+B 实测）；Ctrl+S 原会在组合中误触发
  保存+快照，已按 S3-03 加 `isComposing || keyCode===229` 门禁。**CDP 合成 ≠ 真实微软拼音**：
  preedit/候选窗/富文本粘贴仍需人工走查（V-02 保持部分验证）。
- **原生 SQL 读 DATETIME 是字符串**：`session.execute(text(...))` 不走 ORM 类型映射，搜索等服务里需
  `datetime.fromisoformat()` 转回再序列化（已处理）。
- **检索分页的正确性条件**：两侧各取 `page*page_size` 条再合并，只有当「每侧都覆盖到本页之前的全部名次」时
  前缀才完整；单侧上限一旦小于窗口，深页就会静默变少/变空（旧上限 100 时 120 条命中的第 6 页即空页）。
  现上限 1000，超出返回 `page_limited=true` + `hint`；彻底方案为游标分页（阶段三）。
- **日志脱敏两层**：`redact`（token/sig 值 → `***`，单条 1000 字）+ `sanitize_client_report`
  （#44 去 HTML 标签、`content_html` 等正文字段整值省略、message 300 / context 值 120 字）；
  前端 `logger.js` 只替换密钥值，不再整条丢弃诊断信息。
