import os
import sys

import PySide6
import qtawesome as qta
from PySide6 import QtMultimedia
from PySide6.QtCore import Qt, QUrl
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
from objects.types import FixedInteger
from widets.chart_view import ChartViewWidget
from widets.details_view import DetailsViewWidget
from widets.front_view import FrontViewWidget


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

        self.setWindowTitle("BEATiCA EDiTOR")
        self.resize(Const.WINDOW_WIDTH, Const.WINDOW_HEIGHT)

        self.setupMenubar()
        self.setupToolbar()
        self.setupWidget()

    def setupMenubar(self):
        menubar = self.menuBar()
        fileMenu = QMenu("ファイル", self)
        menubar.addMenu(fileMenu)

        saveAction = QAction("保存", self)
        fileMenu.addAction(saveAction)

        def loadAudio():
            filename, _ = QFileDialog.getOpenFileName(
                self,
                "ファイルを開く",
                "",
                "音声ファイル (*.wav *.ogg *.mp3)",
            )

            if filename:
                self.player.setSource(QUrl.fromLocalFile(filename))
                self.chartAreaCanvas.syncWidth()

        saveAction = QAction("音声ファイルをインポート", self)
        fileMenu.triggered.connect(loadAudio)
        fileMenu.addAction(saveAction)

        fileMenu.addSeparator()

        exitAction = QAction("終了", self)
        fileMenu.addAction(exitAction)

    def setupToolbar(self):
        toolbar = QToolBar("メインツールバー", self)
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
                    setattr(self.editing, "editMode", mode) if checked else None
                )
            )

            actionGroup.addAction(action)
            toolbar.addAction(action)

    def setupWidget(self):
        verticalSplitter = QSplitter(Qt.Orientation.Vertical)
        horizontalSplitter = QSplitter(Qt.Orientation.Horizontal)

        # チャートエリア
        chartScrollArea = QScrollArea(verticalSplitter)
        self.chartAreaCanvas = ChartViewWidget(
            self.editing, chartScrollArea, self.player
        )

        chartScrollArea.setWidget(self.chartAreaCanvas)
        chartScrollArea.setWidgetResizable(False)

        # 正面図
        frontViewScrollArea = QScrollArea(verticalSplitter)
        frontViewCanvas = FrontViewWidget(self.editing)

        frontViewScrollArea.setWidget(frontViewCanvas)
        frontViewScrollArea.setWidgetResizable(False)

        verticalSplitter.addWidget(chartScrollArea)
        verticalSplitter.addWidget(frontViewScrollArea)

        verticalSplitter.splitterMoved.connect(self.chartAreaCanvas.onResized)

        verticalSplitter.setStretchFactor(0, 3)
        verticalSplitter.setStretchFactor(1, 1)
        verticalSplitter.setSizes(
            [int(Const.WINDOW_HEIGHT * 0.6), int(Const.WINDOW_HEIGHT * 0.4)]
        )

        # 楽曲情報編集
        detailsView = DetailsViewWidget(self.editing)
        detailsView.chartChanged.connect(self.chartAreaCanvas.onChartChanged)

        horizontalSplitter.addWidget(verticalSplitter)
        horizontalSplitter.addWidget(detailsView)
        horizontalSplitter.setStretchFactor(0, 3)
        horizontalSplitter.setStretchFactor(1, 1)
        horizontalSplitter.setSizes(
            [int(Const.WINDOW_WIDTH * 0.75), int(Const.WINDOW_WIDTH * 0.25)]
        )

        self.setCentralWidget(horizontalSplitter)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.chartAreaCanvas.syncWidth()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Space:
            if self.player.isPlaying():
                self.player.pause()
            else:
                self.player.play()


if __name__ == "__main__":
    # 環境変数にPySide6を登録
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
