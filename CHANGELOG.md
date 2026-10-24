# 变更日志

本项目采用 SemVer 版本号规则（D-12，【暂定】待 Q-03 确认发布渠道）。

## [未发布]

### 阶段一：项目骨架（报告 §九 1.1~1.5）

**新增**

- `DECISIONS.md`：关闭 D-01~D-13 决策项；D-12 / D-13 按默认执行并标注暂定
- `backend/config.py`：数据目录解析（§4.4 四级优先级）、一次性 token、随机端口、代理环境清理
- `backend/server.py`：FastAPI 应用工厂；三层安全中间件
  - 拒绝 absolute-form 请求行（R-17 缓解措施 ③）
  - Host 白名单校验（NFR-S5）
  - `X-Inkwell-Token` 校验（NFR-S2）
- `backend/schemas.py`：统一响应结构 `{code, message, data}` 与错误码枚举
- `backend/storage.py`：HMAC-SHA256 静态资源签名签发/校验、路径规范化与白名单（ADR-009 / NFR-S7）
- `backend/api/system.py`：`GET /api/system/health`（§6.2 #1）
- `backend/database.py`：SQLAlchemy Engine + PRAGMA 注入、quick_check、WAL checkpoint、在线热备与原子备份
- `backend/migrate.py`：迁移骨架 + 0001 初始 schema（全量 V1 表、索引、FTS5 external content 与同步触发器）
- `main.py`：启动流程编排；子线程 uvicorn；pywebview 窗口与 `js_api` token 注入；`--selfcheck` 自检模式
- `frontend/`：最小骨架页面（index.html / tokens.css / style.css / app.js / api.js / logger.js）
- `tests/`：49 条 pytest 用例，覆盖配置、签名、安全链路、数据库运维、迁移

**决策**

- S1-01：FTS5 分词器采用 **trigram**（unicode61 下中文检索不可用，已实测）
- S1-02：鉴权/访问控制类错误 → HTTP 401，请求行非法 → 400，其余业务错误 → 200
- S1-03：Host 校验失败复用错误码 1002（错误码表未定义该项）
- S1-04：`/api/system/health` 与其他 `/api/*` 一致，均需 token
- S1-05：PRAGMA 在 `connect` 事件中直接执行（官方示例的 `autocommit` 属性在 Python 3.11 不存在，已实测）
- S1-06：窗口 `text_select=True`、`private_mode=False`、`debug=dev`

**验证**

- `pip install -r requirements.lock` 成功
- `python main.py --selfcheck` 7 项全部 PASS
- `pytest tests -q` 49 passed
- `python main.py` 实际拉起窗口，桥接注入与 `pywebviewready` 均正常

### 阶段一评审收尾（2026-10-22）

**决策**（均维持现有实现，零代码改动）

- S1-07：FTS 同步**保留触发器即时同步**；去抖降级为阶段二可选优化假设（L-01 关闭）
- S1-08：全业务表统一 `is_deleted` / `deleted_at`；`volume` / `document` 补 `updated_at`；`document` 暂不建索引；`document_version` / `chapter_version` 保持无 `updated_at`（L-05 关闭）
- S1-09：健康检查维持 `/api/system/health`（L-06 关闭）
- S1-02 / S1-03 错误码映射经发起人确认，状态由「待确认」转为「已确认」

**文档勘误（登记，未修订基线报告）**

- E-01：§5.2 / §5.4「后台去抖更新」→「V1 触发器即时同步；去抖为阶段二可选优化假设」
- E-02：§九 / §12.3 的 `/api/health` → `/api/system/health`

### 阶段二 2.0 + 0002 + 2.12（2026-10-23）

**新增**

- `backend/models.py`：同步 SQLAlchemy ORM（`sessionmaker`）覆盖全部业务表；`active(Model)` 查询辅助（显式带 `is_deleted=0`，回收站裸查）；`session_scope` 事务上下文
- `backend/migrate.py` **迁移 0002**：新增 `document_fts`（external content → `document`，`title` + `content_text`，trigram，三触发器与 chapter 同构）；`SCHEMA_VERSION` 1 → **2**；0001 未改动
- `backend/services/tasks.py`：长任务管理器 —— 进程内内存任务表 + **互斥锁**（第二个任务抛 `TaskConflict`）；任务对象 8 字段；已完成任务 TTL 5 分钟惰性清理；不做取消、不持久化
- `backend/api/tasks.py`：§6.2 **新增 #45** `GET /tasks/{tid}`、`DELETE /tasks/{tid}`
- `backend/schemas.py`：新增错误码 **3004**（已有长任务进行中）→ HTTP 409
- `frontend/vendor/quill/`：Quill **2.0.3** 离线副本（UMD 构建 `quill.js` + `quill.snow.css` + LICENSE），附校验和与来源说明
- `pyproject.toml`：ruff / black 配置，排除 `_backups` 等目录
- `tests/test_models_ddl.py`（11 条）、`tests/test_tasks.py`（12 条）

**决策**

- S2-01：Quill 锁定 2.0.3，UMD 构建（实测非 ESM），离线 vendor，不走 CDN
- S2-02：设定文档纳入全文检索，迁移 0002 + `SCHEMA_VERSION=2`；查询在 service 层分两次查后合并
- S2-03：长任务采用方案 A（内存任务表 + `GET /tasks/{tid}`）；互斥 → 409 + 3004；不做取消与持久化
- S2-04：同步 ORM + 显式过滤 + `active()` 辅助；DDL 一致性测试必须真跑
- S2-05：2.12 排期提前到 2.0 之后，与 2.1~2.4 并行

**验证**

- `pytest tests -q` → **71 passed**
- `python main.py --selfcheck` → 7 项 PASS，`schema_version` 已升到 2
- 真实库 `data/inkwell.db` 由 v1 迁移至 v2：迁移前备份 `inkwell_premigrate_20261023_001333_v1.db` 已生成；`document_fts` 与三个触发器就位
- `ruff check` / `black --check` 全绿

