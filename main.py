import os
import sys
from datetime import datetime
from pathlib import Path

import PySide6
import qtawesome as qta
from PySide6 import QtMultimedia
from PySide6.QtCore import QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QKeyEvent, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QMenu,
    QScrollArea,
    QSplitter,
    QToolBar,
)

from etc import constants as Const
from objects.chart import Chart, Difficulty
from objects.edit import EditingChart, EditMode
from objects.note import Change, Layer
from objects.serialize import loadProject, saveBinary, saveProject
from objects.types import FixedInteger
from widets.chart_view import ChartViewWidget
from widets.details_view import DetailsViewWidget
from widets.front_view import FrontViewWidget
from widets.settings_view import SettingsDialog, applySavedAudioSettings

ICON_SIZES = {"small": 20, "medium": 32, "large": 48}

# p4a sets ANDROID_PRIVATE (and getandroidapkpath) inside the APK.
IS_ANDROID = "ANDROID_PRIVATE" in os.environ or hasattr(sys, "getandroidapkpath")
# PySide6 の iOS ビルドでは sys.platform が "ios" になる
IS_IOS = sys.platform == "ios"


def writableDataDir() -> Path:
    """書き込み可能なアプリデータ目录（iOS/Android のサンドボックス対応）"""
    if IS_ANDROID or IS_IOS:
        from PySide6.QtCore import QStandardPaths

        location = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation
        )
        if location:
            return Path(location)
    return Const.ASSETS_PATH.parent


