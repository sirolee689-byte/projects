from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SoftwareItem:
    """安装包条目：name 为文件名；breadcrumb 为相对共享根的纯文件夹名层级（不含路径分隔符样式）。"""

    name: str
    version: str
    download_url: str
    tutorial: str
    breadcrumb: str = ""
