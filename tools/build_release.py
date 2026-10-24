"""阶段四 4.1：onedir 构建 + 冻结产物自检 + 真实启动验证（唯一构建入口，R-16）。

用法（推荐用项目 venv）：

    .venv\\Scripts\\python.exe tools\\build_release.py
    ... --skip-check     # 只构建，不跑冻结自检与启动验证（调打包参数时用）
    ... --skip-launch    # 自检照跑，跳过开窗验证
    ... --keep           # 保留验证用的临时数据目录

四步：

1. `python -m PyInstaller build.spec --noconfirm --clean` → `dist/Inkwell/`
2. **冻结自检**：用冻结后的 exe 跑 `--selfcheck`（windowed 构建没有控制台，
   结果看 `data/logs/*.log` 的 `[selfcheck]` 行 + 退出码）。其中「前端资源已就位」
   一项直接对应 R-1（打包漏 `frontend/`）。
3. **真实启动**：起冻结窗口 → 等窗口出现 → 等前端自己走到 `GET /api/projects` →
   断言 `[editor] 编辑器初始化失败` / `Quill 未加载` 这类 R-1 症状没有出现 →
   发 `WM_CLOSE` 让它自己退出（顺带覆盖 beforeunload 关窗路径）。
4. 打印产物体积与入口路径。

注意：`dist/`、`build/` 都在 `.gitignore` 里；`build.spec` 是交付物，已用
`!build.spec` 单独放行。
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # 让脚本方式运行时能 import backend.*
DIST = ROOT / "dist" / "Inkwell"
EXE = DIST / "Inkwell.exe"
WINDOW_TITLE = "Inkwell"
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
IDNO = 7

# R-1 在日志里的典型症状：出现任意一条就说明前端资源没打全
RESOURCE_FAILURE_MARKERS = (
    "Quill 未加载",
    "编辑器初始化失败",
    "[editor] Quill",
)

user32 = ctypes.windll.user32
user32.EnumWindows.argtypes = [
    ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM),
    wt.LPARAM,
]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowTextLengthW.argtypes = [wt.HWND]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.EnumChildWindows.argtypes = [
    wt.HWND,
    ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM),
    wt.LPARAM,
]

# 4.3 引导框的标题与必须出现的下载页（与 backend/webview2.py 保持一致）
WEBVIEW2_TITLE = "Inkwell 需要 Microsoft Edge WebView2 运行时"
WEBVIEW2_DOWNLOAD_HOST = "developer.microsoft.com/microsoft-edge/webview2"


def human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def dir_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def log_lines(data_dir: Path) -> list[str]:
    log_dir = data_dir / "logs"
    if not log_dir.is_dir():
        return []
    lines: list[str] = []
    for log_file in sorted(log_dir.glob("*.log")):
        lines.extend(
            log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        )
    return lines


def find_window(pid: int, timeout: float, title: str = WINDOW_TITLE) -> int:
    """等该进程的、标题含 `title` 的可见顶层窗口出现，返回句柄（0 = 超时）。"""
    deadline = time.time() + timeout

    def callback(hwnd: wt.HWND, _lparam: wt.LPARAM) -> bool:
        owner = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid or not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        if title in buffer.value:
            matches.append(int(hwnd))
            return False
        return True

    while time.time() < deadline:
        matches: list[int] = []
        user32.EnumWindows(ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)(callback), 0)
        if matches:
            return matches[0]
        time.sleep(0.2)
    return 0


def window_child_texts(hwnd: int) -> str:
    """把窗口内所有子控件的文字拼起来（读 MessageBox 正文用）。"""
    texts: list[str] = []

    def callback(child: wt.HWND, _lparam: wt.LPARAM) -> bool:
        length = user32.GetWindowTextLengthW(child)
        if length > 0:
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(child, buffer, length + 1)
            texts.append(buffer.value)
        return True

    user32.EnumChildWindows(
        hwnd, ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)(callback), 0
    )
    return " | ".join(texts)


def build() -> None:
    print("[1/6] PyInstaller onedir 构建 …", flush=True)
    started = time.time()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "build.spec",
            "--noconfirm",
            "--clean",
            "--log-level",
            "WARN",
        ],
        cwd=str(ROOT),
    )
    if result.returncode != 0:
        raise SystemExit(f"PyInstaller 失败（退出码 {result.returncode}）")
    elapsed = time.time() - started
    if not EXE.exists():
        raise SystemExit(f"构建完成但找不到入口：{EXE}")
    print(
        f"      产物 {DIST.name}/ = {human_size(dir_size(DIST))}，耗时 {elapsed:.1f}s",
        flush=True,
    )


def frozen_selfcheck(keep: bool) -> None:
    """用冻结 exe 跑一次启动自检：这是「打包没打坏」的最短闭环。"""
    print("[2/6] 冻结产物自检（--selfcheck）…", flush=True)
    data_dir = Path(tempfile.mkdtemp(prefix="inkwell-frozen-check-"))
    env = _clean_env(data_dir)
    try:
        result = subprocess.run(
            [str(EXE), "--selfcheck"],
            env=env,
            timeout=180,
            capture_output=True,
            text=True,
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        raise SystemExit("冻结自检超时（180s）") from None

    lines = [line for line in log_lines(data_dir) if "[selfcheck]" in line]
    print(f"      退出码 {result.returncode}；日志 {len(lines)} 行", flush=True)
    for line in lines:
        print(f"      {line}", flush=True)
    if result.returncode != 0:
        tail = "\n".join((result.stdout or "").strip().splitlines()[-20:])
        raise SystemExit(f"冻结自检未通过：\n{tail}")
    if not any("自检通过" in line or "结果：" in line for line in lines):
        raise SystemExit(
            "冻结自检没有留下可判定的日志（应包含 [selfcheck] 结果行）；"
            "检查 main.py 的 selfcheck 日志是否落地"
        )
    if keep:
        print(f"      自检数据目录保留在 {data_dir}", flush=True)
    else:
        shutil.rmtree(data_dir, ignore_errors=True)


def launch_smoke(keep: bool) -> None:
    """真实启动冻结窗口：窗口出现 + 前端跑到项目列表 + 没有 R-1 症状。"""
    print("[3/6] 真实启动验证（开窗 → 首屏 → 关窗）…", flush=True)
    data_dir = Path(tempfile.mkdtemp(prefix="inkwell-frozen-launch-"))
    env = _clean_env(data_dir)
    process = subprocess.Popen([str(EXE)], env=env)
    started = time.time()
    try:
        hwnd = find_window(process.pid, timeout=40.0)
        if not hwnd:
            raise SystemExit("40s 内没有等到 Inkwell 窗口出现")
        window_elapsed = time.time() - started
        print(f"      窗口出现：{window_elapsed:.2f}s（pid={process.pid}）", flush=True)

        # 前端自检（20 次 health）→ initWriter/initDocuments → initProjects
        deadline = time.time() + 30.0
        booted = False
        while time.time() < deadline:
            if any("GET /api/projects -> 200" in line for line in log_lines(data_dir)):
                booted = True
                break
            if process.poll() is not None:
                break
            time.sleep(0.2)
        if not booted:
            raise SystemExit(
                "窗口已出现，但前端没有走到 GET /api/projects（首屏没渲染出来）"
            )
        boot_elapsed = time.time() - started
        print(f"      首屏就绪：{boot_elapsed:.2f}s（前端已拉到项目列表）", flush=True)

        time.sleep(1.0)  # 给前端把首屏 DOM 画完、把可能的异常上报完
        lines = log_lines(data_dir)
        bad = [
            line
            for line in lines
            if any(marker in line for marker in RESOURCE_FAILURE_MARKERS)
        ]
        if bad:
            raise SystemExit("前端资源疑似未打全：\n" + "\n".join(bad[:5]))
        if any(" ERROR " in line for line in lines):
            raise SystemExit(
                "日志出现 ERROR：\n"
                + "\n".join(line for line in lines if " ERROR " in line)[:2000]
            )
        print("      无 R-1 症状（Quill / 编辑器 / 前端资源均正常）", flush=True)

        # ---- 回归 10 / NFR-S3：重复启动不得起第二实例，首个实例保持运行 ----
        second = subprocess.Popen([str(EXE)], env=env)
        second_started = time.time()
        try:
            second.wait(timeout=20)
        except subprocess.TimeoutExpired:
            second.kill()
            second.wait(10)
            raise SystemExit(
                "重复启动：第二实例 20s 内没退出（单实例锁没生效）"
            ) from None
        second_elapsed = time.time() - second_started
        if second.returncode != 0:
            raise SystemExit(f"重复启动：第二实例退出码 {second.returncode}（期望 0）")
        if process.poll() is not None:
            raise SystemExit("重复启动：第一个实例被顶掉了（应当继续运行）")
        lines = log_lines(data_dir)
        if not any("已有实例在运行" in line for line in lines):
            raise SystemExit("重复启动：日志里没有「已有实例在运行」记录")
        print(
            f"      重复启动：第二实例 {second_elapsed:.2f}s 退出（code 0），"
            "首实例仍在运行（回归 10）",
            flush=True,
        )
        foreground = _foreground_title()
        if "Inkwell" in (foreground or ""):
            print("      已有窗口已切到前台（激活成功）", flush=True)
        else:
            # 不设为失败项：构建机可能被别的窗口抢了前台，属环境噪声
            print(
                f"      前台窗口：{foreground or '（取不到）'}（激活未验证，非失败项）",
                flush=True,
            )
    finally:
        _close_window_and_wait(process)
        if keep:
            print(f"      启动验证数据目录保留在 {data_dir}", flush=True)
        else:
            shutil.rmtree(data_dir, ignore_errors=True)


def _foreground_title() -> str:
    """取当前前台窗口标题（窗口激活的旁证；取不到返回空串）。"""
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value
    except OSError:  # pragma: no cover - 纯诊断，失败不影响构建结论
        return ""


def webview2_guidance_smoke(keep: bool) -> None:
    """回归 9 / NFR-C2：冻结产物能检测运行时；缺运行时给出可读引导而不是堆栈。"""
    print("[4/6] WebView2 检测与引导验证 …", flush=True)

    # (a) 冻结产物里的注册表检测（本机装的是 155.x）
    check_dir = Path(tempfile.mkdtemp(prefix="inkwell-wv2-check-"))
    try:
        result = subprocess.run(
            [str(EXE), "--check-webview2"],
            env=_clean_env(check_dir),
            timeout=90,
            capture_output=True,
            text=True,
            errors="replace",
        )
        lines = [line for line in log_lines(check_dir) if "WebView2 Runtime" in line]
        if result.returncode != 0:
            raise SystemExit(
                f"--check-webview2 退出码 {result.returncode}（本机应已安装 WebView2）"
            )
        version = lines[-1].split("WebView2 Runtime:", 1)[-1].strip() if lines else "?"
        print(f"      冻结产物检测到运行时：{version}", flush=True)
    finally:
        if keep:
            print(f"      检测数据目录保留在 {check_dir}", flush=True)
        else:
            shutil.rmtree(check_dir, ignore_errors=True)

    # (b) 强制「缺失」：必须弹出带官方下载页的引导框，关掉后以非 0 退出
    guide_dir = Path(tempfile.mkdtemp(prefix="inkwell-wv2-guide-"))
    env = _clean_env(guide_dir)
    env["INKWELL_FAKE_NO_WEBVIEW2"] = "1"
    process = subprocess.Popen([str(EXE)], env=env)
    try:
        hwnd = find_window(process.pid, timeout=30.0, title=WEBVIEW2_TITLE)
        if not hwnd:
            raise SystemExit("强制缺失 WebView2 时没有出现引导对话框（回归 9 未满足）")
        texts = window_child_texts(hwnd)
        if WEBVIEW2_DOWNLOAD_HOST not in texts:
            raise SystemExit(f"引导框里没有官方下载页：{texts[:400]}")
        print("      强制缺失：已弹出引导框，且含官方下载页", flush=True)
        # MB_YESNO 的 MessageBox 没有「取消」按钮，WM_CLOSE 会被忽略；
        # 用 WM_COMMAND + IDNO(7) 按「否」（按钮 ID 与系统语言无关）
        user32.PostMessageW(hwnd, WM_COMMAND, IDNO, 0)
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                raise SystemExit("点了「否」之后进程仍没有退出") from None
        if process.returncode == 0:
            raise SystemExit(
                f"缺 WebView2 却以 0 退出（returncode={process.returncode}）"
            )
        print(
            f"      关掉引导框后退出码 {process.returncode}（非 0，符合预期）",
            flush=True,
        )
        if not any("未检测到 WebView2 运行时" in line for line in log_lines(guide_dir)):
            raise SystemExit("引导路径没有留下日志")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(10)
        if keep:
            print(f"      引导验证数据目录保留在 {guide_dir}", flush=True)
        else:
            shutil.rmtree(guide_dir, ignore_errors=True)


def _close_window_and_wait(process: subprocess.Popen) -> None:
    """发 WM_CLOSE 让它自己退出（覆盖 beforeunload 关窗路径），超时再强杀。"""
    if process.poll() is not None:
        return
    hwnd = find_window(process.pid, timeout=1.0)
    if hwnd:
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - 防御性兜底
            process.kill()
            process.wait(timeout=10)


def _clean_env(data_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["INKWELL_DATA_DIR"] = str(data_dir)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    return env


def release_package(skip: bool = False) -> None:
    """4.5：打成发布 zip + SHA256SUMS，并把 zip 解压到临时目录再自检一遍。

    命名按 D-12：`Inkwell-<version>-win-x64.zip` + `SHA256SUMS.txt`。
    解压后自检是「用户拿到的是不是能跑」的最短证明（同时能抓出对仓库路径的隐式依赖）。
    """
    if skip:
        print("[5/6] 跳过发布打包（--skip-package）", flush=True)
        return
    from backend.config import APP_VERSION

    print("[5/6] 发布打包（zip + SHA256SUMS + 解压自检）…", flush=True)
    archive = ROOT / "dist" / f"Inkwell-{APP_VERSION}-win-x64.zip"
    if archive.exists():
        archive.unlink()
    started = time.time()
    file_count = 0
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(DIST.rglob("*")):
            if path.is_file():
                bundle.write(
                    path, arcname=str(Path("Inkwell") / path.relative_to(DIST))
                )
                file_count += 1

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    sums = ROOT / "dist" / "SHA256SUMS.txt"
    sums.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(
        f"      {archive.name}：{human_size(archive.stat().st_size)}，{file_count} 个文件，"
        f"耗时 {time.time() - started:.1f}s",
        flush=True,
    )
    print(f"      sha256 {digest}", flush=True)

    # 解压到临时目录再跑一次冻结自检：模拟用户「下载 → 解压 → 双击」
    extract_dir = Path(tempfile.mkdtemp(prefix="inkwell-unzip-check-"))
    try:
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(extract_dir)
        unzipped_exe = extract_dir / "Inkwell" / "Inkwell.exe"
        if not unzipped_exe.exists():
            raise SystemExit("解压后找不到 Inkwell/Inkwell.exe（zip 结构不对）")
        data_dir = Path(tempfile.mkdtemp(prefix="inkwell-unzip-data-"))
        try:
            result = subprocess.run(
                [str(unzipped_exe), "--selfcheck"],
                env=_clean_env(data_dir),
                timeout=180,
                capture_output=True,
                text=True,
                errors="replace",
            )
            lines = [line for line in log_lines(data_dir) if "[selfcheck]" in line]
            if result.returncode != 0 or not any("自检通过" in line for line in lines):
                raise SystemExit("解压后的产物自检未通过（发布包不可用）")
            print("      解压自检：通过（解压到新路径后仍可运行）", flush=True)
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)


def report() -> None:
    from backend.config import APP_VERSION

    print("[6/6] 完成", flush=True)
    print(f"      版本：{APP_VERSION}", flush=True)
    print(f"      入口：{EXE}", flush=True)
    print(f"      体积：{human_size(dir_size(DIST))}", flush=True)
    archive = ROOT / "dist" / f"Inkwell-{APP_VERSION}-win-x64.zip"
    if archive.exists():
        print(f"      发布包：{archive}", flush=True)
        print(f"      校验和：{ROOT / 'dist' / 'SHA256SUMS.txt'}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inkwell 阶段四打包")
    parser.add_argument(
        "--skip-check", action="store_true", help="只构建，不跑自检与启动验证"
    )
    parser.add_argument("--skip-launch", action="store_true", help="跳过真实启动验证")
    parser.add_argument("--skip-package", action="store_true", help="跳过发布 zip 打包")
    parser.add_argument("--keep", action="store_true", help="保留验证临时数据目录")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    build()
    if args.skip_check:
        print("[2/6] 跳过冻结自检与后续验证", flush=True)
    else:
        frozen_selfcheck(args.keep)
        if args.skip_launch:
            print("[3/6] 跳过真实启动验证", flush=True)
        else:
            launch_smoke(args.keep)
        webview2_guidance_smoke(args.keep)
    release_package(args.skip_package)
    report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
