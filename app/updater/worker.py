from __future__ import annotations

import ctypes
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QThread, Signal

import requests

from app.updater.custom_sources import build_custom_provider_map, load_custom_sources
from app.updater.providers import LatestRelease, get_provider_map
from app.updater.versioning import Version, compare_versions, format_version, parse_version_from_filename


@dataclass(frozen=True)
class UpdateItem:
    software_key: str
    folder: Path
    installers: tuple[Path, ...]


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def _iter_installers(root: Path) -> list[Path]:
    result: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".exe", ".msi"}:
            continue
        result.append(p)
    return result


def _normalize_software_key(raw: str) -> str:
    """
    归一化软件名称：
    - 支持从常见文件名关键词映射到统一 key（用于匹配自定义更新源）。
    """
    s = (raw or "").strip()
    if not s:
        return ""
    low = s.casefold()
    if "wechat" in low or "weixin" in low:
        return "微信"
    if low.startswith("qq") or "qqnt" in low or "tencentqq" in low:
        return "QQ"
    if "chrome" in low:
        return "Chrome"
    if "vscode" in low or low == "code" or "visualstudiocode" in low:
        return "VSCode"
    if "wps" in low:
        return "WPS"
    return s


def _group_update_items(common_root: Path) -> list[UpdateItem]:
    installers = _iter_installers(common_root)
    groups: dict[str, list[Path]] = {}
    for f in installers:
        try:
            rel = f.relative_to(common_root)
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) >= 2:
            key = _normalize_software_key(parts[0])
        else:
            key = _normalize_software_key(f.stem)
        groups.setdefault(key, []).append(f)

    items: list[UpdateItem] = []
    for key, files in groups.items():
        # folder 为 key 对应的一层目录；若文件在 common_root 根下，则 folder=common_root
        folder = (common_root / key) if (common_root / key).is_dir() else common_root
        files_sorted = sorted(files, key=lambda p: p.name.casefold())
        items.append(UpdateItem(key, folder, tuple(files_sorted)))

    items.sort(key=lambda it: it.software_key.casefold())
    return items


def _best_local_version(paths: tuple[Path, ...]) -> tuple[Version | None, Path | None]:
    best: Version | None = None
    best_path: Path | None = None
    for p in paths:
        v = parse_version_from_filename(p.name)
        if compare_versions(best, v) < 0:
            best = v
            best_path = p
    # 如果都解析不到版本号，则返回 (None, 第一个文件) 作为“未知版本”
    if best is None and paths:
        return None, paths[0]
    return best, best_path


def _stream_download(url: str, dest_path: Path, progress_cb=None, timeout_seconds: int = 30) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=timeout_seconds) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        downloaded = 0
        with open(dest_path, "wb") as wf:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                wf.write(chunk)
                downloaded += len(chunk)
                if progress_cb:
                    progress_cb(downloaded, total)


def _replace_installers_in_folder(folder: Path, keep_file: Path, others: list[Path]) -> None:
    """
    替换策略：把旧安装包移动到 __backup__，只保留 keep_file。
    """
    backup_dir = folder / "__backup__"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for p in others:
        if not p.exists():
            continue
        if p.resolve() == keep_file.resolve():
            continue
        target = backup_dir / p.name
        # 避免重名覆盖
        if target.exists():
            stem = p.stem
            suf = p.suffix
            i = 1
            while True:
                cand = backup_dir / f"{stem}.bak{i}{suf}"
                if not cand.exists():
                    target = cand
                    break
                i += 1
        p.replace(target)


