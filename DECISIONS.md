# Inkwell 决策记录

> 对应 `docs/项目报告/Inkwell项目报告_v0.5.md` §11「待决策与待确认事项」。
> **任务 1.1 交付物**：D-01~D-13 逐条给出明确结论。
>
> 说明：D 组条目均有报告给出的默认建议，且 §11 已声明「不确认则按默认执行」，
> 因此本阶段按默认建议落地；仅 D-12 / D-13 因其上游 Q-03 / Q-05 仍待发起人答复，
> 标注为 **【暂定】**，在对应决策时点前可无成本调整。

## 一、D 组结论

| ID | 决策项 | 结论 | 依据 / 来源 | 状态 |
|---|---|---|---|---|
| D-01 | 富文本编辑器 | **Quill 2.x** | 报告 §3.3「版本锁定」；ADR-004（与「无构建工具」一致，可静态引入） | 已关闭 |
| D-02 | 开源许可证 | **MIT** | 报告 §3.3 / §4.3 中 `LICENSE # 待 D-02`；§8.3 建议 MIT / Apache-2.0 | 已关闭（阶段四前落文件） |
| D-03 | 自动保存触发 | **停输 3s 或最长 30s** | 报告 §11 D-03 默认建议；关联 AC-4（丢失 ≤30 秒输入） | 已关闭 |
| D-04 | 快照策略参数 | auto：≥5 分钟 **且** 字数变化 ≥200 字，保留 30 条；每日首条额外保留 30 天；manual / milestone / restore 永久保留 | 报告 §5.3「版本快照策略（分级）」、ADR-006、P-10（避免每 30 秒一条快照撑爆上限） | 已关闭 |
| D-05 | 设定文档版本历史 | **功能进 V1.1，`document_version` 表 V1 建** | 报告 §5.2 `document_version` 说明、§11 D-05 | 已关闭 |
| D-06 | 性能实测口径 | 中位机 i5-10 代 / 8G / SSD；阶段四回填 §3.2 与 §12.1 | 报告 §11 D-06、AC-1~AC-3 | 已关闭 |
| D-07 | 首发平台 | **仅 Windows 10/11 x64** | 报告 §1.4 / §3.3；V1 不做跨平台 | 已关闭 |
| D-08 | AI 数据策略 | 用户自带 Key；不内置、不默认外发 | 报告 §11 D-08、附录 A | 已关闭 |
| D-09 | 快照是否压缩 | **默认不压缩** | 报告 §11 D-09；关联 R-11（存储膨胀） | 已关闭 |
| D-10 | 静态资源鉴权方案 | **短期签名 query token**（HMAC-SHA256，`?sig=<exp>.<mac>`） | ADR-009；`<img>` 只能带 URL 参数，头鉴权不可行 | 已关闭 |
| D-11 | 签名有效期 | **30 分钟** | 报告 §11 D-11 标注为假设；§12.1 同 | 已关闭（假设·可测后调） |
| D-12 | 版本号规则与发布渠道 | **SemVer + GitHub Release** | 报告 §11 D-12 默认建议 | **【暂定】待 Q-03 答复** |
| D-13 | 磁盘不足时是否自动清理最老备份 | **仅提示，不自动删除** | 报告 §11 D-13 默认建议；涉及「自动删除用户数据」的接受度，属偏好 | **【暂定】待 Q-05 答复** |

## 二、阶段一新增决策（实施中产生，需留痕）

