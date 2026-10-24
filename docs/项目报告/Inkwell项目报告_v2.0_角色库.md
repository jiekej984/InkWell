# Inkwell 小说辅助工具 — V2.0 需求与设计报告（角色库）

## 文档信息

| 项 | 内容 |
|---|---|
| 文档名称 | Inkwell 小说辅助工具 — V2.0 需求与设计报告 |
| 版本 | **v2.0（V2.0 设计基线）** |
| 日期 | 2026-10-24 |
| 状态 | **待发起人确认**。确认后进入任务 5.0 开工；未确认项按 §11.2 默认方案执行 |
| 适用范围 | V2.0（角色库）的需求、数据模型、接口、交互、验收依据 |
| 与旧基线的关系 | **并存**：`Inkwell项目报告_v0.8.md` 继续作为 V1.0 的设计基线；本报告只覆盖 V2.0 增量，未重述部分以 v0.8 为准 |
| 配套文档 | `../任务清单/V2.0任务清单.md`、`../../DECISIONS.md`（新增决策 S4-xx 待落）、`../版本更新/阶段三_接口与回归同步清单.md`（回归编号沿用） |

## 修订记录

| 版本 | 日期 | 主要变更 |
|---|---|---|
| v2.0 | 2026-10-24 | 首版：确认「V2.0 先做角色库、AI 后置」；给出角色库数据模型、13 个接口、AI 预留三项契约、任务分解与待确认事项 |

---

## 目录

