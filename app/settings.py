from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AppSettings:
    download_dir: Path
    share_root: str


def load_app_settings(path: Path) -> AppSettings:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config.json 根节点必须是对象")

    download_dir = data.get("download_dir")
    if not isinstance(download_dir, str) or not download_dir.strip():
        raise ValueError("config.json 字段 download_dir 必须是非空字符串")

    share_root = data.get("share_root")
    if not isinstance(share_root, str) or not share_root.strip():
        raise ValueError("config.json 字段 share_root 必须是非空字符串")

    return AppSettings(download_dir=Path(download_dir), share_root=share_root)