class CommonSoftwareUpdateWorker(QThread):
    progress = Signal(int, int)  # done, total
    current = Signal(str)  # 当前软件
    detail = Signal(str)  # 日志行
    file_progress = Signal(int, int)  # downloaded, total
    finished_summary = Signal(int, int, int)  # updated, skipped, failed
    failed_fatal = Signal(str)

    def __init__(
        self,
        share_root: Path,
        custom_sources_path: Path | None = None,
        target_software_key: str | None = None,
    ):
        super().__init__()
        self._share_root = share_root
        self._custom_sources_path = custom_sources_path
        self._target_software_key = (target_software_key or "").strip() or None

    def run(self) -> None:
        if not is_admin():
            self.failed_fatal.emit("仅管理员可执行「常用软件自动更新」。请用管理员权限运行本程序。")
            return

        common_root = (self._share_root / "常用软件").resolve()
        if not common_root.exists() or not common_root.is_dir():
            self.failed_fatal.emit(f"未找到常用软件目录：{common_root}")
            return

        # 写权限探测
        try:
            tmp = common_root / f".__write_test__{os.getpid()}.tmp"
            tmp.write_text("ok", encoding="utf-8")
            tmp.unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001
            self.failed_fatal.emit(f"无共享目录写权限：{common_root}\n{e}")
            return

        provider_map = get_provider_map()
        if self._custom_sources_path:
            try:
                custom_items = load_custom_sources(self._custom_sources_path)
                provider_map.update(build_custom_provider_map(custom_items))  # 自定义覆盖内置
                if custom_items:
                    self.detail.emit(f"[配置] 已加载自定义更新源：{self._custom_sources_path}")
            except Exception as e:  # noqa: BLE001
                self.detail.emit(f"[警告] 读取自定义更新源失败：{self._custom_sources_path} - {e}")
        items = _group_update_items(common_root)
        if self._target_software_key:
            items = [it for it in items if it.software_key == self._target_software_key]
        total = len(items)
        done = 0
        updated = 0
        skipped = 0
        failed = 0

        if total == 0:
            if self._target_software_key:
                self.detail.emit(f"未找到可更新的软件：{self._target_software_key}")
            else:
                self.detail.emit("常用软件目录下未发现任何 .exe/.msi 安装包。")
            self.finished_summary.emit(0, 0, 0)
            return

        for item in items:
            done += 1
            self.progress.emit(done, total)
            self.current.emit(item.software_key)

            prov = provider_map.get(item.software_key)
            if not prov:
                skipped += 1
                self.detail.emit(f"[跳过] 未配置更新源：{item.software_key}")
                continue

            try:
                latest = prov.get_latest()
            except Exception as e:  # noqa: BLE001
                failed += 1
                self.detail.emit(f"[失败] 获取最新版失败：{item.software_key} - {e}")
                continue

            local_v, local_best = _best_local_version(item.installers)
            if local_v is None:
                self.detail.emit(f"[提示] 本地版本未知（文件名无版本号）：{item.software_key}")

            cmp = compare_versions(local_v, latest.version)
            if cmp >= 0 and local_v is not None:
                skipped += 1
                self.detail.emit(
                    f"[已最新] {item.software_key} 本地 {format_version(local_v)} >= 官网 {format_version(latest.version)}"
                )
                continue

            # 需要更新：下载到临时文件，再替换/清理
            try:
                # 先下载到本机临时目录，避免直接写共享目录导致半成品
                with tempfile.TemporaryDirectory(prefix="ub_ai_update_") as td:
                    tmp_local = Path(td) / latest.suggested_filename
                    self.detail.emit(f"[更新] {item.software_key} → 下载 {latest.download_url}")
                    _stream_download(latest.download_url, tmp_local, progress_cb=lambda d, t: self.file_progress.emit(d, t))

                    # 写入共享目录：先写 .tmp 再 replace
                    dest = item.folder / latest.suggested_filename
                    tmp_share = dest.with_suffix(dest.suffix + ".tmp")
                    shutil.copyfile(tmp_local, tmp_share)
                    tmp_share.replace(dest)

                # 备份并移走旧安装包
                old_list = list(item.installers)
                _replace_installers_in_folder(item.folder, dest, old_list)

                updated += 1
                self.detail.emit(f"[完成] {item.software_key} 已更新到 {format_version(latest.version)}")
            except Exception as e:  # noqa: BLE001
                failed += 1
                self.detail.emit(f"[失败] 更新失败：{item.software_key} - {e}")

        self.finished_summary.emit(updated, skipped, failed)

