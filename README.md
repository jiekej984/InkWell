# Inkwell

本地优先的中文长篇小说写作辅助工具。

技术栈：pywebview(WebView2) + FastAPI(uvicorn 子线程) + SQLite/SQLAlchemy + Quill 2.x，
V1 仅支持 Windows 10/11 x64。

> 设计基线与验收口径见 [`docs/项目报告/Inkwell项目报告_v0.8.md`](docs/项目报告/Inkwell项目报告_v0.8.md)
> （**v0.8 = 阶段四收口 / V1.0 发布基线**），决策结论见 [`DECISIONS.md`](DECISIONS.md)，
> 验收凭证见 [`docs/版本更新/阶段三_验收单.md`](docs/版本更新/阶段三_验收单.md) 与
> [`docs/版本更新/阶段四_验收单.md`](docs/版本更新/阶段四_验收单.md)。

## 安装与使用（Windows 10/11 x64）

**不需要装 Python。** 从 [Releases](https://github.com/jiekej984/InkWell/releases) 下载
`Inkwell-1.0.0-win-x64.zip`，解压到任意**可写目录**，双击 `Inkwell.exe` 即可。

```
Inkwell-1.0.0-win-x64.zip
└── Inkwell/                 ← 解压后是文件夹，不是单文件
    ├── Inkwell.exe          ← 双击这个
    └── _internal/           ← 运行时与前端资源（不能删、不能单独拿走 exe）
```

几条实用说明：

| 事项 | 说明 |
|---|---|
| **放哪里** | 解压到 D 盘、桌面等可写位置；**不要放 `Program Files`**——数据要写在 exe 同目录的 `data/`，不可写时会回退到「文档」 |
| **数据在哪** | 默认 `Inkwell/data/`（书库、日志、备份、导出、图片都在里面）。换机 = 拷这个文件夹；也可以用 `INKWELL_DATA_DIR` 指定别处，或在 exe 同目录放 `portable.txt` 走便携模式 |
| **WebView2** | Windows 11 和新版 Windows 10 一般已自带；万一缺失，应用会弹引导框并给官方下载地址，装完即可用 |
| **首次运行提示** | 未做代码签名，SmartScreen 可能提示「Windows 已保护你的电脑」：点**更多信息 → 仍要运行**。源码可自行构建，不放心可以从源码编译 |
| **更新** | 不做自动更新。下载新版 zip、解压覆盖到同一个 `Inkwell/` 目录即可（`data/` 在里面会被保留；覆盖前建议先整目录备份一次） |
| **只允许一个实例** | 重复双击不会起第二个进程，而是把已开着的窗口切到前台；不同数据目录可以各开一个 |
| **校验** | 每个 Release 附 `SHA256SUMS.txt`：`Get-FileHash .\Inkwell-1.0.0-win-x64.zip -Algorithm SHA256` 对照 |

## 开发者上手

前置：Python 3.11.9（本机位于 `E:\Python311`），项目虚拟环境位于 `D:\小说辅助\.venv`。

```bat
:: 1. 创建虚拟环境（已创建，重建时才需要）
E:\Python311\python.exe -m venv D:\小说辅助\.venv

:: 2. 安装依赖（lock 含 sha256 哈希）
D:\小说辅助\.venv\Scripts\python.exe -m pip install -r D:\小说辅助\requirements.lock
```

## 运行

```bat
:: 打开应用窗口
D:\小说辅助\.venv\Scripts\python.exe D:\小说辅助\main.py

:: 不开窗口，只跑一次启动自检（数据目录 / 建库 / 迁移 / 鉴权 / R-17 回归）
D:\小说辅助\.venv\Scripts\python.exe D:\小说辅助\main.py --selfcheck
```

## 测试与规范

```bat
D:\小说辅助\.venv\Scripts\python.exe -m pytest tests -q
D:\小说辅助\.venv\Scripts\python.exe -m ruff check main.py backend tests
D:\小说辅助\.venv\Scripts\python.exe -m black --check main.py backend tests
```

`pytest` 会自动执行前端逻辑单测（`tests/test_frontend_js.py` → `tests/js/*.test.js`，
Node 内置 test runner、零第三方依赖）；机器上没有 Node 时该项自动跳过。
单独跑前端用例：

```bat
node --test tests/js/*.test.js
```

真实窗口冒烟（会短暂弹出窗口；使用临时数据目录，不读写 `data/`）：

```bat
D:\小说辅助\.venv\Scripts\python.exe tests\e2e\window_smoke.py
:: 仅输出 JSON（便于脚本解析）
D:\小说辅助\.venv\Scripts\python.exe tests\e2e\window_smoke.py --json
:: 保留临时数据目录，便于排查失败现场
D:\小说辅助\.venv\Scripts\python.exe tests\e2e\window_smoke.py --keep-data
```

流程：临时数据目录 → 起后端 → 造样例 → 开窗口 → 项目列表 / 写作页输入 / 3s 自动保存 /
暂存清理 / 快捷键（Ctrl+N/S/F、Ctrl+Shift+F/V/E）/ 章内查找 / 大纲树右键与拖拽 /
检索高亮与短词降级 → 回查 HTTP 结果 → 关窗。退出码 0 通过、1 失败。

键盘与无障碍走查（回归 28；按键走 WebView2 CDP 真键位，含对比度与缩放实测）：

```bat
D:\小说辅助\.venv\Scripts\python.exe tests\e2e\a11y_walk.py
:: 输出逐项取值（对比度比值 / 三档缩放的视口宽与横向溢出）
D:\小说辅助\.venv\Scripts\python.exe tests\e2e\a11y_walk.py --json
```

## 目录结构

```
main.py                 入口：清代理 → 数据目录 → 建库/迁移 → 起后端 → 起窗口
backend/
  config.py             配置与数据目录解析（§4.4）
  server.py             应用工厂与安全中间件（token / Host / 请求行）
  schemas.py            统一响应与错误码（§6.1）
  storage.py            静态资源签名签发/校验、路径白名单（ADR-009）
  database.py           SQLite 连接、PRAGMA、WAL checkpoint、在线备份
  migrate.py            schema 迁移脚本（权威 DDL）
  models.py             同步 ORM 模型 + active() + session_scope（任务 2.0）
  timeutil.py           UTC 时间与 ISO 8601 序列化（BR-8）
  api/                  路由层：system / projects / volumes / chapters / documents /
                        files / drafts / versions / trash / backup / export /
                        search / maintenance / tasks
  services/             业务规则层：project_service / chapter_service / document_service /
                        wordcount / maintenance_service / sanitize / media / drafts /
                        version_service / trash_service / backup_service /
                        export_service / search_service / logging_service / tasks
frontend/
  index.html
  css/                  tokens.css / style.css
  js/                   app.js / api.js / logger.js / projects.js / format.js /
                        view.js / editor.js / writer.js / sidebar.js / autosave.js /
                        fallback.js / pending.js / versions.js / documents.js /
                        capacity.js / trash.js / backup.js / tasks.js / search.js /
                        hotkeys.js / find.js
  vendor/               Quill 2.0.3 离线副本（2.3 已接线）
data/                   开发环境数据目录
docs/                   全部项目文档（报告 / 任务清单 / 进度汇报）
  README.md             文档索引
  项目报告/             项目报告 v0.1~v0.6 + 三轮自审意见（v0.6 为当前设计基线）
  任务清单/             阶段二 / 阶段三任务清单
  版本更新/             逐次进度汇报、走查基线、验收单、UI 截图
package.json            仅声明 ES Module 与 Node 测试脚本（前端无构建步骤）
tests/                  pytest 用例
tests/js/               前端逻辑单测（Node 内置 test runner）
tests/e2e/              真实窗口冒烟（pywebview + WebView2）
_backups/               历史全量快照（已 gitignore；旧快照压在 _archive/ 下）
```

## 数据目录

按报告 §4.4（修订见 `DECISIONS.md` S3-04），优先级从高到低：

| 环境 | 数据目录 | 判定方式 |
|---|---|---|
| 覆盖 | 任意 | `INKWELL_DATA_DIR` |
| 可移植 | exe 同目录 `portable_data/` | 存在 `portable.txt` |
| 打包 | **exe 同目录 `data/`**（与程序同盘） | `sys.frozen` 为真 |
| 打包（回退） | `%USERPROFILE%/Documents/Inkwell/` | 仅当 exe 目录不可写（如装在 `Program Files`） |
| 开发 | `<仓库>/data/` | 默认 |

**打包模式不再默认写 C 盘**：程序装在 D 盘时数据就落在 D 盘，只有安装在受保护目录
（不可写）时才回退到「文档」。需要强制指定时用 `INKWELL_DATA_DIR` 或 `portable.txt`。

子目录：`covers/`、`media/`、`backups/`、`drafts/`、`logs/`、`exports/`（导出 TXT/MD）、
`webview/`（WebView2 缓存与 localStorage）。`webview/` 是显式指定的 `storage_path`——
不指定时 pywebview 会把 WebView2 的 `UserDataFolder` 写到 `%APPDATA%\pywebview`（系统盘），
并随使用持续增长。

## 安全约定

- 业务接口经头 `X-Inkwell-Token` 鉴权，token 每次启动随机生成，经窗口桥接注入，**不写入 URL**
- 仅放行 `127.0.0.1` / `localhost` 来源
- 本地服务仅监听回环地址，端口随机
- 静态资源走短期签名 query token（阶段二 2.3 实装路由）
- 进程启动时清除代理环境变量，避免 R-17（本机代理污染本地 HTTP 通信）

## 当前状态

- **阶段一（项目骨架）已完成**：目录结构、FastAPI 骨架与鉴权、pywebview 窗口与 token 注入、
  SQLite 初始化与迁移骨架。
- **阶段二功能开发完成**（14/14 任务）：2.0 数据访问层、2.1 项目、2.2 卷章、2.3 编辑器/图片/
  `/files/` 签名/消毒、2.4 自动保存/暂存、2.5 字数、2.6 快照/回滚、2.7 设定文档、2.8 回收站、
  2.9 备份恢复/后台流程、2.10 导出、2.11 检索、2.12 长任务框架、2.13 日志/诊断。
  真机验收 V-02、AC-4、AC-5、AC-9、AC-10 与回归 17/19 已随阶段三 3.9 收口（详见
  `docs/版本更新/进度记录.md` 与各期汇报）。
- **阶段三完成（10/10）**：3.0 UI 走查基线、3.1 Design Token、3.2 侧边栏/大纲树、
  3.3 项目卡片与首启引导、3.4 编辑器排版与中文适配、**3.5 状态栏三态 + 单章导出（#50）**、
  **3.6 P5 差异对比 / P6 分页 / P9 设置页 / P7 P8 三态**、**3.7 快捷键注册表**、
  **3.8 章内查找**、**3.9 交互回归与无障碍验收**。验收凭证：`docs/版本更新/阶段三_验收单.md`。
- **阶段四完成（5/5，V1.0.0 发布）**：
  - **4.1 PyInstaller onedir 打包**：`build.spec`（入库）+ `tools/build_release.py`（唯一出包入口）；
    产物 54.2 MB，前端资源打进 `_internal/frontend`，冻结自检 8/8（含 R-1「前端资源已就位」）
  - **4.2 单实例锁（回归 10）**：`backend/single_instance.py` 命名互斥量（按数据目录哈希），
    重复双击 0.7s 内退出并把已有窗口切到前台；`--selfcheck` 不受锁影响
  - **4.3 WebView2 检测与引导（回归 9）**：`backend/webview2.py` 查三处注册表 → 缺失时原生引导框
    + 官方下载页；「装了但起不来」也走同一条引导（`INKWELL_FAKE_NO_WEBVIEW2=1` 可复演）
  - **4.4 性能实测**：AC-2 冷启动 **0.98s**、AC-3 打开 5 万字章 **97ms**、AC-10 检索 **14ms**、
    AC-1 2001 章大纲树 **492ms**、导出 505 万字 **0.31s**；NFR-P6 空闲私有内存 284MB 达标
    （口径见 `DECISIONS.md` S4-01）。明细：`docs/版本更新/2026-10-24_2019_阶段四_4.4性能实测汇报.md`
  - **4.5 发布物料**：版本 **1.0.0**、`Inkwell-1.0.0-win-x64.zip` + `SHA256SUMS.txt`、
    报告 v0.8、阶段四验收单；发布形态与分发方式见 `DECISIONS.md` S4-02
- **阶段三验收状态（2026-10-24 收口）**：自动化 **A1~A7 全绿**（`pytest` 281 passed、
  `node --test` 79 passed、窗口冒烟 132 步、无障碍走查 20/20、截图 14 张、ruff/black/`node --check`
  全通过）；人工项 **M1 / M3 / M4 / M5 通过，M2 发起人主动跳过，M6 初测未过 → 已修复 → 人工复测通过**
  （见下条）。**阶段三可闭环**，打磨项归 V1.1。
- **3.9 后修复（S3-17）：`Ctrl+Shift+F` 在中文输入法下无反应**。根因不是 `openSearch()` 抛异常、
  也不是 `scope` 写错 —— 是**微软拼音在中文态把 `Ctrl+Shift+F` 当作自带的「简体/繁体切换」系统
  热键**，`F` 的 keydown 被输入法吞掉（`F` 的 keyup 仍会到达）。`frontend/js/hotkeys.js` 因此加
  **keyup 兜底**（只对带 Ctrl/Alt/Win 的命令组合，keydown 已执行过的去重，一次按键只触发一次），
  `frontend/js/app.js` 把 `openSearch()` 失败送到搜索页状态栏；真机六组合（中/英 × 项目列表 /
  写作页 / 设定页）复核全部打开且无双触发。判定方法与用户侧彻底解法见
  [`docs/故障排查.md`](docs/故障排查.md)。
- **真机验收修复（2026-10-24）**：B1 对话框「取消」关不掉、B2 设定文档删除入口、B3 代码块
  保存往返、B5 IME 组合期间占位消失已修；容量提示 warn 档已进窗口冒烟。待办：B4 库丢失引导。
- 3.5 补充的保存口径：状态栏三态（保存中 / 已保存 HH:MM / 保存失败，已本地暂存）；
  失败态「重试 / 导出本章」（#50 可导出未入库的当前正文）、3002 冲突「刷新并恢复」；
  窗口失焦 / 页面隐藏 / 切换章节 / 关闭均强制保存（BR-2）；窗口冒烟 54 → 76 步。
- 3.6 补充的能力：P5 版本差异对比（行级 LCS，5 万字上限）、P6 搜索「加载更多」（`page_limited`
  提示）、P9 应用设置页（#42/#43/#51/#52、诊断包 #49、桥接 `open_data_dir()`、数据/磁盘信息）；
  备份与回收站列表补齐加载 / 空 / 出错（可重试）三态；窗口冒烟 76 → 98 步。
- 3.7 / 3.8 补充的能力：统一快捷键注册表（Ctrl+N/S/F、Ctrl+Shift+F/V/E、Esc；IME 与输入框门禁；
  按钮 `title` + `aria-keyshortcuts` 标注）与章内查找条（`n/N`、上一个 / 下一个、区分大小写、
  CSS Custom Highlight 优先并支持 Selection 降级）；窗口冒烟 98 → 112 步。
- 3.9 补充的能力与口径：回归 21/22 固化进窗口冒烟（大纲树右键菜单 + 拖拽排序，112 → **131 步**），
  顺带修掉跨卷拖拽 `vid` 传参与树折叠焦点两处缺陷；新增 `tests/e2e/a11y_walk.py` 做键盘与无障碍
  走查（Tab 顺序 / 焦点可见 / 对话框焦点陷阱 + Esc / 树方向键 / 对比度 / 100·125·150% 缩放），
  实测对比度 4.72~14.16:1（全 AA）、三档缩放无横向溢出；回归 21~28 全部自动化。
- S3-17 补充的能力：快捷键注册表增加 **keyup 兜底**（`isCommandCombo()` / `matchShortcutOnKeyUp()` /
  `matchShortcut()` 的 `ignoreIme`），单测 71 → **79 passed**、窗口冒烟 131 → **132 步**；
  覆盖「输入法吞掉 keydown、只留 keyup」的真实场景，见上文「3.9 后修复」。
- 3.4 补充的排版口径：正文 17px / 行高 1.9 / 行宽 ≤760px 居中；首行缩进 2 字符只作用于正文段落；
  字体栈优先思源黑体（本机已装则全站生效）；`spellcheck=false`；单章超 5 万字 / 8 万字给出
  「建议拆章」提示但不阻断编辑与保存（FR-3.9）。
- 常用验证命令：`pytest tests -q`、`python main.py --selfcheck`、
  `python tests\e2e\window_smoke.py`、`python tests\e2e\a11y_walk.py`、
  `python tests\e2e\capture_ui.py --label after_3_9`。
- **出包与性能（阶段四）**：

  ```bat
  :: 出发布包：构建 → 冻结自检 → 开窗首屏 → 回归 9/10 → WebView2 引导 → zip + SHA256 + 解压自检
  .venv\Scripts\python.exe tools\build_release.py

  :: 性能实测：造 505 万字数据 → 检索 / 导出 / 5 次冷启动 / UI 场景 / 内存，结果落 JSON
  .venv\Scripts\python.exe tools\perf_probe.py --json docs\版本更新\阶段四_性能实测.json
  ```

  产物在 `dist/`（`Inkwell-<version>-win-x64.zip`、`SHA256SUMS.txt`），不入库。

## 故障排查

**窗口打不开、报 `Failed to resolve Python.Runtime.Loader.Initialize`**：工作区目录被打了
Low 完整性标签，.NET Framework 拒绝加载其中的程序集。一条命令修复：

```bat
icacls "D:\小说辅助" /setintegritylevel (OI)(CI)Medium
```

判定方法、其它同源症状（`black` 卡住、临时目录落到仓库根）见
[`docs/故障排查.md`](docs/故障排查.md)。
