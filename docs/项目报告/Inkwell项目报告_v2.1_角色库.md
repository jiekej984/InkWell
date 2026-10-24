# Inkwell 小说辅助工具 — V2.0 需求与设计报告（角色库 · 三层关系模型）

## 文档信息

| 项 | 内容 |
|---|---|
| 文档名称 | Inkwell 小说辅助工具 — V2.0 需求与设计报告 |
| 版本 | **v2.1（V2.0 设计基线 · 三层关系模型）** |
| 日期 | 2026-10-24 |
| 状态 | **口径已确认 + 已自审**（发起人 2026-10-24「按这个来」；同日完成 24 项自审修订，见 [`Inkwell项目报告_v2.1_自审意见.md`](Inkwell项目报告_v2.1_自审意见.md)）。本文档为 5.0 开工依据 |
| 适用范围 | V2.0（角色库：角色 / 组织 / 阵营 / 三视图）的需求、数据模型、接口、交互、验收依据 |
| 与旧基线的关系 | `Inkwell项目报告_v2.0_角色库.md` **已被本版取代**（仅覆盖「角色 + 一对一关系」）；`Inkwell项目报告_v0.8.md` 继续作为 V1.0 基线 |
| 配套文档 | `../任务清单/V2.0任务清单.md`、`../../DECISIONS.md`（S4-xx 待落）、`../版本更新/阶段三_接口与回归同步清单.md`（回归编号沿用） |

## 修订记录

| 版本 | 日期 | 主要变更 |
|---|---|---|
| v2.0 | 2026-10-24 | 首版：确认「V2.0 先做角色库、AI 后置」；角色卡 + 一对一关系 + 单一关系图，13~15 人日 |
| **v2.1** | 2026-10-24 | **并入三层关系模型**：新增大立场 / 组织 / 组织成员 / 组织关系 / 立场关系 5 张表；关系类型 11 → 20 类；关系增加生效章区间与隐秘标记；视图由 1 张图扩为 三模式画布（人物 / 组织 / 阵营）+ 角色卡小面板；剧情线导图移出本版；工期 13~15 → **22~24 人日**；接口由 13 个扩为 28 组 |
| **v2.1+** | 2026-10-24 | **自审修订（24 项）**：补 `character.note` 列、`custom_label` 改空串并入唯一索引、组织软删递归、根组织删除规则、立场继承、主组织降级、`#64` 返回契约、P10/P11 职责边界、文本字段纯化、布局体积与按模式隔离等；DDL 修订后重跑验证。逐项见 [`Inkwell项目报告_v2.1_自审意见.md`](Inkwell项目报告_v2.1_自审意见.md) |

---

## 目录

