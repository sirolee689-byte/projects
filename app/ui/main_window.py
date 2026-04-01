from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileIconProvider,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QMenu,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from app.catalog import CatalogDirNode, scan_share_root
from app.config import SoftwareItem
from app.downloader import download_streaming, expected_local_download_path
from app.installer import open_download_folder, run_installer_interactive
from app.updater.worker import CommonSoftwareUpdateWorker, is_admin
from app.updater.custom_sources import CustomSource, load_custom_sources, normalize_software_key, save_custom_sources

# 浅色界面样式（零外部资源）
_APP_STYLESHEET = """
QWidget#CentralRoot {
    background-color: #eef1f6;
}
QFrame#LeftCard, QFrame#RightCard {
    background-color: #ffffff;
    border: 1px solid #dde2ea;
    border-radius: 10px;
}
QTreeWidget {
    background: #fbfcfe;
    border: none;
    border-radius: 8px;
    padding: 4px;
    outline: none;
    font-size: 13px;
    color: #1a1a1a;
}
QTreeWidget::item {
    padding: 6px 6px;
    min-height: 22px;
    border-radius: 5px;
    color: #1a1a1a;
}
QTreeWidget::item:selected {
    background-color: #d8e5ff;
    color: #142c52;
}
QTreeWidget::item:hover:!selected {
    background-color: #f0f3f8;
    color: #1a1a1a;
}
QHeaderView::section {
    background-color: #f4f6fa;
    color: #3d4f6f;
    padding: 9px 8px;
    border: none;
    border-bottom: 1px solid #e5e9f0;
    font-weight: 600;
    font-size: 12px;
}
QLineEdit#SearchBox {
    background-color: #fbfcfe;
    border: 1px solid #e5e9f0;
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 13px;
    color: #1a1a1a;
}
QLineEdit#SearchBox:focus {
    border: 1px solid #9bb8f6;
    background-color: #ffffff;
}
QLabel#TitleLabel {
    font-size: 18px;
    font-weight: 600;
    color: #1a2233;
    padding-bottom: 2px;
}
QLabel#MetaLabel {
    color: #5a6578;
    font-size: 12px;
}
QLabel#SectionLabel {
    color: #6b778c;
    font-size: 12px;
    font-weight: 600;
    margin-top: 4px;
}
QTextEdit {
    background-color: #fafbfd;
    border: 1px solid #e5e9f0;
    border-radius: 8px;
    padding: 10px;
    font-size: 13px;
    color: #2c3340;
}
QPushButton {
    padding: 8px 18px;
    border-radius: 7px;
    font-weight: 600;
    font-size: 13px;
}
QPushButton#BtnPrimary {
    background-color: #2563eb;
    color: #ffffff;
    border: none;
}
QPushButton#BtnPrimary:hover { background-color: #1d4ed8; }
QPushButton#BtnPrimary:pressed { background-color: #1e40af; }
QPushButton#BtnPrimary:disabled { background-color: #93b4f0; color: #f1f5ff; }
QPushButton#BtnSecondary {
    background-color: #ffffff;
    color: #2563eb;
    border: 1px solid #c7d7f5;
}
QPushButton#BtnSecondary:hover { background-color: #f0f5ff; }
QPushButton#BtnGhost {
    background-color: transparent;
    color: #5a6578;
    border: 1px solid #dde2ea;
}
QPushButton#BtnGhost:hover { background-color: #f4f6fa; color: #2c3340; }
QPushButton#BtnInstall {
    background-color: #0d9488;
    color: #ffffff;
    border: none;
}
QPushButton#BtnInstall:hover { background-color: #0f766e; }
QPushButton#BtnInstall:disabled { background-color: #99d5cf; color: #f0fdfa; }
QProgressBar {
    border: none;
    border-radius: 5px;
    background-color: #e8ecf2;
    height: 8px;
    text-align: center;
    font-size: 11px;
}
QProgressBar::chunk {
    border-radius: 5px;
    background-color: #2563eb;
}
"""


