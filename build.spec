# -*- mode: python ; coding: utf-8 -*-
"""Inkwell 打包配置（阶段四 4.1 / 报告 §9）。

**onedir**：产物 `dist/Inkwell/Inkwell.exe` + `dist/Inkwell/_internal/`。
onedir 而不是 onefile：报告 §9 4.1 + R-2 已定（onefile 每次启动都要解压到临时目录，
冷启动必然超 AC-2 的 3 秒预算）。

三个要点：

1. **`frontend/` 整目录进 datas**（落到 `_internal/frontend`）。打包后
   `backend/config.py` 的 `bundle_root()` 指向 `sys._MEIPASS`，前端从这里解析；
   漏一个文件就是「窗口白屏 / Quill 未加载」，属 R-1 头号风险。
2. **动态导入必须 collect_submodules**：uvicorn 的 loop / 协议实现、
   SQLAlchemy 的 dialect 都是按字符串动态 import，静态分析看不见。
3. **pywebview 与 pythonnet 各自带 `_pyinstaller/hook-*.py`**，并通过
   `pyinstaller40` entry point 注册，不需要在这里手写 datas/hiddenimports。

构建入口见 `tools/build_release.py`（PyInstaller → 冻结自检 → zip + SHA256）。
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH)  # noqa: F821 - PyInstaller 注入的 spec 所在目录

hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("sqlalchemy.dialects")
    + [
        # webview WinForms 后端与 .NET 桥（pythonnet 的 hook 负责 DLL）
        "clr",
        "webview.platforms.winforms",
        # uvicorn 默认 asyncio 后端需要显式列出（anyio 动态选择后端）
        "anyio._backends._asyncio",
        # 应用自身的动态导入点（长任务线程 / 迁移脚本按模块名加载）
        "backend.migrate",
        "backend.services.backup_service",
        "backend.services.logging_service",
        "backend.services.maintenance_service",
    ]
)

a = Analysis(  # noqa: F821
    ["main.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / "frontend"), "frontend")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 只排掉明确不需要、且体积/误报成本高的东西；不要把 unittest 之类排掉
    # （pydantic / sqlalchemy 的运行时分支会 import 到它们）
    excludes=["pytest", "PyInstaller", "pytest_cov", "tkinter", "IPython", "matplotlib"],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Inkwell",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX 会被部分杀软误报（R-3），且对 SQLite/WebView2 无收益
    console=False,  # 写作应用不开黑窗；--selfcheck 结果写日志文件 + 退出码
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Inkwell",
)