### 阶段二 2.1：项目 CRUD + 封面 + 标签（2026-10-23）

**新增**

- `backend/services/project_service.py`：项目业务规则 —— 新建（自动建默认卷 BR-6）、列表、详情、局部更新、封面路径、级联软删（BR-4）、统计（#9）
- `backend/api/projects.py`：§6.2 **#3~#9** 全部接口
- `backend/api/system.py`：新增 **#2 `GET /system/meta`**（版本 / 数据目录 / 端口 / 最近项目）
- `backend/timeutil.py`：`utc_now()` 与 ISO 8601 序列化（BR-8 持久化用 UTC）
- `backend/server.py`：`create_app(config, database)`；新增 `RequestValidationError` → **1001** 处理器（统一响应，避免 FastAPI 的 422）
- `frontend/js/projects.js` + `index.html` + `style.css`：页面 P1（项目列表卡片）与 P4（设置对话框，含换封面与删除二次确认）
- `tests/test_projects.py`：21 条用例

**要点**

- FR-1.7 项目名允许重复（**不做**唯一校验）；FR-1.3 未设目标字数时进度为 `null` 不显示
- 封面：白名单 jpg/png/webp + ≤10MB + **Pillow 校验真实格式**（防扩展名伪装）；库内只存相对路径；换封面删除旧文件
- 软删除级联卷 / 章 / 设定文档；**快照表不加软删除字段**（勘误 E-03）
- 封面预览与「打开」按钮待 2.3 / 2.2 接线，当前显示占位（FR-1.8）

**验证**

- `pytest tests -q` → **92 passed**（2.1 新增 21 条）
- `python main.py --selfcheck` → 7 项 PASS（无回归）
- 前端 4 个 JS 模块经 `node --check` 语法校验通过
- `ruff check` / `black --check` 全绿

### 阶段二 2.2：卷章 CRUD + 排序 + 默认卷（2026-10-23 15:56）

**新增**

- `backend/services/chapter_service.py`：卷章业务规则 —— 默认卷不变量（BR-6）、BR-3 步长排序与局部重整、非空卷二选一删除（move/cascade）、跨卷移动、卷/章统计、`move_chapters_to_volume()`（C-03 数据层预留，V1.1 合并卷复用）
- `backend/api/volumes.py`：§6.2 **#10~#17、#22** 全部接口
- `backend/api/__init__.py`：挂载 volumes 路由
- `tests/test_volumes.py`：20 条用例（排序头部/尾部/中间/相邻差重整、跨卷移动、非空卷两条删除路径、默认卷保护、卷统计）

**决策**

- S2-06：默认卷在 #10 响应中**单列 `default_volume`**，不混入 `volumes`（对应 BR-6「大纲树默认隐藏，项目无其他卷时才显示」）；排序接口用 `{id, prev_id, next_id}` 表达「拖拽到两项之间」，服务端按 BR-3 计算并仅在必要时整体重整；2.2 只做数据层，大纲树 UI 归阶段三 3.2
- 非空卷缺 `mode` → 1001；默认卷改名/删除 → 1001；头部落到 ≤0 时整体重整为 1000 步长（与 BR-3「相邻差 ≤1 局部重整」同策略）

**验证**

- `pytest tests -q` → **112 passed**（2.2 新增 20 条）
- `python main.py --selfcheck` → 7 项 PASS
- `ruff check` / `black --check` 全绿

### 阶段二 2.5：字数统计 + 重算工具（2026-10-23 15:57）

**新增**

- `backend/services/wordcount.py`：BR-1 字数口径纯函数 —— `extract_text()`（HTML→纯文本，stdlib `HTMLParser`）、`count_words()`（CJK 逐字 / 西文按词 / 标点 emoji 可开关）、`count_html()`
- `backend/services/maintenance_service.py`：`rebuild_wordcount()` 分批重算 `content_text` / `word_count` 并汇总 `project.total_word_count`；`recompute_project_totals()`
- `backend/api/maintenance.py`：§6.2 **#43 `POST /maintenance/rebuild-wordcount`**（长任务，复用 2.12 框架）
- `tests/test_wordcount.py`：15 条用例（纯函数口径 + 长任务提交/轮询/互斥/软删除忽略）

**决策**

- S2-07：字数实现口径 —— CJK 范围含基本区/扩展 A/兼容区/扩展 B；西文词允许内部连字符、下划线、撇号；标点/emoji/符号默认逐字符计，可用 `count_punctuation=False` 关闭；去标签用标准库 `HTMLParser`（不新增依赖），块级标签转段落、连续空行压缩为两行
- 重算任务**只处理活跃章节**，软删除章节保留原值（恢复后由下次重算修正）

**验证**

- `pytest tests -q` → **127 passed**（2.5 新增 15 条）
- `python main.py --selfcheck` → 7 项 PASS
- `ruff check` / `black --check` 全绿

### 阶段二 2.3：Quill 编辑器 + 图片 + `/files/` 签名 + 消毒（2026-10-23 16:03）

**新增**

- `backend/services/sanitize.py`：服务端白名单消毒（NFR-S6）—— 允许排版标签、块级 `class`、`img src` 仅 `media/`、外链图片丢弃、`script`/`style`/`iframe` 连内容删除、`style` 属性一律去除
- `backend/services/media.py`：正文图片校验（jpg/png/webp、≤10MB、Pillow 真实格式）、落盘 `media/{cid}/{uuid}.ext`、签名 URL 与相对路径互转
- `backend/api/chapters.py`：§6.2 **#18~#21**（详情/局部更新/正文保存/软删除）+ **#46 图片上传**（§6.2 未列，见 S2-08）
- `backend/api/files.py`：§6.2 **#36 `GET /files/{relpath}?sig=`**（root 挂载、不走 token）与 **#37 `POST /files/sign`**（批量签发）
- `backend/services/chapter_service.py`：新增详情（图片签名）、`update_chapter`、`save_chapter_content`（消毒 + 字数 + 乐观锁 + 图片路径还原 + 项目字数增量）、`delete_chapter`
- `backend/server.py`：在静态目录挂载前注册 `/files` 路由
- 前端：`index.html` 改为「顶栏 + 视图切换 + 写作页（P2）」；`js/editor.js`（Quill 2.0.3 封装、BR-1 同口径字数、图片上传、签名续签、缺失占位）、`js/writer.js`（大纲树/章节加载/标题与正文保存/状态栏）、`js/view.js`（视图切换与输入对话框）
- `frontend/js/projects.js`：封面预览经 #37 签名后显示、「打开」进入写作页
- `frontend/css/style.css`：应用骨架、三栏写作页、Quill 排版（行宽 760px、首行缩进 2 字符、图片缺失占位）
- `tests/test_sanitize.py`（11 条）、`tests/test_chapters.py`（18 条）

