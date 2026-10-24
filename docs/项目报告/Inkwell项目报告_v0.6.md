# Inkwell 小说辅助工具 — 项目报告

## 文档信息

| 项 | 内容 |
|---|---|
| 文档名称 | Inkwell 小说辅助工具 — 项目报告 |
| 版本 | **v0.6（阶段三修订基线）** —— 把阶段二/三实施中产生的接口增补、行为语义、决策与勘误并回正式报告 |
| 日期 | 2026-10-24 |
| 状态 | **阶段一、二已完成；阶段三进行中（3.0~3.4 已交付，3.5~3.9 待做）**。D 组全部关闭（D-12/D-13 暂定，待 Q-03/Q-05）；Q-01、Q-04 已实测确认，Q-02 / Q-03 / Q-05 仍待答复 |
| 适用范围 | V1.0 开发的设计基线、任务分解与验收依据；v0.6 起同时作为**阶段三验收与 V1.0 发布核对**的口径 |
| 配套文档 | 评审：`Inkwell项目报告_评审意见与改进建议.md`、`Inkwell项目报告_v0.2_自审意见.md`~`_v0.4_自审意见.md`；实施：`../版本更新/阶段二_接口与勘误同步清单.md`、`../版本更新/进度记录.md`、`../../DECISIONS.md` |

## 修订记录

| 版本 | 日期 | 主要变更 | 对应问题 |
|---|---|---|---|
| v0.1 | 2026-10-21 | 初稿 | — |
| v0.2 | 2026-10-21 | 补齐背景/目标/范围/术语、NFR、接口、数据模型约束、质量保障、风险与决策 | P-01~P-42 |
| v0.3 | 2026-10-22 | 保存失败暂存、静态资源端点、服务端消毒、迁移前备份、非空卷删除、恢复 AI 抽象层、FTS external content | SA-01~SA-24 |
| v0.4 | 2026-10-22 | ADR-009 签名鉴权、清理异步化、BR-6 默认卷、FTS 去抖与 WAL、3002 先落暂存、恢复前校验、AC-9~11、BR-7 原子写 | SB-01~SB-21 |
| v0.5 | 2026-10-22 | 新增 §8.4 Definition of Done（任务级完成标准） | SC-01 |
| v0.5 | 2026-10-22 | 新增 §1.4.1 目标澄清（本期解决/不解决/推迟） | SC-02 |
| v0.5 | 2026-10-22 | 新增 R-14：数据目录与同步盘/防病毒冲突风险及缓解方案 | SC-03 |
| v0.5 | 2026-10-22 | 新增 R-16：依赖供应链与打包可复现性风险 | SC-04 |
| v0.5 | 2026-10-22 | 新增 FR-6.8 数据目录迁移 + §12.4 换机迁移步骤 | SC-05 |
| v0.5 | 2026-10-22 | 重构 §4.5：迁移归入「升级首启」例外，AC-2 仅约束日常启动 | SC-06 |
| v0.5 | 2026-10-22 | 明确长任务接口清单与超时（§6.1）、索引更新延迟窗口（§6.3） | SC-07、SC-14 |
| v0.5 | 2026-10-22 | 新增 NFR-R10（不可写/磁盘满行为）、NFR-M6（日志轮转上限） | SC-08、SC-10 |
| v0.5 | 2026-10-22 | §7.2 补充窗口尺寸；新增 §12.3 开发者上手；§11 拆为 D/Q 两组 | SC-11、SC-12、SC-13 |
| v0.5 | 2026-10-22 | **环境基线回填**：新增 §3.4 实测环境；Q-01 / Q-04 关闭；新增 R-17（本机代理污染本地 HTTP）；§12.3 改为真实路径 | 环境审查 |
| v0.6 | 2026-10-24 | 并入 §6.2 接口增补 **#45~#53**（#50/#51/#52 标注待实现）、长任务提交契约（500ms 轮询 / 409 + 3004）、#3 `last_opened_at` 与 #47 字段增强 | 阶段二/三实施 |
| v0.6 | 2026-10-24 | **勘误 E-01~E-03 落地**：FTS 触发器即时同步、`/api/system/health`、快照表无软删除字段；§5.2 `version_no` 明确为修订号 | 阶段二评审 |
| v0.6 | 2026-10-24 | §4.3 / §4.4 追加 `exports/`、`webview/`，打包落点改为 **exe 同目录 `data/`**；仓库文档集中到 `docs/`（S3-04 / S3-05） | 数据目录反馈 |
| v0.6 | 2026-10-24 | §7.2 视觉规范回填 3.1/3.4 实测：`--danger #B84F36`、派生 token、字体栈接思源黑体、首行缩进与豁免、选中色 | 3.1 / 3.4 |
| v0.6 | 2026-10-24 | §7.4 / §7.5 补阶段三交互契约：大纲树、首屏三态与首启引导、单章容量提示、快捷键 IME 门禁、对话框取消、设定文档删除、代码块序列化 | 3.2~3.4 / 验收修复 |
| v0.6 | 2026-10-24 | §8.1 回归清单 **20 → 28 项**，补前端纯函数单测与窗口冒烟/截图两种固定验证手段；§8.2 补 #44 正文兜底 | 阶段三 |
| v0.6 | 2026-10-24 | §9 阶段二补 2.12 / 2.13；阶段三重排为 3.0~3.9 并记录 3.0~3.4 交付与估算（12~14 人日） | 任务清单 |
| v0.6 | 2026-10-24 | §10 增 R-18（设计基线滞后实现）与 R-UI1~R-UI7（阶段三 UI 风险）；§11 指向 `DECISIONS.md` 实施决策索引 | 文档债 D1 |

### v0.6 修订要点（快速核对用）

| 类别 | 内容 | 落在哪一节 |
|---|---|---|
| 接口 | #45~#53 入清单（#50/#51/#52 标注**待实现**，#53 已在 3.2 实现）；#3 写入 `last_opened_at`；#47 列表补 `project_id` / `project_title` | §6.2 |
| 行为 | 长任务「返回 tid + 500ms 轮询 + 409/3004」；`/files` 校验顺序；回滚与 `version_no` 语义；回收站 `requires_parent`；检索 `fuzzy` / `page_limited`；日志正文兜底 | §6.1、§6.3、§8.2 |
| 勘误 | E-01 FTS 触发器即时同步；E-02 `/api/system/health`；E-03 快照表无软删除字段 | §5.2、§5.4、§9、§12.3 |
| 架构 | 数据目录：打包落 exe 同目录 `data/`（不可写才回退文档）；新增 `exports/`、`webview/`；仓库文档集中 `docs/` | §4.3、§4.4 |
| 视觉 | `--danger` 调深至 `#B84F36`（AA）、`--accent-strong` 等派生 token、字体栈接思源黑体、正文 17/1.9/≤760、首行缩进 2 字符与豁免、选中色加权 | §7.2 |
| 交互 | 状态栏三态（3.5 待做）、大纲树右键/拖拽/键盘、首屏三态与首启引导、单章容量提示、快捷键 IME 门禁、对话框取消契约、设定文档删除、代码块序列化、组合态占位 | §7.4、§7.5 |
| 质量 | 回归清单 20 → 28；前端纯函数单测（node --test）+ 窗口冒烟 + 截图基线成为固定验证手段 | §8.1、§8.3 |
| 计划 | 阶段三 3.0~3.4 已交付、3.5~3.9 待做，合计 **12~14 人日** | §9 |

> 实施侧的过程记录（逐次汇报、决策、勘误、截图）在 `docs/版本更新/` 与 `DECISIONS.md`；
> 本报告只保留**结论**，不复述过程。

## 目录

