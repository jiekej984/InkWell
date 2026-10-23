# 阶段三 UI 走查基线（任务 3.0）

> **时点**：2026-10-23 21:59
> **方法**：真实 pywebview 窗口（1280×800，内容区 1264×761）+ WebView2 CDP
> `Page.captureScreenshot` 截取页面内容（不受窗口遮挡影响）；临时数据目录，不读写项目 `data/`
> **物料**：`docs/版本更新/阶段三_截图/`（8 张 PNG + `baseline_manifest.json`）
> **用途**：3.1~3.6 改动后的视觉对照；本文件不做任何代码修改

---

## 一、截图清单

| 文件 | 页面 | 说明 |
|---|---|---|
| `baseline_P1_projects.png` | P1 项目列表 | 两张卡片（长夜将尽 / 短篇练习集）、顶栏、运行日志折叠区 |
| `baseline_P2_writer.png` | P2 写作页 | 大纲树（1 卷 2 章）+ 编辑器 + 状态栏 |
| `baseline_P3_documents.png` | P3 设定文档页 | 分类筛选 + 2 篇文档 |
| `baseline_P4_project_settings.png` | P4 项目设置对话框 | 模态遮罩 + 表单 |
| `baseline_P5_versions.png` | P5 版本历史弹窗 | 版本列表 + 预览区 + 回滚按钮 |
| `baseline_P6_search.png` | P6 全局搜索 | 「海风」2 条命中 + `<mark>` 高亮 |
| `baseline_P7_backup.png` | P7 备份与导出 | 备份列表 + 导出区 + 诊断包 |
| `baseline_P8_trash.png` | P8 回收站 | 被删章节 + 恢复/彻底删除 |
| — | P9 应用设置 | **页面不存在，无截图**（3.6 新建） |

## 二、实测值（`baseline_manifest.json`）

| 项 | 实测 | 说明 |
|---|---|---|
| 内容区 | 1264 × 761 | 由窗口 1280×800 扣除边框/标题栏 |
| 大纲树卷数 / 章数 | **1 卷 / 2 章** | 默认卷里的「楔子」**未出现在树中** → 印证 C-04 |
| 状态文案 | `已加载`（写作页头部 `#save-status`） | 三态不在状态栏；保存前 `#stat-saved` 为空 |
| 状态栏内容 | `本章 35 字 / 版本 #3 / 全书 62 字` | 无保存态、无重试动作 |
| 编辑器字号 / 行高 | **17px / 32.3px（=1.9）** | 符合 §7.2 |
| 编辑器行宽 | **760px** | 符合 §7.2 |
| `:focus-visible` 支持 | `true`（WebView2 支持） | 但 `style.css` 中没有任何 `:focus-visible` 规则 |
| 页面 JS 异常 | `[]` | 基线无脚本错误 |

## 三、Token 对照（现状 vs §7.2）

现状 `tokens.css` 是阶段一骨架，与 §7.2 存在系统性偏差；`style.css` 另有 **18 处硬编码颜色**。

| Token | 现状 | 报告 §7.2 | 处理建议（3.1） |
|---|---|---|---|
| `--bg` | `#FBFAF8` | `#FAF9F7` | 改为 §7.2 值 |
| `--panel` | `#FFFFFF` | `#FFFFFF` | 命名对齐 |
| `--sidebar` | **缺失** | `#F3F1ED` | 新增；当前侧栏用 `#F7F5F1` 近似值 |
| `--text` | `#2B2A28` | `#2B2B2B` | 改为 §7.2 值 |
| `--text-2` | `#6B6862` | `#6B6B6B` | 改为 §7.2 值 |
| `--border` | `#E5E1DA` | `#E5E2DC` | 改为 §7.2 值 |
| `--accent` | `#8A6F4E` | `#7A6A58` | 改为 §7.2 值 |
| `--accent-soft` | **缺失** | `#F0EBE3` | 新增（选中态/标签底色） |
| `--danger` | `#A8443A` | `#C0563C` | **冲突**：§7.2 值在 `#FAF9F7` 上仅 **4.30:1**，不达 AA；建议 `#B84F36`（4.74:1，白字 4.99:1） |
| `--success` | `#3F7D52` | `#4F7A5B` | 改为 §7.2 值（4.68:1，勉强达 AA） |
| 界面字号 | 15px | **14px** | 改为 14px；正文仍 17px |
| 圆角 | 4 / 8px | **6px** | 统一为 6px（小控件可保留 4px，需在 3.1 定稿） |
| 间距 | 4/8/12/16/24 | 4/8/12/16/24 | 已一致 |
| 字体栈 | `Microsoft YaHei UI` / `PingFang SC` / system-ui | 思源黑体 / 苹方 / 微软雅黑 + 西文 Inter | 补 `Inter` 与 `Source Han Sans SC` 到栈首（离线不引入 Web 字体，装了才生效） |