**决策**

- S2-08：图片上传接口新增（#46）；`/files/` 校验顺序调整为「路径 → 签名 → 存在」以匹配回归 13；`chapter.version_no` 每次正文保存 +1，2.6 快照复用该修订号；`expect_version` 缺省不做乐观锁；图片 HTML 只存相对路径、返回时签名、前端 20 分钟续签

**验证**

- `pytest tests -q` → **156 passed**（2.3 新增 29 条）
- `python main.py --selfcheck` → 7 项 PASS
- 前端 7 个 ES Module 经 Node 语法检查通过
- `ruff check` / `black --check` 全绿
- **未完成**：V-02（WebView2 下 Quill 中文输入法/粘贴）专项实测，尚未在真机窗口走查

### 阶段二 2.4：自动保存 + 失败/冲突暂存（2026-10-23 18:36）

**新增**

- `backend/services/drafts.py`：暂存文件层 —— `drafts/chapter_{cid}.json` 覆盖写、原子落盘、列表/读取/删除、损坏文件忽略、单章 8MB 上限
- `backend/api/drafts.py`：**#47 暂存接口**（`POST/GET /drafts`、`GET/DELETE /drafts/{cid}`，§6.2 未列，见 S2-09）
- `backend/api/chapters.py`：正文保存成功后**自动清理该章节暂存**（BR-2：暂存只存在于失败/冲突时）
- `frontend/js/autosave.js`：停输 3s / 最长 30s 调度；失败重试 1s/3s/9s；3 次失败交给暂存；3002 不重试
- `frontend/js/pending.js`：localStorage 与服务端 `drafts/` 双份读写
- `frontend/js/writer.js`：接入自动保存、重试按钮、暂存恢复提示与自动补写、`beforeunload` 同步写本地暂存、每 10 秒本地暂存（AC-4）
- `frontend/js/projects.js` + `index.html`：项目列表「未保存暂存」横幅
- `frontend/css/style.css`：重试按钮与暂存横幅样式
- `tests/test_drafts.py`：8 条用例（落盘/列表/详情/删除/覆盖/超限/损坏忽略/保存后清理）

**决策**

- S2-09：暂存接口与策略 —— 新增 #47；双份暂存；localStorage 首写 2s + 每 10s；保存成功自动清理；3002 不重试；恢复后自动补写；8MB/章上限

**验证**

- `pytest tests -q` → **164 passed**（2.4 新增 8 条）
- `python main.py --selfcheck` → 7 项 PASS
- 前端 9 个 ES Module 语法检查通过；`autosave.js` 调度行为经 Node 自测（失败→重试成功；冲突→不重试）
- `ruff check` / `black --check` 全绿
- **未完成**：AC-4（`taskkill /F` 后丢失 ≤30 秒）与回归 15 的**浏览器端到端**走查，需与 V-02 一并在真机窗口完成

### 阶段二 2.6：分级快照 + 回滚（2026-10-23 18:39）

**新增**

- `backend/services/version_service.py`：D-04 分级快照 —— auto（≥5 分钟且字数变 ≥200）、manual、milestone、restore；auto 保留最近 30 条 + 每日首条额外 30 天；回滚先存 restore 快照再覆盖正文
- `backend/api/versions.py`：§6.2 **#23~#27**（列表/详情/手动快照/回滚/物理删除）
- `backend/services/chapter_service.py`：正文保存后接入 auto 快照，保存响应返回 `snapshot_created` / `snapshot_version_no`
- 前端：`js/versions.js` + 页面 P5（版本列表、只读预览、回滚、删快照）；`writer.js` 增加「存为版本 / 版本」按钮，**Ctrl+S = 保存 + 手动快照**
- `tests/test_versions.py`：12 条用例

**决策**

- S2-10：`version_no` 语义与回滚契约 —— 正文保存 +1、手动/里程碑再 +1、回滚再 +1；回滚时**先**把回滚前正文存为 `restore` 永久快照（新号 #N），再覆盖为目标版本内容，`chapter.version_no` 保持 #N；auto 首次快照条件（无历史快照时 ≥200 字）、保留策略与清理实现细节；Ctrl+S 语义

**验证**

- `pytest tests -q` → **176 passed**（2.6 新增 12 条）
- 前端 10 个 ES Module 语法检查通过
- `ruff check` / `black --check` 全绿
- **未完成**：AC-5（写作 1 小时后可回溯 60 分钟前节点）未做真机实测；P5 交互未浏览器走查

### 阶段二 2.7：设定文档 CRUD（2026-10-23 18:42）

**新增**

- `backend/services/document_service.py`：五类分类（world/timeline/faction/glossary/other）、CRUD、消毒 + 图片路径还原 + 字数、软删除；**不改动** `project.total_word_count`（FR-4.1）
- `backend/services/media.py`：拆出 `save_image` / `save_document_image`，文档图片落 `media/documents/{did}/`，避免与章节 id 冲突
- `backend/api/documents.py`：§6.2 **#28~#30**（列表/筛选、新建、详情/更新/软删）+ **#48 文档图片上传**（见 S2-11）
- 前端：`js/documents.js` + 页面 P3（分类筛选、文档列表、Quill 编辑器、图片上传、手工保存）；写作页增加「设定」入口；`editor.js` 图片上传改为调用方注入 `uploadImage`，章节与文档共用
- `tests/test_documents.py`：11 条用例

