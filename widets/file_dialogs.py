"""プラットフォームごとのファイルダイアログを非同期で扱う。

Android のネイティブダイアログ（SAF / content:// URI）は Qt 6.6 以降
QFile から直接読めるが、静的メソッドや exec() によるブロッキング呼び出しは
キャンセル時にアプリが固まる既知の問題がある。そこで QFileDialog を
非同期 (open()) で開き、fileSelected / finished で結果を受け取る。
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QFileDialog

# iOS のネイティブドキュメントピッカー（UIDocumentPicker）は
# 種類フィルタの UTI 解決に失敗すると無言で何も開かないことがある。
# 保存ダイアログは動くのに開くダイアログだけ出ない、という症状になるため、
# iOS ではウィジェットベースのダイアログにフォールバックする。
IS_IOS = sys.platform == "ios"


class FileDialogController(QObject):
    """1 度に 1 つのダイアログだけを開く非同期コントローラ"""

    chosen = Signal(str)  # 選択されたパス（content:// の可能性あり）
    rejected = Signal()  # キャンセル

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dialog: QFileDialog | None = None
        self._picked = False

    def _start(self, dialog: QFileDialog, accept: QFileDialog.AcceptMode):
        self._picked = False
        self._dialog = dialog
        dialog.setAcceptMode(accept)
        if IS_IOS:
            # ネイティブピッカーが無言で失敗する問題の回避
            dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.fileSelected.connect(self._onFileSelected)
        dialog.finished.connect(self._onFinished)
        dialog.open()

    def _onFileSelected(self, path: str):
        self._picked = True
        self.chosen.emit(path)

    def _onFinished(self, result: int):
        dialog = self._dialog
        self._dialog = None
        if dialog is not None:
            dialog.deleteLater()
        if result and not self._picked:
            # 承認されたが fileSelected が来なかった場合の保険
            selected = dialog.selectedFiles() if dialog else []
            if selected:
                self.chosen.emit(selected[0])
                return
        if not result:
            self.rejected.emit()

    def openFile(self, parent, caption: str, name_filter: str):
        dialog = QFileDialog(parent, caption, "", name_filter)
        dialog.setFileMode(QFileDialog.FileMode.OpenFile)
        self._start(dialog, QFileDialog.AcceptMode.AcceptOpen)

    def saveFile(self, parent, caption: str, name_filter: str, suggested: str = ""):
        dialog = QFileDialog(parent, caption, suggested, name_filter)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        self._start(dialog, QFileDialog.AcceptMode.AcceptSave)