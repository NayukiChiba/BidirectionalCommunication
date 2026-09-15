"""
桌面内置后端构建工具

功能：
1. 使用 PyInstaller 打包 Python/FastAPI 后端
2. 附带 Alembic 配置和迁移脚本
3. 按 Tauri 目标三元组生成 sidecar 文件名

使用方法：
    python desktop/buildBackend.py
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DESKTOP_DIR = PROJECT_ROOT / "desktop"
TAURI_DIR = DESKTOP_DIR / "src-tauri"
BUILD_DIR = DESKTOP_DIR / ".backend-build"
DIST_DIR = DESKTOP_DIR / ".backend-dist"
BINARY_DIR = TAURI_DIR / "binaries"
SIDECAR_NAME = "bidirectional-backend"


def getTargetTriple() -> str:
    """读取当前 Rust 工具链使用的目标三元组。"""
    result = subprocess.run(
        ["rustc", "--print", "host-tuple"],
        check=True,
        capture_output=True,
        text=True,
    )
    targetTriple = result.stdout.strip()
    if not targetTriple:
        raise RuntimeError("Rust 未返回目标三元组")
    return targetTriple


def buildBackend() -> Path:
    """构建并返回符合 Tauri 命名约定的 sidecar 路径。"""
    targetTriple = getTargetTriple()
    executableSuffix = ".exe" if os.name == "nt" else ""
    windowMode = (
        "--console" if os.getenv("BACKEND_BUILD_CONSOLE") == "1" else "--windowed"
    )
    BINARY_DIR.mkdir(parents=True, exist_ok=True)
    addDataSeparator = os.pathsep
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        windowMode,
        "--name",
        SIDECAR_NAME,
        "--paths",
        str(PROJECT_ROOT),
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR),
        "--specpath",
        str(BUILD_DIR),
        "--add-data",
        f"{PROJECT_ROOT / 'migrations'}{addDataSeparator}migrations",
        "--add-data",
        f"{PROJECT_ROOT / 'alembic.ini'}{addDataSeparator}.",
        "--add-data",
        f"{PROJECT_ROOT / 'pyproject.toml'}{addDataSeparator}.",
        "--collect-all",
        "argon2",
        "--collect-all",
        "pwdlib",
        "--hidden-import",
        "aiosqlite",
        "--hidden-import",
        "sqlalchemy.dialects.sqlite.aiosqlite",
        "--hidden-import",
        "sqlalchemy.dialects.sqlite.pysqlite",
        "--hidden-import",
        "uvicorn.lifespan.on",
        "--hidden-import",
        "uvicorn.loops.asyncio",
        "--hidden-import",
        "uvicorn.protocols.http.httptools_impl",
        "--hidden-import",
        "uvicorn.protocols.websockets.websockets_impl",
        "--exclude-module",
        "IPython",
        "--exclude-module",
        "pytest",
        str(DESKTOP_DIR / "backendMain.py"),
    ]
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)

    builtExecutable = DIST_DIR / f"{SIDECAR_NAME}{executableSuffix}"
    targetExecutable = BINARY_DIR / f"{SIDECAR_NAME}-{targetTriple}{executableSuffix}"
    shutil.copy2(builtExecutable, targetExecutable)
    print("Backend sidecar build completed")
    return targetExecutable


def main() -> None:
    """命令行入口。"""
    buildBackend()


if __name__ == "__main__":
    main()