| ID | 决策项 | 结论 | 依据 / 来源 | 状态 |
|---|---|---|---|---|
| S1-01 | chapter_fts 分词器 | **trigram** | SQLite 官方 FTS5 文档 §4.3.1 / §4.3.4（见下「三」实测）；unicode61 下中文检索不可用 | 已确认（用户已选） |
| S1-02 | 业务错误 → HTTP 状态码映射 | 鉴权 / 访问控制类（1002、4004）→ **401**；请求行非法（4003）→ **400**；其余业务错误 → **200** | 报告 §6.1 未规定映射；按「HTTP 承载传输语义、code 承载业务语义」补全 | **已确认**（发起人 2026-10-22 定稿：维持实现，不新增错误码） |
| S1-03 | Host 校验失败的错误码 | **复用 1002** | 报告 §6.1 错误码表无「Host 非法」条目；§6.3 只列了签名/路径/不存在的失败码。Host 校验属访问控制，归入 1002 | **已确认**（发起人 2026-10-22 定稿：Host 非法 → 401 + code 1002） |
| S1-04 | `/api/system/health` 是否鉴权 | **鉴权**（与其他 /api/* 一致） | §九 验收标准同时要求「`/api/health` 返回 200」与「无 token 请求返回 1002」；阶段一仅有 health 一个接口，统一规则才能满足后者 | 已决策 |
| S1-05 | PRAGMA 注入方式 | 在 SQLAlchemy `connect` 事件中**直接执行 PRAGMA**（不切换 autocommit） | 官方 SQLAlchemy 2.0 SQLite 文档示例使用 `dbapi_connection.autocommit = True`，但该属性在 **Python 3.11 的 sqlite3.Connection 上不存在**（3.12+ 才有）；实测 3.11.9 下 connect 事件时 `isolation_level=''`（事务未开启），直接执行 `PRAGMA foreign_keys=ON` 有效（返回 1） | 已决策（有实测） |
| S1-06 | pywebview 窗口参数 | `text_select=True`、`private_mode=False`、`debug=dev` | pywebview 官方 API 默认 `text_select=False`（写作应用必须可选中）与 `private_mode=True`（localStorage 不保留，会破坏暂存兜底 AC-4 与「恢复上次项目」） | 已决策（**待确认**，见交付说明） |
| **S1-07** | FTS 同步策略 | **V1 保留触发器即时同步**；不引入 dirty 表与后台去抖批处理。去抖降级为**阶段二可选优化假设**（仅可用于 `optimize` / 批量导入场景） | 发起人 2026-10-22 结论（L-01 关闭）：external content 表不同步则查询结果不可预测（SQLite 官方 FTS5 文档 §4.4.3）；触发器为最小可依赖实现，复杂度与失败面最小 | **已确认**（维持实现，不改代码） |
| **S1-08** | 建表约定（软删除与 `updated_at`） | 全业务表统一 `is_deleted` / `deleted_at`；`volume` / `document` 补 `updated_at`；`document` **暂不建索引**；`document_version` / `chapter_version` **保持无 `updated_at`**（不可变快照语义） | 发起人 2026-10-22 结论（L-05 关闭）：软删除依据 §5.2 通用约定；版本快照为不可变记录，加 `updated_at` 会引入「快照被改」的歧义；`document` 索引待阶段二实测后补 | **已确认**（维持实现，不改代码） |
| **S1-09** | 健康检查路径 | `/api/system/health`（router 挂 `/system/health` + `/api` 前缀） | 发起人 2026-10-22 结论（L-06 关闭）：以 §6.2 接口清单 #1 为准 | **已确认**（维持实现，不改代码） |

## 三、S1-01 分词器实测记录

执行命令（Python 3.11.9，SQLite 3.45.1）：

```
>>> c.execute("CREATE VIRTUAL TABLE tri USING fts5(a, tokenize='trigram')")
>>> c.execute("INSERT INTO tri VALUES('这是一段中文测试文本abc')")
>>> c.execute("SELECT count(*) FROM tri('中文测试')")   -> 1
>>> c.execute("SELECT count(*) FROM tri('中文')")       -> 0   # 少于 3 字符不命中
>>> c.execute("CREATE VIRTUAL TABLE u61 USING fts5(a)")       # 默认 unicode61
>>> c.execute("INSERT INTO u61 VALUES('这是一段中文测试文本')")
>>> c.execute("SELECT count(*) FROM u61 WHERE u61 MATCH '中文'")  -> 0
>>> c.execute("SELECT count(*) FROM u61 WHERE u61 MATCH '这是一段中文测试文本'") -> 1
```

结论（依据 SQLite 官方 FTS5 文档）：

- `unicode61` 默认类别为 `L* N* Co`，汉字属 `Lo`（字母类），且中文无空格分隔，
  因此「Each contiguous run of one or more token characters is considered to be a token」
  会把整段连续中文视为**单个 token**，子串查询必然落空 → 中文全文检索**不可用**。
- `trigram` 将每 3 个字符切为一个 token，支持通用子串匹配，中文可用；
  代价是索引体积更大，且查询串至少 3 个字符（搜两字词无结果）。
- 前置条件：trigram 需要 SQLite ≥ 3.34，本机 3.45.1 满足，实测 `SUPPORTED`。

> 关联：§5.2「FTS5 external content」、ADR-008、R-11（存储膨胀）、FR-7（Must）。

## 四、基线报告勘误登记（**待下次文档修订时统一，本次不改代码**）

> 登记时点：2026-10-22，随 L-01 / L-06 结论一并登记。
> 本节只做登记，不修改 `docs/项目报告/Inkwell项目报告_v0.5.md`；下次修订报告（→ v0.6）时按此执行。

| ID | 位置（`docs/项目报告/Inkwell项目报告_v0.5.md`） | 原文 | 应改为 | 依据 | 状态 |
|---|---|---|---|---|---|
| **E-01** | §5.2 表结构说明（L618）、§5.4 索引维护（L672） | 「FTS5 `chapter_fts` external content，**后台去抖更新**」 | 「FTS5 `chapter_fts` external content，**V1 触发器即时同步；去抖为阶段二可选优化假设**」 | 决策 S1-07 / L-01 结论 | 待修订 |
| **E-02** | §九 阶段一「验证方式」（L909）、§12.3 开发者上手最小验证（L1070） | `/api/health` | `/api/system/health` | 决策 S1-09 / L-06 结论；与 §6.2 #1 对齐 | 待修订 |
| **E-03** | §5.2 表结构中 `chapter_version` / `document_version`，及 L-05 的表述「全表统一 `is_deleted` / `deleted_at`」 | L-05 表述为「**全表统一**软删除」，但 0001 中两张快照表**不含**软删除字段，字面解读会得出「需补字段」的错误结论 | 明确为：**快照表不设软删除字段**。快照的删除状态**依附父资源** —— 父章节软删 → 快照随父进回收站；父被清空 → 级联**物理删**。§6.2 #27「删快照」与 §5.3「快照清理」均为**物理删**，不是回收站语义 | 发起人 2026-10-23 结论：快照是 append-only 历史记录，独立软删除会凭空产生「软删除的历史版本」这种怪状态。**不补迁移 0003**；`models.py` 按 DDL 权威（migrate.py）对齐，不加该字段 | 待修订（实现已确定，无需改代码） |

### E-01 同源关联行（同一问题源头，**是否一并修订待确认**）

| 位置 | 原文要点 | 建议改法 |
|---|---|---|
| §2.4 NFR-P7（L279） | 「索引更新后台去抖（**假设：变更后 10s 批量合并**）」 | 改为「索引更新 V1 触发器即时同步；批量导入/optimize 场景可引入去抖（阶段二可选）」 |
| §12.1 假设清单（L1034） | 「FTS 去抖 10s … 阶段二调优后固化」 | 去抖降级为可选假设；保留「WAL checkpoint 每 5 分钟或 ≥32MB」 |
| §4.5 启动流程（L538） | 「FTS 索引去抖更新」 | 改为「FTS 索引一致性维护（触发器即时同步；必要时 rebuild-fts）」 |
| §九 阶段二 2.11 任务名（L925） | 「全文检索（external content + 去抖 + 转义）」 | 改为「全文检索（external content + 同步策略调优 + 转义）」 |

> 说明：E-01 / E-02 已由发起人确认；关联行**未在本次指令中明确**，故列为待确认项，
> 下次修订报告前与你核对一次即可一并落地。

## 五、阶段二开工前决策（C 组定稿，2026-10-23）

| ID | 决策项 | 结论 | 依据 / 来源 | 状态 |
|---|---|---|---|---|
| **S2-01** | Quill 版本与构建方式 | 锁定 **2.0.3**；使用 **UMD 构建** `dist/quill.js`（挂全局 `window.Quill`）+ `quill.snow.css`；落 `frontend/vendor/quill/`（含 LICENSE.txt），**不走 CDN**、不用 importmap | C-01 默认方案 + 实测：① npm registry `quill/latest` = 2.0.3；② jsDelivr 目录列出 2.0.3 dist 仅 `quill.js`/`quill.core.js`/三个 css，**不存在** `quill.global.js`/`quill.browser.js`；③ 文件头为 UMD 包装器 `…:t.Quill=e()}(self,…)`；④ Node 22 以脚本执行该文件抛 `ReferenceError: document is not defined`（若是 ESM 应抛 `SyntaxError: Cannot use import statement outside a module`）→ **非 ESM** | 已确认（已落盘 + 校验和见 `frontend/vendor/quill/README.md`） |
| **S2-02** | 设定文档纳入全文检索 | 新增**迁移 0002** 建 `document_fts`：external content 指向 `document`，列 `title` + `content_text`，`tokenize='trigram'`，三触发器 `document_fts_ai/ad/au` 与 chapter 同构；`SCHEMA_VERSION` → **2**；查询在 **service 层分两次查后合并**（不 UNION，便于「仅章节 / 仅文档 / 全部」范围切换）；0001 **不回改**；阶段一 `data/inkwell.db` 为空测试库，**不做数据回填** | C-02 确认；FR-7.1 Must；DDL 权威仍在 `migrate.py` | 已确认 |
| **S2-03** | 长任务机制 | 方案 A：进程内内存任务表 + `GET /tasks/{tid}`（§6.2 新增 **#45**）。细节：① **互斥**：进程内一把锁，同时只允许一个长任务，第二个请求返回 **HTTP 409 + 新增 code 3004**；② 任务对象 `{tid, type, state(pending/running/success/failed), progress(0-100), message, result, error, created_at}`；③ 前端 500ms 轮询，`success` 读 `result` 后主动 `DELETE /tasks/{tid}` 清理，失败任务保留 5 分钟后自动清；④ **不做取消、不持久化**（V1 长任务 ≤120s，进程重启任务本就失效） | C-05 确认；方案 B 不可行（备份未完成时 `backups/` 无文件可轮询），方案 C 违反「不静默挂起」；NFR-R2 写串行 | 已确认 |
| **S2-04** | 数据访问层 | **同步** SQLAlchemy ORM（`sessionmaker`），原生 SQL 走 `session.execute(text(...))`；软删除**显式过滤**，并在 `models.py` 提供 `active(Model)` 查询辅助（默认带 `is_deleted=0`），回收站查询裸查不过滤；**DDL 一致性测试必须真跑**（建库后 `PRAGMA table_info` + `index_list` 与 `migrate.py` 结果逐字段比对） | C-06 确认 + 两项微调；80% 为 CRUD、20% 原生 SQL；全局 `before_compile` 自动过滤会与回收站反查冲突 | 已确认 |
| **S2-05** | 阶段二排期调整 | **2.12 长任务框架提前到 2.0 之后立即实施**（与 2.1~2.4 并行），不再排在 2.8 之后 | 发起人建议；2.5(#43)、2.9、2.10、2.11(#42) 均依赖 2.12，后置会卡脖子 | 已确认 |

## 六、阶段二实施决策（实施中产生，需留痕）

| ID | 决策项 | 结论 | 依据 / 来源 | 状态 |
|---|---|---|---|---|
| **S2-06** | 卷树接口与排序契约 | ① `GET /projects/{pid}/volumes` 返回 `{volumes, default_volume}`，**默认卷单列**、不混入 `volumes`；`volumes` 为空时前端把 `default_volume` 当作唯一卷显示（对应 BR-6「大纲树默认隐藏，项目无其他卷时才显示」）。② 排序接口用 `{id, prev_id, next_id}` 表达「拖到两项之间」，由服务端按 **BR-3** 计算序号；头部落到 ≤0 或相邻差 ≤1 时整体重整为 1000 步长。③ C-03 合并卷**不做接口与 UI**，仅在 `chapter_service.move_chapters_to_volume()` 预留数据层函数。④ 2.2 只交付**大纲树数据层**，树 UI 归阶段三 3.2（依据清单 2.2 目标原文） | 报告 §6.2 #10/#14/#22、BR-3、BR-6；阶段二清单 2.2 目标与 C-03 默认处理 | 已决策 |
| **S2-07** | 字数统计实现口径（BR-1） | ① CJK 逐字范围：`U+3400-4DBF`、`U+4E00-9FFF`、`U+F900-FAFF`、`U+20000-2FA1F`；② 西文词：字母/数字开头，内部允许 `.` `_` `'` `’` `-`（don't / well-known 各计 1）；③ 标点/emoji/符号默认**逐字符计 1**，`count_punctuation=False` 时不计；④ 去标签用标准库 `HTMLParser`（不新增依赖），`script`/`style` 跳过，块级标签转段落，连续空行压缩为两行；⑤ 重算任务只处理活跃章节，软删除章节保留原值 | 报告 BR-1、§8.1「字数误差 ≤0.5%」；V-06 样本口径在阶段四回填 | 已决策（V-06 实测待阶段四） |
| **S2-08** | 2.3 编辑器实施契约 | ① **新增 #46 `POST /chapters/{cid}/images`**（multipart）：§6.2 无图片上传接口，按 #45 先例补入，待下次文档修订同步 §6.2；② `/files/{relpath}` 校验顺序改为「**路径规范化 → 签名 → 文件存在**」：报告 §6.3 原顺序会让穿越路径先报 4004，与回归 13 要求的 4003 冲突；③ `chapter.version_no` 语义：**每次正文保存 +1**（修订号）；2.6 快照以该修订号记录（唯一约束保证同号一条），`expect_version` 不一致 → 3002；`expect_version` 缺省时不做乐观锁；④ 图片落 `media/{cid}/{uuid}.{ext}`，HTML 只存相对路径 `media/...`；返回详情时临时签名，前端 **20 分钟**批量续签（V-03）；⑤ 消毒白名单：块级标签允许 `class`，`img src` 仅 `media/`，外链图片丢弃，`style` 属性一律去除，`script`/`style`/`iframe` 连内容删除；⑥ V1 编辑器格式仅 FR-3.1 所需项（颜色/字号/字体不入库） | 报告 §6.2 #18~#21/#36/#37、§6.3、NFR-S6/S7、ADR-009、回归 13/14/18；V-02 真机走查仍待做 | 已决策 |
| **S2-09** | 自动保存与暂存策略 | ① **新增 #47 暂存接口**：`POST/GET /drafts`、`GET/DELETE /drafts/{cid}`，文件 `drafts/chapter_{cid}.json`（覆盖写、原子落盘、损坏忽略、8MB/章）；② **双份暂存**：localStorage（编辑中首写 2s、随后每 10s、`beforeunload` 同步写）+ 服务端 `drafts/`（保存失败/冲突时写）；③ 自动保存：停输 **3s** / 最长 **30s**；切换章节、离开写作页、关闭窗口强制保存；④ 失败重试 **1s/3s/9s**，3 次仍失败保留暂存并停止；**3002 不重试**（先落暂存再提示刷新）；⑤ 恢复：打开项目时列服务端暂存并确认，打开章节时再查 localStorage，恢复后**自动补写**；⑥ 正文 `PUT` 成功后服务端自动清理该章暂存 | 报告 BR-2、D-03、NFR-R6、AC-4、回归 15；§6.2 无暂存接口 | 已决策（AC-4 / 回归 15 真机端到端待走查） |
| **S2-10** | 版本号与回滚契约 | ① `chapter.version_no` = **修订号**：正文保存 +1；手动/里程碑快照再 +1；回滚再 +1；`chapter_version.version_no` = 创建时修订号（唯一约束）。② **回滚**：新号 #N 先存**回滚前**正文为 `restore` 永久快照 → 目标版本内容覆盖正文（重新消毒/还原图片路径/重算字数）→ `chapter.version_no = N`（不再二次递增）；返回 `restored_from` + `version_no`。③ auto 快照：无历史快照时需 ≥200 字；有历史时需距最近快照 ≥5 分钟 **且** 字数变化 ≥200；新快照用当前修订号。④ 保留：auto 最近 30 条 + 每日首条额外 30 天（本地日期）；manual/milestone/restore 永不清。⑤ **Ctrl+S = 保存 + 手动快照**（FR-5.5）；「存为版本」按钮等价。⑥ 快照异常只记日志，不阻断正文保存 | 报告 D-04、BR-9、FR-5、AC-5、§5.3、§6.3；版本号语义原文存在歧义，按「回滚生成新版本 + 回滚前永久保留」两条硬约束定稿 | 已决策（AC-5 真机实测待补） |
| **S2-11** | 设定文档实施契约 | ① 分类固定五类 `world/timeline/faction/glossary/other`（中文标签随列表返回）；② `order_index` 步长 1000，新建排末尾；`PATCH` 接受 `order_index`（排序 UI 留阶段三）；③ **新增 #48 `POST /documents/{did}/images`**，图片落 `media/documents/{did}/`（避免与章节 id 冲突），与章节图片同一套校验/签名；④ 文档正文复用 `normalize → sanitize → 提取纯文本 → 字数` 链路，但**不计入** `project.total_word_count`；⑤ 版本历史按 D-05 **不做**（`document_version` 表已建，V1.1 补）；⑥ P3 采用**手工保存** + 切换/离开前强制保存（自动保存与状态栏三态留阶段三 3.5） | 报告 FR-4.1~4.4、D-05、§6.2 #28~#30、BR-4 | 已决策 |
| **S2-12** | 回收站与父链恢复契约 | ① 类型固定 `project/volume/chapter/document`；列表按类型分组，含父级标题与 `days_left`；② **父资源在回收站时返回 `HTTP 200 + code 0 + data.requires_parent=true`**，`parent` 字段给出类型/id/标题；前端确认后带 `with_parent=true` 重试；③ 恢复父资源只恢复**同批次**（`deleted_at` 相同）的级联子项，先前单独删除的仍留在回收站；④ 清空与 30 天过期清理走**物理删除**（DB 外键级联 + FTS 触发器同步），`purge_expired_trash()` 供 2.9 启动后台调用；⑤ 恢复后统一 `recompute_project_totals()`；⑥ 级联删卷时同步扣减项目总字数 | 报告 BR-4、FR-1.6、FR-2.1、AC-11、§6.2 #39~#41；错误码表无「父资源待恢复」，故用 code 0 + 标志位而非新增错误码 | 已决策 |
| **S2-13** | 备份/恢复与启动后台契约 | ① 命名：`inkwell_backup_*`（手动）、`inkwell_daily_*`（每日）、`inkwell_premigrate_*`/`inkwell_prerestore_*`（自动安全备份）；② 保留：每日 7 日 + 4 周，手动/迁移前/恢复前**不自动删**；③ 恢复先**同步校验**（路径→存在→quick_check→schema_version）：损坏 3001、版本高于应用 3003、非法名 4003，校验通过才提交长任务；④ 恢复流程：prerestore 备份 → dispose → 删 WAL/SHM → 替换文件 → reopen → 按需迁移；⑤ 启动后台（窗口模式）：每日备份、回收站 30 天清理、过期备份、孤儿媒体（>24h 且未被引用）、每周 integrity_check、磁盘 1GB 预警、WAL checkpoint；**时间回拨跳过**备份与清理（BR-8）；⑥ `--selfcheck` 不启动后台，避免污染真实数据目录 | 报告 FR-6.1~6.3、6.7、6.8、NFR-R4/R5/R7~R10、BR-7/BR-8、回归 6/16/17/19 | 已决策（AC-9 真机演练待补） |
| **S2-14** | 导出契约 | ① 输出位置：数据目录 `exports/`，文件名 `{安全书名}_{YYYYMMDD_HHMMSS}.{txt|md}`（非法字符替换为 `_`，重名追加序号）；② 只导出**正文**（卷/章），不含设定文档；③ 流式写入：按 50 章批量读取正文，写 `.tmp` 后 `os.replace`（BR-7，NFR-P6/V-07）；④ 空项目：TXT 输出书名/简介/`（暂无正文）`，MD 输出 `# 书名` + `## 目录` + `（暂无章节）`；⑤ 默认卷无其他卷时不输出卷标题，有其他卷时输出「默认卷」分组；⑥ 返回 `relpath`/章数/字数（章节缓存字数之和，AC-6 口径） | 报告 FR-6.4/6.5、BR-7、AC-6、回归 7/19、V-07 | 已决策（AC-6/回归 19 真机演练待补） |
| **S2-15** | 全文检索契约 | ① 查询串 ≥3 字符走 FTS5 trigram，整体作为短语（双引号包裹、内部引号翻倍）；<3 字符降级 LIKE（转义 `% _ \`）并返回 `hint`；② 章节与设定文档**分两次查后合并**（不 UNION），支持 `scope=all/chapters/documents` 与 `project_id`；③ 摘要由 Python 生成：正文 HTML 转义，仅服务端生成的 `<mark>` 受信；标题命中但正文无片段时取正文开头；④ 分页：两侧各取 `page*page_size`（合并按 `(bm25, -updated_at)` 排序后切片，`total` 为两侧 count 之和；单侧上限经 **S2-17** 由 100 调整为 1000，并新增 `page_limited`）；⑤ 排序/更名后由触发器保证索引即时同步；`#42` 用 FTS5 `rebuild` 重建两张 external content 表 | 报告 FR-7.1~7.4、§6.2 #31/#42、AC-10；S2-02「分两次查合并」 | 已决策（AC-10 性能实测待补） |
| **S2-16** | 日志与诊断契约 | ① 日志 `logs/inkwell-YYYY-MM-DD.log`，按天切换；单文件 >10MB 再按时间切分；总量 >50MB 删最老（活动文件不删）；② 脱敏：`X-Inkwell-Token`、`token=`、`sig=`、`signature` 值替换为 `***`，单条 ≤1000 字符；**不记正文/响应体/认证头**；③ 请求日志只记方法 / 路径（去 query）/ 状态码 / 耗时；④ **#44** 接受 `level∈{info,warning,warn,error}`、`message`（1~1000）、可选 `context`；⑤ 诊断包 = `diagnostics.txt` + `schema.json`（表/列/索引/行数）+ 最近 ≤7 个日志文件（≤5MB），**不含正文/token/签名**；⑥ 前端普通请求 10 秒超时并明确报错；error/warn 经 #44 上报，全局 `error`/`unhandledrejection` 捕获 | 报告 NFR-M4、NFR-M6、§8.2、§6.1、#44；50MB 与 10s 为假设阈值 | 已决策 |
| **S2-17** | 检索分页窗口与总数字段（评审补强） | ① 合并分页的正确性要求**每侧都覆盖到本页之前的所有名次**，因此单侧取数窗口 = `page*page_size`，单侧上限由 **100 提升到 1000**（此前 120 条命中时第 6 页会静默返回空页）；② 窗口超出上限时返回 `page_limited=true`，`hint` 说明「仅支持前 N 条以内的分页，请加长搜索词」，**不再静默给出不完整分页**；③ 响应新增 `fuzzy` 字段表示是否降级 LIKE，前端据此显示「（模糊匹配）」，不再把任意 `hint` 当成模糊匹配；④ `total` 仍为两侧 count 之和，不截断；⑤ 双查询合并结构不变（S2-02），根治方案（游标分页）留阶段三 | 阶段二评审 P2-3；旧上限 100 的空页已用回归用例复现（`test_search_deep_page_returns_last_window`） | 已决策（游标分页待阶段三） |
| **S2-18** | 日志正文兜底与前端按值脱敏（评审补强） | ① NFR-M4 由「碰巧安全」改为「设计安全」：**#44** 入参新增 `sanitize_client_report` —— 去掉 HTML 标签、`content_html`/`content`/`text` 等正文字段整值替换为 `[正文已省略]`、`message` 截 300 字（尾部 `…[已截断]`）、`context` 每个值截 120 字；标量（int/float/bool/None）保留原类型；② 落盘前仍经 `redact`（token/sig 脱敏 + 1000 字上限），两层防护；③ 前端 `logger.js` 由「命中关键字整条替换」改为**按值脱敏**：只替换 `token=` / `sig=` / `signature=` / `X-Inkwell-Token:` 的取值，保留路径、错误码与文案，单条仍限 1000 字；④ 本条只是兜底，响应正文/编辑器正文仍不得主动上报 | 阶段二评审 P2-4；`api.js` 现有错误信息只含 path + code，本条防未来误用 | 已决策 |

## 七、阶段三实施决策（实施中产生，需留痕）

| ID | 决策项 | 结论 | 依据 / 来源 | 状态 |
|---|---|---|---|---|
| **S3-01** | 视觉 Token 与 WCAG AA 调整 | ① 单主题浅色，严格按 §7.2；深色模式归 V1.1（FR-3.8，C-01 确认）；② `--danger` 由 §7.2 的 `#C0563C` 调为 **`#B84F36`**：原值在 `--bg` 上仅 4.30:1，不达 C-01 确认的 AA；新值 4.74:1（`--panel` 上 4.99:1，白字 4.99:1）；③ 派生 token：`--accent-strong #6B5B49`（主按钮悬停，白字 6.53:1）、`--danger-soft #FBEEE9`、`--overlay rgb(43 43 43 / 32%)`、`--shadow`；④ 界面字号 14px；正文 17px / 1.9 / 760px 全部由 token 驱动；⑤ **禁用组合**：`--accent` / `--text-2` 写在 `--accent-soft` 上仅 4.39 / 4.49:1，故其上文字统一用 `--text`；`--danger` 文字只用于 `--panel` / `--bg` | 报告 §7.2、§7.1（WCAG AA）、C-01；3.1 实测对比度（记录见 `docs/版本更新/阶段三_UI走查基线.md` §八） | 已实施（danger 差异待 v0.6 勘误同步） |
| **S3-02** | 大纲树交互与默认卷迁入（C-04） | ① 右键菜单为自绘 `#tree-menu`（可键盘操作、随窗口滚动关闭）；② 删除非空卷用三选一 `<dialog>`：取消 / 移入默认卷 / 一并删除，空卷仍需确认；③ **新增 #53 `POST /volumes/{vid}/adopt-default`**：仅当目标卷是该项目唯一命名卷时，把默认卷章节按原顺序一次性迁入（复用 `_append_all_chapters`），前端在创建首个命名卷并确认后调用；④ 章节属性用 `#chapter-info-dialog`（标题/状态/梗概/目标字数），保存走 `PATCH /chapters/{cid}`；⑤ **标记定稿** = 当前章节先保存 → 建 `milestone` 快照 → `PATCH status=final` → 刷新树；⑥ 拖拽用 HTML5 DnD，支持章内/跨卷/卷排序（`target_volume_id` + `prev_id/next_id`）；⑦ 折叠状态按项目存 localStorage；⑧ **不提供「章节移入默认卷」菜单项** —— 默认卷在大纲树隐藏，移入会导致章节不可达，故只在删卷时允许移入 | C-04 确认；FR-2.1~2.5、BR-3/BR-6、NFR-U3；3.2 端到端驱动验证（8 步） | 已实施（`#53` 待 v0.6 同步） |
| **S3-03** | 快捷键与 IME 组合 | ① 所有全局快捷键在 `event.isComposing === true` 或 `event.keyCode === 229` 时**直接放行**（不 `preventDefault`、不执行动作）；② 3.7 快捷键注册表统一实现该门禁，3.8 查找条输入框同样遵守；③ 现有 `writer.js` 的 Ctrl+S 已加门禁（修复「组合中按 Ctrl+S 生成非预期版本」）；④ 该结论由 WebView2 CDP 组合事件验证：组合期间 keydown 的 `isComposing=true` 可稳定读取 | V-03；3.2 后 IME 初测（`docs/版本更新/阶段三_IME验证记录.md`）；3.7/3.8 设计前置 | 已实施（Ctrl+S）；3.7/3.8 全量接入 |
| **S3-04** | 数据目录默认落点与 WebView2 缓存位置（**修订 §4.4**） | ① 打包模式默认目录由 `%USERPROFILE%/Documents/Inkwell/` 改为 **exe 同目录 `data/`**，装到哪个盘数据就落在哪个盘；② 仅当 exe 目录**实测不可写**（`is_writable_dir()` 写入探针文件判定，`os.access` 在 Windows 上会因 UAC 虚拟化误报）时才回退「文档」；③ 新增数据子目录 `webview/`，`main.py` 与两个 e2e 脚本均把 pywebview `storage_path` 显式指向它——不指定时 WebView2 的 `UserDataFolder` 会落在 `%APPDATA%\pywebview`（系统盘，实测已占 25MB 且持续增长） | 发起人反馈「数据不应写 C 盘」；pywebview `platforms/winforms.py` `init_storage()`：`cache_dir = _state['storage_path'] or os.path.join(APPDATA, 'pywebview')` | 已实施（待打包后实测） |
| **S3-05** | 仓库目录规约（文档集中到 `docs/`） | ① 根目录**只保留**构建与协作入口：`README.md`、`CHANGELOG.md`、`DECISIONS.md`、`main.py`、`smoke_test.py`、`pyproject.toml`、`package.json`、`requirements.*`、`.gitignore` 及代码/数据目录；② 其余文档一律放 `docs/`：`项目报告/`（v0.1~v0.5 + 自审意见）、`任务清单/`、`版本更新/`（进度记录 + 走查基线 + 截图）；③ 文档间引用统一写**仓库根相对路径**（如 `docs/版本更新/进度记录.md`），`docs/项目报告/` 内部互引用保持「同目录」裸文件名；④ 根目录曾存在的 9 份报告副本与 `docs/项目报告/` 内容逐字节相同，已删除 | 发起人反馈「根目录杂乱」；`docs/README.md` 为文档索引 | 已实施 |
