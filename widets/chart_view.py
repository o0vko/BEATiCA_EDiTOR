import math

from PySide6.QtCore import QTimer
from PySide6.QtGui import (
    QColor,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QScrollArea, QWidget

from etc import constants as Const
from objects.edit import EditingChart, NoteAction
from objects.note import CurveType, FlickType, Note, NoteFlag


class ChartViewWidget(QWidget):
    def __init__(self, editing: EditingChart, scrollArea: QScrollArea):
        super().__init__()
        self.editing: EditingChart = editing
        self.scrollArea = scrollArea

        self.tapNotePixMap = QPixmap(Const.IMAGES_PATH / "tap_note.png")

        def setup():
            self.setMinimumSize(self.scrollArea.width(), 1000)
            self.scrollArea.verticalScrollBar().setValue(
                self.scrollArea.verticalScrollBar().maximum()
            )

        QTimer.singleShot(
            0,
            setup,
        )

    def syncWidth(self):
        viewportWidth = self.scrollArea.viewport().width()
        self.resize(viewportWidth, 1000)

    def onResized(self, pos: int, index: int):
        self.syncWidth()

    def mousePressEvent(self, event: QMouseEvent):
        lane = math.floor(self.getLaneFromXPoint(event.x()))

        if 0 <= lane <= 16:
            self.editing.pushAction(
                NoteAction(
                    type="note_place",
                    data=Note(
                        id=self.editing.nextNoteId,
                        beat=self.getBeatFromYPoint(event.y()),
                        lane=lane,
                        width=1,
                        curveType=CurveType.linear,
                        flickType=FlickType.none,
                        flag=NoteFlag.none,
                        layer=0,
                        skyNote=0,
                    ),
                )
            )
            self.update()

    def keyPressEvent(self, event: QKeyEvent):
        print(f"キー入力：{event.key()}")

    def getXPointFromLane(self, lane: float) -> float:
        if not (parent := self.parentWidget()):
            raise SystemError()

        center = (parent.width() / 2) - (Const.NOTE_WIDTH * (Const.LANE_COUNT / 2))

        return center + lane * Const.NOTE_WIDTH

    def getBeatFromYPoint(self, y: int) -> float:
        return (self.height() - 50 - y) / 2

    def getYPointFromBeat(self, beat: float) -> float:
        return (self.height() - 50) - beat * 2

    def getLaneFromXPoint(self, point: int) -> float:
        if not (parent := self.parentWidget()):
            raise SystemError()

        center = (parent.width() / 2) - (Const.NOTE_WIDTH * (Const.LANE_COUNT / 2))

        return (point - center) / Const.NOTE_WIDTH

    def paintEvent(self, event: QPaintEvent):
        if not (parent := self.parentWidget()) or not (parent.size()):
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 背景を黒で塗りつぶす
        painter.fillRect(self.rect(), QColor("#000"))

        # レーン
        center = (parent.width() / 2) - (Const.NOTE_WIDTH * (Const.LANE_COUNT / 2))

        for x in range(Const.LANE_COUNT + 1):
            isOdd = x % 2 != 0
            if isOdd:
                painter.setPen(QPen(QColor("#888"), 1))
            else:
                painter.setPen(QPen(QColor("#ddd"), 1))

            point = round(center + x * Const.NOTE_WIDTH)
            painter.drawLine(point, 0, point, self.height())

        # 拍線 (BPM / Beat を見ないなど、バグあり)
        for y in range(self.height() - 50, 0, -round(self.getBeatFromYPoint(1) / 4)):
            painter.setPen(QPen(QColor("#888"), 1))
            painter.drawLine(
                round(self.getXPointFromLane(0)),
                y,
                round(self.getXPointFromLane(16)),
                y,
            )

        # ノーツ
        if not self.tapNotePixMap.isNull():
            for note in self.editing.chart.notes:
                match note.flag:
                    case NoteFlag.none:
                        painter.drawPixmap(
                            round(self.getXPointFromLane(note.lane)),
                            round(
                                self.getYPointFromBeat(note.beat)
                                - Const.NOTE_HEIGHT / 2
                            ),
                            Const.NOTE_WIDTH,
                            Const.NOTE_HEIGHT,
                            self.tapNotePixMap,
                        )

        # 音声再生位置
        painter.setPen(QPen(QColor("#f00"), 1))
        painter.drawLine(
            round(center + Const.NOTE_WIDTH),
            self.height() - 50,
            round(center + Const.LANE_COUNT * Const.NOTE_WIDTH),
            self.height() - 50,
        )

        painter.end()
