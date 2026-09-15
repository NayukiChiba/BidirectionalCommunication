"""
桌面内置后端冒烟测试

验证 sidecar 能在全新数据目录中自动迁移 SQLite、通过健康检查并接受注册。
"""

import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from buildBackend import BINARY_DIR, SIDECAR_NAME, getTargetTriple

START_TIMEOUT_SECONDS = 60


def reservePort() -> int:
    """申请一个当前可用的本地端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def waitUntilReady(baseUrl: str) -> None:
    """等待内置后端完成单文件解压、迁移和启动。"""
    deadline = time.monotonic() + START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"{baseUrl}/health/ready", timeout=1
            ) as response:
                payload = json.load(response)
                if response.status == 200 and payload == {"status": "ready"}:
                    return
        except OSError:
            time.sleep(0.25)
    raise TimeoutError("内置后端未在 60 秒内就绪")


def registerSmokeUser(baseUrl: str) -> None:
    """使用公开接口验证八位密码注册。"""
    request = urllib.request.Request(
        f"{baseUrl}/auth/register",
        data=json.dumps({"username": "sidecar-smoke", "password": "12345678"}).encode(
            "utf-8"
        ),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = json.load(response)
    if response.status != 201 or payload["username"] != "sidecar-smoke":
        raise RuntimeError("内置后端注册冒烟测试失败")


def runSmokeTest() -> None:
    """启动 sidecar 并验证无外部服务的完整最小闭环。"""
    executableSuffix = ".exe" if os.name == "nt" else ""
    executable = BINARY_DIR / f"{SIDECAR_NAME}-{getTargetTriple()}{executableSuffix}"
    if not executable.is_file():
        raise FileNotFoundError(f"找不到内置后端：{executable}")
    port = reservePort()
    baseUrl = f"http://127.0.0.1:{port}"
    creationFlags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with tempfile.TemporaryDirectory(prefix="bidirectional-sidecar-") as dataDirectory:
        process = subprocess.Popen(
            [
                str(executable),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--data-dir",
                dataDirectory,
                "--parent-pid",
                str(os.getpid()),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationFlags,
        )
        try:
            waitUntilReady(baseUrl)
            registerSmokeUser(baseUrl)
            if not (Path(dataDirectory) / "chat.sqlite3").is_file():
                raise RuntimeError("内置后端没有创建 SQLite 数据库")
        finally:
            terminateProcessTree(process)
    print("内置后端冒烟测试通过")


def terminateProcessTree(process: subprocess.Popen[bytes]) -> None:
    """终止 PyInstaller bootloader 及其内层 Python 进程。"""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> None:
    """命令行入口。"""
    runSmokeTest()


if __name__ == "__main__":
    main()