**决策**

- S2-11：文档分类与排序（`order_index` 步长 1000，PATCH 可改）、文档图片接口 #48、文档不参与全书字数、版本历史按 D-05 不做、P3 采用**手工保存**（切换/离开前强制保存）

**验证**

- `pytest tests -q` → **187 passed**（2.7 新增 11 条）
- `python main.py --selfcheck` → 7 项 PASS
- 前端 11 个 ES Module 语法检查通过
- `ruff check` / `black --check` 全绿
- **未完成**：P3 浏览器交互走查；文档自动保存/排序 UI 留待阶段三

### 阶段二 2.8：回收站 + 父链恢复（2026-10-23 18:45）

**新增**

- `backend/services/trash_service.py`：回收站列表（项目/卷/章/文档，含父级与剩余天数）、父链恢复（`requires_parent` 提示 + `with_parent` 批次恢复）、清空（物理删除）、`purge_expired_trash()`（30 天，供 2.9 后台调用）
- `backend/api/trash.py`：§6.2 **#39~#41**
- `backend/services/chapter_service.py`：级联删卷时同步扣减项目总字数（与章节软删口径一致）
- 前端：`js/trash.js` + 页面 P8（分组列表、恢复/一并恢复、清空二次确认）；项目列表增加「回收站」入口
- `tests/test_trash.py`：7 条用例

**决策**

- S2-12：回收站类型与恢复契约 —— `requires_parent` 用 **HTTP 200 + code 0 + data.requires_parent** 表达（非错误）；同批次（同 `deleted_at`）级联恢复；清空/过期清理为物理删除（外键级联 + FTS 触发器同步）；恢复后重算项目总字数

**验证**

- `pytest tests -q` → **194 passed**（2.8 新增 7 条）
- `python main.py --selfcheck` → 7 项 PASS
- 前端 12 个 ES Module 语法检查通过
- `ruff check` / `black --check` 全绿
- **未完成**：P8 浏览器交互走查；30 天清理的实际后台调度在 2.9 落地

### 阶段二 2.9：备份与恢复 + 启动后台流程（2026-10-23 18:48）

**新增**

- `backend/services/backup_service.py`：手动/每日备份（原子写入）、列表、校验（quick_check + schema_version）、恢复（prerestore 备份 → 替换 DB → 迁移）、每日备份保留 7 日 + 4 周、孤儿媒体清理、磁盘余量、启动后台流程（每日备份/清理/周完整性检查/时间回拨跳过）
- `backend/api/backup.py`：§6.2 **#32~#34**（立即备份/列表/恢复，前后两项为长任务；恢复先同步校验）
- `backend/database.py`：`reopen()` 与 `integrity_check()`
- `main.py`：窗口模式启动后异步执行后台流程（`--selfcheck` 不触发）
- 前端：`js/backup.js` + `js/tasks.js`（500ms 长任务轮询，供 2.10/2.11 复用）+ 页面 P7
- `tests/test_backup.py`：9 条用例

**决策**

- S2-13：备份命名与保留（`inkwell_backup_*` 手动不自动删、`inkwell_daily_*` 7 日 + 4 周、迁移前/恢复前备份永久保留）、恢复同步校验（损坏 3001 / 版本过高 3003）、恢复前自动备份、启动后台流程与时间回拨跳过、孤儿媒体 24 小时保护期

**验证**

- `pytest tests -q` → **203 passed**（2.9 新增 9 条）
- `python main.py --selfcheck` → 7 项 PASS
- 前端 14 个 ES Module 语法检查通过
- `ruff check` / `black --check` 全绿
- **未完成**：P7 浏览器交互走查；恢复流程在真实窗口中的端到端演练（AC-9）待真机

### 阶段二 2.10：导出 TXT / Markdown（2026-10-23 18:50）

**新增**

- `backend/services/export_service.py`：#35 导出 —— 数据目录 `exports/`、安全文件名、流式写入（50 章一批）、`.tmp` + `os.replace`（BR-7）、空项目仍有书名/简介/说明
- `backend/api/export.py`：§6.2 **#35 `POST /projects/{pid}/export`**（长任务；格式/项目同步校验）
- `backend/config.py`：数据子目录新增 `exports/`
- 前端：P7 页面增加「导出正文」（项目 + TXT/Markdown + 导出结果路径）
- `tests/test_export.py`：7 条用例

**决策**

- S2-14：导出契约 —— 只导出正文（不含设定文档）；输出到 `exports/`；文件名 `{安全书名}_{时间戳}.{fmt}`；流式写入 + 原子落盘；空项目 TXT 输出书名/简介/（暂无正文），MD 输出 `## 目录（暂无章节）`；返回 `relpath`/章数/字数

**验证**

- `pytest tests -q` → **210 passed**（2.10 新增 7 条）
- `python main.py --selfcheck` → 7 项 PASS
- 前端 14 个 ES Module 语法检查通过
- `ruff check` / `black --check` 全绿
- **未完成**：AC-6 真机字数/内容比对、回归 19（导出中强杀不留半截文件）真机演练；P7 走查

### 阶段二 2.11：全文检索 + 重建索引（2026-10-23 18:53）

**新增**

- `backend/services/search_service.py`：#31 检索 —— 章节/设定文档分两次查后合并、trigram ≥3 字符、短查询 LIKE 降级 + 提示、Python 生成摘要并 HTML 转义、分页与项目/范围过滤
- `backend/api/search.py`：§6.2 **#31 `GET /search`**
- `backend/services/maintenance_service.py` + `api/maintenance.py`：§6.2 **#42 `POST /maintenance/rebuild-fts`**（长任务，FTS5 rebuild）
- 前端：`js/search.js` + 页面 P6（搜索框、范围/项目筛选、结果高亮、点击跳转章节/设定、重建索引）；顶栏增加「搜索」入口；写作页/设定页导出定位入口
- `tests/test_search.py`：11 条用例

