from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileIconProvider,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTextEdit,
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