- [一、项目背景与目标](#一项目背景与目标)
- [二、需求分析](#二需求分析)
- [三、竞品分析与技术选型](#三竞品分析与技术选型)
- [四、系统架构设计](#四系统架构设计)
- [五、数据模型设计](#五数据模型设计)
- [六、接口设计](#六接口设计)
- [七、UI/UX 设计方向](#七uiux-设计方向)
- [八、质量保障与工程规范](#八质量保障与工程规范)
- [九、开发计划与里程碑](#九开发计划与里程碑)
- [十、风险登记册](#十风险登记册)
- [十一、待决策与待确认事项](#十一待决策与待确认事项)
- [十二、附录](#十二附录)
- [附录 A：AI 接口抽象层](#附录-aai-接口抽象层)
- [附录 B：需求追踪矩阵](#附录-b需求追踪矩阵)
- [附：本次改动汇总（v0.4 → v0.5）](#附本次改动汇总v04--v05)
- [附：本次改动汇总（v0.5 → v0.6）](#附本次改动汇总v05--v06)

---

## 一、项目背景与目标

### 1.1 背景与痛点

| 现有方案 | 典型问题 |
|---|---|
| Word / WPS / 记事本 | 无卷章结构、无全书字数与进度、大文件卡顿、无版本历史 |
| 网文平台后台 | 必须联网、数据在平台服务器、与平台强绑定、无法离线 |
| Notion / Obsidian | 无小说领域模型，全靠模板插件自搭，配置成本高于收益 |
| Scrivener | 收费、汉化弱、学习曲线陡、不含中文网文工作流 |
| 零散记录 | 灵感设定散落，写作时找不到 |

**一句话痛点**：长篇作者需要的不是"又一个编辑器"，而是**懂小说结构的、数据归自己、不会丢稿、开箱即用的本地工作台**。

### 1.2 目标用户与画像

| 画像 | 特征 | 核心诉求 | V1 优先级 |
|---|---|---|---|
| **A. 长篇网文作者** | 日更 3000~10000 字，常开 1~3 本 | 写得快、不卡、不丢稿、字数准 | **最高** |
| **B. 传统/严肃文学作者** | 重结构与设定一致性，周期长 | 设定文档与正文并列管理、长周期可靠 | **高** |
| **C. 同人/轻小说作者** | 重灵感与素材 | 灵感库、图库 | 低（V2） |

V1.0 优先服务 **A 与 B 的交集**。

### 1.3 核心价值主张

1. **数据主权**：数据落在自己的 `Documents/Inkwell/`，可拷可读，卸载不丢、换机即拷
2. **零配置体验**：一个 exe，双击即用，不装 Python、不开浏览器、不注册、不联网
3. **中文长篇领域模型**：卷-章 + 字数进度 + 设定文档并列 + 章节版本历史
4. **可扩展与开源**：模块像插件一样加

### 1.4 项目目标与成功标准

**产品目标**：让一位作者能够**从零开始、完整写完一本 30 万字以上的长篇小说**，全程不丢稿、不卡顿、数据可备份可导出。

#### 1.4.1 目标澄清（本期解决 / 不解决 / 推迟）

| 本期明确解决 | 本期明确不解决 | 推迟到 |
|---|---|---|
| 多项目管理（封面/简介/标签/进度） | 云端同步、多设备同步 | 不在路线图 |
| 卷-章两级大纲与拖拽排序 | 角色库与人物关系图 | V2.0 |
| 富文本章节写作（含图片） | 灵感库、场景图库 | V2.1 / V2.2 |
| 设定文档（世界观/时间线/势力/名词表） | AI 情节分析与人物提取 | V3.0（接口 V1 预留） |
| 自动保存 + 分级版本快照 + 回滚 | EPUB / DOCX 排版导出 | V3.1 |
| 全文检索（章节 + 设定文档） | 自动更新机制 | 待确认 Q-02 |
| 本地备份与恢复、导出 TXT/MD | 数据加密 | 不在路线图 |
| 回收站（误删恢复） | 移动端 / Web 版 | 不在路线图 |
| Windows 10/11 x64 打包分发 | macOS / Linux 打包 | V1.1 评估 |

**V1.0 发布验收标准（11 条，全部满足方可发布）**

| 编号 | 验收标准 | 判定方式 |
|---|---|---|
| AC-1 | 支撑单项目 ≥20 卷 / ≥2000 章 / 单章 ≤5 万字 / 全书 ≤500 万字 | 脚本生成压力数据，实测满足 §2.4 |
| AC-2 | **日常启动**（无待执行迁移）双击到窗口可交互 ≤ 3s | 中位机实测 5 次取中位数 |
| AC-2b | **升级首启**（有待执行迁移）展示"正在升级数据…"进度，≤30s（**假设值**） | 构造跨版本迁移用例实测 |
| AC-3 | 打开 5 万字章节到可编辑 ≤ 1s（承诺范围：单章 ≤5 万字） | 同上 |
| AC-4 | 断电/强杀后丢失 ≤30 秒输入 | `taskkill /F` 后重启 |
| AC-5 | 写作 1 小时后仍可回溯到 60 分钟前节点 | 版本历史抽查 |
| AC-6 | 导出 TXT/MD 内容与正文一致 | 字数误差 ≤0.5% |
| AC-7 | 5 名内测作者全流程通过，≥4 人愿继续使用 | 内测问卷 |
| AC-8 | 第三方按 README 30 分钟内跑通开发环境 | 找 1 名未参与开发者计时 |
| AC-9 | 破坏数据库后能从最近备份完整恢复（正文/设定/版本） | 破坏性演练 |
| AC-10 | 10 万字项目检索 ≤1s，且同时覆盖章节正文与设定文档 | 构造 10 组关键词测试项目 |
| AC-11 | 删除章节 30 天内可完整恢复，含"父卷已删"的孤儿场景 | 回归第 4 项 + 孤儿专项 |

### 1.5 范围界定

**In Scope**：项目基础信息管理、卷-章大纲与写作、设定文档、自动保存与版本历史、字数统计、全文检索、备份恢复与导出导入、回收站、Windows 打包分发。

**Out of Scope（新增两项显式声明）**：
- ❌ 云端同步 / 多人协作 / 移动端 / Web 版
- ❌ 角色库、人物关系图、灵感库、场景图库（→ V2.0~V2.2）
- ❌ AI 情节分析、AI 人物提取（→ V3.0；接口抽象层 V1 预留，附录 A）
- ❌ EPUB / DOCX 排版导出（→ V3.1）
- ❌ 账号体系 / 付费 / 插件市场
- ❌ macOS / Linux 打包（→ V1.1 评估）
- ❌ 图片 OCR、公式编辑、复杂表格排版
- ❌ 实时协作编辑、评论批注
- ❌ **自动更新机制**（待确认 Q-02，默认不做）
- ❌ **数据加密**（本地单机场景，不在路线图）

### 1.6 术语表

| 术语 | 定义 |
|---|---|
| **项目 / 作品** | 一部小说，Inkwell 中最高层级容器 |
| **卷** | 项目下的分卷；可选 |
| **默认卷** | 系统自动创建的隐藏卷（BR-6），承载"不分卷"的章节，并作为删除非空卷与恢复孤儿章节的落点 |
| **章节** | 正文最小组织单元，隶属于某个卷 |
| **设定文档** | 与正文并列的项目级参考资料，不参与字数统计 |
| **章节版本** | 章节正文在某时刻的快照，记作"章节版本 #N"。**版本号单调递增，回滚也产生新版本号**（BR-9） |
| **快照** | 生成一次章节版本的动作 |
| **暂存保存（pending）** | 自动保存连续失败或版本冲突时，把内容暂存在本地（localStorage + `drafts/`）的机制 |
| **字数** | 按 BR-1 统计的中文字数，不含 HTML 标签，默认含标点 |
| **软删除** | 标记删除并移入回收站，数据仍在库中 |
| **数据目录** | 运行时数据根目录，默认 `%USERPROFILE%/Documents/Inkwell`（同步盘冲突见 R-14） |

---

## 二、需求分析

### 2.1 用户故事

| ID | 用户故事 |
|---|---|
| US-1 | 双击 exe 就能写，不用装环境、不用开浏览器 |
| US-2 | 同时管理 3 本书，各有封面、简介、进度 |
| US-3 | 按"卷-章"组织大纲并拖拽排序 |
| US-4 | 看到本章与全书字数 |
| US-5 | 自动保存且能找回一小时前的版本 |
| US-6 | 单独维护世界观/时间线，写作时可查但不混进正文 |
| US-7 | 定期导出留底或整盘备份 |
| US-8 | 搜索地名能同时命中章节与设定文档 |
| US-9 | 误删的章节能找回 |
| US-10 | 界面浅色安静，不干扰写作 |
| US-11 | 导入旧稿（TXT，可能 GBK）不乱码 |

### 2.2 功能需求（V1.0，MoSCoW 优先级）

#### FR-1 项目基础信息管理（Must）

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-1.1 | 项目创建 / 编辑 / 删除 | Must |
| FR-1.2 | 属性：书名、简介、封面、标签、状态（连载/暂停/完结）、目标字数 | Must |
| FR-1.3 | 列表页卡片：封面 + 书名 + 简介 + 字数 + 进度（未设目标则不显示） | Must |
| FR-1.4 | 设置页：改信息、换封面、删项目 | Must |
| FR-1.5 | 记住上次打开的章节 | Should |
| FR-1.6 | 删除进回收站，可恢复/彻底删除 | Must |
| FR-1.7 | 项目名允许重复 | Must |
| FR-1.8 | 封面文件缺失显示默认图标 | Should |

#### FR-2 卷-章大纲管理（Must）

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-2.1 | 卷-章两级 CRUD；删除非空卷强制二选一确认 | Must |
| FR-2.2 | 章节列表、新建/重命名/删除/拖拽排序；标题允许重复 | Must |
| FR-2.3 | 章节属性：标题、状态、梗概、目标字数 | Should |
| FR-2.4 | 跨卷拖动；合并卷 = 章节移入目标卷末尾并删除本卷 | Could（V1.1） |
| FR-2.5 | 大纲树折叠/展开、键盘移动 | Should |

#### FR-3 富文本章节写作（Must）

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-3.1 | 加粗/斜体/标题/列表/引用/分割线/撤销重做 | Must |
| FR-3.2 | 图片插入（存 `media/`，经 `/files/` 签名访问） | Must |
| FR-3.3 | 实时字数（本章/本卷/全书） | Must |
| FR-3.4 | 中文排版：首行缩进 2 字符、行宽行高 | Must |
| FR-3.5 | 自动保存（防抖 + 最大间隔；失败/冲突暂存兜底） | Must |
| FR-3.6 | Markdown 快捷输入 | Could（V1.1） |
| FR-3.7 | 专注/打字机模式 | Should（V1.1） |
| FR-3.8 | 深色模式 | Could（V1.1） |
| FR-3.9 | 超容量单章提示不阻断 | Should |
| FR-3.10 | 图片缺失显示占位符 | Should |

#### FR-4 设定文档（Must）

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-4.1 | 项目级设定文档区，与章节并列，不参与全书字数 | Must |
| FR-4.2 | 类型：世界观 / 时间线 / 势力 / 名词表 / 其他 | Must |
| FR-4.3 | 复用章节编辑器 | Must |
| FR-4.4 | 多文档、排序、分类筛选 | Should |
| FR-4.5 | 设定文档版本历史（表 V1 建，功能 V1.1） | Should |

#### FR-5 自动保存与版本历史（Must）

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-5.1 | 停输 3s 或最长 30s 触发保存 | Must |
| FR-5.2 | 分级快照策略（§5.3） | Must |
| FR-5.3 | 版本列表（倒序 + 字数差异） | Must |
| FR-5.4 | 预览对比 + 一键回滚（版本号递增） | Must |
| FR-5.5 | 手动快照（Ctrl+S） | Must |
| FR-5.6 | 里程碑快照（定稿时） | Should |
| FR-5.7 | 失败/冲突兜底 | Must |

#### FR-6 备份、导出、导入与迁移（Must）

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-6.1 | 每日自动备份（后台异步），保留 7 日 + 4 周 | Must |
| FR-6.2 | 手动立即备份（原子写入） | Must |
| FR-6.3 | 从备份恢复（先校验；§4.6 流程） | Must |
| FR-6.4 | 导出 TXT（空项目输出含书名与简介的文件） | Must |
| FR-6.5 | 导出 Markdown（空项目输出目录说明） | Must |
| FR-6.6 | 导入 TXT/MD，自动拆章；单文件 ≤50MB；编码探测 BOM→UTF-8→GB18030→手动 | Could（V1.1） |
| FR-6.7 | 磁盘余量低于阈值预警 | Should |
| FR-6.8 | **数据目录迁移/换机流程**：退出应用 → 整体拷贝目录 → 新机装同版或更高版 → 首启自动校验（quick_check + schema_version），不匹配则引导从备份恢复（§12.4） | Should |

#### FR-7 搜索（Must）

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-7.1 | 全局搜索：章节标题 + 章节正文 + 设定文档 | Must |
| FR-7.2 | 当前项目 / 全部项目范围 | Should |
| FR-7.3 | 上下文片段高亮 + 点击跳转 | Must |
| FR-7.4 | FTS5 external content，10 万字 ≤1s | Must |

### 2.3 关键业务规则

| 编号 | 规则 | 要点 |
|---|---|---|
| **BR-1** | 字数统计 | 去标签纯文本；CJK 逐字计；西文按词计；标点/emoji/符号默认计入，可开关 |
| **BR-2** | 自动保存与兜底 | 停输 3s / 最长 30s；失败重试 3 次（1s/3s/9s）后落本地双份暂存并告警；3002 冲突**先落暂存再提示刷新**；关闭/切换/失焦强制保存 |
| **BR-3** | 排序 | 步长 1000；头部 = min−1000，尾部 = max+1000，中间 = floor((前+后)/2)；相邻差 ≤1 局部重整 |
| **BR-4** | 删除与恢复 | 全软删除；项目级联；非空卷二选一；默认卷不可删；回收站 30 天；**恢复校验父链**（父在回收站提示一并恢复，父已物理删除则挂默认卷/项目根级） |
| **BR-5** | 文件路径 | 库内只存相对路径；图片白名单 jpg/png/webp、单张 ≤10MB；图片经 `/files/` 访问 |
| **BR-6** | 默认卷 | 新建项目/导入时自动创建；大纲树默认隐藏（项目无其他卷时才显示）；不可删除、不可重命名；`order_index` 固定 0；参与卷内字数统计。**创建首个命名卷时**若默认卷已有章节，二次确认后一次性迁入新卷（#53 / C-04），避免章节「消失」 |
| **BR-7** | 原子写入 | 备份与导出先写 `*.tmp` 再 `os.replace()`；扫描忽略 `.tmp` |
| **BR-8** | 时间基准 | 持久化用 UTC；日期类策略用本地日期 + `app_meta` 记录上次处理日期；**检测到时间回拨则跳过本次清理与每日备份并提示** |
| **BR-9** | 版本编号 | `version_no` 单调递增、永不回退；回滚产生新版本（UI："由 #13 回滚至 #7，生成 #14"）；乐观锁以 `chapter.version_no` 为准 |

### 2.4 非功能需求

| 类别 | 编号 | 要求 |
|---|---|---|
| 性能 | NFR-P1 | 冷启动（日常启动，无迁移）≤ 3s |
| | NFR-P2 | 打开 5 万字章节到可编辑 ≤ 1s（承诺范围 ≤5 万字） |
| | NFR-P3 | 输入延迟 ≤ 16ms，落盘异步 |
| | NFR-P4 | 全书字数异步增量重算 |
| | NFR-P5 | 检索 10 万字 ≤1s；100 万字 ≤3s |
| | NFR-P6 | 常驻内存 ≤ 300MB |
| | NFR-P7 | **索引更新由触发器即时同步**（E-01 修订：external content 不同步则检索结果不可预测；去抖降级为 V1.1 可选优化）；导出 500 万字 ≤60s（**假设·待实测**） |
| 可靠性 | NFR-R1 | 断电/强杀丢失 ≤30 秒输入 |
| | NFR-R2 | WAL + `busy_timeout=5000`，写串行化 |
| | NFR-R3 | 启动 quick_check；完整 integrity_check 每周一次或异常时（后台） |
| | NFR-R4 | 每日备份，后台异步 |
| | NFR-R5 | 迁移前原子备份；事务内执行，失败回滚 |
| | NFR-R6 | 失败 ≥3 次或冲突时先落暂存再提示 |
| | NFR-R7 | 恢复前在临时副本上校验完整性与版本兼容性 |
| | NFR-R8 | 启动阶段的备份/清理/自检全部后台异步 |
| | NFR-R9 | 磁盘余量低于 1GB（**假设阈值**）预警 |
| | NFR-R10 | **数据目录不可写（权限/受控文件夹访问）时阻断并明确提示，不静默失败** |
| 数据安全 | NFR-S1 | 仅绑定 `127.0.0.1`，随机端口 |
| | NFR-S2 | 业务接口 `X-Inkwell-Token` 头，经窗口对象注入，不入 URL |
| | NFR-S3 | 单实例锁 |
| | NFR-S4 | 无需联网；AI 须显式开启并明示外发范围 |
| | NFR-S5 | Host 头校验（防 DNS rebinding） |
| | NFR-S6 | 富文本服务端白名单消毒 |
| | NFR-S7 | `/files/` 路径规范化 + 白名单 |
| | NFR-S8 | 静态资源短期签名 token（ADR-009） |
| | NFR-S9 | 生产禁用 DevTools / 右键菜单 |
| 兼容性 | NFR-C1 | Windows 10 1809+ / Windows 11 x64 |
| | NFR-C2 | 启动时检测 WebView2 Runtime 并引导 |
| | NFR-C3 | 数据目录支持中文与空格路径 |
| | NFR-C4 | **数据目录不得位于同步盘同步范围内**（R-14）；检测到则提示 |
| 易用性 | NFR-U1 | 首次启动 30s 内完成"建书 → 写第一句" |
| | NFR-U2 | 快捷键（§7.5） |
| | NFR-U3 | 破坏性操作二次确认 |
| | NFR-U4 | 超容量 / 超长章节**只提示不阻断**（不弹窗、不禁用输入、不拦截保存）；提示须颜色 + 文案双重编码 |
| 可维护性 | NFR-M1 | services 单测覆盖 ≥60% |
| | NFR-M2 | 新增模块仅三文件 |
| | NFR-M3 | schema 变更带迁移与备份 |
| | NFR-M4 | 日志脱敏 + 前端异常/超时上报 |
| | NFR-M5 | 迁移单调递增、不支持降级、附 fixture 测试 |
| | NFR-M6 | **日志按天轮转，总量 ≤50MB（假设阈值），超出删最老** |

### 2.5 迭代路线图

| 版本 | 模块 | 说明 |
|---|---|---|
| V1.1 | 写作体验增强 | 专注/打字机模式、深色模式、写作目标与打卡 |
| V1.1 | 导入增强 | TXT/MD 批量导入、自动拆章、编码探测 |
| V1.1 | 设定文档版本历史 | 表已建，补功能 |
| V1.1 | 卷操作增强 | 合并卷、Markdown 快捷输入 |
| V1.1 | 跨平台评估 | macOS / Linux 打包 |
| V2.0 | 角色库 | 档案卡、关系图、立绘 |
| V2.1 | 灵感库 | 随手记、标签、搜索 |
| V2.2 | 场景图库 | 按项目分类浏览 |
| V3.0 | AI 情节分析 / 人物提取 | 附录 A，用户自带 Key |
| V3.1 | 导出增强 | EPUB / DOCX、设定集 |

---

## 三、竞品分析与技术选型

### 3.1 差异化

| 产品 | 本地优先 | 卷章模型 | 版本历史 | 中文长篇 | 费用 |
|---|---|---|---|---|---|
| Word / WPS | ✅ | ❌ | 弱 | 一般 | 付费/免费 |
| 网文平台后台 | ❌ | ✅ | 部分 | ✅ | 免费 |
| Notion | ❌ | ❌ | 有 | 一般 | 订阅 |
| Obsidian | ✅ | ❌ | 需插件 | 一般 | 付费商用 |
| Scrivener | ✅ | ✅ | 有 | 弱 | 付费 |
| **Inkwell** | **✅** | **✅** | **✅** | **✅** | 免费开源 |

### 3.2 方案对比（数值为经验预估·阶段四实测校准）

| 对比项 | PyQt / PySide | 本地 Web | **pywebview（选定）** | Electron |
|---|---|---|---|---|
| 独立 exe | ✅ | ❌ | ✅ | ✅ |
| UI 上限 | 中 | 高 | 高 | 高 |
| 打包体积 | 40~70MB | 20~40MB | **35~60MB** | 100~200MB |
| 冷启动 | 1~2s | 1~2s | **2~3s** | 2~4s |
| 常驻内存 | 150~250MB | 120~200MB | **180~300MB** | 250~400MB |
| 学习成本(人日) | 5~8 | 1~2 | **2~3** | 4~6 |

### 3.3 技术栈（版本锁定）

| 层级 | 技术 | 版本 | 用途 |
|---|---|---|---|
| 桌面壳 | pywebview | ≥5.0 | 窗口；生产 `debug=False` |
| 后端 | FastAPI | ≥0.110 | REST API |
| ASGI | uvicorn | ≥0.27 | 子线程运行 |
| 数据库 | SQLite + SQLAlchemy | 3.35+ / 2.0 | 存储 + FTS5 |
| 编辑器 | **Quill** | **2.x** | 零构建静态引入 |
| 消毒 | bleach | ≥6.0 | 白名单消毒 |
| 图片处理 | **Pillow** | ≥10.0 | 封面/正文图片压缩（FR-1.2、FR-3.2 隐含需求，环境审查时补入） |
| 文件上传 | **python-multipart** | ≥0.0.9 | FastAPI 接收封面上传（FR-1.2 隐含需求，环境审查时补入） |
| 前端 | 原生 CSS / ES Module | — | 无构建工具 |
| 打包 | PyInstaller | ≥6.0 | onedir |
| AI | 抽象层 | — | 附录 A，V1 不实现 |

### 3.4 环境基线（2026-10-22 本机实测）

**结论：本机环境满足 V1.0 开发需求。** 实测结果如下。

| 项 | 实测结果 | 状态 |
|---|---|---|
| 操作系统 | Windows（C/D/E/F 四盘；E 盘可用 201.9 GB） | ✅ |
| Python | **E:\Python311\python.exe — Python 3.11.9（本次新装）** | ✅ 与 Q-04 假设一致 |
| pip | E:\Python311\Lib\site-packages\pip — 24.0 | ✅ |
| 项目虚拟环境 | **D:\小说辅助\.venv（Python 3.11.9）** | ✅ 本次创建 |
| Node.js | `C:\Program Files\nodejs\node.exe` — v24.19.0（另有托管版 v22.22.2） | ✅ |
| npm | 10.9.7 | ✅ |
| Git | `E:\Git\cmd\git.exe` — 2.55.0 | ✅ |
| VS Code | `E:\VScode\Microsoft VS Code\bin\code.cmd`，`code` 已在 PATH | ✅ |
| Java | `C:\Program Files\Eclipse Adoptium\jdk-17.0.20.101-hotspot` | ✅（本项目不用） |
| winget | 可用（用于后续补装工具） | ✅ |
| **WebView2 Runtime** | `C:\Program Files (x86)\Microsoft\EdgeWebView\Application\155.0.4283.62` | ✅ **R-8 风险在本机不成立** |
| **Documents 是否被同步盘接管** | **否**（非重解析点；无 OneDrive 目录） | ✅ **R-14 风险在本机不成立** |
| ⚠️ 本机代理 | `http_proxy` / `https_proxy` = `http://127.0.0.1:64530`；WinINet 系统代理 `ProxyEnable=0` | ⚠️ **新增 R-17** |

**已安装版本（`D:\小说辅助\.venv`）**

| 用途 | 包 | 实测版本 | 报告要求 |
|---|---|---|---|
| 桌面壳 | pywebview | **6.2.1** | ≥5.0 ✅ |
| Windows 依赖 | pythonnet / clr_loader | 3.2.1 / 0.3.1 | pywebview 自动拉取 ✅ |
| 后端 | fastapi / starlette / pydantic | 0.159.1 / 1.9.0 / 2.14.1 | ≥0.110 ✅ |
| ASGI | uvicorn | 0.54.0 | ≥0.27 ✅ |
| ORM | SQLAlchemy | 2.1.6 | 2.0 ✅ |
| 消毒 | bleach | 6.4.0 | ≥6.0 ✅ |
| 打包 | PyInstaller / hooks-contrib | 6.22.3 / 2026.9 | ≥6.0 ✅ |
| 图片（新增依赖） | Pillow | 13.0.0 | 报告未列，因"图片压缩"需要而补 |
| 文件上传（新增依赖） | python-multipart | 0.0.32 | 报告未列，因封面上传（FR-1.2）需要而补 |
| 开发 | pytest / httpx / ruff / black / pip-tools | 9.1.1 / 0.28.1 / 0.17.1 / 26.10.1 / 7.6.2 | — |

**已完成的实证验证**：`smoke_test.py` 全绿 —— uvicorn 在**非主线程**启动无 signal handler 报错；随机端口绑定 127.0.0.1 成功；连续 3 次复用 keep-alive 连接请求均 200。这直接消除了 ADR-002 的最大技术不确定性。

### 3.5 架构决策记录（ADR-001~009）

| ID | 决策 | 备选 | 理由 | 代价 |
|---|---|---|---|---|
| ADR-001 | pywebview(WebView2) | PyQt/Electron/Tauri | 表达力 + 独立 exe | 依赖 Runtime |
| ADR-002 | 本地 HTTP(FastAPI) | js_api 直调 | 契约清晰、可调试、可复用 | 端口与安全面 |
| ADR-003 | SQLite + WAL | Markdown 目录 | 事务、FTS5、易备份 | 并发自处理 |
| ADR-004 | Quill 2.x | TipTap | 与无构建一致 | 高级排版弱 |
| ADR-005 | HTML + content_text | Markdown/Delta | 回显 + 统计 | 双列维护 |
| ADR-006 | 分级快照 | 每次保存快照 | 防爆炸 | 粒度粗 |
| ADR-007 | onedir 打包 | onefile | 启动快 | 分发为文件夹 |
| ADR-008 | FTS5 external content | 默认内容表 | 省一份正文 | 需触发器 |
| ADR-009 | **静态资源签名 query token** | 头鉴权(不可行)/fetch→blob | img 只能带 URL 参数 | 签名入 URL |

---

## 四、系统架构设计

### 4.1 架构总览

```
┌────────────────────────────────────────────────────┐
│                用户双击 Inkwell.exe                 │
│  ┌──────────────────────────────────────────────┐  │
│  │       pywebview 窗口壳 (WebView2 内核)        │  │
│  │  ┌──────────────────────────────────────┐   │  │
│  │  │  前端 (原生 HTML/CSS/ES Module)       │   │  │
│  │  └──┬──────────────────────────┬──────┘   │  │
│  │     │ 业务接口                │ img/封面    │  │
│  │     │ X-Inkwell-Token 头       │ ?sig= 签名   │  │
│  │  ┌──▼──────────────────────────▼──────┐   │  │
│  │  │  FastAPI 后端 (uvicorn 子线程)     │   │  │
│  │  │  api/ → services/ → models/       │   │  │
│  │  └──────────────┬───────────────────┘   │  │
│  └─────────────────┼───────────────────────┘  │
│                    ▼                          │
│   数据目录 Documents/Inkwell/                  │
│   inkwell.db · covers/ · media/ · backups/     │
│   drafts/ · logs/                              │
└────────────────────────────────────────────────┘
```

**图 1　运行时架构图**（业务走 token 头，静态资源走签名 query）

> 澄清：不是"不用浏览器"，而是"不需要用户手动开浏览器"。应用内嵌 WebView 内核，本地服务仅监听 `127.0.0.1`，对用户不可见。

### 4.2 分层职责

| 层 | 职责 | 约束 |
|---|---|---|
| 前端 | 渲染、编辑器交互、调用 API、暂存兜底 | 不直接操作数据库 |
| API 层 | 路由、校验、统一响应；token/Host/签名校验 | 不含业务规则 |
| Service 层 | 业务规则（保存/快照/字数/备份/导出/消毒/默认卷） | 可单测 |
| Model 层 | 表定义与关系 | 变更带迁移 |
| 存储层 | SQLite + 文件 | 路径相对数据目录 |

### 4.3 目录结构

```
Inkwell/
├── main.py                      # 入口：起服务 → token 注入 → 起窗口（--selfcheck 自检模式）
├── requirements.txt / .lock     # 运行依赖 / 含哈希的锁定文件
├── pyproject.toml               # ruff / black / pytest 配置
├── package.json                 # 仅声明 ES Module 与 Node 测试脚本（前端无构建步骤）
├── CHANGELOG.md / DECISIONS.md / README.md
├── backend/
│   ├── server.py  config.py  database.py  models.py  schemas.py  migrate.py  storage.py
│   ├── api/   projects volumes chapters versions documents search backup files
│   │          trash tasks maintenance system drafts export
│   └── services/ project_service chapter_service document_service version_service
│                 wordcount sanitize search_service backup_service export_service
│                 drafts media tasks logging_service maintenance_service trash_service
├── frontend/
│   ├── index.html
│   ├── css/ tokens.css style.css
│   ├── js/  app api view editor writer sidebar documents projects format capacity
│   │        autosave fallback pending versions search trash backup tasks logger
│   └── vendor/quill/               # Quill 2.0.3 离线副本（前端不引入构建步骤）
├── tests/  test_*.py（pytest）· js/*.test.js（node --test）· e2e/（pywebview 窗口冒烟 + 截图）
├── docs/   README.md（索引）· 项目报告/ · 任务清单/ · 版本更新/（进度记录、逐次汇报、截图）
└── data/                         # 开发环境数据目录（打包后为 exe 同目录 data/）
```

### 4.4 数据存储与路径策略

**图 2　数据目录布局**

```
<数据目录>/
├── inkwell.db · inkwell.db-wal / -shm
├── covers/     # 项目封面
├── media/      # 正文图片（按章节 / 文档子目录）
├── backups/    # 数据库备份（迁移前、恢复前的备份不自动删）
├── drafts/     # 保存失败 / 冲突时的服务端暂存
├── exports/    # 导出的 TXT / MD
├── logs/       # 运行日志（按天轮转，总量 ≤50MB）
└── webview/    # WebView2 缓存与 localStorage（显式 storage_path，避免写 %APPDATA%）
```

| 环境 | 数据目录 | 判定方式 |
|---|---|---|
| 覆盖 | 任意 | `INKWELL_DATA_DIR`（优先级最高） |
| 可移植 | exe 同目录 `portable_data/` | 存在 `portable.txt` |
| 打包 | **exe 同目录 `data/`**（装到哪个盘，数据就落哪个盘） | `sys.frozen` 为真 |
| 打包（回退） | `%USERPROFILE%/Documents/Inkwell/` | **仅当 exe 目录实测不可写**（写探针判定；`os.access` 在 Windows 上会因 UAC 虚拟化误报） |
| 开发 | `<仓库>/data/` | 默认 |

> **v0.6 修订（S3-04）**：打包默认目录由「文档」改为 **exe 同目录 `data/`**（响应「数据不应写 C 盘」）；
> `webview/` 子目录作为强制的 `storage_path`，不指定时 WebView2 缓存会落到 `%APPDATA%\pywebview`（系统盘，且持续增长）。

> **同步盘风险（R-14）**：若本机 `Documents` 被 OneDrive/其他同步盘接管，应用启动时检测并给出一次性提示，提供"更换数据目录"入口；README 明确"应用运行时请勿同步，或退出后再同步"。

### 4.5 启动与生命周期

```
【前台 · 计入冷启动（目标 ≤3s，AC-2）】
1. 单实例锁 → 已运行则聚焦已有窗口并退出
2. 解析数据目录 → 不存在则初始化；不可写则阻断并提示（NFR-R10）
3. 检测 WebView2 Runtime → 缺失则引导下载（NFR-C2）
4. 打开数据库 → foreign_keys=ON / journal_mode=WAL / busy_timeout=5000
5. 快速自检 PRAGMA quick_check（毫秒级）
   ├─ 异常 → 阻断，引导从 backups/ 恢复
   └─ 正常 → 继续
   > **空库陷阱（v0.6 登记，B4）**：`inkwell.db` 丢失时 SQLite 会自动建空库，而 quick_check 对空库
   > 同样返回健康 —— 当前实现会静默进入「一本书都没有」的空状态，不提示 `backups/` 里有备份。
   > 设计口径：**项目数为 0 且 backups/ 非空 → 首屏提示「检测到 N 份备份，可去备份页恢复」**；
   > 实现排在阶段三遗留项（见 §九）。
6. **迁移必要性检查（仅比对 schema_version，快）**
   ├─ 无需迁移 → 直接渲染窗口与编辑器 → 可交互（AC-2 到此为止）
   └─ 需迁移 → 转「升级首启」路径（见下，不计入 AC-2）
7. 渲染窗口与编辑器，拉取 /api/meta，恢复上次项目与章节

【升级首启 · 例外路径（目标 ≤30s，AC-2b，假设值）】
8. 显示"正在升级数据…"进度页（编辑器只读遮罩）
9. 原子备份当前库为 backups/inkwell_premigrate_*.db（BR-7 / NFR-R5）
10. 按 schema_version 递增顺序在事务内应用迁移，失败回滚并引导恢复（NFR-M5）
11. 完成后转入前台第 7 步

【后台异步 · 全程不阻塞（NFR-R8）】
12. 时间基准检查（BR-8）：时间回拨 → 跳过清理与每日备份，记录 WARNING 并提示
13. 每日首次启动：原子备份数据库（FR-6.1）
14. 清理：过期备份、回收站 >30 天、孤儿媒体；结果以通知呈现
15. WAL checkpoint（TRUNCATE，假设：每 5 分钟或 ≥32MB）；FTS 由**触发器即时同步**（E-01）；字数增量重算
16. 磁盘余量检查 → 低于阈值预警（NFR-R9 / FR-6.7）
17. 退出：强制保存（含暂存检查与未保存提醒）→ 关闭服务 → 释放锁
```

---

## 五、数据模型设计

### 5.1 实体关系

```
Project ──1:N──> Volume ──1:N──> Chapter ──1:N──> ChapterVersion
   │                                  │
   ├──1:N──> Document ──1:N────────── DocumentVersion
   ├──1:N──> ProjectTag <──N:1── Tag
   └──1:1──> Volume(is_default=1)     # 默认卷，每个项目恰好一条（BR-6）
```

**约束补充**：应用逻辑层保证"每个项目有且仅有一条 `is_default=1` 的卷"；该不变量在新建项目、导入旧稿、项目恢复三处统一由 `project_service` 维护（修复时自动补齐）。

### 5.2 表结构

**通用约定**：`is_deleted` / `deleted_at` 软删除；外键 `ON DELETE CASCADE`；时间存 UTC；书名/卷名/章节标题允许重复。

#### project

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | INTEGER | PK | — |
| title | TEXT | NOT NULL | 允许重复 |
| description | TEXT | | 简介 |
| cover_path | TEXT | | 相对路径 |
| status | TEXT | NOT NULL DEFAULT 'writing' | writing/paused/finished |
| target_word_count | INTEGER | DEFAULT 0 | 0=未设 |
| total_word_count | INTEGER | NOT NULL DEFAULT 0 | 异步重算，最终一致 |
| last_opened_at | DATETIME | | — |
| last_chapter_id | INTEGER | FK SET NULL | 上次位置 |
| created_at / updated_at | DATETIME | NOT NULL | — |
| is_deleted / deleted_at | INTEGER / DATETIME | DEFAULT 0 | 软删除 |

索引：`idx_project_updated (updated_at DESC)`

#### tag / project_tag

| 表 | 字段 |
|---|---|
| tag | id PK；name TEXT UNIQUE NOT NULL；color TEXT |
| project_tag | project_id FK CASCADE；tag_id FK CASCADE；PK(project_id, tag_id) |

#### volume

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | — |
| project_id | INTEGER FK CASCADE NOT NULL | 所属项目 |
| title | TEXT NOT NULL | 卷名 |
| summary | TEXT | 卷梗概 |
| order_index | INTEGER NOT NULL DEFAULT 1000 | 默认卷固定 0 |
| is_default | INTEGER DEFAULT 0 | 1=默认卷（隐藏、不可删改、不排序） |
| created_at | DATETIME NOT NULL | — |

索引：`idx_volume_project (project_id, order_index)`

#### chapter

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | — |
| volume_id | INTEGER FK CASCADE NOT NULL | 默认卷兜底 |
| title | TEXT NOT NULL | 允许重复 |
| content | TEXT | 正文 HTML（消毒后入库） |
| content_text | TEXT | 去标签纯文本（wordcount 服务维护） |
| word_count | INTEGER NOT NULL DEFAULT 0 | 缓存 |
| status | TEXT DEFAULT 'draft' | draft/first/final |
| summary / target_word_count | TEXT / INTEGER | 梗概 / 本章目标 |
| order_index | INTEGER NOT NULL DEFAULT 1000 | 排序 |
| version_no | INTEGER NOT NULL DEFAULT 0 | **单调递增** |
| created_at / updated_at | DATETIME NOT NULL | — |

索引：`idx_chapter_volume (volume_id, order_index)`；FTS5 `chapter_fts` external content，**由触发器即时同步**（E-01：external content 不同步则检索结果不可预测）

#### chapter_version

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | — |
| chapter_id | INTEGER FK CASCADE NOT NULL | — |
| version_no | INTEGER NOT NULL | **修订号**：正文保存 +1、手动/里程碑快照再 +1、回滚再 +1（见 §6.3） |
| title | TEXT | 当时标题 |
| content | TEXT NOT NULL | 快照（消毒后） |
| word_count / diff_word_count | INTEGER | 字数 / 增减 |
| change_type | TEXT NOT NULL | auto/manual/milestone/restore |
| created_at | DATETIME NOT NULL | — |

索引：`idx_version_chapter (chapter_id, created_at DESC)`；唯一 `(chapter_id, version_no)`

> **E-03**：`chapter_version` / `document_version` 是不可变快照，**不设 `is_deleted` / `deleted_at`**；
> 删除状态一律依附父资源（阶段二 L-05 结论）。

#### document / document_version

- `document`：id PK；project_id FK CASCADE；title NOT NULL；content/content_text（消毒）；category（world/timeline/faction/glossary/other）；order_index；word_count（不计入全书）；时间戳；软删除
- `document_version`：与 chapter_version 对齐；表 V1 建，功能 V1.1

#### app_meta（key 集中枚举）

| key | 类型 | 维护者 | 说明 |
|---|---|---|---|
| `schema_version` | INTEGER | migrate.py | 库结构版本 |
| `app_version` | TEXT | 启动流程 | 上次运行的应用版本 |
| `last_backup_date` | TEXT(本地日期) | backup_service | 每日备份判定 |
| `last_integrity_check_date` | TEXT | 启动流程 | 每周完整性检查判定 |
| `last_cleanup_date` | TEXT | 清理任务 | 回收站/过期备份判定 |
| `last_snapshot_daily_date` | TEXT | version_service | 每日首条快照保留判定 |
| `ai_provider` | TEXT | 设置页（V3） | 选中的 Provider |

### 5.3 版本快照策略（分级）

| 类型 | 触发条件 | 保留规则 |
|---|---|---|
| auto | ≥5 分钟 **且** 字数变化 ≥200 字 | 最近 30 条；每日首条额外保留 30 天 |
| manual | Ctrl+S / "存档" | 永久 |
| milestone | 标记定稿、卷/书完结 | 永久 |
| restore | 回滚前自动建 | 永久 |

- 快照失败为非致命错误，延迟重试；正文保存始终是主路径
- 每日首条判定依赖 `last_snapshot_daily_date`，时间回拨时跳过清理（BR-8）
- 连续写作 1 小时 → 约 12 条 auto 快照，保留 30 条可回溯约 2.5 小时，满足 AC-5 的 60 分钟要求

### 5.4 数据库运维

| 项 | 做法 |
|---|---|
| 并发 | WAL + `busy_timeout=5000`，写串行化 |
| WAL 维护 | 后台 `wal_checkpoint(TRUNCATE)`（**假设：每 5 分钟或 ≥32MB**）；备份前强制 checkpoint |
| 完整性 | 启动 quick_check；完整检查每周一次或异常时（后台） |
| 索引维护 | FTS **触发器即时同步**（E-01 修订）；损坏用「重建全文索引」（#42）修复；批量导入的去抖优化留 V1.1 |
| 备份 | `Connection.backup()` 在线热备 + 原子写入 |
| 迁移 | 迁移前原子备份；单调递增顺序；不支持降级；附 fixture 测试（NFR-M5） |
| 清理 | 后台：过期备份、回收站 >30 天、孤儿媒体；时间回拨跳过 |
| 日志 | 按天轮转，总量 ≤50MB（**假设阈值**），超出删最老（NFR-M6） |

---

## 六、接口设计

### 6.1 接口约定

| 项 | 约定 |
|---|---|
| 基址 | `http://127.0.0.1:<随机端口>/api` |
| 业务接口鉴权 | 头 `X-Inkwell-Token`，经窗口对象注入，不入 URL（NFR-S2） |
| 静态资源鉴权 | `GET /files/{relpath}?sig=<签名>`（ADR-009 / NFR-S8） |
| Host 校验 | 仅 `127.0.0.1` / `localhost`（NFR-S5） |
| **普通接口超时** | 10s（**假设**）；前端超时须明确提示，不静默挂起 |
| **长任务接口超时** | 120s（**假设**）：#32 备份、#34 恢复、#35 导出、#38 导入、#42 重建索引、#43 重算字数 |
| 统一响应 | `{ "code":0, "message":"ok", "data":{...} }` |
| 字段级错误 | `data.errors: [{"field":"title","reason":"不能为空"}]` |
| 分页 | `?page=1&page_size=50` |
| 时间格式 | ISO 8601（UTC，带 `Z`） |
| 大列表接口 | 章节树 / 章节列表仅返回元数据 |
| 日志 | 只记方法 / 路径（去 query 中签名）/ 耗时 / 状态码，禁止正文与凭据（NFR-M4） |
| **长任务提交契约** | 长任务接口**不再同步阻塞**，立即返回 `{tid, type}`；前端每 **500ms** 轮询 `GET /tasks/{tid}`，成功读 `result` 后 `DELETE` 清理；**同时只允许一个长任务**，冲突返回 **HTTP 409 + code 3004** |

**错误码**：0 成功；1001 参数校验失败；1002 token 无效；2001 资源不存在；2002 资源已删除；3001 数据库错误；3002 版本冲突；3003 迁移/版本不兼容；**3004 已有长任务进行中（HTTP 409）**；4001 文件写入失败；4002 文件格式/大小不合法；4003 路径非法；4004 签名无效或过期；5001 AI 服务不可用。

### 6.2 接口清单

| # | 方法 | 路径 | 说明 | 优先级 | 版本 |
|---|---|---|---|---|---|
| 1 | GET | `/system/health` | 健康检查 | Must | V1.0 |
| 2 | GET | `/system/meta` | 版本、数据目录、端口、最近项目 | Must | V1.0 |
| 3 | GET | `/projects` | 项目列表 | Must | V1.0 |
| 4 | POST | `/projects` | 新建项目（自动建默认卷） | Must | V1.0 |
| 5 | GET | `/projects/{pid}` | 项目详情 | Must | V1.0 |
| 6 | PATCH | `/projects/{pid}` | 改信息与状态 | Must | V1.0 |
| 7 | DELETE | `/projects/{pid}` | 软删除（级联） | Must | V1.0 |
| 8 | POST | `/projects/{pid}/cover` | 上传/换封面 | Must | V1.0 |
| 9 | GET | `/projects/{pid}/stats` | 项目统计 | Must | V1.0 |
| 10 | GET | `/projects/{pid}/volumes` | 卷列表 + 章节树（仅元数据；默认卷隐藏） | Must | V1.0 |
| 11 | POST | `/projects/{pid}/volumes` | 新建卷 | Must | V1.0 |
| 12 | PATCH | `/volumes/{vid}` | 改卷名/梗概（默认卷拒绝） | Must | V1.0 |
| 13 | DELETE | `/volumes/{vid}?mode=move\|cascade` | 删卷；非空卷缺 mode 返回 1001 | Must | V1.0 |
| 14 | POST | `/projects/{pid}/volumes/reorder` | 卷排序 | Must | V1.0 |
| 15 | POST | `/volumes/{vid}/merge-into/{target_vid}` | 合并卷 | Could | V1.1 |
| 16 | GET | `/volumes/{vid}/chapters` | 章节列表（仅元数据） | Must | V1.0 |
| 17 | POST | `/volumes/{vid}/chapters` | 新建章节 | Must | V1.0 |
| 18 | GET | `/chapters/{cid}` | 章节详情 | Must | V1.0 |
| 19 | PATCH | `/chapters/{cid}` | 改标题/状态/梗概 | Should | V1.0 |
| 20 | PUT | `/chapters/{cid}/content` | 正文保存（消毒 + 乐观锁） | Must | V1.0 |
| 21 | DELETE | `/chapters/{cid}` | 软删除章节 | Must | V1.0 |
| 22 | POST | `/volumes/{vid}/chapters/reorder` | 章节排序 / 跨卷移动 | Must | V1.0 |
| 23 | GET | `/chapters/{cid}/versions` | 版本列表 | Must | V1.0 |
| 24 | GET | `/versions/{vid}` | 版本详情 | Must | V1.0 |
| 25 | POST | `/chapters/{cid}/versions` | 手动快照 | Must | V1.0 |
| 26 | POST | `/chapters/{cid}/versions/{vid}/restore` | 回滚（版本号递增） | Must | V1.0 |
| 27 | DELETE | `/versions/{vid}` | 删快照 | Should | V1.0 |
| 28 | GET | `/projects/{pid}/documents` | 文档列表 | Must | V1.0 |
| 29 | POST | `/projects/{pid}/documents` | 新建文档 | Must | V1.0 |
| 30 | GET/PATCH/DELETE | `/documents/{did}` | 文档 CRUD | Must | V1.0 |
| 31 | GET | `/search` | 全文检索（转义） | Must | V1.0 |
| 32 | POST | `/backup` | 立即备份【长任务】 | Must | V1.0 |
| 33 | GET | `/backups` | 备份列表（忽略 .tmp） | Must | V1.0 |
| 34 | POST | `/backups/{name}/restore` | 恢复（先校验）【长任务】 | Must | V1.0 |
| 35 | POST | `/projects/{pid}/export` | 导出 txt/md【长任务】 | Must | V1.0 |
| 36 | GET | `/files/{relpath}?sig=` | 静态资源 | Must | V1.0 |
| 37 | POST | `/files/sign` | 签发/续签签名 | Must | V1.0 |
| 38 | POST | `/projects/{pid}/import` | 导入（编码探测）【长任务】 | Could | V1.1 |
| 39 | GET | `/trash` | 回收站 | Must | V1.0 |
| 40 | POST | `/trash/{type}/{id}/restore` | 恢复（父链校验） | Must | V1.0 |
| 41 | DELETE | `/trash/empty` | 清空 | Must | V1.0 |
| 42 | POST | `/maintenance/rebuild-fts` | 重建索引【长任务】 | Should | V1.0 |
| 43 | POST | `/maintenance/rebuild-wordcount` | 重算字数【长任务】 | Should | V1.0 |
| 44 | POST | `/system/logs` | 前端异常/超时上报 | Should | V1.0 |
| 45 | GET / DELETE | `/tasks/{tid}` | 长任务状态查询 / 清理 | Should | V1.0 |
| 46 | POST | `/chapters/{cid}/images` | 章节正文图片上传（返回相对路径 + 签名 URL） | Must | V1.0 |
| 47 | POST / GET / DELETE | `/drafts`、`/drafts/{cid}` | 服务端暂存（保存失败 / 冲突兜底） | Must | V1.0 |
| 48 | POST | `/documents/{did}/images` | 设定文档图片上传（落 `media/documents/{did}/`） | Must | V1.0 |
| 49 | GET | `/system/diagnostics` | 诊断包下载（日志 + 库结构摘要，不含正文） | Should | V1.0 |
| 50 | POST | `/chapters/{cid}/export` | 导出单章 TXT/MD（失败态「导出本章」，C-03） | Must | **待实现（3.5）** |
| 51 | POST | `/maintenance/cleanup-snapshots` | 清理过期自动快照（P9） | Should | **待实现（3.6）** |
| 52 | GET | `/system/integrity` | 数据库自检（P9） | Should | **待实现（3.6）** |
| 53 | POST | `/volumes/{vid}/adopt-default` | 首个命名卷创建后迁入默认卷章节（C-04） | Should | V1.0（3.2 已实现） |
| 3 增补 | GET | `/projects/{pid}` | **行为增补**：详情即「打开项目」事件，写入 `last_opened_at`；**不触碰 `updated_at`** | Must | V1.0（3.3） |
| 47 增补 | GET | `/drafts` | **字段增补**：列表项新增 `project_id` / `project_title`（章节→卷→项目，任一环节软删则不填） | Must | V1.0（3.3） |

### 6.3 关键接口说明

**PUT `/api/chapters/{cid}/content`**
请求 `{ content_html, client_saved_at, expect_version }` → 响应 `{ word_count, project_word_count, saved_at, snapshot_created, snapshot_version_no }`
- `expect_version` 不匹配 → **3002**，前端**先落暂存再提示刷新**
- `project_word_count` 为异步值，**最终一致**（秒级）

**POST `/api/chapters/{cid}/versions/{vid}/restore`**
事务内：当前正文存为 `restore` 永久快照 → 覆盖正文（重新消毒 + 重算）→ `version_no` **递增** → 返回新版本。UI："由 #13 回滚至 #7，生成 #14"。

**`GET /api/files/{relpath}?sig=`**
校验顺序（**阶段二实施修订**）：Host → **路径规范化并落在 `covers/` 或 `media/`** → **签名有效/未过期** → 文件存在。
失败码：路径非法 **4003**、签名无效/过期 **4004**、文件不存在 **2001**（前端降级占位符）。
> 原顺序「签名在路径前」会让 `/files/../../inkwell.db` 先报 4004，与回归 13 要求的 4003 冲突。

**`POST /api/trash/{type}/{id}/restore`**
父资源在回收站时**不报错**：返回 `HTTP 200 + code 0 + data.requires_parent=true` 与 `parent{type,id,title}`；
前端确认后带 `?with_parent=true` 重试；恢复父资源只恢复**同批次**（`deleted_at` 相同）的级联子项。

**`POST /api/projects/{pid}/export`（#35）**
只导出正文（不含设定文档）；输出 `exports/{安全书名}_{时间戳}.{txt|md}`；空项目 TXT 仍输出书名 / 简介 /
「（暂无正文）」，MD 输出 `## 目录` +「（暂无章节）」。**#50 单章导出**沿用同一写入器（3.5 实现）。

**`GET /api/search`（#31）**
≥3 字符走 FTS5 trigram；<3 字符降级 LIKE，并在 `hint` 说明「模糊匹配」；章节与设定文档分两次查后合并；
摘要由服务端生成并 HTML 转义（仅 `<mark>` 受信）。响应新增 **`fuzzy`**（是否降级 LIKE）与
**`page_limited`**（分页窗口是否被单侧上限截断）；分页窗口 = `page*page_size`，单侧上限 **1000**。

**备份 / 恢复（#32~#34）**
手动 `inkwell_backup_*`、每日 `inkwell_daily_*`（保留 7 日 + 4 周）；迁移前 / 恢复前的备份不自动删；
恢复前先校验（损坏 3001、版本过高 3003、非法名 4003），并先做 prerestore 备份。

**日志上报（#44）**
`logs/inkwell-YYYY-MM-DD.log`，单文件 10MB 切分、总量 50MB 删最老；`token` / `sig` / `signature` 脱敏；
请求日志只记方法 / 路径（去 query）/ 状态码 / 耗时。**正文兜底**：`message` 去 HTML 标签后截 300 字
（尾部 `…[已截断]`），`content_html` / `content` / `text` 等正文字段整值替换为 `[正文已省略]`，
`context` 每个值 ≤120 字；前端 `logger.js` 只替换密钥值（保留路径与错误码）。

**`POST /api/volumes/{vid}/adopt-default`（#53）**
仅当目标卷是该项目**唯一命名卷**时，把默认卷章节按原顺序一次性迁入（复用追加排序）；
前端在「创建首个命名卷」并二次确认后调用（C-04 / BR-6）。

---

## 七、UI/UX 设计方向

### 7.1 设计原则

专注写作优先 · 克制 · 可预期 · 安静浅色（WCAG AA）

### 7.2 视觉规范

| Token | 值 |
|---|---|
| `--bg` / `--panel` / `--sidebar` | `#FAF9F7` / `#FFFFFF` / `#F3F1ED` |
| `--text` / `--text-2` | `#2B2B2B` / `#6B6B6B` |
| `--border` | `#E5E2DC` |
| `--accent` / `--accent-soft` | `#7A6A58` / `#F0EBE3` |
| `--accent-strong`（派生） | `#6B5B49`：主按钮悬停，白字 6.53:1 |
| `--danger` / `--danger-soft` | **`#B84F36`** / `#FBEEE9`（原 `#C0563C` 在 `--bg` 上仅 4.30:1，按 AA 调深） |
| `--success` / `--success-soft` | `#4F7A5B` / `#EDF3EE` |
| 字体 | 思源黑体 / 苹方 / 微软雅黑；西文 Inter。栈内补入**实际家族名**（`Source Han Sans CN` / `Noto Sans CJK SC`），装了才生效，不引 Web 字体 |
| 字号 | 界面 14px；编辑器正文 **17px / 行高 1.9 / 行宽 ≤760px 居中** |
| 中文排版 | 首行缩进 **2 字符**（2em = 34px）；标题 / 列表 / 引用 / 代码块**不缩进**；段间距 0（靠缩进断段） |
| 选中与光标 | `::selection` = `--accent` 24% 叠加；`caret-color: --accent-strong` |
| 圆角 / 间距 | 6px / 10px；4/8/12/16/24（小控件与标签用 4px / 胶囊） |
| **窗口尺寸** | **默认 1280×800，最小 1024×640（假设值）** |

> **AA 实测（3.1）**：`--text` 13.46:1、`--text-2` 5.06:1、`--accent` 4.95:1、`--success` 4.68:1 均达 AA；
> `--danger` 调深后 4.74:1（`--panel` 上 4.99:1）。**禁用组合**：`--accent` / `--text-2` 写在 `--accent-soft`
> 上仅 4.39 / 4.49:1，因此浅底胶囊（徽标、状态提示）上的文字统一用 `--text`。
>
> **排版复核（3.4）**：正文 17px / 32.3px / 760px；`p` 缩进 34px；标题、引用、列表、代码块缩进 0；
> `spellcheck=false`；三段中英混排 / emoji 行高均为 32.296875px（不跳动）；空文档占位与首行正文同列。

### 7.3 页面清单

| # | 页面 | 要点 |
|---|---|---|
| P1 | 项目列表页 | 卡片：封面（缺失→默认图标）+ 书名 + 简介 + 状态 + 进度条 + 新建 |
| P2 | 项目写作页 | 大纲树（默认卷隐藏）+ 编辑器 + 状态栏 |
| P3 | 设定文档页 | 分类分组 + 编辑器 |
| P4 | 项目设置页 | 基础信息、封面、标签、目标字数、危险操作区 |
| P5 | 版本历史弹窗 | 版本列表 + 差异 + 预览 + 恢复 |
| P6 | 全局搜索页 | 高亮上下文 + 跳转 |
| P7 | 备份与导出页 | 备份列表、立即备份、恢复（含校验结果）、导出、磁盘余量 |
| P8 | 回收站页 | 恢复（父链缺失按 BR-4 提示）/彻底删除 + 30 天倒计时 |
| P9 | 应用设置页 | 字数口径、快照清理、修复工具、打开数据目录、导出诊断包 |

> **状态（v0.6）**：P1~P8 已在阶段二/三落地；**P9 待建（3.6）**。
> 图 3 中「状态栏三态」尚待 3.5 落地（当前保存状态显示在写作页头部右侧文本，无颜色 / 图标 / 重试动作）。

**图 3　写作页布局草图**

```
┌──────────────────────────────────────────────────────────┐
│  📖 Inkwell            [🔍 搜索]        [⚙ 设置]  [— □ ✕] │
├────────────┬─────────────────────────────────────────────┤
│ 📚 项目 ▾   │            章节编辑器（Quill）             │
│ 📝 大纲     │        行宽 760px 居中，首行缩进 2 字符      │
│ 📋 设定     │                                            │
├────────────┴─────────────────────────────────────────────┤
│ 本章 3,287 字 │ 全书 128,456 │ ✓ 已保存 23:45 │ 版本 #13 │
└──────────────────────────────────────────────────────────┘
```

### 7.4 交互细节

- **状态栏三态**：`保存中…`（灰）→ `✓ 已保存 HH:MM`（绿）→ `保存失败，已本地暂存`（红，附「重试 / 导出本章」，导出走 #50）；3002 冲突态**先落暂存再提示刷新**；`aria-live="polite"`，颜色 + 图标 + 文案三重编码（**3.5 待做**）
- **单章容量提示（FR-3.9 / NFR-U4）**：状态栏胶囊；≥5 万字（承诺范围）→「已超 5 万字建议上限」，≥8 万字 →「建议拆章（不影响保存）」；**只提示不阻断**（不弹窗、不禁用、不拦截保存），描边色区分档位、文字统一 `--text`
- **大纲树**：卷折叠/展开（按项目记忆）、右键菜单（重命名 / 删除 / 新建章 / 标记定稿 / 章节信息）、拖拽排序（卷内 + 跨卷 + 卷排序）、键盘（↑↓ 选章、←→ 折叠、Enter 打开、F2 重命名、Delete 删除）；**「合并卷」V1.1 不做**（C-08）；默认卷不出现在菜单
- **默认卷**：大纲树隐藏；创建首个命名卷时若默认卷已有章节，二次确认后一次性迁入（#53）
- **首屏三态**：项目列表「骨架 → 卡片 / 空态 / 出错态」；空态给主 CTA「新建第一本书」；首启引导为「新建项目 → 自动建第一章 → 直达写作页 → 聚焦正文」（C-09；聚焦必须等章节加载完成，见 `阶段三_IME验证记录.md` §二）
- **设定文档**：列表每行「打开 + ✕ 删除」；删除为软删除（回收站 30 天可恢复），删除当前文档后自动切到剩余第一篇，全删回空态
- **对话框取消**：取消按钮一律 `type="button" data-dialog-cancel`，由统一委托 `dialog.close()`；**不得把取消做成 submit**（必填校验会吞掉点击，`method="dialog"` 的原生关闭又会被 submit 回调里的 `preventDefault` 拦掉）
- **编辑器**：粘贴自动清理样式（服务端另有消毒兜底）；图片缺失显示占位符；代码块保存前序列化为 `<pre><code>`（否则重开丢格式）；IME 组合期间隐藏空文档占位
- **破坏性操作**：一律二次确认，文案说明可恢复期限与「未保存修改会丢弃」（NFR-U3）

### 7.5 快捷键

Ctrl+N 新建章节 · Ctrl+S 手动快照 · Ctrl+F 章内查找 · Ctrl+Shift+F 全局搜索 · Ctrl+Shift+V 版本历史 · Ctrl+Shift+E 导出 · F11 专注模式(V1.1) · Ctrl+B/I 加粗/斜体

> **统一门禁（S3-03）**：全局快捷键在 `event.isComposing === true` 或 `keyCode === 229`（IME 组合中）
> **直接放行** —— 不 `preventDefault`、不触发动作；输入框与对话框内不触发（Ctrl+S 除外）；Ctrl+B/I 交给 Quill。
> 输入法真机复核仍按 V-02 人工走查。

---

## 八、质量保障与工程规范

### 8.1 测试策略

| 层级 | 范围 | 目标 |
|---|---|---|
| 单元测试 | services 全部：字数/快照/排序/备份恢复/消毒/FTS 转义/签名签发校验/默认卷规则 | 覆盖 ≥60% |
| 接口测试 | TestClient 覆盖主路径与错误码（含 4003/4004） | 主路径 100% |
| 迁移测试 | 每迁移脚本配旧库 fixture | 覆盖已发布版本 100% |
| 纯函数单测（前端） | `tests/js/*.test.js`（Node 内置 runner）：自动保存时序、暂存兜底、展示格式化、容量判定 | 与 pytest 同一入口执行 |
| 窗口冒烟（e2e） | `tests/e2e/window_smoke.py`：真实 pywebview 窗口驱动页面，断言 UI 并回查 HTTP 侧 | 关键链路每次改动必跑 |
| 视觉基线（e2e） | `tests/e2e/capture_ui.py --label <批次>`：11 张页面截图 + manifest，用于前后像素对照 | 每个 UI 任务完成时重截 |
| 手工回归 | 28 项清单 | 发布前全绿 |

**发布前回归清单（28 项）**

1. 冷启动 ≤3s（AC-2）
2. 写作中 `taskkill /F`，丢失 ≤30 秒输入（AC-4）
3. 写作 1 小时后可回溯到 60 分钟前节点（AC-5）
4. 新建 → 写作 → 删除 → 回收站恢复 → 数据完整（AC-11）
5. 800 章规模下列表与切换不卡（AC-1）
6. 破坏数据库 → 从备份恢复成功（AC-9）
7. 导出 TXT/MD 字数误差 ≤0.5%（AC-6）
8. 中文/带空格路径读写正常（NFR-C3）
9. 无 WebView2 时给出正确引导（NFR-C2）
10. 重复双击不启动第二实例（NFR-S3）
11. schema 迁移：迁移前自动备份；注入失败迁移验证回滚（NFR-R5）
12. 删除非空卷：二选一确认，两种路径数据均正确（FR-2.1）
13. `/files/../../inkwell.db` 穿越被拒 4003（NFR-S7）
14. 粘贴 `<script>` 保存后重新打开已清除（NFR-S6）
15. 模拟保存失败：3 次重试后进入暂存，恢复后自动补写（NFR-R6）
16. 损坏的备份执行恢复被拒绝并给出原因（NFR-R7）
17. 系统时间回拨 7 天后启动，自动清理被跳过并提示（BR-8）
18. 无签名 / 签名过期请求 `/files/` 被拒 4004（ADR-009）
19. 导出中强杀不留半截文件（BR-7）
20. 打开 8 万字超长章节给出拆分提示且不崩溃（FR-3.9）
21. 大纲树拖拽排序（卷内 / 跨卷）后顺序、字数、默认卷迁移正确（FR-2.2 / BR-3）
22. 章节右键菜单：重命名、删除进回收站、标记定稿（生成 milestone 快照）、章节信息保存（FR-2.3 / FR-5.6）
23. 状态栏三态：保存中 → 已保存 → 模拟失败 → 重试恢复；冲突 3002 提示刷新（BR-2）
24. 快捷键：Ctrl+N/S/F、Ctrl+Shift+F/V/E 全部生效，输入框与 IME 下不误触（§7.5）
25. 章内查找：中英 / emoji 匹配、上下切换、Esc 关闭、正文不变
26. 搜索分页：120 条命中可翻到第 6 页；`page_limited` 有提示（FR-7.4）
27. P9：重建字数 / 索引、快照清理、数据库自检、打开数据目录、诊断包
28. 无障碍：全键盘走查、焦点可见、对比度 ≥4.5:1、对话框焦点陷阱（NFR-U2）

> **执行状态（v0.6）**：20 已自动化（窗口冒烟 54 步内含 8 万字拆章提示）；21/22 由 3.2 端到端驱动验证；
> 23~28 随 3.5~3.9 落地；28 的对比度部分已有自动化实测（§7.2 AA 实测）。
> 真机验收发现并修复的 B1 / B2 / B3 / B5 断言已并入窗口冒烟（38 → 54 步），不单列回归号。

### 8.2 日志与诊断

- 目录 `logs/`，按天轮转，总量 ≤50MB（假设阈值）
- 级别：INFO / WARNING / ERROR
- **脱敏**：禁记 token、签名、认证头、正文
- 前端全局异常与请求超时经 `#44` 上报
- 诊断包：日志 + 库结构摘要，不含正文 / token / 签名（#49）
- **#44 正文兜底**：`message` 去 HTML 标签后截 300 字（尾部 `…[已截断]`）；`content_html` / `content` / `text`
  等正文字段整值替换为 `[正文已省略]`；`context` 每个值 ≤120 字；前端 `logger.js` 只替换密钥值（保留路径与错误码）

### 8.3 工程规范

| 项 | 规范 |
|---|---|
| 分支 | `main` / `develop` / `feature/*` |
| 提交 | Conventional Commits |
| 风格 | Python: ruff + black；JS: 以 `node --check` + 仓库既有风格为准（未引入格式化工具链，避免新增构建依赖） |
| 前端构建 | **不引入构建步骤**：原生 ES Module + 本地化 vendor（Quill 离线副本） |
| 前端测试 | 纯函数进 `tests/js/`（node --test，随 pytest 入口执行）；窗口级交互进 `tests/e2e/window_smoke.py` |
| 依赖 | `requirements.txt` + `requirements.lock`（含 hash） |
| 许可证 | 待 D-02（建议 MIT / Apache-2.0） |
| 开源配套 | README（AC-8）、CONTRIBUTING、CHANGELOG、Issue/PR 模板 |
| 生产构建 | `debug=False`、禁 DevTools / 右键菜单 |

### 8.4 Definition of Done（任务级完成标准）

一个任务只有在以下**全部满足**时才算完成：

1. **功能实现**：满足对应 FR 条目与 BR 规则，含成功路径与失败路径
2. **测试**：相关 services 单测通过；涉接口的补 TestClient 用例（含错误码）
3. **接口同步**：涉及接口的同步更新 §6.2 清单与 §6.3 示例
4. **回归项**：新增/更新的回归项写入 §8.1 清单，并实际执行通过
5. **可观测**：关键路径有日志（且不违反 NFR-M4 脱敏）；错误码表同步
6. **文档**：CHANGELOG 记录；README / 本报告相关章节同步

> 任一条不满足，任务不得标记为完成。

---

## 九、开发计划与里程碑

> 粗略估算（单人全职、Python 背景、含自测），阶段一结束后校准。

### 阶段一：项目骨架（3.5~4.5 人日）

| # | 任务 | 估算 | 产出物 | 验收标准 |
|---|---|---|---|---|
| 1.1 | 关闭决策项 | 0.5 | 决策记录 | D-01~D-13 有明确结论 |
| 1.2 | 目录结构与依赖 | 0.5 | 目录、`requirements.txt`/`.lock` | `pip install -r requirements.lock` 成功 |
| 1.3 | FastAPI + `/health` + token/Host 校验 + 签名签发 | 1.5 | `server.py`/`config.py`/`storage.py` | 无 token 请求被拒；签名可签发校验 |
| 1.4 | pywebview 窗口 + token 注入 + 禁调试 | 1 | `main.py` | 窗口正常；生产 F12 不可用 |
| 1.5 | SQLite 初始化 + WAL/checkpoint + 迁移骨架 | 1 | `database.py`/`migrate.py` | 表建成、`schema_version` 写入、迁移前产生备份 |

**关键技术决策**：ADR-001/002/003/007/009 落地；uvicorn 在子线程启动（需实测确认不注册 signal handler）。
**验证方式**：`python main.py` 窗口打开显示前端页面；`/api/system/health` 返回 200（E-02 修订）；无 token 请求返回 1002。

### 阶段二：核心功能（17~22 人日；实施中补 2.12 / 2.13，实际约 19~24 人日）

| # | 任务 | 估算 | 产出物 | 验收标准 |
|---|---|---|---|---|
| 2.1 | 项目 CRUD + 封面 + 标签 | 2 | `api/projects.py`、`project_service.py`、页面 P1/P4 | FR-1.1~1.4 全通过 |
| 2.2 | 卷章 CRUD + 排序 + 默认卷 + 非空卷删除 + 合并卷 | 3 | `api/volumes.py`/`chapters.py`、大纲树 | FR-2.1~2.2、BR-3、BR-6；回归 12 |
| 2.3 | Quill + 图片插入 + `/files/` 签名 + 消毒 + 缺失降级 | 3 | `editor.js`、`api/files.py`、`sanitize.py` | FR-3.1~3.4/3.9/3.10；回归 13/14/18 |
| 2.4 | 自动保存 + 失败/冲突暂存兜底 + 异常退出恢复提示 | 2.5 | `autosave.py`、`pending.js` | AC-4；回归 15 |
| 2.5 | 字数统计 + 重算工具 | 1 | `wordcount.py`、设置页 | 误差 ≤0.5% |
| 2.6 | 分级快照 + 回滚（版本号递增） | 2.5 | `version_service.py`、页面 P5 | AC-5；BR-9 |
| 2.7 | 设定文档 CRUD | 1.5 | `api/documents.py`、页面 P3 | FR-4.1~4.4 |
| 2.8 | 软删除 + 回收站 + 父链恢复 | 1.5 | `api/trash.py`、页面 P8 | AC-11 |
| 2.9 | 备份与恢复（原子 + 校验 + 运行时流程） | 2 | `backup_service.py`、页面 P7 | AC-9；回归 6/16/19 |
| 2.10 | 导出 TXT/MD（原子 + 空项目） | 1 | `export_service.py` | AC-6；回归 19 |
| 2.11 | 全文检索（external content + 触发器同步 + 转义） | 2 | `search_service.py`、页面 P6 | AC-10；NFR-P5 |
| 2.12 | 长任务框架（tid + 500ms 轮询 + 并发 409/3004） | 1 | `api/tasks.py`、`tasks.js` | 备份 / 导出 / 重建不阻塞 UI |
| 2.13 | 日志与诊断（轮转 + 脱敏 + 诊断包） | 1 | `logging_service.py`、`#44` / `#49` | NFR-M4 / NFR-M6 |

### 阶段三：UI 与体验（**12~14 人日**；原估算 6~9 人日，细项与验收见 `docs/任务清单/阶段三任务清单.md`）

| # | 任务 | 估算 | 状态 | 验收标准 |
|---|---|---|---|---|
| 3.0 | 走查基线与视觉对照（截图 + 差异清单） | 0.5 | ✅ 2026-10-23 | P1~P9 截图 + 基线文档 |
| 3.1 | Design Token 与全局样式 | 1 | ✅ 2026-10-23 | 无硬编码色；AA；焦点可见 |
| 3.2 | 侧边栏 + 大纲树（折叠 / 右键 / 拖拽 / 键盘 / #53） | 2.5 | ✅ 2026-10-24 | FR-2.1~2.5、BR-3/6、回归 21/22 |
| 3.3 | 项目卡片与首启引导（C-09） | 1 | ✅ 2026-10-24 | NFR-U1、FR-1.3 / 1.8 |
| 3.4 | 编辑器排版与中文适配 | 1 | ✅ 2026-10-24 | §7.2 逐项；FR-3.9 提示不阻断 |
| 3.5 | 状态栏三态 + 暂存提示（含 #50 导出本章） | 1.5 | ⬜ 下一步 | BR-2；回归 23 |
| 3.6 | P5 差异对比 + P6 分页 + P9 设置页 + P7/P8 打磨（含 #51 / #52） | 3 | ⬜ | 回归 26 / 27 |
| 3.7 | 快捷键注册表 | 0.75 | ⬜ | §7.5；回归 24 |
| 3.8 | 章内查找（Ctrl+F） | 0.75 | ⬜ | 回归 25 |
| 3.9 | 交互回归与无障碍验收 | 1 | ⬜ | 回归 21~28 全绿；验收单 |

> **阶段三遗留（v0.6 登记）**：
> ① **B4**：库文件丢失时静默新建空库、未提示「有备份可恢复」——待补首屏引导（见 §4.5 第 5 步）；
> ② 真实输入法（V-02 / V-03）与 AC-4 / AC-5 / AC-9 / AC-10、回归 17/19 仍为人工走查项；
> ③ 代码块「保存 → 重开」丢格式已在真机验收修复中解决（D-3.4-1 关闭）。

### 阶段四：打包与发布（4.5~6.5 人日）

| # | 任务 | 估算 | 产出物 | 验收标准 |
|---|---|---|---|---|
| 4.1 | PyInstaller onedir 打包 | 2 | `build.spec`、dist 目录 | 干净机器可运行 |
| 4.2 | 单实例锁 + 随机端口 + token + 禁调试 | 1 | `main.py` | 回归 10 |
| 4.3 | WebView2 检测与引导 | 0.5 | 引导页 | 回归 9 |
| 4.4 | 性能实测与调优 | 1.5 | 实测报告 | AC-1~AC-3、AC-10，回填 §3.2 / §12.1 |
| 4.5 | README / CHANGELOG / 仓库初始化 | 1 | 文档与仓库 | AC-8 |

**合计：约 37~47 人日**（v0.5 原估 31~42 人日；阶段二实施中补了 2.12 / 2.13，阶段三由 6~9 重估为 12~14）。
关键路径：2.2 → 2.4 → 2.6 → 3.2 → 4.1。

---

## 十、风险登记册

| ID | 风险 | 概率 | 影响 | 应对 |
|---|---|---|---|---|
| R-1 | 打包后前端资源/Quill 丢失 | 中 | 高 | `importlib.resources` 解析 + 干净机器验证 |
| R-2 | 冷启动超时 | 中 | 中 | onedir；并行启动；自检降频；清理异步；迁移归例外（AC-2b） |
| R-3 | 端口占用 / 被安全软件拦截 | 中 | 中 | 随机端口 + 仅绑 127.0.0.1；降级只读 |
| R-4 | SQLite 损坏导致全稿丢失 | 低 | **极高** | WAL + 每日备份 + 自检 + 迁移前备份 + 导出 + 暂存兜底 |
| R-5 | 快照撑爆磁盘 | 中 | 中 | 分级快照 + 清理入口 + 磁盘预警 |
| R-6 | Quill 在 WebView2 下兼容问题（输入法/粘贴） | 中 | 中 | 早期专项验证；锁定版本 |
| R-7 | 需求蔓延 | **高** | 高 | 严格按 §1.5，走变更评审 |
| R-8 | 缺少 WebView2 Runtime | 中 | 中 | 检测 + 引导；考虑打包 Bootstrapper |
| R-9 | 大章节编辑卡顿 | 中 | 中 | 分块加载；超容量提示；实测调优 |
| R-10 | 工期不可控 | 中 | 高 | ≤3 人日粒度；每阶段重估；收缩 Should/Could |
| R-11 | 存储膨胀超预期 | 中 | 中 | FTS external content + 快照清理 + D-09 压缩 |
| R-12 | 系统时间/时区异常导致清理误判 | 低 | 中 | BR-8 回拨检测 + 跳过清理并提示 |
| R-13 | 签名 token 实现不当 | 中 | 中 | ADR-009 明确方案 + 回归 18 专项 |
| **R-14** | **数据目录位于同步盘（OneDrive）导致 SQLite 被占用/冲突损坏；防病毒或受控文件夹访问拦截写入** | **中** | **极高** | ① 启动检测目录是否在已知同步目录内，是则一次性提示并提供"更换目录"入口；② 支持 `INKWELL_DATA_DIR` 与 portable 模式规避；③ README 声明"应用运行时请勿同步，退出后再同步"；④ 写入失败按 NFR-R10 明确提示而非静默 |
| **R-15** | **长文 + 多图章节的渲染与内存压力** | 中 | 中 | 图片懒加载；超大章节提示拆分；阶段四实测内存与滚动帧率 |
| **R-16** | **依赖供应链与打包不可复现** | 中 | 中 | `requirements.lock` 带 hash（已生成，545 行）；打包机已定为 Windows + Python 3.11.9（Q-04 已确认）；构建脚本统一入口 |
| **R-17** | **本机代理污染本地 HTTP 通信**（实测：`http_proxy`/`https_proxy=127.0.0.1:64530`）。httpx 等遵循环境代理的客户端会把请求行改写为 **absolute-form**（`GET http://127.0.0.1:PORT/api/...`），本地源站无法匹配路由而返回 404；实测中表现为"同一 keep-alive 连接上第二次请求起全部 404" | **高（本机已复现）** | 高 | ① 后端/测试客户端统一 `trust_env=False` 或显式 `proxies=None`；② 应用进程启动时清除本进程的 `HTTP(S)_PROXY` 环境变量，避免 WebView2 继承；③ 服务端增加"请求行必须为 origin-form"校验，absolute-form 直接拒绝（复用 4003）；④ 阶段一实装窗口后必须实测"前端连续请求不 404" |
| **R-18** | **设计基线滞后于实现**（v0.5 停在开发启动，阶段二/三的接口、决策、勘误长期只在过程文档里） | **高（已发生）** | 中 | ① 每阶段收口时同步修订正式报告（v0.6 已执行）；② `DECISIONS.md` 与接口清单作为报告的上游输入，登记即约定「下次修订必并」；③ §8.4 DoD 第 6 条要求文档同步 |
| **R-UI1** | 800 章大纲树全量重绘导致输入卡顿（AC-1） | 中 | 高 | 3.2 已改为保存后增量更新章节字数；阶段四实测后如仍超阈值再上虚拟滚动 |
| **R-UI2** | 拖拽 / 右键菜单与文本选择、编辑器内右键冲突 | 中 | 中 | 仅树节点启用 draggable / contextmenu；编辑区不冒泡（3.2 已验证） |
| **R-UI3** | 新增接口 / 桥接方法遗漏同步到报告与同步清单 | 中 | 中 | #50~#53 已并入 §6.2；后续新增同样先进清单再进报告（R-18 同源） |
| **R-UI4** | 状态栏改造使回归 15 / E2E 文案断言失效 | 高 | 低 | 3.5 同步更新 Node / E2E 断言；容量胶囊随字数刷新，不占保存态文案 |
| **R-UI5** | 首启引导改变「新建项目后停留列表」的既有行为，影响 E2E | 中 | 低 | 3.3 已更新 `window_smoke` 流程（现状 54 步） |
| **R-UI6** | 视觉改动无基线可对照而返工 | 中 | 中 | 3.0 起固定用 `capture_ui.py` 截图与像素对照（含 `after_3_1`~`after_fix` 批次） |
| **R-UI7** | 快捷键与 WebView2 默认键冲突（Ctrl+F / N） | 低 | 中 | C-06 统一 `preventDefault`；IME 组合期间放行（S3-03）；3.7 实测确认 |

> R-17 说明：Windows 系统代理 `ProxyEnable=0` 且 `ProxyOverride` 已含 `<local>;localhost;127.*`，故**浏览器侧大概率不受影响**；但环境变量对进程内 HTTP 客户端是真实的、已复现的故障源，因此按高概率登记。

**本机已排除的风险**：R-8（缺 WebView2 Runtime）—— 已装 155.0.4283.62；R-14（同步盘接管 Documents）—— 实测未被接管。两项仍对**目标用户机器**保留在登记册中。

---

## 十一、待决策与待确认事项

### D 组：待决策（有默认值，不阻塞开发）

> **v0.6 说明**：D-01~D-13 已于阶段一关闭（结论见 `DECISIONS.md` §一，D-12 / D-13 仍为暂定）；
> 阶段二/三实施中新增的 **S2-01~S2-18、S3-01~S3-08** 记录在 `DECISIONS.md` §六 / §七，
> 本报告只在相关章节引用结论（§4.4 / §5.2 / §6.3 / §7.x / §8.1），不逐条复述。

| ID | 决策项 | 默认建议 | 决策时点 |
|---|---|---|---|
| D-01 | 富文本编辑器 | Quill 2.x | 阶段二前 |
| D-02 | 开源许可证 | MIT | 阶段四前 |
| D-03 | 自动保存触发 | 停输 3s 或最长 30s | 阶段二 2.4 |
| D-04 | 快照策略参数 | auto ≥5min 且 ≥200 字，保留 30 条；每日首条 30 天；manual/milestone/restore 永久 | 阶段二 2.6 |
| D-05 | 设定文档版本历史 | 进 V1.1（表 V1 建） | 阶段二 2.7 |
| D-06 | 性能实测口径 | 中位机 i5-10代/8G/SSD，阶段四回填 | 阶段四 |
| D-07 | 首发平台 | 仅 Windows 10/11 x64 | 阶段四前 |
| D-08 | AI 数据策略 | 用户自带 Key，不内置、不默认外发 | V3 前 |
| D-09 | 快照是否压缩 | 默认不压缩 | 阶段二 2.6 |
| D-10 | 静态资源鉴权方案 | 短期签名 query token（ADR-009） | 阶段二 2.3 |
| D-11 | 签名有效期 | 30 分钟（假设） | 阶段二 2.3 |
| D-12 | 版本号规则与发布渠道 | SemVer + GitHub Release（**待确认 Q-03**） | 阶段四前 |
| D-13 | 磁盘不足时是否自动清理最老备份 | 默认只提示，不自动删（**待确认 Q-05**） | 阶段二 2.9 |

### Q 组：待确认（信息不足，我未做任何假设，需你答复）

| ID | 待确认内容 | 为什么无法判断 | 需要你提供 | 影响若不确认 |
|---|---|---|---|---|
#### 已实测确认（无需再答复）

| ID | 原问题 | 实测结论 | 对报告的影响 |
|---|---|---|---|
| **Q-01** ✅ | `Documents` 是否被 OneDrive 接管 | **未被接管**：`C:\Users\Administrator\Documents` 非重解析点，无 OneDrive/Dropbox 目录 | 默认数据目录 `Documents\Inkwell` 可直接用；R-14 的缓解措施（目录更换入口、README 声明）仍对**目标用户**保留 |
| **Q-04** ✅ | 开发与打包的 Python 版本与机器环境 | **Python 3.11.9 @ `E:\Python311`（已装）**；项目 venv @ `D:\小说辅助\.venv`；Windows 多盘（E 盘可用 201.9 GB）；WebView2 Runtime 155.0.4283.62 已装 | 依赖锁与打包脚本可最终固化；R-16 关闭一半；R-8 在本机不成立 |

#### 仍需你答复（信息不足，我未做假设）

| ID | 待确认内容 | 为什么无法判断 | 需要你提供 | 影响若不确认 |
|---|---|---|---|---|
| **Q-02** | V1.0 是否需要自动更新机制？ | 报告默认"不做"，但这是产品决策而非技术推断 | 明确"V1 手动下载更新"还是"需自动检查更新" | 影响阶段四工作量与 README 说明；不确认则按默认"不做"执行 |
| **Q-03** | 版本号规则与发布渠道？ | 无信息可推断（是否发 GitHub Release、是否内网分发） | 指定渠道（GitHub Release / 网盘 / 内部共享）与版本命名规则 | 影响阶段四 4.5 与用户获取方式；不确认则默认 SemVer + GitHub Release |
| **Q-05** | 磁盘不足时，是仅提示还是自动清理最老的自动备份？ | 涉及用户对"自动删除其数据"的接受度，属于偏好而非技术判断 | 明确选择 | 影响 FR-6.7 与 R-5；不确认则按"仅提示"执行 |

---

## 十二、附录

### 12.1 假设与依据

| 假设 | 类型 | 说明 |
|---|---|---|
| 单项目规模 ≤20 卷 / ≤2000 章 / 单章 ≤5 万字 / 全书 ≤500 万字 | 行业经验 | 覆盖绝大多数中文长篇 |
| 打包体积 35~60MB、冷启动 2~3s、常驻内存 180~300MB | **经验预估·未实测** | 阶段四回填 |
| 全库磁盘占用约 6~10GB | **推算·待实测** | 100 万汉字≈3MB；HTML +40%；FTS external content 只存索引；auto 快照为主占用 |
| 完整性检查每周一次 | **假设** | 可配置 |
| 导出 500 万字 ≤60s | **假设·待实测** | 阶段四回填 |
| 前端超时 10s / 长任务 120s | **假设** | 可按实测调整 |
| WAL checkpoint 每 5 分钟或 ≥32MB | **假设** | 阶段二调优后固化；**FTS 去抖假设已作废**（E-01 改为触发器即时同步） |
| 签名有效期 30 分钟 | **假设** | D-11 |
| 磁盘预警阈值 1GB、日志总量 ≤50MB | **假设** | 可按实测调整 |
| 窗口默认 1280×800、最小 1024×640 | **假设** | 可按屏幕调整 |
| 内测作者 5 人可招募 | 假设 | 不足则 AC-7 降至 3 人并注明 |

### 12.2 参考资料

- pywebview 官方文档（窗口创建、`js_api`、`evaluate_js`、debug、打包）
- Microsoft WebView2 Runtime 分发文档
- Quill 2.x 官方文档
- SQLite WAL、`PRAGMA`、FTS5 external content、在线备份、`wal_checkpoint`
- FastAPI / uvicorn 后台线程运行方式
- bleach 白名单消毒文档
- PyInstaller 数据文件打包、`sys.frozen`、onedir vs onefile

### 12.3 开发者上手（最小前置）

> 以下为**本机已实测可用**的命令（Python 3.11.9 @ `E:\Python311`，venv @ `D:\小说辅助\.venv`）。

```bat
:: 1. 创建虚拟环境（已创建，重建时才需要）
E:\Python311\python.exe -m venv D:\小说辅助\.venv

:: 2. 安装依赖（lock 含 hash，已生成：requirements.lock，545 行）
D:\小说辅助\.venv\Scripts\python.exe -m pip install -r D:\小说辅助\requirements.lock

:: 3. 运行环境冒烟测试（验证 uvicorn 非主线程 + 本地 HTTP，须全绿）
D:\小说辅助\.venv\Scripts\python.exe D:\小说辅助\smoke_test.py

:: 4. 启动（开发模式，数据目录为 ./data）
set INKWELL_ENV=dev
D:\小说辅助\.venv\Scripts\python.exe main.py

:: 5. 最小验证
::    - pywebview 窗口打开并显示前端页面
::    - http://127.0.0.1:<随机端口>/api/system/health 返回 200（E-02 修订）
::    - ./data/inkwell.db 已生成且 schema_version 已写入
::    - 前端连续多次请求均不出现 404（R-17 代理问题回归）
```

**⚠️ 本机特有注意事项（R-17）**：环境中存在 `http_proxy` / `https_proxy = http://127.0.0.1:64530`。
任何访问本地服务的 HTTP 客户端（httpx / requests 等）必须 **禁用环境代理**（`trust_env=False`），
否则请求行会被改写为 absolute-form，导致本地源站返回 404。应用进程启动时建议清除本进程的代理变量。

### 12.4 换机 / 数据目录迁移步骤（FR-6.8）

1. 在旧机器上**完全退出 Inkwell**（确认无后台进程）
2. 对整个数据目录执行一次手动备份（"立即备份"）
3. 拷贝**整个数据目录**（`inkwell.db` + `covers/` + `media/` + `backups/` + `drafts/`）到新机器
4. 在新机器安装**同版本或更高版本**的 Inkwell
5. 首次启动时应用自动执行 `quick_check` 与 `schema_version` 校验：
   - 一致 → 正常打开
   - `schema_version` 高于应用支持 → 返回 **3003**，提示"请先升级应用"或"从备份恢复"
   - 完整性异常 → 阻断启动并引导从 `backups/` 恢复
6. 若需指定自定义位置：设置环境变量 `INKWELL_DATA_DIR`，或使用 `portable.txt` 启用可移植模式

> **注意**：迁移前请确保应用已退出；同步盘内的数据目录请等待同步完成后再拷贝（R-14）。

---

## 附录 A：AI 接口抽象层

> V1 仅定义接口与注册机制，**不实现任何 Provider**；V3.0 按 D-08 执行（用户自带 Key、显式开启、外发前确认）。

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class PlotAnalysis:
    summary: str
    conflicts: list[str]
    pacing_notes: list[str]

@dataclass
class CharacterMention:
    name: str
    aliases: list[str]
    first_position: int

class AIProvider(ABC):
    """AI 能力抽象层：所有 Provider 实现同一契约，运行时可切换。"""

    @abstractmethod
    async def analyze_plot(self, chapter_content: str) -> PlotAnalysis:
        """分析章节情节。入参为去标签纯文本（content_text）。"""

    @abstractmethod
    async def extract_characters(self, chapter_content: str) -> list[CharacterMention]:
        """提取出场人物，供关联角色库（V2.0 character 表）。"""

    @abstractmethod
    def name(self) -> str:
        """Provider 标识，用于设置页展示与切换。"""
```

| Provider | 时点 | 说明 |
|---|---|---|
| `NullProvider`（默认） | V1 | 返回"AI 功能未启用"；全程不联网 |
| `CloudAPIProvider` | V3.0 | DeepSeek / OpenAI 等，用户自带 Key；发送前弹确认并明示范围 |
| `LocalModelProvider` | V3.0 | 本地 Ollama 等，数据不出本机 |

- 注册表 `PROVIDERS: dict[str, type[AIProvider]]`，选择持久化到 `app_meta.ai_provider`。
- 外发约束：正文**仅在用户显式触发单次分析时**外发当章 `content_text`；不发快照、不发设定文档、不批量外发。

---

## 附录 B：需求追踪矩阵

| FR | 用户故事 | 接口（§6.2） | 验收 AC | 回归项 |
|---|---|---|---|---|
| FR-1 项目基础信息 | US-2 | #3~9、36、37 | AC-1 | 4 |
| FR-2 卷章大纲 | US-3 | #10~17、22 | AC-1 | 5、12 |
| FR-3 富文本写作 | US-4 | #18~21、36、37、46 | AC-2/3/4 | 2、7、14、20 |
| FR-4 设定文档 | US-6 | #28~30、48 | AC-1 | 4 |
| FR-5 自动保存与版本 | US-5 | #20、23~27、47、**#50（3.5 待实现）** | AC-4、AC-5 | 2、3、15 |
| FR-6 备份/导出/导入/迁移 | US-7、US-11 | #32~35、38 | AC-6、AC-9 | 6、7、16、19 |
| FR-7 搜索 | US-8 | #31、42 | AC-10 | — |
| 回收站（FR-1.6 + BR-4） | US-9 | #39~41 | AC-11 | 4 |
| 暂存兜底（BR-2 + NFR-R6） | US-5 | #20、44 | AC-4 | 15 |
| 默认卷（BR-6） | US-3 | #4、10、13、22 | AC-1、AC-11 | 12 |

---

## 附：本次改动汇总（v0.4 → v0.5）

**【必须修改】**
1. 新增 §8.4 Definition of Done（六条任务级完成标准）
2. 新增 §1.4.1 目标澄清：本期解决 / 不解决 / 推迟到哪版（三栏）
3. 新增 R-14：数据目录与同步盘（OneDrive）/ 防病毒 / 受控文件夹访问冲突风险 + 四条缓解措施
4. 新增 R-16：依赖供应链与打包可复现性风险（锁定 hash + 固定打包环境）
5. 新增 FR-6.8 数据目录迁移流程 + §12.4 换机迁移步骤（含 3003 处理）
6. 重构 §4.5 启动流程：新增 AC-2b「升级首启」例外路径（目标 ≤30s，假设），解除迁移与 AC-2 的矛盾

**【建议修改】**
7. 新增 NFR-R10：数据目录不可写时阻断并明确提示
8. 新增 NFR-M6：日志按天轮转 + 总量上限（假设 ≤50MB）
9. §6.1 明确长任务接口清单（#32/#34/#35/#38/#42/#43，超时 120s）与普通接口 10s
10. §6.3 补充索引更新延迟窗口（≤10s，假设）与 UI 标注
11. §7.2 补充窗口默认/最小尺寸（假设值）
12. 新增 §12.3 开发者上手最小步骤（venv / 依赖 / 启动 / 最小验证）
13. §11 拆为 D 组（有默认值，不阻塞）与 Q 组（信息不足，需你确认，未假设）
14. §12.1 假设清单补全（新增窗口尺寸、日志上限、升级首启时长共 3 项）
15. 新增 NFR-C4：数据目录不得位于同步盘；§4.4 增加同步盘风险提示

---

## 附：本次改动汇总（v0.5 → v0.6）

**【必须修改（勘误与接口）】**
1. §6.2 并入接口 **#45~#53**（#50/#51/#52 标注待实现），并补 #3「写 `last_opened_at`」、#47「补 `project_id`/`project_title`」两行增补
2. §6.1 补**长任务提交契约**（返回 tid + 500ms 轮询 + 409/3004）与错误码 **3004**
3. §6.3 补 `/files` 校验顺序（路径 → 签名，修 E-02 同源的 4003/4004 冲突）、回收站 `requires_parent`、导出、检索 `fuzzy`/`page_limited`、日志正文兜底、#53
4. §5.2 FTS 由「后台去抖」改为 **触发器即时同步**（E-01）；`version_no` 明确为**修订号**；补 E-03「快照表无软删除字段」
5. §5.4 索引维护同步 E-01；§9 阶段一验证方式与 §12.3 的 `/api/health` → **`/api/system/health`**（E-02）

**【架构与数据】**
6. §4.3 目录结构按实际重写（后端 api/services 全量、前端 js 全量、tests/docs 分层）
7. §4.4 数据目录：打包落点改为 **exe 同目录 `data/`** + 不可写回退；新增 `exports/`、`webview/`
8. §4.5 补「空库陷阱」设计口径（B4：项目数 0 且 backups 非空 → 首屏提示可从备份恢复，待实现）

**【UI/UX 与交互】**
9. §7.2 视觉规范回填 3.1/3.4 实测：`--danger #B84F36`、`--accent-strong`、`--danger-soft`、`--success-soft`、字体栈家族名、正文 17/1.9/≤760、首行缩进与豁免、选中色
10. §7.3 标注 P9 待建与状态栏三态待落地
11. §7.4 重写交互细节：状态栏三态、单章容量提示、大纲树、默认卷迁入、首屏三态与首启引导、设定文档删除、对话框取消契约、编辑器（代码块序列化 / 组合态占位）、破坏性操作确认
12. §7.5 补 IME 快捷键门禁（S3-03）

**【质量与计划】**
13. §8.1 回归清单 **20 → 28**，并补前端纯函数单测 / 窗口冒烟 / 截图基线三种验证手段
14. §8.2 补 #44 正文兜底；§8.3 补「前端无构建步骤」「前端测试入口」两条工程约定
15. §9 阶段二补 2.12 / 2.13；阶段三重排为 **3.0~3.9** 并记录 3.0~3.4 交付状态，估算 6~9 → **12~14 人日**
16. §10 增 **R-18**（设计基线滞后实现）与 **R-UI1~R-UI7**（阶段三 UI 风险）
17. §11 说明实施决策（S2-xx / S3-xx）在 `DECISIONS.md`，报告只引用结论
18. 附录 B 需求追踪矩阵补 #46 / #48 / #47 / #50 映射

> 未随本版修订的内容：§1（背景与目标）、§2.1 / §2.2（用户故事与 FR 主体）、§3（技术选型与实测环境）、
> §5.1 / §5.3（ER 与快照策略）、附录 A（AI 抽象层）——它们与实施结论一致，无需改动。

---

> 本报告为 V1.0 开发的**开发启动基线**（v0.6 起兼作阶段三验收口径）。阶段一不依赖任何待确认项即可启动；Q 组五项需在对应时点前由发起人答复，否则按 D 组默认值执行。