> 对比度实测（WCAG 2.1）：`text #2B2B2B` 13.46:1、`text-2 #6B6B6B` 5.06:1、`accent #7A6A58` 4.95:1、
> `success #4F7A5B` 4.68:1 均达 AA；**`danger #C0563C` 4.30:1 不达标** —— 3.1 需调值或限定为大字号/图标用色。

## 四、页面级问题（截图对照）

| 页面 | 基线截图 | 主要问题 | 任务 |
|---|---|---|---|
| P1 项目列表 | P1 | 卡片信息密度低；缺加载骨架；空态只有一行文案；首启无引导（NFR-U1） | 3.3 |
| P2 写作页 | P2 | 树只有「新建卷/章 + 打开」；无折叠/拖拽/右键/删除/属性；默认卷章节不可达（C-04） | 3.2 |
| P3 设定文档 | P3 | 分类筛选可用；无排序 UI（FR-4.4 Should） | 3.6 附带 |
| P4 项目设置 | P4 | 表单可用；视觉与 token 未统一 | 3.1 |
| P5 版本历史 | P5 | 只有列表 + 预览，**无内容差异对比**（FR-5.4） | 3.6 |
| P6 搜索 | P6 | 只请求第 1 页 20 条，无分页/加载更多 | 3.6 |
| P7 备份导出 | P7 | 功能可用；加载/空/错误态未打磨 | 3.6 |
| P8 回收站 | P8 | 功能可用；视觉一致性待处理 | 3.1 |
| P9 应用设置 | 无 | **整页缺失**（字数口径、快照清理、修复工具、打开数据目录、诊断包入口） | 3.6 |

## 五、可访问性初检

- WebView2 支持 `:focus-visible`，但当前**没有任何焦点样式**（仅 `input:focus` 去掉了 outline，反而更差）
- 状态提示没有 `aria-live`，保存失败只能靠肉眼发现
- `danger` 文字色对比度不足 4.5:1（见上）
- 模态使用原生 `<dialog>`，焦点陷阱与 Esc 行为待 V-06 实测
- 树节点是可点击 `<button>`（键盘可达性基础尚可），但无方向键导航

## 六、结论与下一步

1. **3.1 优先级最高**：token 与 §7.2 对齐（含 danger 调值）、清掉 18 处硬编码色、补 `:focus-visible`
2. **C-04 已被截图证实**：默认卷「楔子」不在树中；3.2 按确认方案（建首个命名卷时迁入）处理
3. **3.5/3.6 的缺口明确**：三态仍在头部、P9 不存在、P5 无 diff、P6 无分页
4. 每个 UI 任务完成后，用同一命令重新截图（`--label after_3_1` 等）做前后对照

## 七、复现方式

```bat
:: 基线（已完成）
D:\小说辅助\.venv\Scripts\python.exe tests\e2e\capture_ui.py --label baseline

:: 3.1 完成后对照
D:\小说辅助\.venv\Scripts\python.exe tests\e2e\capture_ui.py --label after_3_1
```

- 脚本：`tests/e2e/capture_ui.py`（临时数据目录、CDP 截图、退出码 0/1、`--json` 可解析）
- 数据：1 本书 2 卷（含默认卷楔子）、2 章、2 篇设定、2 个版本、1 条回收站记录、1 份备份

---

## 八、3.1 复核（2026-10-23 22:28）

### 8.1 Token 落实