**决策**

- S2-15：检索契约 —— 少于 3 字符降级 LIKE 并返回 `hint`；摘要由 Python 生成（正文 HTML 转义，仅 `<mark>` 受信）；两侧各取 `page*page_size`（≤100）后合并排序；`total` 为两侧命中数之和；索引重建走 FTS5 `rebuild`

**验证**

- `pytest tests -q` → **221 passed**（2.11 新增 11 条）
- `python main.py --selfcheck` → 7 项 PASS
- 前端 15 个 ES Module 语法检查通过
- `ruff check` / `black --check` 全绿
- **未完成**：AC-10（10 万字 ≤1s）真机性能实测、P6 浏览器走查

### 阶段二 2.13：日志与前端异常上报（2026-10-23 18:56）

**新增**

- `backend/services/logging_service.py`：按天日志（单文件 10MB 再切分）、总量 ≤50MB 删最老、脱敏（token/sig/signature/authorization）、诊断包（日志 + 库结构摘要，不含正文）
- `backend/server.py`：`RequestLogMiddleware` —— 只记方法 / 路径（去 query）/ 状态码 / 耗时，不记正文与凭据
- `backend/api/system.py`：§6.2 **#44 `POST /system/logs`**、诊断包 `GET /system/diagnostics`
- `main.py`：启动时配置日志并在退出时释放 handler
- 前端：`api.js` 统一 **10 秒超时**（§6.1）+ `requestBlob`；`logger.js` 远端上报与 `installGlobalHandlers`；P7 增加「诊断包」下载
- `tests/test_logging.py`：8 条用例

**决策**

- S2-16：日志命名与轮转、总量控制、脱敏规则、请求日志字段、#44 上报契约、诊断包内容与前端超时/上报策略

**验证**

- `pytest tests -q` → **229 passed**（2.13 新增 8 条）
- `python main.py --selfcheck` → 7 项 PASS，并已生成 `data/logs/inkwell-2026-10-23.log`
- 前端 15 个 ES Module 语法检查通过
- `ruff check` / `black --check` 全绿
- **未完成**：日志轮转/脱敏的真机长时间运行验证、诊断包在窗口内的下载走查

### 阶段二收尾（2026-10-23）

**结果**

- 阶段二 **14/14 项全部实现**：2.0 数据访问层、2.1 项目、2.2 卷章、2.3 编辑器、2.4 自动保存、
  2.5 字数、2.6 快照、2.7 设定文档、2.8 回收站、2.9 备份/后台、2.10 导出、2.11 检索、
  2.12 长任务、2.13 日志/诊断
- 接口新增 **#45~#49**（长任务查询、章节图片、暂存、文档图片、诊断包），错误码新增 **3004**
- `pytest tests -q` → **229 passed**；`python main.py --selfcheck` → 7 项 PASS；ruff / black 全绿
- **真实 pywebview 窗口冒烟通过**：页面/导航/桥接（token 注入）、项目卡片、写作页、Quill、
  输入→3s 自动保存（字数一致）、手动快照、检索高亮、导出 TXT（文件含正文）、立即备份，均无 JS 错误

**文档**

- `docs/版本更新/阶段二_接口与勘误同步清单.md`：§6.2 增补 #45~#49、长任务提交契约、§6.3 行为差异、
  E-01~E-03 修订位置、验证状态矩阵（供 v0.6 一次性同步）
- `docs/任务清单/阶段二任务清单.md` §七：14 项执行结果表 + 仍需真机验收清单
- `DECISIONS.md` §六 S2-06~S2-16；`README.md` 标记阶段二功能完成

**仍待真机验收**

- V-02（中文输入法/粘贴）、AC-4（taskkill 丢 ≤30s）、AC-5（1 小时回溯）、AC-6（导出误差）、
  AC-9（真实窗口恢复演练）、AC-10（检索性能）、回归 15/17/19；P3/P5/P8 深度交互走查

### 阶段二评审补强：测试缺口与日志/分页加固（2026-10-23 19:45）

**新增**

- `tests/js/`（Node 内置 test runner，零依赖）+ `tests/test_frontend_js.py` 入口：
  - `autosave.test.js`：停输 3s、最长 30s、失败重试 1s/3s/9s、耗尽提示、3002 不重试、成功后重试计数归零（5 条）
  - `draft-fallback.test.js`：**回归 15** 全链路（连续失败 → localStorage + 服务端双份暂存 → 重启恢复 →
    自动补写并清理）+ 本地兜底 / 服务端失败兜底（5 条）
  - `logger.test.js`：按值脱敏、限长、#44 上报前已脱敏（3 条）
  - `support/env.js`：假时钟 / localStorage / 与后端接口同构的内存 drafts 实现
- `frontend/js/fallback.js`：双份暂存读写器（`createDraftStore`：persist / recover / clear），`writer.js` 改为调用它
- `package.json`：仅用于 `type: module` 与 `npm test`（前端无构建步骤，浏览器不读取该文件）

**修复**

- **回归 15 无自动化覆盖**：新增 10 条 Node 用例，覆盖「重试耗尽 → 双份暂存 → 重启恢复 → 补写清理」；
  后端 `test_drafts.py` 继续覆盖暂存落盘 / 覆盖 / 清理
- **AC-6 无量化断言**：`test_export.py` 新增中英混排 + 标点 + emoji 样本，逐字比对导出正文与库内
  `content_text`，并用**独立参考计数器**断言字数误差 ≤0.5%（实测 0）
- **检索深页可能静默空页**：`MAX_PER_SIDE` 100 → 1000，并新增 `page_limited` 字段与 `hint`；
  `search.js` 改用新增的 `fuzzy` 字段判断「（模糊匹配）」，不再把任意 hint 当成模糊匹配
