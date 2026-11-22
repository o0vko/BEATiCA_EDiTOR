import os
import sys

import PySide6
from PySide6.QtGui import QAction, QColor, QIcon, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMenu,
    QScrollArea,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from etc import constants as Const
from objects.chart import Chart, Difficulty
from objects.edit import EditingChart
from objects.note import Layer
from objects.types import FixedInteger
from widets.chart_view import ChartViewWidget


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.editing: EditingChart = EditingChart(
            chart=Chart(
                version=1,
                id="new_chart",
                difficultyType=Difficulty.NORMAL,
                difficulty=FixedInteger(major=1, minor=0),
                notes=[],
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

        # メニューバー
        menubar = self.menuBar()
        file_menu = QMenu("ファイル", self)
        menubar.addMenu(file_menu)

        # アクション作成
        open_action = QAction("保存", self)
        file_menu.addAction(open_action)

        # ツールバー作成
        toolbar = QToolBar("メインツールバー", self)
        self.addToolBar(toolbar)

        open_action = QAction(
            self, icon=QIcon(str(Const.IMAGES_PATH / "icons" / "tap_note.png"))
        )
        toolbar.addAction(open_action)

        # Central Widget
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        # スクロールエリア
        scroll_area = QScrollArea(central_widget)
        canvas = ChartViewWidget()

        scroll_area.setWidget(canvas)
        scroll_area.setWidgetResizable(False)

        # レイアウト
        layout = QVBoxLayout(central_widget)
        layout.addWidget(scroll_area)


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