| 分组 | 落值 |
|---|---|
| 颜色 | `--bg #FAF9F7`、`--panel #FFFFFF`、`--sidebar #F3F1ED`、`--text #2B2B2B`、`--text-2 #6B6B6B`、`--border #E5E2DC`、`--accent #7A6A58`、`--accent-soft #F0EBE3`、`--success #4F7A5B` |
| 调整项 | `--danger #B84F36`（§7.2 为 `#C0563C`，前者达 AA）；派生 `--accent-strong #6B5B49`、`--danger-soft #FBEEE9`、`--overlay rgb(43 43 43 / 32%)`、`--shadow` |
| 排版 | `--font-ui`（Inter → 思源黑体 → 苹方 → 微软雅黑）、`--font-mono`；界面 `--font-size-ui 14px`；正文 `--font-size-editor 17px / --line-height-editor 1.9 / --editor-width 760px` |
| 尺寸 | `--radius 6px`、`--radius-sm 4px`、`--radius-pill 999px`、`--topbar-height 52px`、`--sidebar-width 260px`、间距 4/8/12/16/24 |

### 8.2 对比度复核（WCAG AA，正文阈值 4.5:1）

| 组合 | 比值 | 结论 |
|---|---|---|
| `--text` / `--bg` | 13.46:1 | ✅ |
| `--text-2` / `--bg` | 5.06:1 | ✅ |
| `--text-2` / `--sidebar` | 4.72:1 | ✅ |
| `--accent` / `--bg` | 4.95:1 | ✅ |
| `--accent` / `--panel` | 5.21:1 | ✅ |
| `--danger` / `--bg`（新值） | 4.74:1 | ✅（原 `#C0563C` 仅 4.30:1） |
| `--danger` / `--panel` | 4.99:1 | ✅ |
| `--success` / `--bg` | 4.68:1 | ✅ |
| 白字 / `--accent` / `--accent-strong` | 5.21 / 6.53:1 | ✅ |
| 白字 / `--danger` | 4.99:1 | ✅ |

> **禁用组合（已避免）**：`--accent` 或 `--text-2` 写在 `--accent-soft` 上仅 4.39 / 4.49:1，
> 因此标签/草稿横幅/选中态上的文字统一用 `--text`；`--danger` 文字只出现在 `--panel`/`--bg` 上。

### 8.3 样式迁移结果

- `style.css` 硬编码颜色：**18 处 → 0 处**（`--font-mono` 也已 token 化，无未定义变量）
- 新增交互状态：`button/a:focus-visible`、`input :focus-visible` 光晕、`.btn:disabled`、
  `::selection`、`dialog::backdrop`（32% 遮罩）、滚动条统一、`prefers-reduced-motion`
- 编辑器排版全部改由 token 驱动（17px / 1.9 / 760px 数值不变）
- 界面基础字号 15px → **14px**（§7.2）

### 8.4 截图对照（`after_3_1_*` vs `baseline_*`）

| 页面 | 变化像素占比 | 说明 |
|---|---|---|
| P1 项目列表 | 0.4% | token 值与字号微调 |
| P2 写作页 | 1.5% | 侧栏/状态栏底色、界面字号 |
| P3 设定页 | 1.3% | 同上 |
| P4 项目设置 | 71.1% | **对话框遮罩由浏览器默认（约 10%）改为 32% token** |
| P5 版本历史 | 58.4% | 同上 |
| P6 搜索 | 1.2% | 提示色/片段色 token 化 |
| P7 备份 | 0.5% | 微调 |
| P8 回收站 | 0.1% | 微调 |

### 8.5 运行验证

- `capture_ui.py --label after_3_1`：8 张全部成功、`page_errors=[]`、退出码 0
- 运行时计算值：body `rgb(250,249,247)`、sidebar `rgb(243,241,237)`、编辑器 `17px / 32.3px / 760px`
- `tests/e2e/window_smoke.py`：14 步全部 PASS
- `pytest tests -q`：**237 passed**

---

## 九、3.2 复核（2026-10-24 00:41）

- 新增 `frontend/js/sidebar.js`（折叠/右键菜单/章节信息/标记定稿/拖拽/卷排序/键盘/删卷三选一）
  与 **#53 `POST /volumes/{vid}/adopt-default`**（C-04）