- **#44 日志正文风险**：后端新增 `sanitize_client_report`（去 HTML 标签、`content_html` 等正文字段
  整值省略、消息 ≤300 字 / 上下文值 ≤120 字），前端 `logger.js` 改为**按值**脱敏
  （只替换密钥值，保留路径与错误码）

**验证**

- `pytest tests -q` → **237 passed**（+8；其中 1 条为 Node 入口，实际执行 13 条 Node 用例）
- `ruff check` / `black --check` 全绿；前端 16 个 ES Module `node --check` 通过
- 真实 pywebview 窗口冒烟（真实后端 + 临时数据目录）：项目列表、写作页 Quill、输入 → 3s 自动保存
  （暂存已清理）、检索命中 + 模糊匹配提示，`js errors = []`
- 检索深页回归用例在旧上限 100 下失败、修正后通过（已实测）

### 真机窗口冒烟脚本固化（2026-10-23 21:25）

**新增**

- `tests/e2e/window_smoke.py`：一键真实窗口冒烟（临时数据目录、不碰 `data/`）——
  桥接 token → 项目列表 → 写作页 Quill → 输入 3s 自动保存 → 暂存清理 →
  检索命中/高亮/短词降级 → 页面无 JS 异常；支持 `--json` / `--keep-data` / `--timeout`，
  退出码 0/1，跑完自动关窗并清理临时目录
- `pyproject.toml`：`tests/e2e/*` 增加 E402 豁免（脚本需先插入项目根目录）
- `README.md`：测试与规范补充窗口冒烟命令与目录说明

**验证**

- 脚本实跑：14 步全部 PASS（`ok=true`、`page_errors=[]`），退出码 0，临时目录已自动清理
- `pytest tests -q` 仍 **237 passed**；ruff / black 全绿

### 阶段三 3.1：Design Token 与全局样式（2026-10-23 22:28）

**新增 / 修改**

- `frontend/css/tokens.css`：按 §7.2 重写 token —— 颜色（bg/panel/sidebar/text/text-2/border/
  accent/accent-soft/danger/success）、字体栈（Inter / 思源黑体 / 苹方 / 微软雅黑）、界面 14px、
  正文 17px/1.9/760px、圆角 6px、间距 4/8/12/16/24、顶栏 52px、侧栏 260px、动效 120ms
- 派生 token：`--accent-strong`、`--danger-soft`、`--overlay`（32%）、`--shadow`、`--font-mono`
- `frontend/css/style.css`：硬编码颜色 **18 处 → 0**；`--color-*` 更名成语义 token；
  编辑器排版改由 token 驱动；补 `:focus-visible`、`:disabled`、`::selection`、
  `dialog::backdrop`、滚动条统一、`prefers-reduced-motion`
- `DECISIONS.md` §七：**S3-01**（单主题浅色、`--danger` 调为 `#B84F36` 以满足 AA、禁用组合约束）

**验证**

- 8 张 `after_3_1_*` 截图：无 JS 异常；运行时 body `rgb(250,249,247)`、sidebar `rgb(243,241,237)`、
  编辑器 `17px / 32.3px / 760px`
- 对比度：10 组关键组合全部达 WCAG AA（`--danger` 4.74:1，原 §7.2 值仅 4.30:1）
- `window_smoke.py` 14 步 PASS；`pytest tests -q` → **237 passed**
- 与基线对比：P1/P3/P6/P7/P8 变化 ≤1.3%，P2 1.5%，P4/P5 因对话框遮罩变更 58%~71%

### 阶段三 3.2：侧边栏 + 大纲树（2026-10-24 00:41）

**新增**

- `frontend/js/sidebar.js`：卷折叠/展开（按项目记忆）、右键菜单、章节信息、
  标记定稿、拖拽排序（卷内/跨卷）、卷排序、键盘导航、删卷三选一
- `#53 POST /volumes/{vid}/adopt-default`（C-04）：首个命名卷创建后，把默认卷章节一次性迁入；
  仅允许唯一命名卷，服务层 `_append_all_chapters` 复用给 V1.1 合并卷
- `frontend/index.html`：章节信息对话框、删卷对话框、右键菜单容器
- `frontend/css/style.css`：菜单/折叠/拖拽/定稿标记/对话框说明样式

**修改**

- `frontend/js/writer.js`：树渲染拆到 sidebar.js；保存后增量更新章节字数（不再整树重绘）；
  新增 `markChapterFinal`（保存 → milestone 快照 → 状态同步）
- `backend/services/chapter_service.py`、`backend/api/volumes.py`：adopt-default 服务与路由
- `DECISIONS.md` §七：**S3-02**（大纲树交互与默认卷迁入契约）

**验证**

- `pytest tests -q` → **239 passed**（+2 adopt-default 用例）
- 真实窗口端到端驱动 8 项：C-04 迁入、章节属性、标记定稿、新建章节、拖拽排序、折叠记忆、删除章节，`page_errors=[]`
- `window_smoke.py` 14 步 PASS；`capture_ui.py --label after_3_2` 8 张无 JS 异常

### 版本控制基线 + IME 初测（2026-10-24 00:50）

**工程**

- **`git init` + 首个基线提交**（`4163afb`，181 文件）：`.gitignore` 排除 `.venv/`、`data/`、
  `_backups/`、`__pycache__/`、缓存与打包产物；工作区干净
- 第二次提交：IME 门禁修复 + 本次验证记录

**修复**

- `writer.js` 的 Ctrl+S（保存 + 手动快照）在 IME 组合期间也会触发，产生非预期版本；
  已加 `isComposing / keyCode===229` 门禁（S3-03），复测组合期间状态保持「未保存」

**验证（V-02/V-03 初测，`docs/版本更新/阶段三_IME验证记录.md`）**

- CDP `Input.imeSetComposition`：提交「你好」正确、取消组合正确、无拼音残留
- 组合期间 keydown 稳定带 `isComposing: true`（Ctrl+S/Ctrl+B 实测）
- 纯文本 Ctrl+V 粘贴正常；富文本粘贴与真实微软拼音候选窗仍需人工走查（V-02 仍为部分验证）

