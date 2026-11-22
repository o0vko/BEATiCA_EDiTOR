from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from etc import constants as Const
from objects.edit import EditingChart


class FrontViewWidget(QWidget):
    def __init__(self, editing: EditingChart):
        super().__init__()
        self.editing: EditingChart = editing

        # スクロールさせたい全体の描画サイズを指定
        self.setMinimumSize(Const.WINDOW_WIDTH, 1000)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 背景を白で塗りつぶす
        painter.fillRect(self.rect(), QColor("#FFFFFF"))

        # グリッドと図形の描画例
        painter.setPen(QPen(QColor("#CCCCCC"), 1))
        for x in range(0, self.width(), 50):
            painter.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 50):
            painter.drawLine(0, y, self.width(), y)

        painter.setPen(QPen(QColor("#0000FF"), 3))
        painter.drawEllipse(100, 100, 300, 300)
        painter.drawText(800, 800, "スクロール先のテキスト")
