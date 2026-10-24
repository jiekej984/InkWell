# Inkwell

本地优先的中文长篇小说写作辅助工具。

技术栈：pywebview(WebView2) + FastAPI(uvicorn 子线程) + SQLite/SQLAlchemy + Quill 2.x，
V1 仅支持 Windows 10/11 x64。

> 设计基线与里程碑见 `docs/项目报告/Inkwell项目报告_v0.6.md`；决策结论见 `DECISIONS.md`。

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
暂存清理 / 检索高亮与短词降级 → 回查 HTTP 结果 → 关窗。退出码 0 通过、1 失败。

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
                        capacity.js / trash.js / backup.js / tasks.js / search.js
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

按报告 §4.4（修订见 `DECISIONS.md` D-14），优先级从高到低：

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
- **待真机验收**：V-02、AC-4、AC-5、AC-9、AC-10 与回归 17/19，以及 P3/P5/P6/P7/P8 走查
  （AC-6 已有自动化量化断言、回归 15 前端链路已自动化；详见 `docs/版本更新/进度记录.md` 与各期汇报）。
- **阶段二评审补强（2026-10-23）**：回归 15 与 AC-6 补齐自动化；检索深页新增 `page_limited`/`fuzzy`
  字段；#44 日志增加正文兜底、前端 logger 改为按值脱敏。
- **阶段三进行中（5/10）**：3.0 UI 走查基线、3.1 Design Token、3.2 侧边栏/大纲树、
  3.3 项目卡片与首启引导、3.4 编辑器排版与中文适配已完成；下一步 3.5 状态栏三态。
- **真机验收修复（2026-10-24）**：B1 对话框「取消」关不掉、B2 设定文档删除入口、B3 代码块
  保存往返、B5 IME 组合期间占位消失已修；容量提示 warn 档已进窗口冒烟（38 → 54 步）。
  待办：B4 库丢失引导、报告 v0.6 修订。
- 3.4 补充的排版口径：正文 17px / 行高 1.9 / 行宽 ≤760px 居中；首行缩进 2 字符只作用于正文段落；
  字体栈优先思源黑体（本机已装则全站生效）；`spellcheck=false`；单章超 5 万字 / 8 万字给出
  「建议拆章」提示但不阻断编辑与保存（FR-3.9）。
- 常用验证命令：`pytest tests -q`、`python main.py --selfcheck`、
  `python tests\e2e\window_smoke.py`、`python tests\e2e\capture_ui.py --label after_3_4`。

## 故障排查

**窗口打不开、报 `Failed to resolve Python.Runtime.Loader.Initialize`**：工作区目录被打了
Low 完整性标签，.NET Framework 拒绝加载其中的程序集。一条命令修复：

```bat
icacls "D:\小说辅助" /setintegritylevel (OI)(CI)Medium
```

判定方法、其它同源症状（`black` 卡住、临时目录落到仓库根）见
[`docs/故障排查.md`](docs/故障排查.md)。