### 仓库整理 + 数据目录落点修订（2026-10-24）

**修复：打包模式不再默认写系统盘（S3-04，修订报告 §4.4）**

- `backend/config.py`：打包模式默认数据目录由 `%USERPROFILE%/Documents/Inkwell/`
  改为 **exe 同目录 `data/`**（装到哪个盘数据就落哪个盘）；仅当该目录实测不可写时才回退「文档」
- 新增 `is_writable_dir()`：写探针文件判定可写——`os.access` 在 Windows 上会因 UAC
  虚拟化对 `Program Files` 误报为可写
- `DATA_SUBDIRS` 新增 `webview/`，`AppConfig.webview_storage_dir` 指向它；
  `main.py` 与 `tests/e2e/window_smoke.py`、`tests/e2e/capture_ui.py` 的 `webview.start()`
  均显式传 `storage_path`——不指定时 pywebview 会把 WebView2 的 `UserDataFolder` 写到
  `%APPDATA%\pywebview`（系统盘，本机实测已 938 文件 / 25.1 MB 且随使用增长）

**整理：文档集中到 `docs/`（S3-05）**

- 根目录 9 份 `Inkwell项目报告*.md` 与 `项目报告/` 内容逐字节相同（纯重复），已删除
- 迁移：`项目报告/` → `docs/项目报告/`；`版本更新/` → `docs/版本更新/`；
  `阶段二任务清单.md`、`阶段三任务清单.md` → `docs/任务清单/`（`git mv`，历史保留）
- 根目录由 24 个散落文件收敛为 11 个（`README` / `CHANGELOG` / `DECISIONS` / 入口与依赖）
- 新增 `docs/README.md` 文档索引；README 补目录结构与数据目录说明
- 全仓 35 个文件、113 行路径引用同步更新（含 `docs/项目报告/` 内部保持「同目录」裸文件名）

**整理：`_backups/` 快照归档**

- 25 个全量快照（2866 文件 / 44.9 MB）中，旧 22 个压缩为
  `_backups/_archive/Inkwell_2026-10-22_1949至2026-10-23_2228.zip`（12.7 MB），
  字节数校验一致后删除原目录；保留最近 3 个可直接回滚
- `_backups/` 由 2866 文件降至 553，减少约 21.5 MB 占用

### 故障排查：窗口打不开（环境，非代码，2026-10-24）

**现象**：`python main.py` 在 `webview/platforms/winforms.py` 的 `import clr` 处失败：

```
RuntimeError: Failed to resolve Python.Runtime.Loader.Initialize from
.venv\Lib\site-packages\pythonnet\runtime\Python.Runtime.dll
```

**定位**（与代码无关）：
- `.venv\Scripts\python.exe -c "import clr"` 不引入任何项目代码即失败 → 环境问题
- pythonnet 3.2.1 / clr-loader 0.3.1 / pywebview 6.2.1 与 `requirements.lock` 一致，
  `.venv` 完整性核对 0 缺失 → 依赖未装坏
- 同一 DLL 复制到 `C:\...\Temp`、`D:\dprobe`、`D:\中文目录测试` 用 .NET Framework 的
  `Assembly.LoadFrom` 均可加载；唯独在 `D:\小说辅助\` 下失败 → 与中文路径无关，与该目录有关
- `icacls "D:\小说辅助"` 显示多出 `Mandatory Label\Low Mandatory Level:(OI)(CI)(NW)`
- 对照实验：给普通目录里的 DLL 打上 Low 标签 → `LoadFrom` 立刻失败（`0x80131515`）；
  恢复 Medium → 立刻成功

**根因**：工作区被盖了 Low 完整性级别标签。.NET Framework 拒绝从低完整性文件加载程序集，
pythonnet 因此加载失败，pywebview 无法初始化 WinForms 窗口。**与本次仓库整理、数据目录
改动均无关**（失败发生在 `import clr`，早于任何项目代码执行）。

**修复**：`icacls "D:\小说辅助" /setintegritylevel (OI)(CI)Medium`（继承标签自动下推子项）。
修复后 `import clr` 正常（.NET Framework 4.0.30319.42000），
`tests/e2e/window_smoke.py` 14 项检查全部通过（`ok: true`，无 page error）。

同源症状一并消失：`black` 不再卡死（低完整性进程写不了 `%LOCALAPPDATA%` 缓存）、
`tempfile.gettempdir()` 从仓库根恢复为 `%TEMP%`。

**文档**：新增 `docs/故障排查.md`（现象 / 判定 / 一条命令修复 / 同源症状）。

### 阶段三 3.3：项目卡片与首启引导（2026-10-24 02:05）

**P1 项目列表**

- 卡片补齐信息：封面（缺图或加载失败回退「书名首字」默认封面，FR-1.8）、
  状态徽标（连载中 / 已暂停 / 已完结，颜色 + 文案双重编码）、简介两行截断、
  字数与「最近打开」同排、进度条 + 百分比（FR-1.3，未设目标字数则不显示）、标签
- 整卡可点（`role="button"` + Enter / 空格）打开作品；「打开 / 设置」常显，
  悬停时卡片抬升、按钮描边加深
- **首屏骨架态**（3 张 shimmer 占位 + `aria-busy`）、**出错态**（说明 + 重试）、
  **空态**（标题 + 主 CTA「新建第一本书」）
- 暂存横幅改为逐条按钮，可直达对应作品；项目已进回收站时按钮置灰并说明原因

**首启引导（C-09）**

- 新建项目 → 自动在默认卷建「第一章」→ 直达写作页 → **章节加载完成、编辑器可编辑之后**
  聚焦正文并把光标放到末尾
- `frontend/js/writer.js` 新增 `focusEditor()`：返回是否就绪，未就绪时由调用方跳过，
  遵循 `docs/版本更新/阶段三_IME验证记录.md` §二 的时序约束
- 建章失败不阻断：仍进入写作页，用户可手动新建

**接口与数据（向后兼容）**

- `GET /api/projects/{pid}`（#3）详情即「打开项目」事件，写入 `last_opened_at`；
  **不触碰 `updated_at`**，列表更新时间序不变
- `GET /api/drafts`（#47）列表项新增 `project_id` / `project_title`（章节 → 卷 → 项目）；
  任一环节已软删除则不填，前端据此置灰「不可直达」

**新增纯函数与测试**

- `frontend/js/format.js`：`relativeTime` / `initialOf` / `progressPercent` /
  `percentLabel` / `formatCount` / `formatDuration`（零 DOM 依赖）
- `tests/js/format.test.js` 11 条；`tests/test_projects.py` +2（写入最近打开、
  不改 `updated_at`）；`tests/test_drafts.py` +2（项目归属、回收站后不填 `project_id`）
- `tests/e2e/window_smoke.py` 14 → **24 步**：卡片徽标 / 最近打开 / 缺封面回退、
  首启引导（直达写作页 + 自动建章 + 聚焦正文）、空态与 CTA、拦截 `fetch` 模拟后端故障
  → 出错态 → 重试恢复
- `tests/e2e/capture_ui.py` 8 → **9 张**（新增 `P1b_projects_empty`）；
  截图与点击前等待目标卡片就位（3.3 起列表先渲染骨架态）

**验证**

- `pytest` **243 passed**；`--selfcheck` 7 项 PASS；`ruff` / `black --check` 全绿；
  前端 18 个 JS 模块 `node --check` 通过
- 真实窗口冒烟 **24 步全过**（`page_errors=[]`）；`capture_ui --label after_3_3`
  9 张无 JS 异常

### 阶段三 3.4：编辑器排版与中文适配（2026-10-24 09:30）

**正文排版（§7.2 / FR-3.4）**

- 17px / 行高 1.9 / 行宽 ≤760px 居中沿用 token；首行缩进 2 字符（2em = 34px）**只作用于正文段落**，
  标题 / 列表 / 引用 / 代码块**逐类显式**清零（`text-indent` 会继承，漏一类就串味）
- 段间距 0（`--paragraph-gap`）：中文靠缩进断段，不插空白行
- 独占一行的图片居中且该段取消缩进；缺图 = 虚线 + 斜纹 + alt 文案（FR-3.10）
- 空文档占位改相对 `.ql-editor` 定位，与首行正文同列（像素实测 441 = 441；标题列 407）
- 选中色由 `--accent-soft` 改为 `--accent` 24% 叠加（原色在 `--bg` 上几乎看不出选中范围）；
  `caret-color: --accent-strong`
- Quill 默认配色 token 化：代码块深底 `#23241f` → `--sidebar`、引用竖线 `#ccc` → `--border`、
  链接与工具栏悬停 `#06c` → `--accent-strong`

