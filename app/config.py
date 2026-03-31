from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SoftwareItem:
    name: str
    version: str
    download_url: str
    silent_args: str
    tutorial: str


def _require_str(obj: dict[str, Any], key: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"字段 {key} 必须是非空字符串")
    return value


def load_software_list(json_path: Path) -> list[SoftwareItem]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("配置文件根节点必须是对象")

    items = data.get("items")
    if not isinstance(items, list):
        raise ValueError("字段 items 必须是数组")

    result: list[SoftwareItem] = []
    for idx, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise ValueError(f"items[{idx}] 必须是对象")

        result.append(
            SoftwareItem(
                name=_require_str(raw, "name"),
                version=_require_str(raw, "version"),
                download_url=_require_str(raw, "download_url"),
                silent_args=str(raw.get("silent_args") or "").strip(),
                tutorial=str(raw.get("tutorial") or "").strip(),
            )
        )
    return result