- [一、结论先行](#一结论先行)
- [二、为什么是角色库，而不是直接上 AI](#二为什么是角色库而不是直接上-ai)
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
- [附录：术语增补](#附录术语增补)

---

## 一、结论先行

1. **下一版（V2.0）开发角色库，不做 AI。**
2. **角色库不是新想法，是原计划**：v0.1 报告第 58~62 行把角色库排在 V2.0、灵感库 V2.1、场景图库 V2.2、AI V3.0；第 230~236 行还预留了 `Character`、`CharacterRelation` 四张表。V1.0 只交付写作核心，是**有意分期**，不是遗漏。
3. **但 V2.0 的角色卡必须按「AI 可填充」的结构设计**，否则 V3.0 接 AI 时要动表结构。本报告 §5.5、§8 给出三项预留契约。
4. **工作量 13~15 人日（约 3 周）**，拆为 5.0~5.8 九个任务（见 §10 与任务清单）。
5. **需要发起人拍板 6 件事**（§11.2 的 Q-11~Q-16），其中关系图、立绘两项直接决定工期 ±3.5 人日。

---

## 二、为什么是角色库，而不是直接上 AI

### 2.1 AI 功能有三个硬依赖

| 依赖 | 说明 | 现状 |
|---|---|---|
| **容器** | AI 提取出「角色 A：性格冷峻、身高一八五、剑术已至第三境」，必须有结构化位置落库 | **不存在**，数据库里没有任何角色实体 |
| **基准** | 「剧情与大纲有出入」必须先有「大纲基准」；基准要么人手写，要么 AI 反推后确认 | `chapter.summary` 是手填字段，实际几乎无人填 |
| **闭环** | AI 会错、会编。必须有「候选 → 审阅 → 采纳 → 可回滚」的流程 | 无审阅 UI、无字段级来源标记 |

### 2.2 没有角色库时，AI 提取的三种死法

1. **无处可放**：只能写进「设定文档 / 其他」分类的一段文字，AI 第二次提取时无法比对，只能覆盖或追加，越用越乱。
2. **无法累积**：作者想改「林昭的身高」，得在散文里找那一句；AI 也读不出哪个字段是权威值。
3. **无法纠错**：AI 编了一个不存在的角色，没有独立记录可删，只能整段重写。

### 2.3 先做角色库的真实收益

- **对作者**：角色数据从「散文」变成「表」，能筛、能搜、能看关系、能定位出场章节——这本身就是市面写作工具普遍缺失的一层。
- **对后续版本**：V3.0 的 AI 提取、V3.0 的一致性检测（身高前后矛盾、性格崩坏）**全部以 `character` 表为比对基准**。现在建表，V3.0 只加功能；现在跳过，V3.0 要边做 AI 边改表，风险翻倍。
- **对差异化**：市面工具的「人物」多是标签云或纯文本笔记；结构化角色卡 + 关系图 + 出场统计，是 Inkwell「辅助」定位的第一块实体砖。

### 2.4 反面成本（为什么不「先做点 AI 试试」）

一次能用的 AI 角色提取，最少需要：Provider 抽象 + Key 配置 + 设置页 + 提示词 + JSON 校验 + 候选审阅 UI + 落库事务 + token 统计 + 失败重试。**这套东西本身就要 8~10 人日**，且落地时仍然缺容器。先做角色库，这 8~10 人日才有着落点。

---

## 三、现状盘点

> 2026-10-24 对 `backend/`、`frontend/`、`docs/` 的实际走查结论。

| 能力 | 现状 | V2.0 要补 |
|---|---|---|
| 角色数据 | **无 `character` 表**（models.py / migrate.py 均无） | 0003 迁移建 4 张表 |
| 设定文档 | 五类固定枚举 `world / timeline / faction / glossary / other`（`document_service.py:23`），人物只能塞「其他」 | 不扩展枚举；角色独立成域 |
| 章节/卷摘要 | `chapter.summary`、`volume.summary` 字段存在，仅手填，无生成与校验 | 不在 V2.0 处理（AI 阶段用） |
| 全局检索 | FTS5 覆盖 `chapter_fts` + `document_fts`（trigram） | 角色**不并入**全局检索（见 §4.4），角色页自带搜索 |
| 回收站 | `TRASH_TYPES = ("project", "volume", "chapter", "document")`（`trash_service.py:31`） | 扩展 `character` 类型 + 恢复/彻底删除 |
| 长任务 | `backend/services/tasks.py` 进程内任务表 | 角色库不涉及长任务（无需调用） |
| 图片 | 封面/正文图片走 `files` 签名访问 + Pillow 压缩 | 立绘复用同一机制 |
| 前端页面 | 7 个 `.view`：projects / writer / documents / trash / backup / search / settings | 新增 `view-characters`（P10） |
| 导航入口 | 写作页头部有「存为版本 / 版本 / 设定 / 保存」 | 新增「角色」按钮，与「设定」并列 |
| 导出 | 单章/整本 TXT、MD；角色设定集导出归 V3.1 | 不做 |
| AI | 附录 A 只有接口草案；`CODE_AI_UNAVAILABLE = 5001` 已定义；无任何 Provider 实现 | 不做，仅做结构预留 |

---

## 四、需求分析

### 4.1 目标用户与使用场景

| 项 | 结论 |
|---|---|
| 用户 | **发起人自用为主**（2026-10-24 确认「先把功能跑通」），暂不为公开发布做配置向导与隐私条款 |
| 规模 | 单项目 100~500 万字、**30~200 个角色**、关系 50~300 条、单章 ≤8 万字 |
| 时机 | ① 开书前建主要角色；② 写到中途想起某人，回头补档；③ 卡文时翻角色卡找「这个人会怎么做」；④ 写到伏笔时查「这角色前面出现过几次」 |
| 环境 | 完全离线、单机、Windows 10/11 x64、WebView2 |

### 4.2 功能需求

| 编号 | 需求 | 优先级 | 验收要点 |
|---|---|---|---|
| **FR-8.1** | **角色档案卡**：姓名（必填）、身份定位、性别、年龄、身高、外貌、性格、背景、能力/技能、口头禅、目标动机、当前状态、备注 | P0 | 15 个核心字段可录入、编辑、持久化；年龄/身高接受中文描述（「十六七岁」「一丈二」） |
| **FR-8.2** | **别名与称呼**：一个角色多个别名（小名、道号、称号、外号），项目内唯一 | P0 | 同一别名不可属于两个角色；别名与别人的姓名冲突时提示并允许强制 |
| **FR-8.3** | **自定义扩展字段**：键值对，类型 text / longtext / number / date | P1 | 增删改排序持久化；number 校验非法输入；同角色内 key 唯一 |
| **FR-8.4** | **角色列表**：搜索（姓名/别名/标签）、按定位筛选、按出场顺序或创建时间排序、加载/空/错误三态 | P0 | 200 角色首屏 ≤300ms；筛选/搜索 ≤150ms |
| **FR-8.5** | **角色定位与标签**：主角 / 女主 / 重要配角 / 反派 / 龙套 / 其他（6 类固定）+ 自由标签 | P0 | 定位可筛选、可按定位分组；标签可多选 |
| **FR-8.6** | **立绘/头像**：上传图片、等比裁切为方形、压缩至 ≤512px、签名访问 | P1 | 支持 jpg/png/webp；替换与删除；文件缺失时显示占位 |
| **FR-8.7** | **人物关系**：from → to、关系类型（师徒/父母/子女/兄弟姐妹/夫妻/恋人/敌对/盟友/主仆/同门/其他）、补充描述、是否双向 | P0 | 同一对角色可有多条不同类型关系；自环禁止；双向关系在图中只画一条但两侧都显示 |
| **FR-8.8** | **关系图**：SVG 自绘，节点=角色、边=关系；拖拽、缩放、点击节点跳转角色卡；>80 节点降级为列表 | P1 | 50 节点/80 边渲染 ≤500ms；拖拽不丢节点；空关系时给出引导 |
| **FR-8.9** | **出场检索**：把角色姓名与别名当作关键词，复用全局检索，结果按章节聚合，显示出现次数与首次出场章，可跳转 | P2 | 全书 500 万字检索 ≤2s（V1 实测单次 14ms，按别名数线性叠加）；命中可点开对应章节 |
| **FR-8.10** | **删除与回收站**：软删除、30 天恢复、彻底删除；彻底删除时别名/自定义字段/关系物理清除 | P0 | 回收站可见「角色」类型；**恢复后别名/字段/关系完整**；彻底删除不可逆且二次确认 |

### 4.3 非功能需求（增量）

| 编号 | 约束 |
|---|---|
| NFR-P7 | 角色列表 200 条首屏 ≤300ms；角色详情切换 ≤100ms（数据量小，不引入虚拟滚动） |
| NFR-P8 | 关系图 50 节点布局计算 ≤500ms，布局在主线程外或分帧执行，不阻塞输入 |
| NFR-D1 | 迁移 **0003** 单调递增、迁移前自动备份、失败回滚、不支持降级（沿用 NFR-M3 / NFR-M5） |
| NFR-S10 | 全程离线；立绘走 `/files` 签名访问，不新增对外端口（NFR-S4 / NFR-S8 不回归） |
| NFR-U5 | 破坏性操作二次确认（删角色、清空关系）；错误提示可读（不用「500 服务器错误」） |
| NFR-C5 | 旧库（schema 2）升级到 schema 3 不丢数据；`data/inkwell.db` 大小增长 <5%（角色数据量级小） |

### 4.4 明确不做（V2.0 边界）

| 不做 | 原因 | 去向 |
|---|---|---|
| AI 提取、AI 补全、AI 关系推断 | 本版定位是打地基 | V3.0 |
| 角色并入全局检索（FTS） | 角色页自带搜索，字段语义复杂，FTS 索引收益低 | 若确有需要，V2.1 再评估 |
| 立绘生成、AI 绘图 | 与写作辅助无关，成本高 | 不做 |
| 从设定文档**自动**抽取角色 | 抽取规则不稳定，且 V2.0 应先验证「手动建档」是否顺手 | V2.1 评估 |
| 角色设定集导出（TXT/MD/DOCX） | 原计划 V3.1 | V3.1 |
| 多项目共享角色（跨书角色库） | 数据模型要加一层，收益不明 | 暂不规划 |
| 场景图库 | 原 V2.2 | **后置**（见 §12） |

---

## 五、数据模型设计

### 5.1 关系概览

```
project 1 ──── n character 1 ──── n character_alias
                    │
                    ├──── n character_field
                    │
                    └──── n character_relation (from_id / to_id 均指向 character)
```

- 四张表均为 **project 级**（`character_relation` 冗余 `project_id` 便于按项目查图）。
- `character`、`character_alias`、`character_relation` 带 `is_deleted`；`character_field` **不带软删除**（它没有跨行唯一约束，行留着即可，恢复时天然还原）。
- **唯一性用「部分唯一索引」而非表级 `UNIQUE`**：`WHERE is_deleted = 0`。这是本版最关键的一处设计——若用表级 `UNIQUE(from_id, to_id, relation_type)`，作者删掉「师徒」再重新添加会被数据库拦住，产生「删了却加不回来」的诡异 bug。
- **别名随角色一起软删除**（同一个事务内 `is_deleted=1`），恢复角色时一并还原，做到回收站无损。

> ⚠️ 设计取舍：唯一的损失点是**彻底删除**（`force=1`）——别名、自定义字段、关系物理清除，不可恢复。这符合「彻底删」的语义，但需二次确认（Q-13）。

### 5.2 DDL（迁移 0003）

```sql
-- 角色主表
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
    status      TEXT    NOT NULL DEFAULT 'alive',
    avatar_path TEXT,
    tags        TEXT,
    source      TEXT    NOT NULL DEFAULT 'manual',
    meta_json   TEXT,
    order_index INTEGER NOT NULL DEFAULT 1000,
    created_at  DATETIME NOT NULL,
    updated_at  DATETIME NOT NULL,
    is_deleted  INTEGER NOT NULL DEFAULT 0,
    deleted_at  DATETIME
);
CREATE INDEX idx_character_project ON character(project_id, order_index);
CREATE INDEX idx_character_active  ON character(project_id, is_deleted);

-- 别名（项目内唯一：仅在活跃行之间生效）
CREATE TABLE character_alias (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    character_id INTEGER NOT NULL REFERENCES character(id) ON DELETE CASCADE,
    alias        TEXT    NOT NULL,
    created_at   DATETIME NOT NULL,
    is_deleted   INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX uq_alias_active
    ON character_alias(project_id, alias) WHERE is_deleted = 0;
CREATE INDEX idx_alias_character ON character_alias(character_id);

-- 自定义扩展字段
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

-- 人物关系
CREATE TABLE character_relation (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id       INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    from_id          INTEGER NOT NULL REFERENCES character(id) ON DELETE CASCADE,
    to_id            INTEGER NOT NULL REFERENCES character(id) ON DELETE CASCADE,
    relation_type    TEXT    NOT NULL DEFAULT 'other',
    custom_label     TEXT,
    description      TEXT,
    is_bidirectional INTEGER NOT NULL DEFAULT 0,
    created_at       DATETIME NOT NULL,
    updated_at       DATETIME NOT NULL,
    is_deleted       INTEGER NOT NULL DEFAULT 0,
    deleted_at       DATETIME,
    CHECK (from_id <> to_id)
);
-- 同一对角色的同一关系只允许一条「活跃」记录（软删除后可重新添加）
CREATE UNIQUE INDEX uq_relation_active
    ON character_relation(from_id, to_id, relation_type) WHERE is_deleted = 0;
CREATE INDEX idx_relation_project ON character_relation(project_id, is_deleted);
CREATE INDEX idx_relation_from    ON character_relation(from_id);
CREATE INDEX idx_relation_to      ON character_relation(to_id);
```

### 5.3 字段清单与约束

| 字段 | 类型 | 取值 / 约束 | 说明 |
|---|---|---|---|
| `name` | TEXT | 必填、去首尾空白、≤100 字 | 正名（不是别名） |
| `role` | TEXT | `protagonist` / `heroine` / `supporting` / `antagonist` / `extra` / `other` | 固定 6 类，见 §4.2 FR-8.5 |
| `gender` | TEXT | 自由文本 | 「男/女/不明/无性别」均可，不设枚举 |
| `age` | TEXT | 自由文本 | **故意不用 INTEGER**：中文小说「十六七岁」「约莫二十」「三万岁」都是常态，强制数字会逼作者造假数据 |
| `height` | TEXT | 自由文本 | 同上，「一六五」「一丈二」「九尺」并存；V3.0 做矛盾检测时再半结构化解析 |
| `status` | TEXT | `alive` / `dead` / `missing` / `retired` | 影响列表徽标；不影响关系图连线（死亡角色仍可显示） |
| `tags` | TEXT | JSON 数组字符串 | 与 `tag`/`project_tag` 表**无关**，独立表达式标签，避免污染项目标签 |
| `source` | TEXT | `manual` / `ai_extracted` | **V2.0 恒为 `manual`**，为 V3.0 预留（§5.5） |
| `meta_json` | TEXT | JSON，V2.0 不写入 | 为 V3.0 的字段级来源与置信度预留（§5.5） |
| `order_index` | INTEGER | 默认 1000 | 手工排序；V2.0 不提供拖拽排序 UI（P2） |
| `relation_type` | TEXT | 11 类枚举 + `custom_label` | 枚举固定才能聚合统计与作图例 |

**状态枚举**：`alive` 存活 / `dead` 已死 / `missing` 失踪 / `retired` 退场，UI 文案为中文。

**关系类型枚举**（11 类）：`master` 师徒 / `parent` 父母 / `child` 子女 / `sibling` 兄弟姐妹 / `spouse` 夫妻 / `lover` 恋人 / `enemy` 敌对 / `ally` 盟友 / `servant` 主仆 / `peer` 同门 / `other` 其他（中文标签集中在 `character_service.RELATION_LABELS`）。

**软删除字段**：`character`、`character_alias`、`character_relation` 三张表带 `is_deleted`；`character_field` 不带（无跨行唯一约束，行保留即可）。

### 5.4 与 V1 表的联动

| 联动点 | 处理 |
|---|---|
| 项目删除 | `character.project_id` 级联删除（`ON DELETE CASCADE`），与卷/章一致 |
| 角色进入回收站 | 复用 `is_deleted` + `deleted_at`；`TRASH_TYPES` 增加 `"character"`；**同事务内把该角色别名置 `is_deleted=1`**（让出唯一键）；自定义字段行保留；关系保留 |
| 角色恢复 | 恢复角色 + 别名；若某个别名在删除期间已被新角色占用，则跳过该别名并在返回结果里列出（不阻断恢复） |
| 角色彻底删除 | `?force=1`，物理删除：别名、自定义字段、关系经 `ON DELETE CASCADE` 一并清除；二次确认文案写明不可恢复 |
| 章节/卷删除 | **不影响角色**（角色是项目级，不属于章节） |
| 全文检索 | 不并入（§4.4） |
| 备份/自检 | 自动包含新表（备份是整库文件级；`maintenance_service` 的表清单需登记 4 张新表） |

> `maintenance_service` 的完整性自检与诊断包按表枚举实现，**必须同步登记新表**，否则自检会漏表（见任务 5.1）。

### 5.5 为 V3.0 AI 预留的三项契约

> 这一节是 V2.0 最重要的设计约束：**表结构可以加列，但不能改语义**。

**① 字段命名契约（服务端常量）**

固定字段用英文列名，中文标签集中在 `character_service.FIELD_LABELS`：

```python
FIELD_LABELS = {
    "name": "姓名", "role": "定位", "gender": "性别", "age": "年龄",
    "height": "身高", "appearance": "外貌", "personality": "性格",
    "background": "背景", "abilities": "能力/技能", "catchphrase": "口头禅",
    "motivation": "目标动机", "status": "当前状态", "tags": "标签",
}
```

V3.0 的 AI 输出 JSON **必须直接使用这些 key**，落库时零翻译。若 V2.0 改用中文键或自由文本，V3.0 就得写一层映射，映射必然丢字段。

**② 来源与置信度（只留列，不写逻辑）**

- `character.source`：`manual`（V2.0 唯一值）/ `ai_extracted`（V3.0 写入）
- `character.meta_json`：V3.0 写入
  ```json
  {"origin":"ai","confidence":0.82,"batch":"job_7f3a","fields":{"height":{"source":"ai","confidence":0.6}}}
  ```
- V2.0 **不读写 `meta_json`**，只保证列存在。避免空转逻辑，也避免 UI 提前出现「AI」字样造成误导。

**③ 关系类型枚举 + `custom_label`**

AI 关系抽取只允许输出 11 类枚举（超出放 `custom_label`），否则关系图无法聚合、无法做图例。若 V2.0 用自由字符串，V3.0 的关系数据会变成一锅粥。

**V3.0 需要新增、但 V2.0 不预建的表**（预建空表会增加迁移与自检负担，收益为零）：

| 表 | 用途 |
|---|---|
| `chapter_digest` | 章摘要链：`summary`、`characters_json`、`events_json`、`hooks_json`、`content_hash`、`model`、`tokens` |
| `character_candidate` | AI 提取草稿：`name`、`aliases_json`、`evidence`、`chapter_id`、`confidence`、`state`（pending/accepted/rejected）、`job_id` |
| `ai_job` | 调用记录：`kind`、`scope`、`model`、`prompt_tokens`、`completion_tokens`、`cost_estimate`、`state`、`error` |

**兼容性论证**：SQLite 的 `ALTER TABLE ADD COLUMN` 是常数时间、不重写表、不影响既有数据；`0003 → 0004` 单调递增即可。因此 V2.0 的 `character` 表在 V3.0 只需加列（如需 `first_chapter_id`、`last_seen_chapter_id`），**不需要重建表**。

---

## 六、接口设计

> 编号承接 v0.8 §6.2 的 #53，新增 **#54~#66**。所有接口沿用 `ApiResponse{code, message, data}`、一次性 token 鉴权、错误码（1001 参数校验 / 2001 不存在 / 2002 已删除 / 3001 数据库 / 4001~4004 文件与路径）。

| # | 方法与路径 | 用途 | 长任务 |
|---|---|---|---|
| **#54** | `GET /projects/{pid}/characters/meta` | 枚举元数据：定位 6 类、状态 4 类、关系 11 类、字段类型 4 类（中文标签） | 否 |
| **#55** | `GET /projects/{pid}/characters` | 列表：`keyword`、`role`、`status`、`sort`（order/created/name）、`page`、`page_size` | 否 |
| **#56** | `POST /projects/{pid}/characters` | 新建角色（返回完整对象） | 否 |
| **#57** | `GET /characters/{cid}` | 详情（含别名、自定义字段、关系，一次返回，减少往返） | 否 |
| **#58** | `PATCH /characters/{cid}` | 部分更新（字段级保存用；只改传入字段） | 否 |
| **#59** | `DELETE /characters/{cid}` | 软删除（进回收站）；`?force=1` 彻底删除需二次确认参数 | 否 |
| **#60** | `PUT /characters/{cid}/aliases` | 整体替换别名列表（前端编辑后一次提交，避免逐条增删的并发问题） | 否 |
| **#61** | `GET/POST /characters/{cid}/fields` | 自定义字段列表 / 新增 | 否 |
| **#62** | `PATCH/DELETE /fields/{fid}` | 修改（值/类型/排序）/ 删除 | 否 |
| **#63** | `GET /projects/{pid}/relations` | 关系图数据：`nodes[]` + `edges[]`（按角色过滤可传 `?character_id=`） | 否 |
| **#64** | `POST /characters/{cid}/relations` | 新建关系（从 cid 出发） | 否 |
| **#65** | `PATCH/DELETE /relations/{rid}` | 修改 / 删除关系 | 否 |
| **#66** | `POST /characters/{cid}/avatar` | 上传立绘（multipart；服务端压缩 ≤512px 方形） | 否 |

**回收站接口扩展**（不新增编号）：`GET /trash` 返回 `characters` 分组；`POST /trash/{type}/{id}/restore` 与 `DELETE /trash/{type}/{id}` 接受 `type=character`。

### 6.1 关键行为约定

| 场景 | 约定 |
|---|---|
| 别名冲突 | `PUT /characters/{cid}/aliases` 与 `#56` 均校验项目内唯一；冲突返回 `code=1001`，`message` 指明「别名『小昭』已被『林昭』占用」；`force=true` 时允许覆盖（前端二次确认） |
| 别名与姓名交叉冲突 | 新增别名等于另一个角色的 `name` 时，同样按冲突处理（应用层校验，数据库唯一约束管不到跨表） |
| 双向关系 | `is_bidirectional=1` 的关系只存**一条**（from → to）；图中画一条无向边，两个角色的详情页都显示；若作者同时建了 A→B 与 B→A 同类型关系，图查询按「端点对 + 类型」去重后只画一条，详情页仍各显示各的 |
| 关系键值约束 | 同一对角色、同一类型只允许一条活跃关系；要加第二条请用不同 `relation_type` 或 `custom_label` |
| 角色名重复 | **允许**同名角色（小说里同名不同人确实存在），UI 上用定位徽标区分；不阻断 |
| 删除角色 | 默认软删除，关系保留（软删除过滤后不展示），恢复后关系仍在 |
| 立绘替换 | 新文件写入后更新 `avatar_path`，旧文件由备份清理任务按引用计数处理（V2.0 仅记录、不自动清理） |
| 分页 | 默认 50/页，最大 200；`total` 与 `page_limited` 语义沿用 #31 检索接口 |

### 6.2 响应示例（#57 详情）

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "id": 12, "project_id": 3, "name": "林昭", "role": "protagonist",
    "gender": "女", "age": "十六七岁", "height": "一六五",
    "appearance": "眉眼锋利，左手虎口有旧疤",
    "personality": "冷峻，护短，不擅长道谢",
    "background": "剑阁弃徒，后入青云宗",
    "abilities": "御剑术（第三境）、听风辨位",
    "catchphrase": "让开。",
    "motivation": "找出灭门真凶",
    "status": "alive", "tags": ["剑修", "复仇线"],
    "avatar_path": "images/characters/12/avatar.webp",
    "source": "manual", "order_index": 1000,
    "aliases": ["小昭", "昭儿", "剑阁那位"],
    "fields": [
      {"id": 4, "key": "灵根", "value": "单系水灵根", "field_type": "text", "order_index": 1000}
    ],
    "relations": [
      {"id": 7, "from_id": 12, "to_id": 15, "relation_type": "master",
       "custom_label": null, "description": "授业恩师", "is_bidirectional": 0,
       "to_name": "沈砚"}
    ],
    "created_at": "2026-10-24T21:00:00", "updated_at": "2026-10-24T21:30:00"
  }
}
```

---

## 七、UI/UX 设计

### 7.1 入口与信息架构

- 写作页头部按钮序列：`存为版本` / `版本` / **`角色`** / `设定` / `保存`。
- 角色库页（**P10**）与设定文档页同级：从角色页可「← 返回写作」。
- 关系图从角色页右侧面板进入，**不**单独开一级页面。

### 7.2 页面布局

```
┌──────────────────────────────────────────────────────────────────────┐
│  ← 返回作品      Inkwell                          [全局搜索]  [设置]  │
├────────────────────┬─────────────────────────────────┬───────────────┤
│  角色库     ＋角色  │  ┌────┐  林昭                   │  关系 / 出场   │
│  [搜索___________] │  │立绘│  主角 · 存活 · 剑修       │  ┌──────────┐ │
│  定位 [全部 ▾]     │  └────┘  ──────────────────────  │  │  关系图  │ │
│  ─────────────────  │  性别 女        年龄 十六七岁    │  │  ○──○    │ │
│  ● 林昭      主角  │  身高 一六五    身份 剑阁弟子    │  │   ╲ ╱    │ │
│  ○ 沈砚      配角  │  ─────────────────────────────  │  │    ○     │ │
│  ○ 顾长陵    反派  │  外貌   眉眼锋利，虎口旧疤…     │  └──────────┘ │
│  ○ 阿蛮      龙套  │  性格   冷峻，护短…             │  出场 37 章   │
│  ○ 苏晚      女主  │  背景   剑阁弃徒…               │  首次 第 3 章 │
│                    │  能力   御剑术（第三境）…        │  [查看全部]  │
│  ─────────────────  │  口头禅 「让开。」              │               │
│  共 23 个角色      │  ─────────────────────────────  │               │
│                    │  别名  小昭 ×  昭儿 ×  ＋        │               │
│                    │  ─────────────────────────────  │               │
│                    │  自定义 灵根：单系水灵根  ＋      │               │
│                    │  ─────────────────────────────  │               │
│                    │  关系  沈砚 — 师徒 — 授业恩师     │               │
│                    │        ＋ 添加关系               │               │
└────────────────────┴─────────────────────────────────┴───────────────┘
```

**三栏说明**：

| 栏 | 内容 | 行为 |
|---|---|---|
| 左（列表） | 搜索框、定位筛选、角色列表（定位色点 + 姓名 + 定位） | 点击切换；键盘 ↑↓ 切换，Enter 聚焦卡片首字段 |
| 中（卡片） | 立绘 + 姓名 + 定位/状态徽标 + 核心字段 + 别名标签 + 自定义字段 + 关系列表 | 字段**失焦即保存**（debounce 800ms），卡片顶部显示「已保存 HH:MM / 保存中」 |
| 右（关系与出场） | 关系图缩略 + 出场统计 | 关系图点击节点跳转另一角色；出场统计来自 FR-8.9 |

### 7.3 交互细节

| 场景 | 设计 |
|---|---|
| 字段保存 | 失焦保存，失败时字段标红并保留输入值，提供「重试」；不做整卡「保存」按钮（避免漏点） |
| 定位切换 | 下拉即改即存；改变定位会同步列表色点与筛选结果 |
| 别名冲突 | 输入框失焦时校验，冲突时行内红字提示并给出「仍要添加」按钮（走 `force`） |
| 删除角色 | 确认对话框写明「角色进回收站，30 天内可恢复；别名与关系一并保留」。**彻底删除**才提示「别名、自定义字段、关系将不可恢复」 |
| 空态 | 「还没有角色」+ 主 CTA「＋新建角色」+ 次要文案「也可以先从设定文档里的人物设定抄一份」 |
| 加载态 | 列表骨架 5 行；卡片区占位条 |
| 错误态 | 「角色加载失败」+ 重试按钮 + 折叠的技术详情（不暴露堆栈） |
| 关系为空 | 关系图区域显示「添加两条关系，这里会画出人物关系网」 |
| 大纲树侧 | 角色页不显示大纲树（与设定页一致） |

### 7.4 键盘与无障碍

| 键 | 行为 |
|---|---|
| `↑` / `↓` | 列表内切换角色 |
| `Enter` | 列表聚焦时进入卡片编辑 |
| `Esc` | 退出卡片编辑 / 关闭对话框 |
| `Tab` | 卡片内字段顺序：姓名 → 定位 → 性别 → … → 别名 → 自定义 → 关系 |
| `Ctrl+S` | 角色页无副作用（字段已即时保存），不注册 |

- 所有可点区域有 `:focus-visible` 描边；定位色点不单独承载语义（同时有文字）；
- 关系图节点用 SVG `<g>` + `role="button"` + `tabindex`，支持 Tab 遍历与 Enter 跳转；
- 对比度沿用阶段三实测 token（4.72~14.16:1）。

### 7.5 视觉规范增量

| Token | 用途 | 值 |
|---|---|---|
| `--role-protagonist` | 主角 | 取现有 `--accent` 深化 |
| `--role-heroine` | 女主 | 暖粉系低饱和 |
| `--role-supporting` | 重要配角 | 中性灰蓝 |
| `--role-antagonist` | 反派 | 取 `--danger` |
| `--role-extra` | 龙套 | `--text-3` 灰 |
| `--role-other` | 其他 | `--border-strong` |

> 色值在任务 5.3 落地时按 §7.2 现有 token 体系派生，**不在页面内硬编码**（阶段三 3.1 的教训）。

---

## 八、AI 预留与 V3.0 衔接

### 8.1 三层衔接点

| 层 | V2.0 现在做 | V3.0 直接接 |
|---|---|---|
| 数据 | 4 张表 + `source` / `meta_json` 列 | AI 结果按 key 落库，无需转换 |
| 接口 | `#56` 新建、`#58` PATCH、`#60` 别名、`#64` 关系 | AI 审阅采纳时**复用同一批接口**，不写第二套写入逻辑 |
| UI | 卡片字段失焦保存、列表筛选 | AI 候选卡片复用同布局，加「采纳/忽略」徽标即可 |

**这条设计的意义**：V3.0 的「AI 提取 → 审阅 → 落库」不需要新的数据通道，只是多了一个「候选来源」。若 V2.0 把保存做成整卡提交或独立存储，V3.0 就必须重写。

### 8.2 摘要链草案（V3.0，不在本版实现）

```sql
-- 0004（V3.0 才建，此处仅记录设计意图）
CREATE TABLE chapter_digest (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id    INTEGER NOT NULL UNIQUE REFERENCES chapter(id) ON DELETE CASCADE,
    summary       TEXT NOT NULL,          -- 本章发生了什么（150~300 字）
    characters    TEXT,                   -- JSON: [{name, aliases, role_in_chapter}]
    events        TEXT,                   -- JSON: 关键事件
    hooks         TEXT,                   -- JSON: 埋伏笔 / 回收伏笔
    content_hash  TEXT NOT NULL,          -- 正文 hash，未变则复用，不重复花钱
    model         TEXT,
    prompt_tokens INTEGER, completion_tokens INTEGER,
    created_at    DATETIME NOT NULL, updated_at DATETIME NOT NULL
);
```

**关键点**：`content_hash` 是省钱的核心机制——同一章改了一个错字，不该重跑 AI。这条约束反过来要求 V2.0 的角色卡字段是**结构化可序列化**的，否则 hash 比对与候选合并都无从谈起。

### 8.3 审阅落库草案（V3.0）

```
AI 读取第 12 章正文
  → 输出 {characters:[{name:"林昭", fields:{height:"一六五"}, evidence:"…"}, {name:"沈砚", …}]}
  → 与现有 character 表按 name/alias 匹配
      ├─ 命中：生成「字段变更建议」（旧值 165 → 新值 一六八？冲突提示）
      └─ 未命中：生成「新角色候选」
  → 右侧「AI 建议」抽屉：逐条 [采纳] [改后采纳] [忽略]
  → 采纳 → 调 #56 / #58 → 写 source=ai_extracted + meta_json 记置信度
  → 全流程可撤销（复用 V1 章节快照的「生成新版本」思路，角色侧写 meta_json 历史）
```

### 8.4 对附录 A 接口契约的修订建议（**重要**）

v0.8 附录 A 的契约是：

```python
async def analyze_plot(self, chapter_content: str) -> PlotAnalysis
async def extract_characters(self, chapter_content: str) -> list[CharacterMention]
```

**只能吃单章纯文本**，无法表达三件事：分析范围（章/卷/全书）、已确认的大纲基准与角色卡、输出的结构化落点。V3.0 若照此实现，会立刻需要推倒重来。建议改为：

```python
@dataclass
class AnalysisRequest:
    kind: str                      # digest / character_extract / consistency / chat
    scope: str                     # chapter / volume / book
    project_id: int
    chapter_ids: list[int]
    outline: str | None            # 已确认的大纲基准（FR-8 之外，V3.0 才有）
    characters: list[dict]         # 轻量角色卡（name/aliases/role/关键字段）
    prior_digests: list[dict]      # 摘要链上下文
    options: dict[str, Any]

@dataclass
class AnalysisResult:
    kind: str
    payload: dict[str, Any]        # 键名 = 落库字段名（§5.5 契约①）
    evidence: list[dict]           # [{chapter_id, quote, offset}]，供追溯与高亮
    usage: dict[str, int]          # prompt/completion tokens
    model: str

class AIProvider(ABC):
    @abstractmethod
    async def analyze(self, request: AnalysisRequest) -> AnalysisResult: ...
    @abstractmethod
    async def stream_chat(self, messages: list[dict], tools: list[dict] | None = None): ...
    @abstractmethod
    def name(self) -> str: ...
```

**结论**：V2.0 不改附录 A（避免未实现先改文档产生空转），但本报告 §8.4 作为 V3.0 修订依据登记，届时 v3.0 报告需正式替换附录 A。

---

## 九、质量保障与验收

### 9.1 验收标准

| 编号 | 验收项 | 判定 |
|---|---|---|
| **AC-12** | 角色全链路：新建 → 编辑 15 字段 → 加别名 → 加自定义字段 → 加关系 → 删除 → 回收站恢复，数据完整 | 手工走查 + e2e 断言 |
| **AC-13** | 别名唯一性：项目内别名冲突被拦截；与别的角色姓名冲突被提示；`force` 可强制 | 单测覆盖 4 种冲突组合 |
| **AC-14** | 自定义字段：4 种类型可增删改排序；number 类型非法输入报错且不落库 | 单测 + UI 走查 |
| **AC-15** | 关系图：50 节点 80 边渲染 ≤500ms；拖拽后节点位置稳定；点击节点跳转正确；>80 节点降级列表 | 性能脚本 + 窗口冒烟 |
| **AC-16** | 列表性能：200 角色首屏 ≤300ms；搜索/筛选 ≤150ms | 实测脚本（沿用 4.4 口径） |
| **AC-17** | 迁移安全：schema 2 → 3 成功；迁移前自动备份存在；失败回滚；降级被拒绝；fixture 测试通过 | `tests/test_migrations.py` 增补 |
| **AC-18** | 断网可用：拔网线后角色库全部功能正常（NFR-S4 不回归） | 手工 + e2e（拦截外网） |

### 9.2 回归清单增补（承接 v0.8 §8.1 的 28 项）

| 编号 | 回归项 | 手段 |
|---|---|---|
| **29** | 角色 CRUD + 回收站恢复 | Python 单测 |
| **30** | 别名冲突拦截（含与姓名交叉） | Python 单测 |
| **31** | 自定义字段类型校验与排序 | Python 单测 |
| **32** | 关系图渲染与交互 | 窗口冒烟（`window_smoke.py` 增步） |
| **33** | 角色列表筛选/搜索/三态 | e2e 断言 |
| **34** | 迁移 0002 → 0003 前后数据一致 | fixture 测试 |

### 9.3 测试策略

| 层 | 内容 |
|---|---|
| 单测 | `character_service` 的全部分支（唯一性、类型校验、级联删除、分页）；目标覆盖率 ≥60%（NFR-M1 沿革） |
| 迁移 | `tests/fixtures/schema_v2.db` → 迁移 → PRAGMA 比对列与索引 |
| e2e | `tests/e2e/window_smoke.py` 增补角色页 10~15 步；沿用 CDP 真键位 |
| 性能 | `tests/perf/character_perf.py`：造 200 角色 + 80 关系，测首屏与关系图布局 |

### 9.4 Definition of Done（沿用 v0.8 §8.4）

一个任务算完成，需同时满足：功能可用 + 单测通过 + 回归不降级 + 文档/决策留痕 + 无新增 P0/P1 缺陷。

---

## 十、任务分解与排期

> 详细清单见 `../任务清单/V2.0任务清单.md`。此处只给总表。

| ID | 任务 | 交付物 | 依赖 | 估算（人日） |
|---|---|---|---|---|
| 5.0 | 走查与设计校准 | 偏差清单；枚举/文案定稿 | — | 0.5 |
| 5.1 | 迁移 0003 + ORM + 服务层 | `migrate.py` 追加；`models.py` 4 个模型；`character_service.py` | 5.0 | 2.0 |
| 5.2 | 角色 API #54~#62 | `backend/api/characters.py` | 5.1 | 1.5 |
| 5.3 | 角色库页：列表 + 筛选 + 三态 | `frontend/js/characters.js`、`view-characters`、入口按钮 | 5.2 | 2.0 |
| 5.4 | 角色卡编辑器 + 别名 + 自定义字段 | 卡片三栏、失焦保存、冲突提示 | 5.3 | 2.5 |
| 5.5 | 立绘上传与展示 | #66、Pillow 压缩、占位 | 5.4 | 1.0 |
| 5.6 | 关系 CRUD + 关系图 | #63~#65、`relations.js`、SVG 布局 | 5.4 | 2.5 |
| 5.7 | 出场检索 + 回收站/自检联动 | FR-8.9、`TRASH_TYPES` 扩展、`maintenance` 登记 | 5.4 | 1.0 |
| 5.8 | 回归 29~34 + 验收 + 文档同步 | 验收单、README/CHANGELOG/DECISIONS | 5.5~5.7 | 1.5 |
| | **合计** | | | **14.5**（并行后 **13~15**） |

**建议节奏**：5.0~5.2 为第一周（可跑通 API）；5.3~5.4 为第二周（能用）；5.5~5.6 为第三周前半（好看）；5.7~5.8 为第三周后半（收口）。**关键路径**：5.1 → 5.2 → 5.3 → 5.4。

---

## 十一、风险与待确认事项

### 11.1 风险登记（承接 v0.8 §10）

| ID | 风险 | 影响 | 缓解 |
|---|---|---|---|
| **R-19** | 作者已把角色写在设定文档里，角色库建了却没人填 | 功能闲置 | 空态引导；V2.1 做「从设定文档导入角色」；先自用验证是否顺手 |
| **R-20** | 关系图无第三方库，SVG 力导向布局抖动/性能差 | 体验差、拖慢 5.6 | 布局迭代上限 300 次、节点 >80 降级列表、布局计算分帧；必要时退化为圆形布局 |
| **R-21** | AI 预留不足，V3.0 仍需改表 | 返工 3~5 人日 | §5.5 三项契约 + 5.2 完成后做一次「V3.0 视角」代码评审 |
| **R-22** | 别名/同名冲突导致检索与 AI 匹配混乱 | 数据质量 | 项目内别名唯一 + 冲突提示 + 允许强制；角色名重复允许但列表加定位徽标 |
| **R-23** | 立绘过大/格式不支持/版权 | 体积、崩溃 | 服务端强制转 webp + ≤512px 方形；单文件上限 8MB；失败给可读提示 |
| **R-24** | 老库迁移失败导致打不开 | 数据安全 | 迁移前原子备份（已有）、fixture 测试、失败回滚、不支持降级（NFR-M5） |

### 11.2 待确认事项（发起人拍板）

| ID | 待确认 | 阻塞 | 默认方案 | 工期影响 |
|---|---|---|---|---|
| **Q-11** | 关系图是否 V2.0 必做？ | **是** | 做（P1） | 不做则 −2.5 人日，移 V2.1 |
| **Q-12** | 立绘/头像是否 V2.0 做？ | 否 | 做（P1） | 不做则 −1 人日 |
| **Q-13** | 彻底删除（`force=1`）时，别名/自定义字段/关系**物理清除且不可恢复**，是否接受？ | **是** | 接受（二次确认兜底） | 不接受则需做二级回收站，+2 人日 |
| **Q-14** | 是否本版提供「从设定文档抽取角色」的一次性导入？ | 否 | 不做，空态给引导文案 | 做则 +1.5 人日 |
| **Q-15** | 场景图库（原 V2.2）是否后置到 V3.1 之后？ | 否 | 后置（见 §12） | — |
| **Q-16** | 版本号与发布：V2.0 是否打 tag `v2.0.0` + schema 0003，并同步 README/CHANGELOG？ | 否 | 是 | — |

---

## 十二、与原路线图的差异

| 模块 | 原计划（v0.1 报告） | 本报告建议 | 理由 |
|---|---|---|---|
| 角色库 | V2.0 | **V2.0**（含 AI 预留结构） | 保留，加预留契约 |
| 灵感库 | V2.1 | **V2.1** | 保留；成本低（表 + 列表 + 标签 + 复用 FTS） |
| 场景图库 | V2.2 | **后置至 V3.1 之后** | 图片管理对写作辅助贡献最低，且与角色立绘能力重叠 |
| AI 情节分析 / 人物提取 | V3.0 | **V3.0（最小闭环）** | 差异化核心，应紧跟灵感库，不再往后压 |
| 导出增强（EPUB/DOCX/设定集） | V3.1 | **V3.1**（与场景图库合并） | 降低版本碎片 |

**修订后的路线**：

```
V2.0 角色库（本次）        →  V2.1 灵感库        →  V3.0 AI 最小闭环        →  V3.1 导出增强 + 场景图库
   13~15 人日                 3~4 人日              18~22 人日                4~6 人日
```

> 这条路线与原始规划的**唯一实质差异**是：场景图库从 V2.2 挪到 V3.1，AI 从 V3.0 前移到第三位。发起人可在 Q-15 确认或否决。

---

## 附录：术语增补

| 术语 | 含义 |
|---|---|
| 角色卡 | 一个角色的结构化档案（15 个固定字段 + 自定义字段 + 别名 + 关系） |
| 固定字段 | 数据库列级字段，字段名英文、标签中文（§5.5 契约①） |
| 自定义字段 | 作者自建的键值对，4 种类型（§4.2 FR-8.3） |
| 定位 | 主角/女主/重要配角/反派/龙套/其他（6 类） |
| 关系图 | 以角色为节点、关系为边的 SVG 可视化（FR-8.8） |
| provenance | 字段来源与置信度，V3.0 写入 `meta_json`（§5.5 契约②） |
| 摘要链 | 章摘要 → 卷摘要 → 全书圣经的分层记忆（§8.2，V3.0） |
| 审阅落库 | AI 候选经人工采纳后才写入业务表（§8.3，V3.0） |
