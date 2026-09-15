"""把 SemVer 内部版本转换为对外发布使用的两段式版本名。"""

import json
from pathlib import Path

DESKTOP_DIR = Path(__file__).resolve().parent
PACKAGE_FILE = DESKTOP_DIR / "package.json"
INSTALLER_DIR = DESKTOP_DIR / "src-tauri" / "target" / "release" / "bundle" / "nsis"


def getVersions() -> tuple[str, str]:
    """返回内部 SemVer 和对外展示版本。"""
    package = json.loads(PACKAGE_FILE.read_text(encoding="utf-8"))
    semanticVersion = str(package["version"])
    versionParts = semanticVersion.split(".")
    displayVersion = (
        ".".join(versionParts[:2])
        if len(versionParts) == 3 and versionParts[2] == "0"
        else semanticVersion
    )
    return semanticVersion, displayVersion


def renameInstallers() -> list[Path]:
    """重命名当前版本的全部 NSIS 安装程序。"""
    semanticVersion, displayVersion = getVersions()
    renamedInstallers: list[Path] = []
    for installer in INSTALLER_DIR.glob(f"*_{semanticVersion}_*-setup.exe"):
        targetName = installer.name.replace(
            f"_{semanticVersion}_",
            f"_{displayVersion}_",
        )
        target = installer.with_name(targetName)
        installer.replace(target)
        renamedInstallers.append(target)
    if not renamedInstallers:
        raise FileNotFoundError("没有找到需要重命名的 NSIS 安装程序")
    return renamedInstallers


def main() -> None:
    """命令行入口。"""
    for installer in renameInstallers():
        print(f"发布安装程序：{installer}")


if __name__ == "__main__":
    main()
