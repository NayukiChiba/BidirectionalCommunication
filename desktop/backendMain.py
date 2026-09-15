"""
桌面内置后端入口

功能：
1. 使用桌面应用数据目录保存 SQLite
2. 自动执行数据库迁移
3. 强制关闭外部 PostgreSQL 和 Redis 依赖
"""

import argparse
import ctypes
import os
import sys
import threading
import time
import traceback
from pathlib import Path

from bootstrap import createStandaloneApp, runStandaloneApp


def parseArguments() -> argparse.Namespace:
    """解析 Tauri sidecar 传入的本地监听参数。"""
    parser = argparse.ArgumentParser(description="双向通信桌面内置后端")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--parent-pid", type=int)
    return parser.parse_args()


def main() -> None:
    """迁移内置 SQLite 并启动本地 FastAPI 服务。"""
    arguments = parseArguments()
    configureWindowedLogStream(arguments.data_dir)
    if arguments.parent_pid is not None:
        startParentMonitor(arguments.parent_pid)
    try:
        app = createStandaloneApp(
            dataDirectory=arguments.data_dir,
            forceLocalServices=True,
        )
        runStandaloneApp(
            app,
            host=arguments.host,
            port=arguments.port,
        )
    except Exception:
        arguments.data_dir.mkdir(parents=True, exist_ok=True)
        errorLog = arguments.data_dir / "backend-error.log"
        errorLog.write_text(traceback.format_exc(), encoding="utf-8")
        raise


def configureWindowedLogStream(dataDirectory: Path) -> None:
    """无控制台运行时把服务日志写入应用数据目录。"""
    if sys.stdout is not None and sys.stderr is not None:
        return
    dataDirectory.mkdir(parents=True, exist_ok=True)
    logStream = (dataDirectory / "backend.log").open(
        "a",
        encoding="utf-8",
        buffering=1,
    )
    if sys.stdout is None:
        sys.stdout = logStream
    if sys.stderr is None:
        sys.stderr = logStream


def startParentMonitor(parentProcessId: int) -> None:
    """桌面主进程退出后终止内置后端。"""

    def monitorParent() -> None:
        while isProcessRunning(parentProcessId):
            time.sleep(1)
        os._exit(0)

    monitorThread = threading.Thread(
        target=monitorParent,
        name="desktop-parent-monitor",
        daemon=True,
    )
    monitorThread.start()


def isProcessRunning(processId: int) -> bool:
    """不发送信号地检查指定进程是否存在。"""
    if os.name == "nt":
        from ctypes import wintypes

        synchronizeAccess = 0x00100000
        waitTimeout = 0x00000102
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(synchronizeAccess, False, processId)
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == waitTimeout
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(processId, 0)
    except OSError:
        return False
    return True


if __name__ == "__main__":
    main()