**字体**

- `--font-ui` 补上思源黑体的实际家族名（`Source Han Sans CN` / `Noto Sans CJK SC`）；
  本机装有「思源黑体 CN」→ 全站中文由微软雅黑切到 §7.2 首选字体（**全站视觉变化、无布局位移**）；
  未装的机器继续回落苹方 / 微软雅黑；新增 `--font-editor` 作为正文字体别名栈
- 新增排版 token：`--indent-first-line: 2em`、`--paragraph-gap: 0`

**输入行为**

- `spellcheck=false`、`autocorrect=off`、`autocapitalize=off`、`data-gramm=false`：
  中文写作不再满屏红色波浪线，自动纠正也不再抢输入法组合串
- 编辑器补 `role="textbox"` + `aria-multiline` + `aria-label`（章节正文 / 设定文档正文）
- 空文档占位文案按页面给：章节「开始写这一章…」、设定「记录设定、人物或时间线…」

**FR-3.9 单章容量提示（回归 20）**

- 新增 `frontend/js/capacity.js`：`CAPACITY_WARN=50000`（NFR-P2 / AC-1 承诺范围）、
  `CAPACITY_SPLIT=80000`（回归 20 超长场景）；`chapterCapacity()` 为纯函数
- 状态栏 `#chapter-capacity`（`role="status"`）：5 万起 warn「已超 5 万字建议上限」、
  8 万起 split「建议拆章（不影响保存）」；**不弹窗、不禁用、不拦截保存**
- 颜色 + 文案双编码（描边色区分档位，文字统一 `--text` 保 AA），`title` 给出完整解释

**测试**

- `tests/js/capacity.test.js` 11 条（阈值边界 / 文案 / 脏输入 / 单调性 / 极值）
- `tests/e2e/window_smoke.py` 24 → **38 步**：排版实测 7 步（字号 / 行高 / 行宽 / 缩进 / 豁免 /
  spellcheck / 行高稳定）、9 万字章节 5 步（提示出现 → split 档 → 仍可编辑 → 保存成功）、
  空文档占位 2 步；种子新增 9 万字超长章节与排版样本
- `tests/e2e/capture_ui.py` 9 → **11 张**（新增 `P2b_typography` / `P2c_placeholder`），
  并把排版实测写进 manifest

**验证**

- `pytest` **243 passed**；Node 单测 **35 passed**；`--selfcheck` 7 项 PASS；
  `ruff` / `black --check` 全绿；19 个 JS 模块 `node --check` 通过
- 真实窗口冒烟 **38 步全过**（`page_errors=[]`）；`capture_ui --label after_3_4` 11 张无 JS 异常
- 实测值：`17px / 32.3px / 760px`、`p indent 34px`、`h3 indent 0px`、行高 `32.296875 × 3`

**已知缺陷**

- **D-3.4-1**：代码块「保存 → 重开」丢格式（服务端消毒白名单不含 `div`，且 Quill 载入端只认
  `<pre>`，不能只把 `div` 加进白名单）；本轮只把代码块样式做到位，持久化待单独批次修复，
  修法见 `DECISIONS.md` §七 S3-07 ⑨




