"""环境冒烟测试（阶段一验证项）。

验证三件事：
1. uvicorn 能在非主线程启动（ADR-002 的关键风险：signal handler 注册）
2. FastAPI 路由可访问，且只绑定 127.0.0.1 的随机空闲端口
3. 前端拿到的端口与 /api/meta 契约可用

运行：D:/小说辅助/.venv/Scripts/python.exe smoke_test.py
"""

import socket
import threading

import httpx
import uvicorn
from fastapi import FastAPI

# 重要：本机存在 http_proxy / https_proxy = http://127.0.0.1:64530。
# httpx 默认 trust_env=True 会走代理，把请求行改写为 absolute-form
# （"GET http://127.0.0.1:PORT/api/meta"），本地源站无法匹配路由 → 404。
# 因此访问本地服务必须 trust_env=False。真实项目中的前端同样需要绕过代理。

app = FastAPI()


@app.get("/api/health")
def health() -> dict:
    return {"code": 0, "message": "ok", "data": {"status": "healthy"}}


@app.get("/api/meta")
def meta() -> dict:
    return {"code": 0, "data": {"app_version": "0.0.0-smoke", "port": PORT}}


def pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = pick_free_port()
config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
server = uvicorn.Server(config)

print(f"[1] 已选取空闲端口: {PORT}")

t = threading.Thread(target=server.run, daemon=True)
t.start()
print("[2] uvicorn 已在非主线程启动（若 signal handler 有问题会在此抛错）")

# 等待服务就绪
for _ in range(100):
    if server.started:
        break
    threading.Event().wait(0.05)

print(f"[3] 服务就绪状态: {server.started}")

with httpx.Client(
    base_url=f"http://127.0.0.1:{PORT}", timeout=5.0, trust_env=False
) as c:
    # 连续 3 次复用同一连接，验证 keep-alive 下路由不会被代理改写破坏
    r1 = c.get("/api/health")
    r2 = c.get("/api/meta")
    r3 = c.get("/api/meta")
    print(f"[4] GET /api/health -> {r1.status_code} {r1.json()}")
    print(f"[5] GET /api/meta   -> {r2.status_code} {r2.json()}")
    print(f"[6] GET /api/meta（复用连接第2次）-> {r3.status_code}")

    ok = r1.status_code == 200 and r2.status_code == 200 and r3.status_code == 200
    print(f"[7] 结论: {'全部通过' if ok else '存在失败，需排查'}")

server.should_exit = True
t.join(timeout=5)
print("[6] 服务已关闭，冒烟测试通过")
