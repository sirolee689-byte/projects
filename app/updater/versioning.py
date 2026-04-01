from __future__ import annotations

import re


Version = tuple[int, ...]


_VERSION_RE = re.compile(r"(\d+(?:\.\d+){1,4})")


def parse_version_from_filename(filename: str) -> Version | None:
    """
    从文件名中提取版本号（形如 1.2 / 1.2.3 / 123.0.0.0）。
    返回 (major, minor, patch, ...) 元组。
    """
    m = _VERSION_RE.search(filename)
    if not m:
        return None
    parts = m.group(1).split(".")
    try:
        nums = tuple(int(p) for p in parts)
    except ValueError:
        return None
    return nums if nums else None


def compare_versions(a: Version | None, b: Version | None) -> int:
    """
    比较版本号。
    - None 视为未知（最小），用于“文件名无版本号”的兜底。
    返回：-1 / 0 / 1
    """
    if a is None and b is None:
        return 0
    if a is None:
        return -1
    if b is None:
        return 1
    max_len = max(len(a), len(b))
    aa = a + (0,) * (max_len - len(a))
    bb = b + (0,) * (max_len - len(b))
    if aa < bb:
        return -1
    if aa > bb:
        return 1
    return 0


def format_version(v: Version) -> str:
    return ".".join(str(x) for x in v)

