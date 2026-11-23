import os
import sys

import PySide6
import qtawesome as qta
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMenu,
    QScrollArea,
    QSplitter,
    QToolBar,
)

from etc import constants as Const
from objects.chart import Chart, Difficulty
from objects.edit import EditingChart
from objects.note import CurveType, FlickType, Layer, Note, NoteFlag
from objects.types import FixedInteger
from widets.chart_view import ChartViewWidget
from widets.front_view import FrontViewWidget


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.editing: EditingChart = EditingChart(
            chart=Chart(
                version=1,
                id="new_chart",
                difficultyType=Difficulty.NORMAL,
                difficulty=FixedInteger(major=1, minor=0),
                notes=[
                    Note(
                        id=0,
                        beat=0.0,
                        lane=0,
                        width=4,
                        curveType=CurveType.linear,
                        flickType=FlickType.none,
                        flag=NoteFlag.none,
                        layer=0,
                        skyNote=0,
                    )
                ],
                layers=[
                    Layer(
                        id=0,
                        bpm=120,
                        beat=FixedInteger(major=4, minor=4),
                        speedRate=1.0,
                        skyNote=0,
                    )
                ],
            )
        )

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

    def setupToolbar(self):
        toolbar = QToolBar("メインツールバー", self)
        self.addToolBar(toolbar)

        selectPencil = QAction(
            self,
            icon=QIcon(qta.icon("fa5s.mouse-pointer", color="#fff")),
            toolTip="選択",
        )
        toolbar.addAction(selectPencil)

        selectPencil = QAction(
            self,
            icon=QIcon(qta.icon("fa5s.eraser", color="#fff")),
            toolTip="消去",
        )
        toolbar.addAction(selectPencil)

        selectTapNote = QAction(
            self,
            icon=QIcon(str(Const.IMAGES_PATH / "icons" / "tap_note.png")),
            toolTip="タップノーツを配置",
        )
        toolbar.addAction(selectTapNote)

    def setupWidget(self):
        verticalSplitter = QSplitter(Qt.Orientation.Vertical)

        # チャートエリア
        chartScrollArea = QScrollArea(verticalSplitter)
        self.chartAreaCanvas = ChartViewWidget(self.editing, chartScrollArea)

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

        self.setCentralWidget(verticalSplitter)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.chartAreaCanvas.syncWidth()


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
