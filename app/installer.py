from __future__ import annotations

import os
import subprocess
from pathlib import Path


def open_in_explorer(path: Path) -> None:
    """打开资源管理器并定位到目标文件或文件夹。"""
    if path.is_file():
        subprocess.Popen(["explorer", "/select,", str(path)], close_fds=True)
    else:
        subprocess.Popen(["explorer", str(path)], close_fds=True)


def run_silent_installer(exe_path: Path, silent_args: str) -> subprocess.Popen:
    """
    以后台方式执行安装程序（不阻塞 UI）。
    注意：不同安装包的静默参数不同，silent_args 由配置提供。
    """
    if not exe_path.exists():
        raise FileNotFoundError(str(exe_path))

    cmd = [str(exe_path)]
    if silent_args:
        # 允许用户在配置里写多个参数（简单按空格拆分）
        cmd += silent_args.split()

    return subprocess.Popen(
        cmd,
        cwd=str(exe_path.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        close_fds=True,
    )

