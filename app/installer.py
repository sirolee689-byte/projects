from __future__ import annotations

import os
import subprocess
from pathlib import Path


def run_installer_interactive(installer_path: Path) -> None:
    """以系统默认方式启动安装包（等同资源管理器中双击），会弹出安装向导。"""
    if not installer_path.exists():
        raise FileNotFoundError(str(installer_path))
    os.startfile(str(installer_path))


def open_download_folder(path: Path) -> None:
    """在资源管理器中打开下载所在文件夹（path 为文件时打开其上级目录）。"""
    target = path.resolve()
    folder = target.parent if target.is_file() else target
    subprocess.Popen(["explorer", str(folder)], close_fds=True)
