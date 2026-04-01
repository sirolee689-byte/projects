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
    EXE：使用 silent_args（按空格拆分追加到命令行）。
    MSI：若无 silent_args，则使用 msiexec /i ... /qn；若有则作为 msiexec 的附加参数追加。
    """
    if not exe_path.exists():
        raise FileNotFoundError(str(exe_path))

    suffix = exe_path.suffix.lower()
    if suffix == ".msi":
        cmd = ["msiexec", "/i", str(exe_path)]
        extra = silent_args.strip()
        if extra:
            cmd.extend(extra.split())
        else:
            cmd.append("/qn")
        return subprocess.Popen(
            cmd,
            cwd=str(exe_path.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            close_fds=True,
        )

    cmd = [str(exe_path)]
    if silent_args.strip():
        cmd.extend(silent_args.split())

    return subprocess.Popen(
        cmd,
        cwd=str(exe_path.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        close_fds=True,
    )