- [一、结论先行](#一结论先行)
- [二、为什么先做角色库](#二为什么先做角色库)
- [三、现状盘点](#三现状盘点)
- [四、需求分析](#四需求分析)
- [五、数据模型设计](#五数据模型设计)
- [六、接口设计](#六接口设计)
- [七、UI/UX 设计](#七uiux-设计)
- [八、AI 预留与 V3.0 衔接](#八ai-预留与-v30-衔接)
- [九、质量保障与验收](#九质量保障与验收)
- [十、任务分解与排期](#十任务分解与排期)
- [十一、风险与待确认事项](#十一风险与待确认事项)
- [十二、与原路线图的差异](#十二与原路线图的差异)
- [附录 A：20 类关系全表](#附录-a20-类关系全表)
- [附录 B：术语增补](#附录-b术语增补)

---

## 一、结论先行

1. **V2.0 做「三层结构 + 三视图」的角色库**：角色是点，组织是面，大立场是背景；三者之间都能画关系。
2. **不直接上 AI 的判断不变**：AI 要读的是「人物圣经」，这份圣经就是本版建的结构化数据。数据没建好，AI 只能读散文。
3. **工作量 22~24 人日（约 5 周半）**，拆为 5.0~5.10 十一个任务，分三个里程碑（M1 能建档 / M2 能看图 / M3 三层完整）。
4. **本版明确不做**：AI、剧情线导图、时间轴 UI、头像节点、关系强度数值。剧情线导图作为 V2.1 独立模块。
5. **两项关键风险已被识别并处理**：一是「势力文档」与「组织实体」的概念重复（§5.5、R-25）；二是关系唯一约束与软删除冲突（用部分唯一索引，已实测 7/7）。

## 二、为什么先做角色库

> 本节结论已在 v2.0 与发起人确认，此处只保留要点，不再展开论证。

| 依赖 | 说明 | 现状 |
|---|---|---|
| **容器** | AI 提取出「林昭：性格冷峻、身高一六五、青云宗剑峰弟子」，必须有结构化位置落库 | 本版建立 |
| **基准** | 「剧情与大纲有出入」需要大纲基准；「人物前后矛盾」需要角色卡基准 | 本版建立角色与关系基准 |
| **闭环** | AI 会错，必须能审阅、采纳、回滚 | 本版奠定字段级结构，V3.0 接审阅 |

**三层模型为什么比「角色 + 一对一关系」更值**：网文里「他为什么帮这个人」的答案，一半在人物关系里，一半在「他是哪个宗门的」。只有人物关系图，回答不了「青云宗和血月教开战，谁会被卷进去」——而这恰恰是长篇写作最需要辅助的地方。

## 三、现状盘点

> 2026-10-24 对 `backend/`、`frontend/` 的实际走查。

| 能力 | 现状 | 本版要补 |
|---|---|---|
| 角色数据 | ❌ 无任何角色实体 | 0003 迁移建 10 张表 |
| 设定「势力」 | ⚠️ 只是富文本分类（`document_service.CATEGORIES` 含 `faction`），**无结构、无成员、无上下级** | 组织实体接管结构化部分，文档保留长篇背景（§5.5） |
| 关系数据 | ❌ 无 | 角色间 / 组织间 / 立场间三层关系 |
| 图表渲染 | ❌ 前端只有 DOM + Quill，**无 d3、无 canvas 库、无构建链** | SVG 自绘 + 手写布局算法 |
| 图片导出 | ❌ 无 | SVG → Canvas → PNG（V-12 验证） |
| 回收站 | `TRASH_TYPES = ("project","volume","chapter","document")` | 加 `character` / `organization` / `faction` |
| 全局检索 | FTS5 覆盖章节 + 设定文档 | 角色不并入，页内搜索 + 出场反查 |
| 长任务 | `tasks.py` 进程内任务表 | 本版不涉及 |
| 图片 | `files` 签名访问 + Pillow | 角色立绘、组织徽记（徽记可选，P2） |
| 前端视图 | 7 个 `.view` | 新增 P10 角色库、P11 关系画布 |
| 迁移版本 | `SCHEMA_VERSION = 2` | 追加 0003 |
| 完整性自检 | SQLite `integrity_check` + 诊断包**自动扫描 `sqlite_master`**（`logging_service._schema_summary`） | 新表自动纳入，**无需手工登记** |
| 性能基线 | 冷启动 0.98s / 检索 14ms / 导出 505 万字 0.31s（v0.8 §12.1） | 画布 80 节点、列表 200 角色 |

## 四、需求分析

### 4.1 用户与场景

| 项 | 结论 |
|---|---|
| 用户 | 发起人自用为主（2026-10-24 确认） |
| 规模 | 单项目 100~500 万字；**角色 30~200、组织 10~40、大立场 2~6、角色关系 100~400、组织关系 20~80** |
| 场景 | ① 开书建卡；② 卡文时翻人物网找「这个人会怎么做」；③ 写宗门线时看组织树；④ 写阵营战前查「谁是谁的人」；⑤ 写到某章想确认「这时他俩已经反目了吗」 |
| 环境 | 完全离线、单机、Windows 10/11 x64、WebView2 155.x |

### 4.2 功能需求

#### 4.2.1 角色域

| 编号 | 需求 | 优先级 | 验收要点 |
|---|---|---|---|
| **FR-8.1** | **角色档案卡**：姓名、定位、性别、年龄、身高、外貌、性格、背景、能力、口头禅、动机、状态、标签、备注 | P0 | 14 个核心字段可录入编辑；年龄/身高接受中文描述 |
| **FR-8.2** | **别名与称呼**：多别名，项目内唯一，冲突可强制 | P0 | 别名 vs 别名、别名 vs 姓名双向校验 |
| **FR-8.3** | **自定义扩展字段**：键值对，text / longtext / number / date | P1 | 增删改排序持久化；number 非法输入拦截 |
| **FR-8.4** | **角色列表**：搜索（姓名/别名/标签）、定位筛选、组织筛选、排序、三态 | P0 | 200 角色首屏 ≤300ms |
| **FR-8.5** | **定位与标签**：主角/女主/重要配角/反派/龙套/其他 + 自由标签（「主角」指第一主角、不限性别；「女主」指感情线核心，不与「主角」互斥） | P0 | 定位可筛选、图上可作描边编码 |
| **FR-8.6** | **立绘**：上传、压缩为 ≤512px 方形 webp、签名访问 | P1 | jpg/png/webp；缺失占位 |

#### 4.2.2 组织与阵营域

| 编号 | 需求 | 优先级 | 验收要点 |
|---|---|---|---|
| **FR-8.7** | **大立场管理**：可自定义增删、命名、上色、写一句简介 | P0 | 至少能建「正道/魔道/中立」三类；颜色用于图 |
| **FR-8.8** | **组织管理**：多层嵌套（不限层，UI 三层展开）、归属一个大立场、首领、类型（宗门/家族/朝堂/帮派/军队/其他）、关联设定文档 | P0 | 建「青云宗 → 剑峰 → 剑堂」三层；改父级不产生环 |
| **FR-8.9** | **组织成员**：角色 ↔ 组织多对多，带职位、主组织标记、隐蔽身份、生效章区间 | P0 | 一个角色可同时是「青云宗弟子（主）」+「血月教卧底（隐蔽）」 |
| **FR-8.10** | **组织间关系**：从属 / 结盟 / 敌对 / 战争 / 中立，带描述与是否双向 | P0 | 同一对组织可有多类型关系；自环禁止 |
| **FR-8.11** | **大立场间关系**：结盟 / 敌对 / 中立 / 从属 | P0 | 图上外圈可画「正道 ⇄ 魔道：敌对」 |

#### 4.2.3 关系域

| 编号 | 需求 | 优先级 | 验收要点 |
|---|---|---|---|
| **FR-8.12** | **角色关系**：20 类固定类型 + 自定义补充标签，单向/双向（有默认方向，可覆盖），描述 | P0 | 20 类全部可选；默认方向正确（附录 A） |
| **FR-8.13** | **关系生效区间**：起始章 / 结束章（可空，可搜索的章节下拉） | P0 | 「第 40 章前师徒、之后仇敌」可表达为两条关系 |
| **FR-8.14** | **隐秘关系**：标记「不为人知」（私情、暗通、卧底） | P1 | 图上虚线；卡片上小锁图标 |
| **FR-8.15** | **关系冲突与唯一性**：同一对角色、同类型、同一自定义标签只允许一条活跃关系；同类型不同标签可共存；软删后可重建 | P0 | 删「师徒」再重建不被拦（已实测）；「其他/青梅竹马」与「其他/指腹为婚」可同时存在 |

#### 4.2.4 视图域

| 编号 | 需求 | 优先级 | 验收要点 |
|---|---|---|---|
| **FR-8.16** | **角色卡小面板**：显示该角色 1 跳关系（按类型分组），可点开对方 | P0 | 与 FR-8.19 大画布同源，不重复取数 |
| **FR-8.17** | **人物关系网大画布**：力导向布局、拖拽摆位、滚轮缩放、点节点跳卡片、按主组织上色 | P0 | 80 节点首屏 ≤800ms；拖拽 ≥30fps |
| **FR-8.18** | **组织层级树视图**：折叠/展开、点成员跳卡片、卧底虚线 | P0 | 3 层 50 节点渲染 ≤300ms |
| **FR-8.19** | **阵营全景视图**：大立场色块 + 组织 + 立场连线 | P0 | 立场间敌对/结盟可见 |
| **FR-8.20** | **画布筛选与聚焦**：按立场/组织/章节/「以某人为中心 2 跳」筛选；超出 80 节点强制筛选 | P0 | 筛选后节点数与边数正确 |
| **FR-8.21** | **布局持久化与锁定**：手动摆位存库、可锁定、可一键重排 | P1 | 重开应用位置不变 |
| **FR-8.22** | **导出 PNG**：当前画布视图导出（白底，含图例） | P1 | 中文字体正确，80 节点 ≤3s |

#### 4.2.5 基础域

| 编号 | 需求 | 优先级 | 验收要点 |
|---|---|---|---|
| **FR-8.23** | **出场检索**：用姓名 + 别名反查全书，按章聚合，显示出场章数与首次出场章，可跳转 | P2 | 505 万字 ≤2s（或给缓存方案） |
| **FR-8.24** | **删除与回收站**：角色/组织/立场软删 30 天恢复；彻底删除物理清除 | P0 | 恢复后别名/关系/成员完整 |

### 4.3 非功能需求（增量）

| 编号 | 约束 |
|---|---|
| NFR-P7 | 角色列表 200 条首屏 ≤300ms；角色切换 ≤100ms |
| NFR-P8 | 画布：50 节点 ≤500ms、80 节点 ≤800ms；拖拽 ≥30fps；布局计算分帧，不阻塞输入 |
| NFR-P9 | 组织树：3 层 50 节点 ≤300ms；折叠/展开 ≤100ms |
| NFR-D1 | 迁移 **0003** 单调递增、迁移前自动备份、失败回滚、不支持降级（NFR-M3 / M5） |
| NFR-S10 | 全程离线；立绘经 `/files` 签名访问（NFR-S4 / S8 不回归） |
| NFR-U5 | 破坏性操作（删角色/组织/立场、清空关系、锁定覆盖）二次确认 |
| NFR-C5 | 旧库 schema 2 → 3 不丢数据；库体积增长 <5% |

### 4.4 边界（本版不做）

| 不做 | 原因 | 去向 |
|---|---|---|
| AI 提取 / 补全 / 关系推断 | 本版是地基 | V3.0 |
| **剧情线导图** | 需要独立的「事件」实体，属剧情域；且与 V3.0 AI 摘要链天然一对 | **V2.1 独立模块** |
| 关系时间轴 UI | 只存字段，不做拖拽播放 | V2.1 或更后 |
| 头像节点 | 已定：文字圆点（首字 + 颜色） | 可作后续开关 |
| 关系强度数值 / 亲密度评分 | 无客观口径，易变噪声 | 不规划 |
| 角色并入全局 FTS | 角色页自带搜索 + 出场反查已够 | 视需要 |
| 立绘 AI 生成、组织徽记上传 | 与写作辅助弱相关 | 徽记作 V2.1 P2 |
| 跨书共享角色 / 多端同步 | 数据模型要加一层 | 不规划 |

## 五、数据模型设计

### 5.1 三层结构总览

```
┌─────────────────────── 大立场 faction（可自定义、带颜色）───────────────────────┐
│   正道            魔道            中立            妖族                          │
│     │  ╲          ╱  │            │               │                            │
│     │   〔敌对/结盟/中立/从属〕  faction_relation                                │
│     ↓               ↓            ↓               ↓                            │
│  组织 organization（可多层嵌套 parent_id、归属立场、首领、关联势力文档）          │
│   青云宗 ──从属──→ 剑峰 ──从属──→ 剑堂        〔org_relation〕                   │
│     │                                    血月教                                │
│     ↓ org_member（职位 / 主组织 / 隐蔽身份 / 生效章）                             │
│   角色 character ←────────── character_relation ──────────→ 角色                │
│                （20 类 / 单向双向 / 生效章 / 隐秘）                              │
└────────────────────────────────────────────────────────────────────────────────┘
                    graph_layout：三张画布的节点坐标与锁定状态
```

### 5.2 DDL（迁移 0003，10 张表）

```sql
-- ① 角色
CREATE TABLE character (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    name        TEXT    NOT NULL,
    role        TEXT    NOT NULL DEFAULT 'supporting',
    gender      TEXT,
    age         TEXT,
    height      TEXT,
    appearance  TEXT,
    personality TEXT,
    background  TEXT,
    abilities   TEXT,
    catchphrase TEXT,
    motivation  TEXT,
    note        TEXT,
    status      TEXT    NOT NULL DEFAULT 'alive',
    avatar_path TEXT,
    tags        TEXT,
    source      TEXT    NOT NULL DEFAULT 'manual',   -- V3.0 预留
    meta_json   TEXT,                                -- V3.0 预留
    order_index INTEGER NOT NULL DEFAULT 1000,
    created_at  DATETIME NOT NULL,
    updated_at  DATETIME NOT NULL,
    is_deleted  INTEGER NOT NULL DEFAULT 0,
    deleted_at  DATETIME
);
CREATE INDEX idx_character_project ON character(project_id, order_index);
CREATE INDEX idx_character_active  ON character(project_id, is_deleted);

-- ② 别名（项目内唯一，仅活跃行）
CREATE TABLE character_alias (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    character_id INTEGER NOT NULL REFERENCES character(id) ON DELETE CASCADE,
    alias        TEXT    NOT NULL,
    created_at   DATETIME NOT NULL,
    is_deleted   INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX uq_alias_active ON character_alias(project_id, alias) WHERE is_deleted = 0;
CREATE INDEX idx_alias_character ON character_alias(character_id);

-- ③ 自定义字段
CREATE TABLE character_field (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL REFERENCES character(id) ON DELETE CASCADE,
    key          TEXT    NOT NULL,
    value        TEXT,
    field_type   TEXT    NOT NULL DEFAULT 'text',
    order_index  INTEGER NOT NULL DEFAULT 1000,
    created_at   DATETIME NOT NULL,
    updated_at   DATETIME NOT NULL,
    UNIQUE (character_id, key)
);

-- ④ 大立场
CREATE TABLE faction (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    name        TEXT    NOT NULL,
    color       TEXT,
    description TEXT,
    order_index INTEGER NOT NULL DEFAULT 1000,
    created_at  DATETIME NOT NULL,
    updated_at  DATETIME NOT NULL,
    is_deleted  INTEGER NOT NULL DEFAULT 0,
    deleted_at  DATETIME
);
CREATE UNIQUE INDEX uq_faction_name ON faction(project_id, name) WHERE is_deleted = 0;
CREATE INDEX idx_faction_project ON faction(project_id, order_index);

-- ⑤ 组织（多层嵌套）
CREATE TABLE organization (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    faction_id  INTEGER REFERENCES faction(id) ON DELETE SET NULL,
    parent_id   INTEGER REFERENCES organization(id) ON DELETE CASCADE,
    name        TEXT    NOT NULL,
    kind        TEXT    NOT NULL DEFAULT 'other',
    leader_id   INTEGER REFERENCES character(id) ON DELETE SET NULL,
    description TEXT,
    document_id INTEGER REFERENCES document(id) ON DELETE SET NULL,
    color       TEXT,
    order_index INTEGER NOT NULL DEFAULT 1000,
    created_at  DATETIME NOT NULL,
    updated_at  DATETIME NOT NULL,
    is_deleted  INTEGER NOT NULL DEFAULT 0,
    deleted_at  DATETIME,
    CHECK (parent_id IS NULL OR parent_id <> id)
);
CREATE UNIQUE INDEX uq_org_name ON organization(project_id, name) WHERE is_deleted = 0;
CREATE INDEX idx_org_project ON organization(project_id, parent_id, order_index);
CREATE INDEX idx_org_faction ON organization(faction_id);

-- ⑥ 组织成员（角色 ↔ 组织）
CREATE TABLE org_member (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id    INTEGER NOT NULL REFERENCES character(id) ON DELETE CASCADE,
    org_id          INTEGER NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    position        TEXT,
    is_primary      INTEGER NOT NULL DEFAULT 0,
    is_secret       INTEGER NOT NULL DEFAULT 0,
    from_chapter_id INTEGER REFERENCES chapter(id) ON DELETE SET NULL,
    to_chapter_id   INTEGER REFERENCES chapter(id) ON DELETE SET NULL,
    created_at      DATETIME NOT NULL,
    updated_at      DATETIME NOT NULL,
    is_deleted      INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX uq_member_active ON org_member(character_id, org_id) WHERE is_deleted = 0;
CREATE INDEX idx_member_org ON org_member(org_id);
CREATE INDEX idx_member_character ON org_member(character_id);

-- ⑦ 组织间关系
CREATE TABLE org_relation (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id       INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    from_id          INTEGER NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    to_id            INTEGER NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    relation_type    TEXT    NOT NULL DEFAULT 'neutral',
    description      TEXT,
    is_bidirectional INTEGER NOT NULL DEFAULT 0,
    from_chapter_id  INTEGER REFERENCES chapter(id) ON DELETE SET NULL,
    to_chapter_id    INTEGER REFERENCES chapter(id) ON DELETE SET NULL,
    created_at       DATETIME NOT NULL,
    updated_at       DATETIME NOT NULL,
    is_deleted       INTEGER NOT NULL DEFAULT 0,
    deleted_at       DATETIME,
    CHECK (from_id <> to_id)
);
CREATE UNIQUE INDEX uq_org_rel_active ON org_relation(from_id, to_id, relation_type) WHERE is_deleted = 0;
CREATE INDEX idx_org_rel_project ON org_relation(project_id, is_deleted);

-- ⑧ 大立场间关系
CREATE TABLE faction_relation (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id       INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    from_id          INTEGER NOT NULL REFERENCES faction(id) ON DELETE CASCADE,
    to_id            INTEGER NOT NULL REFERENCES faction(id) ON DELETE CASCADE,
    relation_type    TEXT    NOT NULL DEFAULT 'neutral',
    description      TEXT,
    is_bidirectional INTEGER NOT NULL DEFAULT 1,
    created_at       DATETIME NOT NULL,
    updated_at       DATETIME NOT NULL,
    is_deleted       INTEGER NOT NULL DEFAULT 0,
    deleted_at       DATETIME,
    CHECK (from_id <> to_id)
);
CREATE UNIQUE INDEX uq_faction_rel_active ON faction_relation(from_id, to_id, relation_type) WHERE is_deleted = 0;

-- ⑨ 角色关系
CREATE TABLE character_relation (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id       INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    from_id          INTEGER NOT NULL REFERENCES character(id) ON DELETE CASCADE,
    to_id            INTEGER NOT NULL REFERENCES character(id) ON DELETE CASCADE,
    relation_type    TEXT    NOT NULL DEFAULT 'other',
    custom_label     TEXT    NOT NULL DEFAULT '',   -- 空串而非 NULL：NULL 不参与唯一比较
    description      TEXT,
    is_bidirectional INTEGER NOT NULL DEFAULT 0,
    is_secret        INTEGER NOT NULL DEFAULT 0,
    from_chapter_id  INTEGER REFERENCES chapter(id) ON DELETE SET NULL,
    to_chapter_id    INTEGER REFERENCES chapter(id) ON DELETE SET NULL,
    created_at       DATETIME NOT NULL,
    updated_at       DATETIME NOT NULL,
    is_deleted       INTEGER NOT NULL DEFAULT 0,
    deleted_at       DATETIME,
    CHECK (from_id <> to_id)
);
CREATE UNIQUE INDEX uq_char_rel_active ON character_relation(from_id, to_id, relation_type, custom_label) WHERE is_deleted = 0;
CREATE INDEX idx_char_rel_project ON character_relation(project_id, is_deleted);
CREATE INDEX idx_char_rel_from ON character_relation(from_id);
CREATE INDEX idx_char_rel_to ON character_relation(to_id);

-- ⑩ 画布布局（每项目一行，三个模式共用一份 JSON）
CREATE TABLE graph_layout (
    project_id INTEGER PRIMARY KEY REFERENCES project(id) ON DELETE CASCADE,
    payload    TEXT    NOT NULL,   -- {"character":{cid:{x,y,pinned}}, "organization":{...}}
    updated_at DATETIME NOT NULL
);
```

> **已实跑验证（2026-10-24，SQLite 3.45.1）**：本段 DDL 从本文档原文抽取执行，29 条语句 /
> 10 张表 / 19 个索引全部建立；`character.note` 存在（24 列）；组织三层嵌套、父删子随删、
> 关系生效段与软删重建、**同类型不同 `custom_label` 可共存、完全重复被拦、未填标签落空串**、
> 章节删除后生效段置 NULL、立场自环拦截、成员唯一与退出重入、组织软删后同名重建、
> 布局单行唯一、立场删除后组织 `faction_id` 置 NULL 全部符合预期，`PRAGMA foreign_key_check` 干净。
> **成环检测、主组织唯一与软删递归属服务层规则（DB 不强制），由 5.2 单测覆盖。**

**三条设计理由（不是随手写的）**

| 设计 | 理由 |
|---|---|
| 统一用**部分唯一索引**（`WHERE is_deleted=0`） | 若用表级 `UNIQUE`，作者删掉一条「师徒」再重新添加会被数据库拦住，出现「删了却加不回来」的诡异 bug。**已实测通过**（见上方验证段落） |
| `age` / `height` 用 TEXT | 「十六七岁」「一丈二」「九万岁」是中文小说常态；强制数字会逼作者造假数据，V3.0 的矛盾检测反而查到假值 |
| 布局用 JSON 单行而非坐标表 | 布局是「一次性整图状态」，逐节点存表会让保存变成 N 次写；单行覆盖写更简单，且随备份迁移 |

### 5.3 关键约束

| 约束 | 规则 |
|---|---|
| 角色名 | **允许重名**（小说里同名不同人存在），列表用定位徽标区分 |
| 别名 | 项目内唯一（活跃行）；与别的角色 `name` 冲突走应用层校验，可 `force` |
| 组织名 | 项目内唯一（活跃行） |
| 组织层级 | `parent_id` 不得指向自己；服务层校验**不得成环**（改父级时向上遍历祖先） |
| 主组织 | 每个角色**最多一个** `is_primary=1`；设置新主组织时清除旧的（服务层事务）。主组织被删或角色退出该组织时，**降级为「无主组织」、不自动改选**；图上着色退化为「第一个成员组织的颜色」，无组织则灰 |
| 组织删除 | 非空组织（有子组织或成员）删除前弹三选一：取消 / 成员与子组织上移一级 / 一并删除。**删的是根组织时「上移」不可选**（没有父级可挂），只能「取消」或「一并删除」 |
| 大立场删除 | 有组织归属时禁止直接删，提示「先迁移或改为中立」；不自动迁移 |
| 立场继承 | 组织未设 `faction_id` 时，**向上取最近祖先组织的立场**；整条祖先链都没有 → 归「未分组」（图上灰色，不参与立场连线） |
| 成员身份 | 同一角色在同一组织**只保留一条活跃身份**；职位变更直接改（不保留历史，历史留 V2.1 时间轴）；卧底/双身份靠「属于不同组织」表达 |
| 关系唯一 | 同一对角色、同一类型、**同一自定义标签**只允许一条活跃关系。`custom_label` 用空串而非 NULL（SQLite 的 NULL 不参与唯一比较）；「师徒中断后又恢复」这类多段关系，用不同 `custom_label`（如「师徒·重逢后」）区分 |
| 章节引用 | `from_chapter_id` / `to_chapter_id` 允许为空（= 一直有效）；引用章节被删则置 NULL（`ON DELETE SET NULL`） |
| 失效关系显示 | 不传 `chapter_id` 时返回全部活跃关系，**已失效的默认隐藏**（筛选可开）；传 `chapter_id` 时只返回该章有效的 |
| 文本字段 | 角色/组织/立场的所有文本字段**一律纯文本**（不走 Quill、不用 `innerHTML`），前端用 `textContent` 渲染；多行字段保留换行 |

### 5.4 软删除与回收站

| 对象 | 软删 | 恢复 | 彻底删除 |
|---|---|---|---|
| 角色 | ✅ 同事务标记别名 `is_deleted=1`；关系与成员记录保留 | ✅ 角色 + 别名一并还原（别名冲突则跳过并提示） | 物理清除，级联别名/字段/关系/成员 |
| 组织 | ✅ **同事务递归标记全部子组织与成员记录** | ✅ 递归还原同批子组织与成员 | 级联子组织（`ON DELETE CASCADE`） |
| 大立场 | ✅ | ✅ | 组织 `faction_id` 置 NULL（不删组织） |
| 三种关系 | ✅ | 随主体恢复 | 随主体级联 |

> **为什么软删也要递归**：只标记父组织会让子组织「父级已删、自己还活跃」，图上直接变成孤儿节点。软删与物理删必须语义一致，恢复时再一起还原。
>
> **所有查询一律 join 主体过滤 `is_deleted=0`**：查组织成员要过滤角色是否已删，查角色卡要过滤组织是否已删，查立场色块要过滤立场是否已删。否则会出现「已删角色的名字还挂在组织里」这类幽灵数据。

### 5.5 与 V1「势力」设定文档的关系（防重复）

| 层 | 负责 | 内容 |
|---|---|---|
| **组织实体**（`organization`） | 结构化 | 名字、类型、归属立场、上下级、首领、成员、对外关系 |
| **设定文档**（`document`，`category=faction`） | 长篇叙事 | 门派历史、规矩、特产、名场面 |

- 组织卡上有一个「**详细设定**」入口，下拉选择已有的势力文档（`document_id`），点了就跳过去。
- 文档编辑页顶部提示：「该势力已建组织卡 → 去查看」（通过 `document_id` 反查）。
- **不把势力文档自动转成组织**（抽取规则不稳定）；也**不删掉 faction 文档分类**（作者已有数据）。

### 5.6 AI 预留契约（沿用并扩展）

| 契约 | 内容 |
|---|---|
| ① 字段命名 | 固定字段英文列名 + 中文标签常量（`character_service.FIELD_LABELS`）；V3.0 的 AI 输出直接落库 |
| ② 来源与置信度 | `character.source` / `character.meta_json` 只留列，V2.0 不写逻辑 |
| ③ 枚举固定 | 关系 20 类、组织类型 6 类、成员职位自由文本、立场关系 4 类：**AI 只能输出枚举 + `custom_label`**，否则图无法聚合 |
| ④ 图即上下文 | V3.0 分析某章时，把「该章出场角色的卡片 + 其组织 + 一跳关系」作为结构化上下文送给模型（而不是塞几万字散文） |

## 六、接口设计

> 编号承接 v0.8 §6.2 的 #53：新增 **#54~#81 共 28 组**（方法对合并计数，实际端点 39 个）。沿用 `ApiResponse{code,message,data}`、一次性 token 鉴权、错误码（1001 参数 / 2001 不存在 / 2002 已删除 / 3001 数据库 / 3002 冲突 / 4004 签名）。

### 6.1 角色（#54~#63）

| # | 方法与路径 | 用途 |
|---|---|---|
| #54 | `GET /projects/{pid}/characters/meta` | 枚举元数据：定位 6 / 状态 4 / 关系 20 类 / 组织类型 6 / 立场关系 4 / 组织关系 5 / 字段类型 4（中文标签） |
| #55 | `GET /projects/{pid}/characters` | 列表：`keyword`、`role`、`org_id`、`status`、`sort`、`page`、`page_size` |
| #56 | `POST /projects/{pid}/characters` | 新建 |
| #57 | `GET /characters/{cid}` | 详情（含别名、字段、关系、成员身份） |
| #58 | `PATCH /characters/{cid}` | 部分更新（字段级保存） |
| #59 | `DELETE /characters/{cid}` | 软删除；`?force=1` 彻底删除 |
| #60 | `PUT /characters/{cid}/aliases` | 整体替换别名 |
| #61 | `GET/POST /characters/{cid}/fields` | 自定义字段列表 / 新增 |
| #62 | `PATCH/DELETE /fields/{fid}` | 修改 / 删除 |
| #63 | `POST /characters/{cid}/avatar` | 立绘上传 |

### 6.2 关系与图（#64~#67）

| # | 方法与路径 | 用途 |
|---|---|---|
| #64 | `GET /projects/{pid}/graph` | **统一图数据**：`mode=character\|organization\|faction`、`faction_id`、`org_id`、`center_id`、`depth`（1~3）、`chapter_id`（按生效段过滤）；返回 `nodes[] + edges[] + groups[]` |
| #65 | `POST /characters/{cid}/relations` | 新建角色关系 |
| #66 | `PATCH/DELETE /relations/{rid}` | 修改 / 删除角色关系 |
| #67 | `GET /characters/{cid}/relations` | 某角色的关系列表（小面板用，含已失效的历史关系标记） |

**`#64` 返回结构（三模式共用，前端只写一套渲染）**

```json
{
  "code": 0, "message": "ok",
  "data": {
    "mode": "character",
    "nodes": [
      {"id": 1, "kind": "character", "name": "林昭", "role": "protagonist",
       "status": "alive", "color": "#7A6A58", "primary_org": "剑峰", "secret": false}
    ],
    "edges": [
      {"id": 7, "kind": "character_relation", "from": 1, "to": 2, "type": "master",
       "label": "师徒", "bidirectional": 0, "secret": 0,
       "from_chapter": 1, "to_chapter": 40, "active": true}
    ],
    "groups": [
      {"id": 1, "kind": "faction", "name": "正道", "color": "#3B6EA5", "member_ids": [1, 2]}
    ],
    "total_nodes": 23,
    "truncated": false
  }
}
```

| 字段 | 约定 |
|---|---|
| `nodes[].kind` | `character` / `organization` / `faction`（阵营模式返回后两种） |
| `edges[].kind` | `character_relation` / `membership` / `org_parent` / `org_relation` / `faction_relation` |
| `edges[].active` | `to_chapter` 已过为 `false`；默认不返回，`include_expired=1` 时返回 |
| `groups[]` | 立场分组：阵营模式画色块/凸包，人物模式用于外圈着色 |
| `truncated` | 节点超 80 时为 `true`，前端显示黄条提示并引导筛选 |
| 尺寸 | 节点带 `x`/`y` 时表示布局已存在（来自 `graph_layout`），前端不再跑布局 |

### 6.3 大立场（#68~#72）

| # | 方法与路径 | 用途 |
|---|---|---|
| #68 | `GET /projects/{pid}/factions` | 列表（含组织数统计） |
| #69 | `POST /projects/{pid}/factions` | 新建 |
| #70 | `PATCH/DELETE /factions/{fid}` | 修改 / 删除（有组织时拒绝） |
| #71 | `GET/POST /projects/{pid}/faction-relations` | 立场关系列表 / 新建 |
| #72 | `PATCH/DELETE /faction-relations/{rid}` | 修改 / 删除 |

### 6.4 组织（#73~#79）

| # | 方法与路径 | 用途 |
|---|---|---|
| #73 | `GET /projects/{pid}/organizations` | 列表；`?tree=1` 返回嵌套树 |
| #74 | `POST /projects/{pid}/organizations` | 新建（可带 `parent_id` / `faction_id`） |
| #75 | `PATCH/DELETE /organizations/{oid}` | 修改（改父级校验成环）/ 删除（非空三选一） |
| #76 | `GET/POST /organizations/{oid}/members` | 成员列表 / 添加 |
| #77 | `PATCH/DELETE /org-members/{mid}` | 改职位·主组织·隐蔽·生效段 / 移除 |
| #78 | `GET/POST /projects/{pid}/org-relations` | 组织关系列表 / 新建 |
| #79 | `PATCH/DELETE /org-relations/{rid}` | 修改 / 删除 |

### 6.5 画布（#80~#81）

| # | 方法与路径 | 用途 |
|---|---|---|
| #80 | `GET /projects/{pid}/graph/layout` | 读布局 JSON（无则返回空对象） |
| #81 | `PUT /projects/{pid}/graph/layout` | 保存布局（整图覆盖写，`If-Match` 用 `updated_at` 防并发） |

### 6.6 回收站扩展（不新增编号）

`GET /trash` 增加 `characters` / `organizations` / `factions` 分组；`POST /trash/{type}/{id}/restore` 与 `DELETE /trash/{type}/{id}` 接受三种新类型。

### 6.7 关键行为约定

| 场景 | 约定 |
|---|---|
| 别名冲突 | 返回 `1001` + 可读消息（「别名『小昭』已被『林昭』占用」）；`force=true` 覆盖 |
| 组织成环 | `PATCH` 改 `parent_id` 时向上遍历祖先链，命中自己返回 `1001`（「不能把组织挂到自己的子孙下」） |
| 主组织唯一 | 设置 `is_primary=1` 时同事务清除该角色其它成员记录的 `is_primary` |
| 章节过滤 | `#64` 传 `chapter_id` 时：关系/成员/生效段包含该章的才返回；未填区间视为一直有效 |
| 双向关系去重 | `#64` 对 A→B 与 B→A 同类型关系按「端点对 + 类型」去重，只返回一条（`is_bidirectional` 标记） |
| 组织树节点 | `#73?tree=1` 返回 `children[]` 结构，服务端只算一层关系，不做前端递归 |
| 布局并发 | `PUT` 带 `updated_at`；服务端不一致返回 `3002`（沿用版本冲突码），前端提示「布局已在别处更新」 |
| 布局体积 | `payload` 上限 1 MB（约 5000 个节点坐标）；超限返回 `1001` 并提示「请先筛选再保存」 |
| 布局按模式隔离 | JSON 内按 `character` / `organization` / `faction` 三个命名空间分存，**保存时只覆盖当前模式**，不清掉另外两个 |
| 文档关联失效 | 组织关联的设定文档被删除后（物理删除才触发 `SET NULL`），组织卡显示「原文档已删除」，允许重新关联；软删除的文档在列表中标灰但不清空关联 |

## 七、UI/UX 设计

### 7.1 信息架构

```
写作页 ──[角色]──→ P10 角色库
                     ├─ Tab 角色  → 列表 | 角色卡 | 关系小面板
                     ├─ Tab 组织  → 组织树 | 组织详情（成员表）
                     └─ Tab 阵营  → 立场卡片列表（可上色）
                   ──[关系图]──→ P11 三模式画布
                                    ├─ 人物（力导向）
                                    ├─ 组织（层级树）
                                    └─ 阵营（分组 + 立场连线）
```

> **P10 的组织 Tab 与 P11 的组织模式长得像，但职责不同，别做成两套编辑器**：
>
> | | P10 组织 Tab | P11 组织模式 |
> |---|---|---|
> | 定位 | **管理视图**：建组织、改父级、加成员、改职位 | **视图**：看格局、看谁跟谁结盟/敌对 |
> | 能力 | 全部增删改 | **只读 + 点击跳转**（双击节点回 P10 编辑） |
> | 布局 | DOM 树（可拖拽） | SVG（层级布局，可缩放） |
>
> 一句话：**要改东西去 P10，要看全貌去 P11**。两边数据同源（`#73?tree=1` 与 `#64`），不各存一份。

### 7.2 P10 角色库页

```
┌───────────────────────────────────────────────────────────────────────────┐
│ ← 返回写作   Inkwell            [角色] [组织] [阵营]      [关系图]  [设置]  │
├────────────────────┬──────────────────────────────────┬───────────────────┤
│ [搜索__________]   │ ┌────┐ 林昭                       │ 关系（6）          │
│ 定位 [全部 ▾]      │ │立绘│ 主角·存活·剑修              │ 沈砚  师徒  第1章→  │
│ 组织 [全部 ▾]      │ └────┘ ─────────────────────────  │ 顾长陵 宿敌  第12章 │
│ ─────────────────  │ 性别 女       年龄 十六七岁        │ 阿蛮  朋友  →      │
│ ● 林昭      主角  │ 身高 一六五   状态 存活            │ ─────────────      │
│ ○ 沈砚      配角  │ 外貌 眉眼锋利，虎口旧疤…          │ 所属组织（2）      │
│ ○ 顾长陵    反派  │ 性格 冷峻，护短…                  │ 青云宗·剑峰 弟子   │
│ ○ 阿蛮      龙套  │ 能力 御剑术（第三境）…            │ 血月教     卧底🔒  │
│                    │ 口头禅 「让开。」                 │ ─────────────      │
│ ─────────────────  │ 别名 小昭 × 昭儿 ×  ＋            │ [在图中查看]       │
│ 共 23 个角色       │ 自定义 灵根：单系水灵根  ＋        │ [导出 PNG]         │
└────────────────────┴──────────────────────────────────┴───────────────────┘
```

| 区域 | 行为 |
|---|---|
| Tab 切换 | 角色 / 组织 / 阵营三个 Tab，状态记住（localStorage） |
| 列表 | 搜索 + 双筛选（定位 / 组织）+ 排序；`↑↓` 切换 |
| 卡片 | 字段失焦即保存（debounce 800ms）；别名标签；自定义字段；顶部「已保存 HH:MM」 |
| 小面板 | 关系按类型分组 + 组织身份；隐蔽关系带 🔒；失效关系灰显；「在图中查看」带该角色进画布 |

### 7.3 组织 Tab

```
┌ 青云宗（正道）                    ＋子组织  ＋成员   [查看势力文档] ┐
│  ├ 剑峰（３人）                    首领：沈砚                     │
│  │  ├ 剑堂（２人）                                               │
│  │  └ 执法堂（１人）                                             │
│  ├ 丹峰（２人）                                                  │
│  └ 外门（５人）                                                  │
├─────────────────────────────────────────────────────────────────┤
│ 成员：林昭｜剑堂｜主组织｜第 3 章起  ｜血月教·卧底 🔒              │
│       ……                                    [编辑] [移除]        │
└─────────────────────────────────────────────────────────────────┘
```

- 树上支持**拖拽改父级**（拖到别的组织即挂载，松手前校验成环）；也支持右键「升一级 / 移到…」；
- 成员表可加人（搜索角色）、改职位、切主组织、标隐蔽、填生效章；
- 顶部「查看势力文档」按 `document_id` 跳设定页；未关联时显示「关联一份设定文档」。

### 7.4 P11 三模式画布

**顶部**：`[人物] [组织] [阵营]` + 右侧 `[筛选] [重排] [锁定] [导出 PNG]`。

| 模式 | 布局算法 | 节点 | 边 |
|---|---|---|---|
| 人物 | 简化力导向（Fruchterman-Reingold，≤300 迭代） | 圆点 + 首字，填色=主组织色，描边=定位 | 关系 20 类（色/线型见表） |
| 组织 | 层级布局（Reingold-Tilford 简化） | 圆角矩形卡（名称 + 人数） | 从属（折线）/ 结盟 / 敌对 / 战争 |
| 阵营 | 分组布局（每个立场一簇，凸包或圆） | 大色块 + 内部组织 | 立场间连线 + 组织间关系 |

**视觉编码表**

| 元素 | 编码 |
|---|---|
| 角色节点 | 圆点 + 姓名首字；填色 = 主组织颜色；**无主组织 → 取第一个成员组织的颜色；无组织 → 灰**；描边：主角 2.5px / 女主 2.5px / 重要配角 1.5px / 反派 2px 红 / 龙套 1px；**已死亡（`status=dead`）加虚线圈** |
| 卧底成员 | 节点半透明 + 成员边虚线 + 🔒 |
| 关系线 | 敌系（宿敌/仇人/血仇/背叛）红；亲系（夫妻/道侣/恋人/父母/子女/兄弟）暖橙；师承（师徒/同门）金；友系（朋友/盟友/同族）绿；其他灰。单向带箭头，双向实线 |
| 隐秘关系 | 虚线 + 线宽减半 |
| 失效关系（有结束章） | 灰色点线（默认隐藏，筛选可开） |
| 立场连线 | 敌对红虚线 / 结盟绿 / 中立灰点线 / 从属灰箭头 |
| 组织边 | 从属细灰折线 / 结盟蓝 / 敌对红 / 战争深红粗线 / 中立灰点线 |

**交互**

| 操作 | 行为 |
|---|---|
| 拖拽节点 | 移动并记入布局（自动固定 `pinned=true`） |
| 滚轮 / 双指 | 缩放（0.3x ~ 3x） |
| 拖拽空白 | 平移 |
| 单击节点 | 侧栏预览（角色卡摘要 + 一跳关系） |
| 双击节点 | 角色节点 → 跳转角色卡；组织节点 → **展开直系成员，一次最多 20 个**，超出显示「还有 N 人」气泡（再点进 P10 组织 Tab 看全量）；立场节点 → 展开其下组织 |
| 右键节点 | 菜单：以此为中心 / 隐藏 / 编辑 / 复制名字 |
| 双击空白 | 复位视图 |
| 筛选抽屉 | 立场 / 组织 / 章节 / N 跳 / 是否显示失效关系 |
| 节点 >80 | 顶部黄条提示「当前 N 个节点，建议筛选」，自动只渲染前 80 个（按出场序），并返回 `truncated=true` |
| 从写作页进入 | 若当前正打开某章，画布默认带 `chapter_id`（只显示该章有效的关系），顶部显示「按第 X 章显示 ✕」可一键取消 |

### 7.5 关系编辑表单

```
关系类型 [师徒 ▾]   自定义标签 [________]    方向 [单向 ▾]
对方角色 [搜索并选择…]
生效范围 从 [第 1 章 ▾]  到 [第 40 章 ▾]   （留空 = 一直有效）
☐ 不为人知（隐秘）
描述 [______________________________]
                                    [取消] [保存]
```

- 章节下拉**必须可搜索**（800 章不可能纯滚动）；
- 选类型时自动带出默认方向（附录 A），用户可覆盖；
- 表单保存时校验自环与重复。

### 7.6 空态与引导

| 场景 | 文案与动作 |
|---|---|
| 无角色 | 「还没有角色」+ [`＋新建角色`] + 小字「也可以先把设定文档里的人物抄一份过来」 |
| 无组织 | 「还没有组织」+ [`＋新建组织`]，并提示「宗门、家族、朝堂都可以建成组织，能画成层级树」 |
| 无立场 | 「还没有阵营」+ [`＋新建立场`]，预填「正道 / 魔道 / 中立」三个建议 |
| 无关系 | 关系面板「添加两条关系，这里会画出人物网」 |
| 画布空 | 「先去建几个角色，再回来看看他们的关系」+ 跳转按钮 |

### 7.7 无障碍与键盘

| 键 | 行为 |
|---|---|
| `↑`/`↓` | 列表切换角色 |
| `Enter` | 进入卡片 / 打开选中节点 |
| `Tab` | 画布内节点依次聚焦（SVG `tabindex`） |
| `+` / `-` / `0` | 放大 / 缩小 / 复位 |
| `Esc` | 关闭抽屉 / 退出编辑 / 返回列表 |

- 节点不只用颜色承载语义（同时有文字首字与描边宽度）；
- 对比度沿用阶段三 token（4.72~14.16:1）；
- 画布支持键盘遍历，不困住焦点。

### 7.8 视觉规范增量

| Token | 用途 |
|---|---|
| `--role-*` × 6 | 角色定位描边色 |
| `--org-hue-*` | 组织自动配色（按创建顺序从 8 色板取，避免撞色） |
| `--rel-family-*` | 关系五大色系（敌/亲/师/友/其他） |
| `--faction-*` | 立场色（作者自选，默认给 6 个预设） |
| `--graph-bg` | 画布底色（米白，比正文页浅一档） |

> 所有色值走 `tokens.css`，**不在页面内硬编码**（阶段三 3.1 的教训）。

## 八、AI 预留与 V3.0 衔接

### 8.1 本版建的三样东西，正好是 V3.0 的输入

| V2.0 产出 | V3.0 用法 |
|---|---|
| 角色卡 20 个结构化字段 | 「这章说他身高一六五，卡片写的是一七零」——矛盾检测的比对基准 |
| 组织 + 成员职位 | 「他是青云宗剑峰弟子，怎么会突然用魔道功法」——身份一致性 |
| 关系（20 类 + 生效段） | 「第 40 章已反目，第 55 章却称兄道弟」——关系时序检测 |

### 8.2 三层衔接点

| 层 | V2.0 现在做 | V3.0 直接接 |
|---|---|---|
| 数据 | 10 张表 + `source` / `meta_json` 预留列 | AI 结果按 key 落库，无需转换 |
| 接口 | `#56` / `#58` / `#60` / `#64` / `#65` | 审阅采纳复用同一批接口，不写第二套写入 |
| UI | 卡片失焦保存、关系表单 | AI 候选复用同布局，加「采纳 / 忽略」徽标 |

### 8.3 摘要链草案（V3.0，不在本版实现）

```sql
-- 0004（V3.0 才建）
CREATE TABLE chapter_digest (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id    INTEGER NOT NULL UNIQUE REFERENCES chapter(id) ON DELETE CASCADE,
    summary       TEXT NOT NULL,
    characters    TEXT,   -- JSON: [{name, aliases, role_in_chapter}]
    events        TEXT,   -- JSON
    hooks         TEXT,   -- JSON: 埋伏笔 / 回收伏笔
    content_hash  TEXT NOT NULL,   -- 未变则复用，不重复花钱
    model         TEXT,
    prompt_tokens INTEGER, completion_tokens INTEGER,
    created_at    DATETIME NOT NULL, updated_at DATETIME NOT NULL
);
```

### 8.4 对附录 A 的修订建议（沿用 v2.0 §8.4）

原契约 `analyze_plot(chapter_content: str)` 只能吃单章纯文本，无法表达分析范围、已确认的大纲与角色卡、输出的结构化落点。V3.0 应改为：

```python
@dataclass
class AnalysisRequest:
    kind: str                      # digest / character_extract / consistency / chat
    scope: str                     # chapter / volume / book
    project_id: int
    chapter_ids: list[int]
    outline: str | None
    characters: list[dict]         # 角色卡（含组织与一跳关系）
    prior_digests: list[dict]
    options: dict

@dataclass
class AnalysisResult:
    kind: str
    payload: dict            # 键名 = 落库字段名
    evidence: list[dict]     # [{chapter_id, quote, offset}]
    usage: dict
    model: str

class AIProvider(ABC):
    async def analyze(self, req: AnalysisRequest) -> AnalysisResult: ...
    async def stream_chat(self, messages, tools=None): ...
    def name(self) -> str: ...
```

> V2.0 不改附录 A（未实现先改文档会空转），本报告登记为 V3.0 修订依据。

## 九、质量保障与验收

### 9.1 验收标准

| 编号 | 验收项 | 判定 |
|---|---|---|
| **AC-12** | 角色全链路：新建 → 14 字段 → 别名 → 自定义字段 → 删除 → 回收站恢复，数据完整 | 手工 + e2e |
| **AC-13** | 别名唯一：4 种冲突组合被拦截，`force` 可覆盖 | 单测 |
| **AC-14** | 自定义字段 4 类型增删改排序，number 非法输入不落库 | 单测 + UI |
| **AC-15** | 组织：三层嵌套、改父级防成环、非空删除三选一（根组织无「上移」）、主组织唯一与降级、软删递归子组织与成员 | 单测 |
| **AC-16** | 立场：增删改上色；有组织时删除被拒绝；立场关系可建 | 单测 |
| **AC-17** | 角色关系：20 类可选、默认方向正确、生效章区间可存、隐秘可标 | 单测 |
| **AC-18** | 人物画布：80 节点首屏 ≤800ms、拖拽 ≥30fps、点节点跳转正确 | 性能脚本 + 冒烟 |
| **AC-19** | 组织树：3 层 50 节点 ≤300ms，折叠/展开 ≤100ms，卧底虚线可见 | 性能脚本 |
| **AC-20** | 阵营全景：立场色块 + 立场连线 + 内部组织可见 | 冒烟截图 |
| **AC-21** | 布局持久化：摆位后关闭画布再打开、刷新窗口，位置不变；锁定后重排按钮禁用 | e2e |
| **AC-22** | PNG 导出：中文在图内正确显示，图例完整 | 人工 + 像素抽查 |
| **AC-23** | 迁移：schema 2 → 3 成功、迁移前备份存在、失败回滚、降级拒绝；断网全功能可用 | fixture + 手工 |

### 9.2 回归清单增补（承接 v0.8 §8.1 的 28 项）

| 编号 | 回归项 | 手段 |
|---|---|---|
| **29** | 角色 CRUD + 回收站恢复（别名/字段/关系完整） | Python 单测 |
| **30** | 别名冲突拦截（含与姓名交叉、`force`） | Python 单测 |
| **31** | 自定义字段类型校验与排序 | Python 单测 |
| **32** | 角色关系 CRUD + 生效章 + 隐秘 + 软删重建 | Python 单测 |
| **33** | 组织树 CRUD + 改父级防成环 + 成员职位/主组织/隐蔽 | Python 单测 |
| **34** | 立场与立场关系（含删除保护） | Python 单测 |
| **35** | 人物画布渲染 / 拖拽 / 筛选 / 降级 | 窗口冒烟 |
| **36** | 组织树视图与阵营全景 | 窗口冒烟 + 截图 |
| **37** | 布局保存与恢复（关闭画布再打开、刷新窗口后位置不变；不依赖重启进程） | e2e |
| **38** | 迁移 0002 → 0003 前后一致 | fixture 测试 |

### 9.3 测试与性能

| 项 | 内容 |
|---|---|
| 单测 | 5 个服务模块分支覆盖 ≥60%（NFR-M1 沿革） |
| 迁移 | `tests/fixtures/schema_v2.db` → 迁移 → PRAGMA 比对列与索引 |
| e2e | `window_smoke.py` 增补角色页/组织页/画布 25~30 步 |
| 性能 | `tests/perf/character_graph_perf.py`：200 角色 + 80 关系 + 组织树，测首屏、布局、拖拽帧率 |
| 视觉 | 三模式截图基线（`docs/版本更新/V2.0_截图/`） |

### 9.4 Definition of Done

沿用 v0.8 §8.4：功能可用 + 单测通过 + 回归不降级 + 文档/决策留痕 + 无新增 P0/P1 缺陷。

## 十、任务分解与排期

> 详细清单见 `../任务清单/V2.0任务清单.md`。

| ID | 任务 | 交付物 | 依赖 | 人日 |
|---|---|---|---|---|
| 5.0 | 走查与设计校准 | 偏差清单；枚举/色板/文案定稿 | — | 0.5 |
| 5.1 | 迁移 0003 + ORM（10 表） | `migrate.py` / `models.py` / `config.py` | 5.0 | 2.5 |
| 5.2 | 服务层（角色/组织/立场/关系/图） | 5 个 service + 单测 | 5.1 | 3.0 |
| 5.3 | 接口 #54~#81（28 组） | `backend/api/characters.py` 等 | 5.2 | 2.0 |
| 5.4 | 角色列表 + 卡片编辑器 | `frontend/js/characters.js` | 5.3 | 3.0 |
| 5.5 | 阵营 / 组织管理 | `organizations.js` + 树 | 5.3 | 2.5 |
| 5.6 | 关系编辑 + 角色卡小面板 | 关系表单 + 面板 | 5.4 | 1.5 |
| 5.7 | 大画布：人物模式 | `graph.js` + 力导向 | 5.6 | 2.5 |
| 5.8 | 组织树 + 阵营全景模式 | 层级/分组布局 | 5.7 | 2.0 |
| 5.9 | 筛选 / 布局持久化 / PNG 导出 / 性能 | 优化与工具 | 5.8 | 1.5 |
| 5.10 | 回收站·检索联动 + 回归 + 验收 + 文档 | 验收单、README 等 | 5.5~5.9 | 2.0 |
| | **合计** | | | **23.0**（22~24） |

**里程碑**

| 里程碑 | 任务 | 周期 | 可验证的状态 |
|---|---|---|---|
| **M1 能建档** | 5.0~5.4 | 2 周 | 角色能建、能搜、能编辑 |
| **M2 能看图** | 5.5~5.7 | 1.5~2 周 | 组织能建、关系能编辑、人物网能拖 |
| **M3 三层完整** | 5.8~5.10 | 1.5 周 | 三模式画布 + 导出 + 验收 |

**关键路径**：5.1 → 5.2 → 5.3 → 5.4 → 5.6 → 5.7 → 5.8 → 5.9 → 5.10。5.5 与 5.6/5.7 可并行。

## 十一、风险与待确认事项

### 11.1 风险登记（承接 v0.8 §10）

| ID | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R-19 | 建了没人填 | 功能闲置 | 空态引导；组织/立场给预设；先自用验证 |
| R-20 | 画布抖动 / 性能差 | 体验崩塌 | 力导向迭代上限 300、分帧计算；>80 节点强制筛选；退化圆形布局 |
| R-21 | AI 预留不足返工 | +3~5 人日 | §5.6 四契约 + 5.3 后「V3.0 视角」评审 |
| R-22 | 别名 / 组织名 / 同名角色冲突 | 数据质量 | 项目内唯一 + 冲突提示 + `force`；同名角色允许但加徽标 |
| R-23 | 立绘体积 / 格式 | 崩溃 / 慢 | 服务端强制 webp 512px、≤10MB（沿用 `media.validate_image`）；落 `media/characters/{cid}/`，复用 `/files` 签名 |
| R-24 | 迁移失败打不开 | 数据安全 | 迁移前原子备份 + fixture + 回滚 + 拒降级 |
| **R-25** | **「势力文档」与「组织」概念重复** | 作者困惑、数据分裂 | §5.5 边界：组织放结构、文档放长篇；双向入口提示；不自动互转 |
| **R-26** | **组织解散 / 角色退场后数据残留** | 图出现幽灵节点 | 软删除 + 生效章；图上默认隐藏已删；失效关系灰显 |
| **R-27** | **关系数量爆炸导致图不可读** | 画布失去意义 | 筛选（立场/组织/章节/N 跳）+ 80 节点上限 + 聚焦模式 |

### 11.2 待确认事项

| ID | 待确认 | 阻塞 | 默认方案 |
|---|---|---|---|
| Q-17 | 布局存库还是 localStorage？ | 否 | **存库**（`graph_layout`），随备份走、换机不丢 |
| Q-18 | 导出 PNG 的背景 | 否 | 白底（含图例）；透明底留作后续选项 |
| Q-19 | 组织删除时「成员与子组织上移一级」是否要实现 | 否 | **实现**（三选一：取消 / 上移 / 一并删） |
| Q-20 | 立场删除时有组织归属 | 否 | **拒绝删除**并提示「先迁移或改为中立」，不自动迁移 |

> Q-11 ~ Q-16（v2.0 报告）已被本版吸收为既定设计，不再单列。

## 十二、与原路线图的差异

| 模块 | 原计划（v0.1） | 本版建议 | 理由 |
|---|---|---|---|
| 角色库 | V2.0 | **V2.0**（三层 + 三视图） | 保留并扩展 |
| 剧情/事件 + 剧情线导图 | 无 | **V2.1（新增，8~10 人日）** | 它是 V3.0 AI 剧情摘要的数据底座 |
| 灵感库 | V2.1 | **V2.2**（3~4 人日） | 被剧情模块前移挤出，但成本低可穿插 |
| 场景图库 | V2.2 | **V3.1 之后** | 价值密度最低，且与立绘能力重叠 |
| AI 情节分析 / 角色提取 | V3.0 | **V3.0**（18~22 人日） | 差异化核心 |

```
V2.0 角色库（本版）  →  V2.1 剧情/事件 + 剧情线导图  →  V2.2 灵感库  →  V3.0 AI  →  V3.1 导出 + 场景图库
   22~24 人日             8~10 人日                      3~4 人日       18~22 人日   4~6 人日
```

## 附录 A：20 类关系全表

| key | 中文 | 默认方向 | 色系 | 说明 |
|---|---|---|---|---|
| `master` | 师徒 | 单向 | 师承金 | A 是 B 的师父 |
| `parent` | 父母 | 单向 | 亲系暖 | A 是 B 的父母 |
| `child` | 子女 | 单向 | 亲系暖 | A 是 B 的子女 |
| `sibling` | 兄弟姐妹 | 双向 | 亲系暖 | 含同父异母 |
| `spouse` | 夫妻 | 双向 | 亲系暖 | 正式婚配 |
| `partner` | 道侣 | 双向 | 亲系暖 | 修仙设定专用 |
| `lover` | 恋人 | 双向 | 亲系暖 | 未成亲 |
| `friend` | 朋友 | 双向 | 友系绿 | 泛交好 |
| `ally` | 盟友 | 双向 | 友系绿 | 利益同盟 |
| `fellow` | 同门 | 双向 | 师承金 | 同师门 |
| `superior` | 上下级 | 单向 | 其他灰 | 职务隶属（与组织成员互补） |
| `servant` | 主仆 | 单向 | 其他灰 | 契约/从属 |
| `rival` | 宿敌 | 双向 | 敌系红 | 长期对手，未必要命 |
| `enemy` | 仇人 | 双向 | 敌系红 | 有具体仇怨 |
| `blood_feud` | 血仇 | 双向 | 敌系红 | 杀亲之仇 |
| `compete` | 竞争 | 双向 | 其他灰 | 资源/名次之争 |
| `betray` | 背叛 | 单向 | 敌系红 | A 背叛过 B |
| `benefactor` | 恩人 | 单向 | 友系绿 | A 于 B 有恩 |
| `kin` | 同族 | 双向 | 亲系暖 | 宗族血脉 |
| `other` | 其他 | 双向 | 其他灰 | 配合 `custom_label` |

**规则**：默认方向只是表单初值，逐条可覆盖；`custom_label` 用于「青梅竹马」「指腹为婚」这类细粒度补充，不影响图例聚合。

## 附录 B：术语增补

| 术语 | 含义 |
|---|---|
| 三层结构 | 大立场 → 组织 → 角色 |
| 大立场 | 正/魔/中立这类宏观阵营，可自定义、带颜色。**界面上这个 Tab 叫「阵营」，数据层实体叫 `faction`**，三者是同一个东西 |
| 组织 | 宗门/家族/朝堂等实体，可多层嵌套 |
| 主组织 | 一个角色在图上用于着色的那一个组织（最多一个）；没有则退化为第一个成员组织 |
| 隐蔽身份 | 卧底/暗桩，图上虚线 + 🔒 |
| 生效区间 | 关系或成员身份的有效章节范围，留空 = 一直有效 |
| 三视图 | 人物关系网 / 组织层级树 / 阵营全景 |
| 孤儿节点 | 父级已删但仍活跃的子组织。本版用「软删递归」+「查询过滤」双保险防住 |
| provenance | 字段来源与置信度，V3.0 写入 `meta_json` |
| 摘要链 | 章摘要 → 卷摘要 → 全书圣经（V3.0） |
