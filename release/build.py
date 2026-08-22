"""Build the Windows onedir distribution without side effects on import."""

import io
import os
import shutil
import subprocess
import sys
from pathlib import Path


RELEASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = RELEASE_DIR.parent
DIST_DIR = RELEASE_DIR / "dist"
APP_DIR = DIST_DIR / "SyncClipboard"
WORK_DIR = RELEASE_DIR / "build_cache"
SPEC_DIR = RELEASE_DIR / "spec"
ENTRY_SCRIPT = PROJECT_ROOT / "gui" / "run.py"
ICON_FILE = PROJECT_ROOT / "gui" / "icon" / "icon-active.png"


def _configure_stdout():
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def _customtkinter_dir():
    try:
        import customtkinter
    except ImportError as exc:
        raise RuntimeError("请先安装 requirements.txt 中的 customtkinter") from exc
    return Path(customtkinter.__file__).resolve().parent


def build_command(customtkinter_dir=None):
    """Return the PyInstaller command so CI can inspect it without building."""
    customtkinter_dir = Path(customtkinter_dir or _customtkinter_dir()).resolve()
    return [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name=SyncClipboard",
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(WORK_DIR),
        "--specpath",
        str(SPEC_DIR),
        f"--icon={ICON_FILE}",
        "--paths",
        str(PROJECT_ROOT),
        "--hidden-import=win32clipboard",
        "--hidden-import=watchdog",
        "--hidden-import=watchdog.observers",
        "--hidden-import=watchdog.events",
        "--add-data",
        f"{customtkinter_dir}{os.pathsep}customtkinter",
        str(ENTRY_SCRIPT),
    ]


def clean_release_outputs():
    print("[Clean] 清理旧构建输出...")
    for item in RELEASE_DIR.iterdir():
        if item.name in {"build.py", "bat", "macrodroid"}:
            continue
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
            print(f"  已删除目录: {item}")
        else:
            item.unlink(missing_ok=True)
            print(f"  已删除文件: {item}")


def copy_runtime_assets():
    exe_path = APP_DIR / "SyncClipboard.exe"
    if not exe_path.exists():
        raise RuntimeError("未找到生成的 exe，打包可能失败")

    # Keep templates separate from mutable runtime config, so extracting a new
    # release over an existing folder does not overwrite the user's settings.
    src_config = PROJECT_ROOT / "config" / "example"
    dst_config = APP_DIR / "config" / "example"
    shutil.copytree(src_config, dst_config, dirs_exist_ok=True)
    print(f"  [OK] 配置模板 -> {dst_config}")

    dst_icon = APP_DIR / "gui" / "icon"
    dst_icon.mkdir(parents=True, exist_ok=True)
    for filename in ("icon.ico", "icon-active.png", "icon-stop.png"):
        source = PROJECT_ROOT / "gui" / "icon" / filename
        if source.exists():
            shutil.copy2(source, dst_icon / filename)
    print(f"  [OK] 图标 -> {dst_icon}")

    src_bat = RELEASE_DIR / "bat"
    if src_bat.exists():
        for file in src_bat.glob("*.bat"):
            shutil.copy2(file, APP_DIR / file.name)
        print(f"  [OK] bat 文件 -> {APP_DIR}")
    return exe_path


def main():
    _configure_stdout()
    clean_release_outputs()
    print("\n[Build] 开始 PyInstaller onedir 打包（窗口模式）...")
    subprocess.run(build_command(), check=True)
    print("PyInstaller 打包完成。")

    print("\n[Copy] 复制运行时资源...")
    exe_path = copy_runtime_assets()
    print("\n[Success] 打包成功！")
    print(f"应用位置: {exe_path}")
    print(f"发布时请将整个 {APP_DIR} 文件夹一起分发。")


if __name__ == "__main__":
    main()