- 真实窗口端到端驱动（一次性验证脚本，未入库）8 项全部通过：
  C-04 默认卷迁入（1 章）、章节信息保存（标题/状态/目标 5000）、标记定稿（status=final + milestone 快照）、
  新建章节、拖拽排序（第二章 → 首位）、折叠记忆（`inkwell:tree:collapsed:<pid>` = `[2]`）、删除章节；`page_errors=[]`
- `pytest tests -q`：**239 passed**（+2 条 adopt-default 用例）；`window_smoke.py` 14 步 PASS
- `capture_ui.py --label after_3_2`：8 张、无 JS 异常；P2 与 after_3_1 像素差异 0.2%（新增折叠按钮）

---

## 十、3.3 复核（2026-10-24 02:05）

### 10.1 截图与差异（`after_3_3_*` vs `after_3_2_*`）

| 页面 | 变化像素占比 | 说明 |
|---|---|---|
| **P1 项目列表** | **3.15%** | 卡片重排：默认封面（书名首字）、状态徽标、字数 + 最近打开同排、进度条 + 百分比、标签、「打开 / 设置」常显 |
| **P1b 项目列表空态** | 新增 | 标题「还没有作品」+ 说明 + 主 CTA「新建第一本书」（虚线框，与错误态区分） |
| P2 写作页 | 0.00% | 无回归（差异仅 1×21px 状态文字） |
| P3 设定页 | 0.00% | 无回归 |
| P4 项目设置 | 2.35% | 对话框背后卡片重排（遮罩内不变） |
| P5 版本历史 | 0.09% | 无实质变化 |
| P6 搜索 | 1.40% | 顶栏「← 作品」出现状态差异，列表本身未变 |
| P7 备份 | 0.10% | 无实质变化 |
| P8 回收站 | 0.00% | 无回归 |

> P5/P6/P7 的零碎差异来自截屏时的焦点/取数可见性，不涉及样式改动；
> 3.3 只改 `projects.js` 与卡片相关 CSS，其余页面 CSS 未触碰。

### 10.2 首屏三态

| 状态 | 触发 | 表现 |
|---|---|---|
| 骨架态 | 列表请求返回前 | 3 张 shimmer 占位卡，容器 `aria-busy="true"`，`prefers-reduced-motion` 下停止动画（沿用 3.1 的全局规则） |
| 空态 | `items.length === 0` | 虚线框 + 标题 + 说明 + 主 CTA；`#empty-new-project` 打开新建对话框 |
| 出错态 | 请求抛错 | 红色描边 + `读取作品列表失败：…` + 重试按钮；错误信息 `word-break: break-word` |

### 10.3 卡片交互取舍（重要变更）

「hover 才露出操作按钮」的初版实现经首轮 `after_3_3` 截图判定为不可接受：
按钮隐去后卡片底部留下无法解释的空隙，且主操作（打开）不可发现、键盘与触屏用户无法看到。
最终改为**常显按钮 + hover 强调**（卡片抬升 `--shadow-soft`、按钮描边转 `--accent`），
结论见 `DECISIONS.md` §七 **S3-06 ④**。

### 10.4 无障碍与 AA

- 徽标文字统一用 `--text`；底色只用 `--accent-soft` / `--sidebar` / `--success-soft`
  （新增 token），三种组合的对比度分别 ≥ 13:1
- 卡片主体 `role="button"` + `tabindex="0"`，`:focus-visible` 2px `--accent` 轮廓、偏移 2px
- 卡片内不嵌套交互元素：`.card__open`（展示区）与 `.card__actions`（按钮区）是**兄弟节点**
- 骨架卡 `aria-hidden="true"`，不朗读占位内容

### 10.5 运行验证

- `capture_ui.py --label after_3_3`：**9 张**全部成功、`page_errors=[]`、退出码 0
- `window_smoke.py`：**24 步**全部 PASS（新增卡片三项 / 首启引导三步 / 空态与出错态四步）
- `pytest tests -q`：**243 passed**；`node --test tests/js/format.test.js`：11 passed
- 运行时计算值沿用 8.5：编辑器 `17px / 32.3px / 760px`，body/sidebar 底色不变

