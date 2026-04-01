from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.config import SoftwareItem

# 自动扫描模式下无单独教程文件时的默认说明
DEFAULT_TUTORIAL = (
    "1) 点击【下载】将安装包保存到本机下载目录。\n"
    "2) 下载完成后点击【安装】，确认「立即安装」即可启动安装向导。\n"
    "3) 请根据安装程序提示完成安装；若需管理员权限，请在弹窗中选择允许。\n\n"
    "如遇安装失败，请联系 IT。"
)

_INSTALLER_EXT = {".exe", ".msi"}


@dataclass(frozen=True)
class CatalogDirNode:
    """目录节点：与共享目录层级一致，仅保存展示用文件夹名。"""

    display_name: str
    abs_path: str
    subdirs: tuple[CatalogDirNode, ...]
    installers: tuple[SoftwareItem, ...]


def _fmt_file_meta(path: Path) -> str:
    st = path.stat()
    mtime = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
    sz = st.st_size
    if sz >= 1024 * 1024:
        return f"{mtime} · {sz // (1024 * 1024)} MB"
    if sz >= 1024:
        return f"{mtime} · {sz // 1024} KB"
    return f"{mtime} · {sz} B"


def _item_from_installer(
    installer_path: Path,
    parent_folder_trail: tuple[str, ...],
    sig_parts: list[str],
) -> SoftwareItem:
    """parent_folder_trail 为从共享根到安装包所在目录的文件夹名（不含文件名）。"""
    st = installer_path.stat()
    sig_parts.append(f"{installer_path.resolve()}|{st.st_mtime_ns}|{st.st_size}")
    resolved = installer_path.resolve()
    breadcrumb = " › ".join(parent_folder_trail) if parent_folder_trail else ""
    return SoftwareItem(
        name=installer_path.name,
        version=_fmt_file_meta(installer_path),
        download_url=str(resolved),
        tutorial=DEFAULT_TUTORIAL,
        breadcrumb=breadcrumb,
    )


def _build_dir_node(
    dir_path: Path,
    folder_trail: tuple[str, ...],
    watch_dirs: list[str],
    sig_parts: list[str],
) -> CatalogDirNode | None:
    """folder_trail 含当前目录展示名，供子项拼 breadcrumb。"""
    watch_dirs.append(str(dir_path.resolve()))
    subnodes: list[CatalogDirNode] = []
    installers: list[SoftwareItem] = []

    try:
        children = list(dir_path.iterdir())
    except OSError:
        watch_dirs.pop()
        return None

    dirs = sorted((p for p in children if p.is_dir()), key=lambda p: p.name.casefold())
    files = sorted(
        (p for p in children if p.is_file() and p.suffix.lower() in _INSTALLER_EXT),
        key=lambda p: p.name.casefold(),
    )

    for d in dirs:
        sub = _build_dir_node(d, folder_trail + (d.name,), watch_dirs, sig_parts)
        if sub:
            subnodes.append(sub)

    for f in files:
        try:
            installers.append(_item_from_installer(f, folder_trail, sig_parts))
        except OSError:
            continue

    if not subnodes and not installers:
        watch_dirs.pop()  # 空目录不再监听
        return None

    return CatalogDirNode(
        display_name=dir_path.name,
        abs_path=str(dir_path.resolve()),
        subdirs=tuple(subnodes),
        installers=tuple(installers),
    )


def scan_share_root(
    share_root: Path,
) -> tuple[tuple[CatalogDirNode | SoftwareItem, ...], str, tuple[str, ...]]:
    """
    按 share_root 下多级目录生成顶层条目列表（子目录为 CatalogDirNode，根下安装包为 SoftwareItem）。
    返回 (顶层条目, 内容签名, 建议监听的目录路径序列)。
    """
    if not share_root.exists() or not share_root.is_dir():
        return (), "", ()

    watch_dirs: list[str] = [str(share_root.resolve())]
    sig_parts: list[str] = []
    top: list[CatalogDirNode | SoftwareItem] = []

    try:
        children = list(share_root.iterdir())
    except OSError:
        return (), "", (str(share_root.resolve()),)

    dirs = sorted((p for p in children if p.is_dir()), key=lambda p: p.name.casefold())
    loose = sorted(
        (p for p in children if p.is_file() and p.suffix.lower() in _INSTALLER_EXT),
        key=lambda p: p.name.casefold(),
    )

    for d in dirs:
        node = _build_dir_node(d, (d.name,), watch_dirs, sig_parts)
        if node:
            top.append(node)

    for f in loose:
        try:
            top.append(_item_from_installer(f, (), sig_parts))
        except OSError:
            continue

    signature = "\n".join(sorted(sig_parts))
    # 去重并稳定排序监听路径
    unique_watch = tuple(sorted(frozenset(watch_dirs)))
    return tuple(top), signature, unique_watch