def fileDialogOptions() -> QFileDialog.Options:
    """Android のネイティブダイアログはキャンセルで固まるためアプリ内で描画する"""
    if IS_ANDROID:
        return QFileDialog.Option.DontUseNativeDialog
    return QFileDialog.Options()


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.editing: EditingChart = EditingChart(
            chart=Chart(
                id="new_chart",
                difficultyType=Difficulty.NORMAL,
                difficulty=FixedInteger(major=1, minor=0),
                offset=0,
                layers=[
                    Layer(
                        id=0,
                        changes=[],
                        skyNote=0,
                    )
                ],
                globalChanges=[
                    Change(
                        beat=0.0,
                        bpm=120,
                        speedRate=1.0,
                        timeSignature=FixedInteger(major=4, minor=4),
                    )
                ],
            )
        )

        self.player = QtMultimedia.QMediaPlayer()
        self.audioOutput = QtMultimedia.QAudioOutput()
        self.player.setAudioOutput(self.audioOutput)
        self.audioOutput.setVolume(1.0)

        # 保存済みの音声設定（出力デバイス・低遅延モード）を適用
        applySavedAudioSettings(self.player, self.audioOutput)

        self.setWindowTitle("BEATiCA EDiTOR")
        self.resize(Const.WINDOW_WIDTH, Const.WINDOW_HEIGHT)

        # 現在のプロジェクト情報
        self.bgmPath: str | None = None
        self.currentProjectPath: Path | None = None

        self.setupWidget()
        self.setupToolbar()
        self.setupMenubar()
        self.setupAutosave()

    def setupMenubar(self):
        menubar = self.menuBar()
        if IS_ANDROID:
            # Qt for Android keeps the menu bar hidden (it expects a native
            # menu button), so ask for the widget form to get a visible bar.
            menubar.setNativeMenuBar(False)

        # ファイル
        fileMenu = QMenu("ファイル", self)
        menubar.addMenu(fileMenu)

        saveProjectAction = QAction("プロジェクトを保存 (.beaproj)", self)
        saveProjectAction.setShortcut("Ctrl+S")
        saveProjectAction.triggered.connect(self.saveProject)
        fileMenu.addAction(saveProjectAction)

        loadProjectAction = QAction("プロジェクトを開く (.beaproj)", self)
        loadProjectAction.setShortcut("Ctrl+O")
        loadProjectAction.triggered.connect(self.loadProject)
        fileMenu.addAction(loadProjectAction)

        exportAction = QAction("本番書き出し (.bea)", self)
        exportAction.triggered.connect(self.exportBinary)
        fileMenu.addAction(exportAction)

        fileMenu.addSeparator()

        importAudioAction = QAction("音声ファイルをインポート", self)
        importAudioAction.triggered.connect(self.importAudio)
        fileMenu.addAction(importAudioAction)

        fileMenu.addSeparator()

        exitAction = QAction("終了", self)
        exitAction.triggered.connect(QApplication.quit)
        fileMenu.addAction(exitAction)

        # 編集
        editMenu = QMenu("編集", self)
        menubar.addMenu(editMenu)
        editMenu.addAction("元に戻す\tCtrl+Z", self.chartAreaCanvas.undo)
        editMenu.addAction("やり直し\tCtrl+Y", self.chartAreaCanvas.redo)
        editMenu.addSeparator()
        self.copyAction = editMenu.addAction(
            "コピー\tCtrl+C", self.chartAreaCanvas.copySelectedNotes
        )
        self.pasteAction = editMenu.addAction(
            "ペースト\tCtrl+V", self.chartAreaCanvas.pasteNotes
        )
        self.selectAllAction = editMenu.addAction(
            "全て選択\tCtrl+A", self.chartAreaCanvas.selectAllNotes
        )
        self.deleteAction = editMenu.addAction(
            "削除\tDelete", self.chartAreaCanvas.deleteSelectedNotes
        )

        editMenu.addSeparator()
        settingsAction = QAction("設定...", self)
        settingsAction.triggered.connect(self.settingsAction)
        editMenu.addAction(settingsAction)

        # 選択/クリップボード/モードに応じて有効・無効を更新
        self.chartAreaCanvas.noteSelectionChanged.connect(self.updateEditActions)
        self.chartAreaCanvas.clipboardChanged.connect(self.updateEditActions)

        # 表示（ウィンドウのオンオフ）
        viewMenu = QMenu("表示", self)
        menubar.addMenu(viewMenu)
        self.chartToggle = QAction("チャート", self)
        self.chartToggle.setCheckable(True)
        self.chartToggle.setChecked(True)
        self.chartToggle.toggled.connect(
            lambda v: self.onViewToggled(self.chartScrollArea, v)
        )
        viewMenu.addAction(self.chartToggle)
        self.frontToggle = QAction("正面図", self)
        self.frontToggle.setCheckable(True)
        self.frontToggle.setChecked(True)
        self.frontToggle.toggled.connect(
            lambda v: self.onViewToggled(self.frontViewScrollArea, v)
        )
        viewMenu.addAction(self.frontToggle)
        self.detailsToggle = QAction("詳細", self)
        self.detailsToggle.setCheckable(True)
        self.detailsToggle.setChecked(True)
        self.detailsToggle.toggled.connect(
            lambda v: self.onViewToggled(self.detailsView, v)
        )
        viewMenu.addAction(self.detailsToggle)

        self.updateEditActions()

    def onViewToggled(self, widget, visible: bool):
        widget.setVisible(visible)
        # レイアウト確定後に再描画・幅再計算
        QTimer.singleShot(0, self.chartAreaCanvas.syncWidth)
        QTimer.singleShot(0, self.chartAreaCanvas.update)

    def settingsAction(self):
        dialog = SettingsDialog(self.player, self.audioOutput, self)
        dialog.autosaveIntervalChanged.connect(self.onAutosaveIntervalChanged)
        dialog.iconSizeChanged.connect(lambda _key: self.applyIconSize())
        dialog.exec()

    def onAutosaveIntervalChanged(self, seconds: int):
        self.autosaveTimer.stop()
        if seconds > 0:
            self.autosaveTimer.start(seconds * 1000)

    # --- ファイル操作 ---
    def importAudio(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "音声ファイルを開く",
            "",
            "音声ファイル (*.wav *.ogg *.mp3)",
            options=fileDialogOptions(),
        )
        if filename:
            self.bgmPath = filename
            self.player.setSource(QUrl.fromLocalFile(filename))
            self.chartAreaCanvas.syncWidth()

    def saveProject(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "プロジェクトを保存",
            "",
            "BEATiCA Project (*.beaproj)",
            options=fileDialogOptions(),
        )
        if not path:
            return
        if not path.endswith(".beaproj"):
            path += ".beaproj"
        self.currentProjectPath = Path(path)
        saveProject(self.editing.chart, Path(path), self.bgmPath)

    def loadProject(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "プロジェクトを開く",
            "",
            "BEATiCA Project (*.beaproj)",
            options=fileDialogOptions(),
        )
        if not path:
            return
        chart, bgm = loadProject(Path(path))
        self.editing.loadChart(chart)
        self.currentProjectPath = Path(path)
        self.bgmPath = bgm or None
        if bgm:
            self.player.setSource(QUrl.fromLocalFile(bgm))
        self.chartAreaCanvas.onChartChanged()
        self.detailsView.updateNoteInfo()

    def exportBinary(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "本番書き出し",
            "",
            "BEATiCA Chart (*.bea)",
            options=fileDialogOptions(),
        )
        if not path:
            return
        if not path.endswith(".bea"):
            path += ".bea"
        saveBinary(self.editing.chart, Path(path))

    # --- オートセーブ ---
    def setupAutosave(self):
        settings = QSettings("BEATiCA", "EDiTOR")
        interval = int(str(settings.value("autosave/intervalSec", 60)))
        self.autosaveTimer = QTimer(self)
        self.autosaveTimer.timeout.connect(self.autosave)
        if interval > 0:
            self.autosaveTimer.start(interval * 1000)

    def autosave(self):
        folder = writableDataDir() / "autosaves"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        saveProject(
            self.editing.chart, folder / f"autosave_{stamp}.beaproj", self.bgmPath
        )

    def setupToolbar(self):
        toolbar = QToolBar("メインツールバー", self)
        self.toolbar = toolbar
        self.addToolBar(toolbar)

        actionGroup = QActionGroup(self)
        actionGroup.setExclusive(True)

        actions = [
            (
                QIcon(qta.icon("fa5s.mouse-pointer", color="#fff")),
                "選択",
                EditMode.SELECT,
            ),
            (
                QIcon(str(Const.IMAGES_PATH / "icons" / "tap_note.png")),
                "タップノーツを配置",
                EditMode.TAP_NOTE,
            ),
            (
                QIcon(str(Const.IMAGES_PATH / "icons" / "trace_note.png")),
                "トレースノーツを配置",
                EditMode.TRACE_NOTE,
            ),
            (
                QIcon(str(Const.IMAGES_PATH / "icons" / "long_note.png")),
                "ロングノーツを配置",
                EditMode.LONG_NOTE,
            ),
            (
                QIcon(str(Const.IMAGES_PATH / "icons" / "long_note_connector.png")),
                "ロングノーツコネクターを配置",
                EditMode.LONG_NOTE_CONNECTOR,
            ),
            (
                QIcon(str(Const.IMAGES_PATH / "icons" / "flick_note.png")),
                "フリックノーツを配置",
                EditMode.FLICK_NOTE,
            ),
            (
                QIcon(str(Const.IMAGES_PATH / "icons" / "sky_note.png")),
                "スカイノーツを配置",
                EditMode.SKY_NOTE,
            ),
            (
                QIcon(),
                "EVENT",
                EditMode.EVENT,
            ),
        ]

        for icon, tooltip, mode in actions:
            action = QAction(icon, tooltip, self)
            action.setToolTip(tooltip)
            action.setCheckable(True)

            if mode == EditMode.SELECT:
                action.setChecked(True)

            action.triggered.connect(
                lambda checked, mode=mode: (
                    self.onModeSelected(mode) if checked else None
                )
            )

            actionGroup.addAction(action)
            toolbar.addAction(action)

        # タッチ操作バー（スマホ横画面向け: 修飾キー・右クリック不要）
        touchBar = QToolBar("タッチ操作", self)
        self.touchBar = touchBar
        self.addToolBar(touchBar)

        zoomInAction = QAction(
            QIcon(qta.icon("fa5s.search-plus", color="#fff")), "ズーム+", self
        )
        zoomInAction.setToolTip("ズーム+")
        zoomInAction.triggered.connect(lambda: self.chartAreaCanvas.zoomBy(1))
        touchBar.addAction(zoomInAction)

        zoomOutAction = QAction(
            QIcon(qta.icon("fa5s.search-minus", color="#fff")), "ズーム−", self
        )
        zoomOutAction.setToolTip("ズーム−")
        zoomOutAction.triggered.connect(lambda: self.chartAreaCanvas.zoomBy(-1))
        touchBar.addAction(zoomOutAction)

        self.snapIgnoreAction = QAction(
            QIcon(qta.icon("fa5s.magnet", color="#fff")), "スナップ無視", self
        )
        self.snapIgnoreAction.setToolTip("スナップ無視")
        self.snapIgnoreAction.setCheckable(True)
        self.snapIgnoreAction.toggled.connect(self.onSnapIgnoreToggled)
        touchBar.addAction(self.snapIgnoreAction)

        touchCopyAction = QAction(
            QIcon(qta.icon("fa5s.copy", color="#fff")), "コピー", self
        )
        touchCopyAction.setToolTip("コピー")
        touchCopyAction.triggered.connect(self.chartAreaCanvas.copySelectedNotes)
        touchBar.addAction(touchCopyAction)
        self.touchCopyAction = touchCopyAction

        touchPasteAction = QAction(
            QIcon(qta.icon("fa5s.paste", color="#fff")), "ペースト", self
        )
        touchPasteAction.setToolTip("ペースト")
        touchPasteAction.triggered.connect(self.chartAreaCanvas.pasteNotes)
        touchBar.addAction(touchPasteAction)
        self.touchPasteAction = touchPasteAction

        touchDeleteAction = QAction(
            QIcon(qta.icon("fa5s.trash", color="#fff")), "削除", self
        )
        touchDeleteAction.setToolTip("削除")
        touchDeleteAction.triggered.connect(self.chartAreaCanvas.deleteSelectedNotes)
        touchBar.addAction(touchDeleteAction)
        self.touchDeleteAction = touchDeleteAction

        self.applyIconSize()

    def onSnapIgnoreToggled(self, checked: bool):
        self.chartAreaCanvas.forceNoSnap = checked

    def applyIconSize(self):
        key = str(QSettings("BEATiCA", "EDiTOR").value("ui/iconSize", "medium"))
        size = ICON_SIZES.get(key, 32)
        if getattr(self, "toolbar", None) is not None:
            self.toolbar.setIconSize(QSize(size, size))
        if getattr(self, "touchBar", None) is not None:
            self.touchBar.setIconSize(QSize(size, size))

    def onModeSelected(self, mode: EditMode):
        self.editing.editMode = mode
        # ノーツ選択中は種類を適用（タップ/トレース/フリック/スカイ）
        self.chartAreaCanvas.applyModeToSelection(mode)
        self.updateEditActions()

    def updateEditActions(self):
        cv = self.chartAreaCanvas
        hasSel = bool(cv.editing.selectedNotes)
        hasClip = bool(cv.clipboard)
        pasteable = cv.editing.editMode not in (
            EditMode.EVENT,
            EditMode.LONG_NOTE_CONNECTOR,
        )
        self.copyAction.setEnabled(hasSel)
        self.deleteAction.setEnabled(hasSel)
        self.pasteAction.setEnabled(hasClip and pasteable)
        self.selectAllAction.setEnabled(bool(cv.editing.chart.notes))
        # タッチ操作バーも同様に更新
        self.touchCopyAction.setEnabled(hasSel)
        self.touchDeleteAction.setEnabled(hasSel)
        self.touchPasteAction.setEnabled(hasClip and pasteable)

    def setupWidget(self):
        verticalSplitter = QSplitter(Qt.Orientation.Vertical)
        horizontalSplitter = QSplitter(Qt.Orientation.Horizontal)

        # チャートエリア
        chartScrollArea = QScrollArea(verticalSplitter)
        self.chartScrollArea = chartScrollArea
        self.chartAreaCanvas = ChartViewWidget(
            self.editing, chartScrollArea, self.player
        )

        chartScrollArea.setWidget(self.chartAreaCanvas)
        chartScrollArea.setWidgetResizable(False)

        # ズーム・スナップ変更をタイトルに反映
        self.chartAreaCanvas.viewSettingsChanged.connect(self.onViewSettingsChanged)

        # 正面図
        frontViewScrollArea = QScrollArea(verticalSplitter)
        self.frontViewScrollArea = frontViewScrollArea
        frontViewCanvas = FrontViewWidget(self.editing, self.chartAreaCanvas)

        frontViewScrollArea.setWidget(frontViewCanvas)
        frontViewScrollArea.setWidgetResizable(True)

        verticalSplitter.addWidget(chartScrollArea)
        verticalSplitter.addWidget(frontViewScrollArea)

        verticalSplitter.splitterMoved.connect(self.chartAreaCanvas.onResized)

        verticalSplitter.setStretchFactor(0, 3)
        verticalSplitter.setStretchFactor(1, 1)
        verticalSplitter.setSizes(
            [int(Const.WINDOW_HEIGHT * 0.6), int(Const.WINDOW_HEIGHT * 0.4)]
        )

        # 楽曲情報編集
        self.detailsView = DetailsViewWidget(self.editing)
        self.detailsView.chartChanged.connect(self.chartAreaCanvas.onChartChanged)
        self.chartAreaCanvas.noteSelectionChanged.connect(
            self.detailsView.updateNoteInfo
        )

        # 表示設定コンボ → チャートビュー
        self.detailsView.zoomChanged.connect(self.chartAreaCanvas.setZoomFactor)
        self.detailsView.snapChanged.connect(self.chartAreaCanvas.setSnapValue)
        self.detailsView.laneDivisionChanged.connect(
            self.chartAreaCanvas.setLaneDivision
        )

        # スカイノーツの付与/解除
        self.detailsView.attachSkyNoteRequested.connect(
            self.chartAreaCanvas.attachSkyNoteToSelection
        )
        self.detailsView.detachSkyNoteRequested.connect(
            self.chartAreaCanvas.detachSkyNoteFromSelection
        )
        self.detailsView.addKnotRequested.connect(self.chartAreaCanvas.addKnot)
        self.detailsView.removeKnotRequested.connect(
            self.chartAreaCanvas.removeSelectedKnot
        )
        self.chartAreaCanvas.skyKnotsChanged.connect(self.detailsView.refreshKnotList)
        self.detailsView.skyKnotCurveChanged.connect(
            self.chartAreaCanvas.setSkyKnotCurve
        )

        # 初期の表示設定を反映
        self.chartAreaCanvas.emitViewSettings()
        # 初期はノーツ未選択の状態を表示
        self.detailsView.updateNoteInfo()

        horizontalSplitter.addWidget(verticalSplitter)
        horizontalSplitter.addWidget(self.detailsView)
        horizontalSplitter.setStretchFactor(0, 3)
        horizontalSplitter.setStretchFactor(1, 1)
        horizontalSplitter.setSizes(
            [int(Const.WINDOW_WIDTH * 0.75), int(Const.WINDOW_WIDTH * 0.25)]
        )

        self.setCentralWidget(horizontalSplitter)

    def onViewSettingsChanged(self, zoom: float, snap: int, laneDivision: int):
        # ホイール等での変更を表示設定コンボへ反映（タイトル表示は廃止）
        self.detailsView.updateViewSettings(zoom, snap, laneDivision)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.chartAreaCanvas.syncWidth()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Space:
            self.chartAreaCanvas.togglePlay()
            return

        modifiers = event.modifiers()
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        key = event.key()

        if ctrl and key == Qt.Key.Key_Z:
            self.chartAreaCanvas.undo()
        elif ctrl and key == Qt.Key.Key_Y:
            self.chartAreaCanvas.redo()
        elif ctrl and key == Qt.Key.Key_A:
            self.chartAreaCanvas.selectAllNotes()
        elif ctrl and key == Qt.Key.Key_C:
            self.chartAreaCanvas.copySelectedNotes()
        elif ctrl and key == Qt.Key.Key_V:
            self.chartAreaCanvas.pasteNotes()
        elif key == Qt.Key.Key_Delete:
            self.chartAreaCanvas.deleteSelectedNotes()


if __name__ == "__main__":
    # Android のみ Qt のプラグインパスを明示する（iOS はアプリバンドルから解決）
    if IS_ANDROID:
        dirname = os.path.dirname(PySide6.__file__)
        plugin_path = os.path.join(dirname, "plugins", "platforms")
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = plugin_path

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(25, 25, 25))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Text, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
    palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(35, 35, 35))
    app.setPalette(palette)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
