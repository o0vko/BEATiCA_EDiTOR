from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QFileDialog


class FileDialogController(QObject):
    """1 度に 1 つのダイアログだけを開く非同期コントローラ"""

    chosen = Signal(str)
    rejected = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dialog: QFileDialog | None = None
        self.picked = False

    def _start(self, dialog: QFileDialog, accept: QFileDialog.AcceptMode):
        self.picked = False
        self.dialog = dialog

        dialog.setAcceptMode(accept)
        dialog.fileSelected.connect(self._onFileSelected)
        dialog.finished.connect(self._onFinished)
        dialog.open()

    def _onFileSelected(self, path: str):
        self.picked = True
        self.chosen.emit(path)

    def _onFinished(self, result: int):
        dialog = self.dialog
        self.dialog = None

        if dialog is not None:
            dialog.deleteLater()

        if result and not self.picked:
            # 承認されたが fileSelected が来なかった場合の保険
            selected = dialog.selectedFiles() if dialog else []
            if selected:
                self.chosen.emit(selected[0])
                return

        if not result:
            self.rejected.emit()

    def openFile(
        self, parent, caption: str, nameFilter: str, directory: str = ""
    ):
        dialog = QFileDialog(parent, caption, directory, nameFilter)
        dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        self._start(dialog, QFileDialog.AcceptMode.AcceptOpen)

    def saveFile(
        self,
        parent,
        caption: str,
        nameFilter: str,
        suggested: str = "",
        directory: str = "",
    ):
        # suggested が空のときは directory を初期ディレクトリにする
        dialog = QFileDialog(parent, caption, suggested or directory, nameFilter)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        self._start(dialog, QFileDialog.AcceptMode.AcceptSave)