class DownloadWorker(QThread):
    progress = Signal(int, int)  # downloaded, total
    finished_ok = Signal(str)  # file path
    failed = Signal(str)  # error message

    def __init__(self, url: str, dest_dir: Path):
        super().__init__()
        self._url = url
        self._dest_dir = dest_dir

    def run(self) -> None:
        try:
            path = download_streaming(
                self._url,
                self._dest_dir,
                progress_cb=lambda d, t: self.progress.emit(d, t),
            )
            self.finished_ok.emit(str(path))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class MainWindow(QWidget):
    def __init__(self, share_root: Path, download_dir: Path):
        super().__init__()
        self.setObjectName("CentralRoot")
        self.setWindowTitle("内网软件助手")
        self.resize(1020, 640)

        self._share_root = share_root
        self._download_dir = download_dir
        self._selected: SoftwareItem | None = None
        self._last_download_path: Path | None = None
        self._catalog_sig: str | None = None
        self._watch_dir_list: tuple[str, ...] = ()

        prov = QFileIconProvider()
        self._folder_icon = prov.icon(QFileIconProvider.IconType.Folder)
        self._file_icon = prov.icon(QFileIconProvider.IconType.File)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["软件目录"])
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tree.setUniformRowHeights(True)
        self._tree.setAnimated(True)
        self._tree.setIndentation(18)
        self._tree.currentItemChanged.connect(self._on_tree_select)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_context_menu)

        self._search = QLineEdit()
        self._search.setObjectName("SearchBox")
        self._search.setPlaceholderText("搜索软件或文件夹（支持模糊匹配）")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)

        self._btn_refresh = QPushButton("刷新目录")
        self._btn_refresh.setObjectName("BtnGhost")
        self._btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_refresh.clicked.connect(self._force_refresh_catalog)

        self._title = QLabel("正在加载目录…")
        self._title.setObjectName("TitleLabel")

        self._meta = QLabel("")
        self._meta.setObjectName("MetaLabel")
        self._meta.setWordWrap(True)

        sec_tutorial = QLabel("安装说明")
        sec_tutorial.setObjectName("SectionLabel")

        self._tutorial = QTextEdit()
        self._tutorial.setReadOnly(True)
        self._tutorial.setMinimumHeight(160)

        self._btn_download = QPushButton("下载")
        self._btn_download.setObjectName("BtnPrimary")
        self._btn_download.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_download.clicked.connect(self._on_download_clicked)

        self._btn_install = QPushButton("安装")
        self._btn_install.setObjectName("BtnInstall")
        self._btn_install.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_install.clicked.connect(self._on_install_clicked)
        self._btn_install.setEnabled(False)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)

        left_inner = QVBoxLayout()
        left_inner.setContentsMargins(14, 14, 14, 14)
        left_inner.setSpacing(10)
        left_inner.addWidget(self._search, 0)
        left_inner.addWidget(self._tree, 1)
        left_inner.addWidget(self._btn_refresh, 0, Qt.AlignmentFlag.AlignLeft)

        left_card = QFrame()
        left_card.setObjectName("LeftCard")
        left_card.setLayout(left_inner)
        left_card.setMinimumWidth(300)
        left_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        right_inner = QVBoxLayout()
        right_inner.setContentsMargins(18, 18, 18, 18)
        right_inner.setSpacing(10)
        right_inner.addWidget(self._title)
        right_inner.addWidget(self._meta)
        right_inner.addWidget(sec_tutorial)
        right_inner.addWidget(self._tutorial, 1)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addWidget(self._btn_download)
        actions.addWidget(self._btn_install)
        actions.addStretch(1)
        right_inner.addLayout(actions)
        right_inner.addWidget(self._progress)

        right_card = QFrame()
        right_card.setObjectName("RightCard")
        right_card.setLayout(right_inner)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_card)
        splitter.addWidget(right_card)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([312, 708])
        splitter.setHandleWidth(10)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.addWidget(splitter)

        self.setStyleSheet(_APP_STYLESHEET)

        self._worker: DownloadWorker | None = None
        self._update_worker: CommonSoftwareUpdateWorker | None = None

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(400)
        self._debounce.timeout.connect(self._try_refresh_catalog)

        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._schedule_refresh)
        self._watcher.fileChanged.connect(self._schedule_refresh)

        sr = str(share_root)
        if sr.startswith("\\\\") or sr.startswith("//"):
            self._poll = QTimer(self)
            self._poll.setInterval(8000)
            self._poll.timeout.connect(self._try_refresh_catalog)
            self._poll.start()
        else:
            self._poll = None

        self._try_refresh_catalog()
        self._update_watcher_paths()

    def _schedule_refresh(self, _path: str = "") -> None:
        self._debounce.start()

    def _force_refresh_catalog(self) -> None:
        self._catalog_sig = None
        self._try_refresh_catalog()
        self._update_watcher_paths()

    def _try_refresh_catalog(self) -> None:
        entries, sig, watch_dirs = scan_share_root(self._share_root)
        if self._catalog_sig is not None and sig == self._catalog_sig:
            return
        self._catalog_sig = sig
        self._watch_dir_list = watch_dirs
        self._rebuild_tree(entries)
        self._update_watcher_paths()
        self._apply_filter()

    def _current_item_download_url(self) -> str | None:
        cur = self._tree.currentItem()
        if not cur:
            return None
        data = cur.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(data, SoftwareItem):
            return data.download_url
        return None

    def _add_dir_item(self, parent: QTreeWidget | QTreeWidgetItem, node: CatalogDirNode) -> None:
        row = QTreeWidgetItem([node.display_name])
        row.setIcon(0, self._folder_icon)
        row.setData(0, Qt.ItemDataRole.UserRole, ("dir", node.abs_path))
        row.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        for sub in node.subdirs:
            self._add_dir_item(row, sub)
        for inst in node.installers:
            leaf = QTreeWidgetItem([inst.name])
            leaf.setIcon(0, self._file_icon)
            leaf.setData(0, Qt.ItemDataRole.UserRole, inst)
            leaf.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            row.addChild(leaf)
        row.setExpanded(True)
        if isinstance(parent, QTreeWidget):
            parent.addTopLevelItem(row)
        else:
            parent.addChild(row)

    def _add_top_entry(self, entry: CatalogDirNode | SoftwareItem) -> None:
        if isinstance(entry, SoftwareItem):
            leaf = QTreeWidgetItem([entry.name])
            leaf.setIcon(0, self._file_icon)
            leaf.setData(0, Qt.ItemDataRole.UserRole, entry)
            leaf.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self._tree.addTopLevelItem(leaf)
            return
        self._add_dir_item(self._tree, entry)

    def _rebuild_tree(self, entries: tuple[CatalogDirNode | SoftwareItem, ...]) -> None:
        prev_url = self._current_item_download_url()

        self._tree.clear()
        self._progress.setValue(0)

        if not self._share_root.exists():
            self._title.setText("共享目录不可用")
            self._meta.setText("无法访问共享根目录，请检查网络与权限。")
            self._tutorial.clear()
            self._selected = None
            self._update_install_button_state()
            return

        if not entries:
            self._title.setText("暂无安装包")
            self._meta.setText("共享目录中尚未发现 .exe / .msi 安装包（任意子文件夹内均可）。")
            self._tutorial.clear()
            self._selected = None
            self._update_install_button_state()
            return

        for e in entries:
            self._add_top_entry(e)

        self._tree.resizeColumnToContents(0)

        if prev_url:
            self._select_item_by_url(prev_url)
        else:
            first_sw = self._first_software_item()
            if first_sw:
                self._tree.setCurrentItem(first_sw)

        if not self._tree.currentItem():
            self._selected = None
            self._title.setText("请选择安装包")
            self._meta.clear()
            self._tutorial.clear()
            self._update_install_button_state()

    @staticmethod
    def _norm(text: str) -> str:
        return "".join(text.casefold().split())

    @classmethod
    def _fuzzy_match(cls, query: str, text: str) -> bool:
        """
        模糊匹配：先做包含匹配；否则做“子序列”匹配（例如 q=abc 可命中 a...b...c）。
        大小写不敏感、忽略空白。
        """
        q = cls._norm(query)
        if not q:
            return True
        t = cls._norm(text)
        if not t:
            return False
        if q in t:
            return True
        qi = 0
        for ch in t:
            if ch == q[qi]:
                qi += 1
                if qi >= len(q):
                    return True
        return False

    def _item_matches_query(self, item: QTreeWidgetItem, query: str) -> bool:
        text = item.text(0)
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(data, SoftwareItem) and data.breadcrumb:
            text = f"{text} {data.breadcrumb}"
        return self._fuzzy_match(query, text)

    def _filter_tree_item(self, item: QTreeWidgetItem, query: str) -> bool:
        matched_self = self._item_matches_query(item, query)
        any_child_visible = False
        for i in range(item.childCount()):
            ch = item.child(i)
            if self._filter_tree_item(ch, query):
                any_child_visible = True
        visible = matched_self or any_child_visible
        item.setHidden(not visible)
        if query.strip() and any_child_visible:
            item.setExpanded(True)
        return visible

    def _apply_filter(self) -> None:
        query = self._search.text()
        if not query.strip():
            # 清空过滤：全部显示，但不强制改变用户展开状态（仅确保根可见）
            for i in range(self._tree.topLevelItemCount()):
                top = self._tree.topLevelItem(i)
                self._show_all(top)
            self._update_install_button_state()
            return

        any_visible = False
        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            if self._filter_tree_item(top, query):
                any_visible = True

        cur = self._tree.currentItem()
        if cur and cur.isHidden():
            first = self._first_visible_software_item()
            if first:
                self._tree.setCurrentItem(first)
        elif not cur and any_visible:
            first = self._first_visible_software_item()
            if first:
                self._tree.setCurrentItem(first)

        self._update_install_button_state()

    def _show_all(self, item: QTreeWidgetItem) -> None:
        item.setHidden(False)
        for i in range(item.childCount()):
            self._show_all(item.child(i))

    def _first_visible_software_item(self) -> QTreeWidgetItem | None:
        for item in self._iter_software_items():
            if not item.isHidden():
                return item
        return None

    def _iter_software_items(self):
        it = QTreeWidgetItemIterator(self._tree)
        while it.value():
            item = it.value()
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, SoftwareItem):
                yield item
            it += 1

    def _first_software_item(self) -> QTreeWidgetItem | None:
        return next(self._iter_software_items(), None)

    def _select_item_by_url(self, url: str) -> None:
        for item in self._iter_software_items():
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, SoftwareItem) and data.download_url == url:
                self._tree.setCurrentItem(item)
                return

    def _update_watcher_paths(self) -> None:
        existing = list(self._watcher.files()) + list(self._watcher.directories())
        if existing:
            self._watcher.removePaths(existing)
        paths = list(self._watch_dir_list) if self._watch_dir_list else [str(self._share_root)]
        for p in paths:
            self._watcher.addPath(p)

    def _update_install_button_state(self) -> None:
        """根据当前选中项在下载目录中是否已有同名文件，控制安装按钮亮/灰。"""
        if not self._selected:
            self._last_download_path = None
            self._btn_install.setEnabled(False)
            return
        local = expected_local_download_path(self._selected.download_url, self._download_dir)
        if local.is_file():
            self._last_download_path = local.resolve()
            self._btn_install.setEnabled(True)
        else:
            self._last_download_path = None
            self._btn_install.setEnabled(False)

    def _on_tree_select(self, current: QTreeWidgetItem | None, _prev: QTreeWidgetItem | None) -> None:
        self._progress.setValue(0)

        if not current:
            self._selected = None
            self._title.setText("请选择安装包")
            self._meta.clear()
            self._tutorial.clear()
            self._update_install_button_state()
            return

        it = current.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(it, SoftwareItem):
            self._selected = None
            self._title.setText(current.text(0))
            self._meta.setText("此为文件夹，请继续展开并选择安装包。")
            self._tutorial.clear()
            self._update_install_button_state()
            return

        self._selected = it
        self._title.setText(it.name)
        loc = f"位置：{it.breadcrumb}" if it.breadcrumb else "位置：共享根目录"
        self._meta.setText(f"{loc}\n文件信息：{it.version}")
        self._tutorial.setPlainText(it.tutorial or "（未提供教程）")
        self._update_install_button_state()

    def _common_root(self) -> Path:
        return (self._share_root / "常用软件").resolve()

    def _software_key_for_installer(self, it: SoftwareItem) -> str | None:
        try:
            p = Path(it.download_url).resolve()
            rel = p.relative_to(self._common_root())
        except Exception:  # noqa: BLE001
            return None
        # 常用软件\<软件名>\...\xxx.exe  -> 软件名
        if len(rel.parts) >= 2:
            return self._normalize_software_key(rel.parts[0])
        # 直接放在常用软件根下：用文件名 stem 兜底
        return self._normalize_software_key(Path(it.name).stem) if it.name else None

    @staticmethod
    def _normalize_software_key(raw: str) -> str:
        return normalize_software_key(raw)

    def _is_common_installer_item(self, item: QTreeWidgetItem) -> tuple[SoftwareItem, str] | None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(data, SoftwareItem):
            return None
        key = self._software_key_for_installer(data)
        if not key:
            return None
        return data, key

    def _on_tree_context_menu(self, pos) -> None:  # type: ignore[no-untyped-def]
        item = self._tree.itemAt(pos)
        if not item:
            return
        hit = self._is_common_installer_item(item)
        if not hit:
            return

        _it, key = hit
        menu = QMenu(self)
        act_update = menu.addAction("更新软件")
        act_manage = menu.addAction("管理更新源")
        chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if chosen == act_update:
            self._on_update_single_software_clicked(key)
        elif chosen == act_manage:
            self._on_manage_update_source_clicked(key)

    def _on_update_single_software_clicked(self, software_key: str) -> None:
        if not is_admin():
            QMessageBox.warning(self, "无权限", "仅管理员可执行「更新软件」。\n请用管理员权限运行本程序。")
            return
        dlg = _UpdateDialog(self)
        dlg.start(self._share_root, self._custom_sources_path(), target_software_key=software_key)
        dlg.exec()
        self._force_refresh_catalog()

    @staticmethod
    def _app_root() -> Path:
        # app/ui/main_window.py -> app/ui -> app -> repo_root
        return Path(__file__).resolve().parents[2]

    def _custom_sources_path(self) -> Path:
        return self._app_root() / "update_sources.json"

    def _on_manage_update_source_clicked(self, software_key: str) -> None:
        if not is_admin():
            QMessageBox.warning(self, "无权限", "仅管理员可管理更新源。")
            return
        dlg = _ManageSourceDialog(self, self._custom_sources_path(), software_key)
        dlg.exec()

    def _on_download_clicked(self) -> None:
        if not self._selected:
            QMessageBox.information(self, "提示", "请先选择一个安装包。")
            return
        if self._worker and self._worker.isRunning():
            QMessageBox.information(self, "提示", "正在处理中，请稍候。")
            return

        local_path = expected_local_download_path(self._selected.download_url, self._download_dir)
        if local_path.is_file():
            reply = QMessageBox.question(
                self,
                "检测到已下载",
                f"本地下载目录中已有同名安装包（可能此前已下载过）：\n{local_path}\n\n是否覆盖并重新下载？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._btn_download.setEnabled(False)
        self._btn_install.setEnabled(False)
        self._progress.setValue(0)

        self._worker = DownloadWorker(self._selected.download_url, self._download_dir)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_download_ok)
        self._worker.failed.connect(self._on_download_failed)
        self._worker.finished.connect(self._on_download_worker_finished)
        self._worker.start()

    def _on_progress(self, downloaded: int, total: int) -> None:
        if total > 0:
            pct = int(downloaded * 100 / total)
            self._progress.setValue(max(0, min(100, pct)))
        else:
            self._progress.setRange(0, 0)

    def _on_download_worker_finished(self) -> None:
        self._btn_download.setEnabled(True)
        self._update_install_button_state()

    def _on_download_ok(self, path_str: str) -> None:
        self._progress.setRange(0, 100)
        self._progress.setValue(100)

        reply = QMessageBox.question(
            self,
            "下载完成",
            f"已保存到：\n{path_str}\n\n是否打开下载所在的文件夹？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                open_download_folder(Path(path_str))
            except OSError as e:
                QMessageBox.warning(self, "无法打开文件夹", str(e))

    def _on_download_failed(self, msg: str) -> None:
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        QMessageBox.critical(self, "下载失败", msg)

    def _on_install_clicked(self) -> None:
        if not self._last_download_path or not self._last_download_path.exists():
            QMessageBox.information(self, "提示", "请先点击「下载」将安装包保存到本机，再使用「安装」。")
            return
        if not self._selected:
            QMessageBox.information(self, "提示", "请先选择一个安装包。")
            return

        reply = QMessageBox.question(
            self,
            "立即安装",
            "是否立即运行已下载的安装程序？\n（将打开安装向导，请按界面提示操作。）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            run_installer_interactive(self._last_download_path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "无法启动安装程序", str(e))


def run_main_window(share_root: Path, download_dir: Path) -> None:
    app = QApplication.instance() or QApplication([])
    w = MainWindow(share_root, download_dir)
    w.show()
    app.exec()


class _UpdateDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("常用软件自动更新")
        self.resize(720, 520)
        self.setModal(True)

        self._lbl_current = QLabel("准备开始…")
        self._lbl_current.setObjectName("TitleLabel")
        self._lbl_overall = QLabel("")
        self._lbl_overall.setObjectName("MetaLabel")
        self._lbl_file = QLabel("")
        self._lbl_file.setObjectName("MetaLabel")

        self._bar_overall = QProgressBar()
        self._bar_overall.setRange(0, 100)
        self._bar_overall.setValue(0)
        self._bar_overall.setTextVisible(True)

        self._bar_file = QProgressBar()
        self._bar_file.setRange(0, 100)
        self._bar_file.setValue(0)
        self._bar_file.setTextVisible(True)

        self._log = QTextEdit()
        self._log.setReadOnly(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)
        root.addWidget(self._lbl_current)
        root.addWidget(self._lbl_overall)
        root.addWidget(self._bar_overall)
        root.addWidget(self._lbl_file)
        root.addWidget(self._bar_file)
        root.addWidget(self._log, 1)

        self._worker: CommonSoftwareUpdateWorker | None = None

    def start(
        self,
        share_root: Path,
        custom_sources_path: Path | None = None,
        target_software_key: str | None = None,
    ) -> None:
        if self._worker and self._worker.isRunning():
            return
        self._worker = CommonSoftwareUpdateWorker(
            share_root,
            custom_sources_path=custom_sources_path,
            target_software_key=target_software_key,
        )
        self._worker.current.connect(self._on_current)
        self._worker.progress.connect(self._on_overall_progress)
        self._worker.file_progress.connect(self._on_file_progress)
        self._worker.detail.connect(self._append_log)
        self._worker.failed_fatal.connect(self._on_fatal)
        self._worker.finished_summary.connect(self._on_finished)
        self._worker.start()

    def _on_current(self, name: str) -> None:
        self._lbl_current.setText(f"正在更新：{name}")
        self._bar_file.setRange(0, 100)
        self._bar_file.setValue(0)
        self._lbl_file.setText("")

    def _on_overall_progress(self, done: int, total: int) -> None:
        pct = int(done * 100 / total) if total > 0 else 0
        self._bar_overall.setValue(max(0, min(100, pct)))
        self._lbl_overall.setText(f"进度：{done}/{total}")

    def _on_file_progress(self, downloaded: int, total: int) -> None:
        if total <= 0:
            self._bar_file.setRange(0, 0)
            self._lbl_file.setText("下载中…")
            return
        self._bar_file.setRange(0, 100)
        pct = int(downloaded * 100 / total)
        self._bar_file.setValue(max(0, min(100, pct)))
        mb = downloaded / (1024 * 1024)
        total_mb = total / (1024 * 1024)
        self._lbl_file.setText(f"下载：{mb:.1f} / {total_mb:.1f} MB")

    def _append_log(self, line: str) -> None:
        self._log.append(line)

    def _on_fatal(self, msg: str) -> None:
        self._append_log(f"[终止] {msg}")
        QMessageBox.critical(self, "更新终止", msg)
        self.close()

    def _on_finished(self, updated: int, skipped: int, failed: int) -> None:
        self._append_log(f"\n汇总：更新 {updated}，跳过 {skipped}，失败 {failed}")
        if failed == 0:
            QMessageBox.information(self, "完成", "全部常用软件已更新到最新版。")
        else:
            QMessageBox.warning(self, "完成（有失败）", f"更新完成：成功 {updated}，跳过 {skipped}，失败 {failed}。\n请查看日志。")
        self.close()


class _ManageSourceDialog(QDialog):
    def __init__(self, parent: QWidget | None, path: Path, software_key: str):
        super().__init__(parent)
        self.setWindowTitle("管理更新源")
        self.resize(720, 260)
        self.setModal(True)
        self._path = path
        self._software_key = software_key

        title = QLabel(f"软件名称：{software_key}")
        title.setObjectName("TitleLabel")

        self._input = QLineEdit()
        self._input.setObjectName("SearchBox")
        self._input.setPlaceholderText("更新源链接（直链 / 页面 / API，程序会自动提取版本号与下载链接）")

        hint = QLabel("提示：该链接返回内容中最好包含版本号与安装包下载链接（exe/msi）。保存后更新会优先使用该配置。")
        hint.setObjectName("MetaLabel")
        hint.setWordWrap(True)

        btn_save = QPushButton("保存")
        btn_save.setObjectName("BtnPrimary")
        btn_save.clicked.connect(self._save)
        btn_clear = QPushButton("清除该软件配置")
        btn_clear.setObjectName("BtnGhost")
        btn_clear.clicked.connect(self._clear)

        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(btn_clear)
        actions.addWidget(btn_save)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)
        root.addWidget(title)
        root.addWidget(self._input)
        root.addWidget(hint)
        root.addLayout(actions)

        self._load_existing()

    def _load_existing(self) -> None:
        try:
            items = load_custom_sources(self._path)
            for it in items:
                if it.software_key == self._software_key:
                    self._input.setText(it.update_source_url)
                    return
        except Exception:  # noqa: BLE001
            return

    def _save(self) -> None:
        url = (self._input.text() or "").strip()
        if not url:
            QMessageBox.warning(self, "提示", "请先填写更新源链接。")
            return
        try:
            items = load_custom_sources(self._path)
        except Exception:
            items = []
        # upsert
        new_items = [it for it in items if it.software_key != self._software_key]
        new_items.append(CustomSource(self._software_key, url))
        save_custom_sources(self._path, new_items)
        QMessageBox.information(self, "已保存", "更新源已保存。后续更新会优先使用该链接。")
        self.close()

    def _clear(self) -> None:
        try:
            items = load_custom_sources(self._path)
        except Exception:
            items = []
        new_items = [it for it in items if it.software_key != self._software_key]
        save_custom_sources(self._path, new_items)
        QMessageBox.information(self, "已清除", "该软件的自定义更新源已清除。")
        self.close()
