from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from etc import constants as Const
from objects.edit import EditingChart


class ChartViewWidget(QWidget):
    def __init__(self, editing: EditingChart):
        super().__init__()
        self.editing: EditingChart = editing

        # スクロールさせたい全体の描画サイズを指定
        self.setMinimumSize(Const.WINDOW_WIDTH, 1000)

    def paintEvent(self, event):
        if not (parent := self.parentWidget()) or not (parent.size()):
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 背景を黒で塗りつぶす
        painter.fillRect(self.rect(), QColor("#000"))

        painter.setPen(QPen(QColor("#fff"), 1))
        for x in range(1, Const.LANE_COUNT + 2):
            center = (parent.size().width() / 2) - (
                Const.NOTE_WIDTH * ((Const.LANE_COUNT / 2) + 2)
            )
            point = round(center + x * Const.NOTE_WIDTH)
            painter.drawLine(
                point,
                0,
                point,
                self.height(),
            )

        painter.end()
