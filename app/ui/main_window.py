from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.config import SoftwareItem
from app.downloader import download_streaming
from app.installer import open_in_explorer, run_silent_installer


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
    def __init__(self, items: list[SoftwareItem], download_dir: Path):
        super().__init__()
        self.setWindowTitle("内网软件助手")
        self.resize(980, 620)

        self._items = items
        self._download_dir = download_dir
        self._selected: SoftwareItem | None = None
        self._last_download_path: Path | None = None

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        for it in self._items:
            row = QListWidgetItem(f"{it.name}  ({it.version})")
            row.setData(0x0100, it)  # Qt.UserRole 兼容写法
            self._list.addItem(row)
        self._list.currentItemChanged.connect(self._on_select)

        self._title = QLabel("请选择左侧软件")
        self._meta = QLabel("")
        self._meta.setWordWrap(True)

        self._tutorial = QTextEdit()
        self._tutorial.setReadOnly(True)

        self._radio_manual = QRadioButton("手动模式（下载后打开文件夹）")
        self._radio_auto = QRadioButton("自动安装（静默参数后台执行）")
        self._radio_manual.setChecked(True)
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self._radio_manual)
        self._mode_group.addButton(self._radio_auto)

        self._btn_download = QPushButton("下载")
        self._btn_download.clicked.connect(self._on_download_clicked)

        self._btn_install = QPushButton("安装")
        self._btn_install.clicked.connect(self._on_install_clicked)
        self._btn_install.setEnabled(False)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)

        right = QVBoxLayout()
        right.addWidget(self._title)
        right.addWidget(self._meta)
        right.addWidget(QLabel("安装教程"))
        right.addWidget(self._tutorial, 1)
        right.addWidget(self._radio_manual)
        right.addWidget(self._radio_auto)

        actions = QHBoxLayout()
        actions.addWidget(self._btn_download)
        actions.addWidget(self._btn_install)
        right.addLayout(actions)
        right.addWidget(self._progress)

        root = QHBoxLayout(self)
        root.addWidget(self._list, 0)
        root.addLayout(right, 1)

        if self._items:
            self._list.setCurrentRow(0)

        self._worker: DownloadWorker | None = None

    def _on_select(self, current: QListWidgetItem | None, _prev: QListWidgetItem | None) -> None:
        self._last_download_path = None
        self._btn_install.setEnabled(False)
        self._progress.setValue(0)

        if not current:
            self._selected = None
            return

        it = current.data(0x0100)
        if not isinstance(it, SoftwareItem):
            self._selected = None
            return

        self._selected = it
        self._title.setText(it.name)
        self._meta.setText(f"版本：{it.version}\n下载：{it.download_url}\n静默参数：{it.silent_args or '(无)'}")
        self._tutorial.setPlainText(it.tutorial or "（未提供教程）")

    def _on_download_clicked(self) -> None:
        if not self._selected:
            QMessageBox.information(self, "提示", "请先选择一个软件。")
            return
        if self._worker and self._worker.isRunning():
            QMessageBox.information(self, "提示", "正在下载中，请稍候。")
            return

        self._btn_download.setEnabled(False)
        self._btn_install.setEnabled(False)
        self._progress.setValue(0)

        self._worker = DownloadWorker(self._selected.download_url, self._download_dir)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_download_ok)
        self._worker.failed.connect(self._on_download_failed)
        self._worker.finished.connect(lambda: self._btn_download.setEnabled(True))
        self._worker.start()

    def _on_progress(self, downloaded: int, total: int) -> None:
        if total > 0:
            pct = int(downloaded * 100 / total)
            self._progress.setValue(max(0, min(100, pct)))
        else:
            # 无 Content-Length 时，显示“活动条”效果
            self._progress.setRange(0, 0)

    def _on_download_ok(self, path_str: str) -> None:
        self._progress.setRange(0, 100)
        self._progress.setValue(100)
        self._last_download_path = Path(path_str)
        self._btn_install.setEnabled(True)

        QMessageBox.information(self, "下载完成", f"已下载到：\n{path_str}")

        if self._radio_manual.isChecked():
            open_in_explorer(self._last_download_path)

    def _on_download_failed(self, msg: str) -> None:
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        QMessageBox.critical(self, "下载失败", msg)

    def _on_install_clicked(self) -> None:
        if not self._selected or not self._last_download_path:
            QMessageBox.information(self, "提示", "请先下载完成。")
            return

        if self._radio_manual.isChecked():
            QMessageBox.information(self, "手动安装", "已为你打开安装包目录，请按右侧教程手动安装。")
            open_in_explorer(self._last_download_path)
            return

        # 自动安装
        try:
            run_silent_installer(self._last_download_path, self._selected.silent_args)
            QMessageBox.information(self, "已开始安装", "安装进程已在后台启动。")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "安装失败", str(e))


def run_main_window(items: list[SoftwareItem], download_dir: Path) -> None:
    app = QApplication.instance() or QApplication([])
    w = MainWindow(items, download_dir)
    w.show()
    app.exec()

