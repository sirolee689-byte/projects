from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

import requests


def _filename_from_source(source: str) -> str:
    # UNC：\\server\share\path\file.exe
    if source.startswith("\\\\") or source.startswith("//"):
        name = os.path.basename(source.replace("/", "\\"))
        return name or "download.bin"

    parsed = urlparse(source)
    name = os.path.basename(parsed.path)
    return name or "download.bin"


def expected_local_download_path(source: str, dest_dir: Path) -> Path:
    """与 download_streaming 写入规则一致的本地下载路径（用于判断是否已存在）。"""
    return dest_dir / _filename_from_source(source)


def download_streaming(
    source: str,
    dest_dir: Path,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    timeout_seconds: int = 30,
) -> Path:
    """
    流式获取文件到目标目录。
    - 支持 HTTP/HTTPS（requests 流式下载）
    - 支持 UNC 路径（从共享目录流式复制）

    progress_cb：回调 (downloaded_bytes, total_bytes)
    - HTTP：total_bytes 可能为 0（服务端未返回 Content-Length）
    - UNC：total_bytes 来自文件大小（若可获取）
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = expected_local_download_path(source, dest_dir)

    if source.startswith("\\\\") or source.startswith("//"):
        src_path = Path(source)
        if not src_path.exists():
            raise FileNotFoundError(f"共享路径不存在或无权限：{source}")

        total = src_path.stat().st_size
        downloaded = 0

        with open(src_path, "rb") as rf, open(dest_path, "wb") as wf:
            while True:
                chunk = rf.read(1024 * 256)
                if not chunk:
                    break
                wf.write(chunk)
                downloaded += len(chunk)
                if progress_cb:
                    progress_cb(downloaded, total)

        return dest_path

    with requests.get(source, stream=True, timeout=timeout_seconds) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        downloaded = 0

        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                if progress_cb:
                    progress_cb(downloaded, total)

    return dest_path

