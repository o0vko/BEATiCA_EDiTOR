import itertools

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from etc import constants as Const
from objects.edit import EditingChart
from objects.note import CurveType, Note, NoteFlag, SkyNote


def _ease(curveType: CurveType, t: float) -> float:
    if curveType == CurveType.linear:
        return t
    if curveType == CurveType.easeIn:
        return t * t
    if curveType == CurveType.easeOut:
        return 1 - (1 - t) * (1 - t)
    if curveType == CurveType.easeInOut:
        return 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2
    if curveType == CurveType.easeOutIn:
        return 1 - (-2 * t + 2) ** 2 / 2 if t < 0.5 else 2 * t * t
    return t


class FrontViewWidget(QWidget):
    """正面図。現在の再生位置にいるノーツを表示し、スカイノーツの位置を編集できる。"""

    # 現在位置として扱う拍のウィンドウ（±この拍数）
    NOTE_WINDOW = 0.5
    MARGIN = 20

    def __init__(self, editing: EditingChart, chartView=None):
        super().__init__()
        self.editing: EditingChart = editing
        self.chartView = chartView

        self.setMinimumSize(0, 240)

        self.skyNotePixMap = QPixmap(Const.assetPath("images", "sky_note.png"))
        self.skyTraceNotePixMap = QPixmap(
            Const.assetPath("images", "sky_trace_note.png")
        )

        # ドラッグ中のスカイノーツ
        self.draggingNote: Note | None = None
        self.draggingSkyNote: SkyNote | None = None

        # 再生位置の変化に合わせて再描画
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.update)
        self.timer.start()

    # --- 座標変換 ---
    def _laneWidth(self) -> float:
        return (self.width() - 2 * self.MARGIN) / Const.LANE_COUNT

    def laneToX(self, lane: float) -> float:
        return self.MARGIN + lane * self._laneWidth()

    def xToLane(self, x: float) -> float:
        lw = self._laneWidth()
        if lw <= 0:
            return 0.0
        return (x - self.MARGIN) / lw

    def positionYToY(self, positionY: float) -> float:
        # positionY VIEW_MIN..VIEW_MAX → 画面下..上
        span = Const.POSITION_Y_VIEW_MAX - Const.POSITION_Y_VIEW_MIN
        ny = (positionY - Const.POSITION_Y_VIEW_MIN) / span
        ny = max(0.0, min(1.0, ny))
        return self.height() - ny * self.height()

    def yToPositionY(self, y: float) -> float:
        if self.height() <= 0:
            return 0.0
        ny = 1.0 - (y / self.height())
        return Const.POSITION_Y_VIEW_MIN + max(0.0, min(1.0, ny)) * (
            Const.POSITION_Y_VIEW_MAX - Const.POSITION_Y_VIEW_MIN
        )

    # --- 現在位置 ---
    def getCurrentBeat(self) -> float:
        if self.chartView is None:
            return 0.0
        try:
            return self.chartView.getBeatFromTime(self.chartView.smoothTime)
        except ValueError:
            return 0.0

    # --- スカイノーツのY座標（拍で補間） ---
    def getSkyPositionYAt(
        self, skyNote: SkyNote, beat: float, curveType: CurveType = CurveType.linear
    ) -> float:
        return self._interpSky(skyNote, beat, curveType, "positionY")

    def getSkyLaneAt(
        self, skyNote: SkyNote, beat: float, curveType: CurveType = CurveType.linear
    ) -> float:
        return self._interpSky(skyNote, beat, curveType, "lane")

    def _interpSky(
        self,
        skyNote: SkyNote,
        beat: float,
        curveType: CurveType,
        attr: str,
    ) -> float:
        points = sorted(skyNote.floatings, key=lambda f: f.beat)
        if not points:
            return 0.0
        if beat <= points[0].beat:
            return getattr(points[0], attr)
        if beat >= points[-1].beat:
            return getattr(points[-1], attr)
        for a, b in itertools.pairwise(points):
            if a.beat <= beat <= b.beat:
                if b.beat == a.beat:
                    return getattr(b, attr)
                t = (beat - a.beat) / (b.beat - a.beat)
                # スカイノーツは lane と positionY で別々の曲線を持てる。
                # 未設定（旧データ）の場合はノーツ側の curveType にフォールバック。
                if attr == "lane":
                    segmentCurve = a.laneCurveType or curveType
                else:
                    segmentCurve = a.positionYCurveType or curveType
                eased = _ease(segmentCurve, t)
                va = getattr(a, attr)
                vb = getattr(b, attr)
                return va + (vb - va) * eased
        return getattr(points[-1], attr)

    def setSkyPositionYAt(self, skyNote: SkyNote, beat: float, positionY: float):
        # 同じ拍の浮動点をまとめて更新（単一位置のスカイノーツを一緒に動かす）
        knotsAt = [f for f in skyNote.floatings if abs(f.beat - beat) < 0.001]
        if knotsAt:
            for f in knotsAt:
                f.positionY = positionY
        elif skyNote.floatings:
            nearest = min(skyNote.floatings, key=lambda f: abs(f.beat - beat))
            nearest.positionY = positionY

    # --- 描画 ---
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.fillRect(self.rect(), QColor("#000"))

        currentBeat = self.getCurrentBeat()
        skyNotes = {s.id: s for s in self.editing.chart.skyNotes}
        zeroY = self.positionYToY(0.0)

        # レーンの縦グリッド
        painter.setPen(QPen(QColor("#444"), 1))
        for i in range(Const.LANE_COUNT + 1):
            x = round(self.laneToX(i))
            painter.drawLine(x, 0, x, self.height())

        # positionY のグリッド（0.5ごと、0.0と5.0は太め）
        step = 0.5
        n = round((Const.POSITION_Y_VIEW_MIN) / step)
        while n * step <= Const.POSITION_Y_VIEW_MAX + 1e-6:
            refY = n * step
            y = round(self.positionYToY(refY))
            if abs(refY) < 1e-6 or abs(refY - 5.0) < 1e-6:
                painter.setPen(QPen(QColor("#2a8"), 1))
            else:
                painter.setPen(QPen(QColor("#234"), 1))
            painter.drawLine(0, y, self.width(), y)
            n += 1

        # 現在の再生位置にいるノーツ（通常は0.0位置、スカイは補間位置）
        for note in self.editing.chart.notes:
            if abs(note.beat - currentBeat) > self.NOTE_WINDOW:
                continue

            skyNote = skyNotes.get(note.id)
            if skyNote is not None:
                # スカイノーツ: X=lane, Y=positionY（拍で補間）
                lane = self.getSkyLaneAt(skyNote, currentBeat, note.curveType)
                posY = self.getSkyPositionYAt(skyNote, currentBeat, note.curveType)
                self._paintSky(painter, note, skyNote, self.laneToX(lane), posY)
            else:
                x = self.laneToX(note.lane)
                w = max(1, note.width) * self._laneWidth()
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#4aa3ff"))
                painter.drawRect(round(x), round(zeroY - 3), round(w), 6)

        # ロングノーツのスカイノーツ（始点〜終点を補間）
        for longNote in self.editing.chart.longNotes:
            if len(longNote.steps) < 2:
                continue
            skyNote = self.editing.longNoteSkyNote(longNote)
            if skyNote is None:
                continue
            startNote = next(
                (n for n in self.editing.chart.notes if n.id == longNote.steps[0]),
                None,
            )
            endNote = next(
                (n for n in self.editing.chart.notes if n.id == longNote.steps[-1]),
                None,
            )
            if startNote is None or endNote is None:
                continue
            if not (startNote.beat <= currentBeat <= endNote.beat):
                continue
            lane = self.getSkyLaneAt(skyNote, currentBeat, startNote.curveType)
            posY = self.getSkyPositionYAt(skyNote, currentBeat, startNote.curveType)
            self._paintSky(painter, startNote, skyNote, self.laneToX(lane), posY)

        # スカイノーツの制御点（knot）をノーツとして表示
        self._drawSkyKnots(painter)

        painter.end()

    def _drawSkyKnots(self, painter: QPainter):
        """スカイノーツのknotをノーツ絵で描画（選択中は強調）"""
        selectedIndex = self.editing.selectedKnotIndex
        selectedSky = None
        if self.chartView is not None:
            _note, selectedSky = self.editing.selectedSkyNote()

        h = Const.NOTE_WIDTH
        w = 4 * self._laneWidth()
        for skyNote in self.editing.chart.skyNotes:
            isSelectedSky = skyNote is selectedSky
            ordered = sorted(skyNote.floatings, key=lambda f: f.beat)

            # 軌跡（knot 同士を結ぶ曲線）
            if len(ordered) >= 2:
                path = QPainterPath()
                first = True
                for a, b in itertools.pairwise(ordered):
                    if b.beat == a.beat:
                        continue
                    for i in range(17):
                        t = i / 16
                        eased = _ease(a.laneCurveType or CurveType.linear, t)
                        lane = a.lane + (b.lane - a.lane) * eased
                        posYEased = _ease(a.positionYCurveType or CurveType.linear, t)
                        posY = a.positionY + (b.positionY - a.positionY) * posYEased
                        x = self.laneToX(lane)
                        y = self.positionYToY(posY)
                        if first:
                            path.moveTo(x, y)
                            first = False
                        else:
                            path.lineTo(x, y)
                if not first:
                    painter.save()
                    painter.setPen(QPen(QColor("#0ff"), 2 if isSelectedSky else 1))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawPath(path)
                    painter.restore()

            for index, f in enumerate(ordered):
                x = self.laneToX(f.lane) - w / 2
                y = self.positionYToY(f.positionY) - h / 2
                pixmap = self.skyNotePixMap
                if not pixmap.isNull():
                    scaled = pixmap.scaled(
                        round(w),
                        h,
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    painter.drawPixmap(QPoint(round(x), round(y)), scaled)
                else:
                    painter.setBrush(QColor("#4aa3ff"))
                    painter.drawRect(round(x), round(y), round(w), h)

                if isSelectedSky and index == selectedIndex:
                    painter.save()
                    painter.setPen(QPen(QColor("#ff0"), 2))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRect(round(x) - 2, round(y) - 2, round(w) + 4, h + 4)
                    painter.restore()

    def _paintSky(self, painter: QPainter, note, skyNote, x: float, posY: float):
        """スカイノーツのマーカーとYPositionを描画"""
        y = self.positionYToY(posY)
        pixmap = (
            self.skyTraceNotePixMap
            if note.flag == NoteFlag.trace
            else self.skyNotePixMap
        )
        w = max(1, note.width) * self._laneWidth()
        h = Const.NOTE_WIDTH
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                round(w),
                h,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(QPoint(round(x), round(y - h / 2)), scaled)
        else:
            painter.setBrush(QColor("#4aa3ff"))
            painter.drawRect(round(x), round(y - h / 2), round(w), h)

        # 現在のYPositionをわかりやすく表示
        painter.setPen(QColor("#fff"))
        painter.drawText(QPoint(round(x + w + 2), round(y + 4)), f"Y{posY:.2f}")

    # --- スカイノーツのドラッグ編集 ---
    def _hitSkyNote(self, pos: QPoint):
        currentBeat = self.getCurrentBeat()
        for note in self.editing.chart.notes:
            if abs(note.beat - currentBeat) > self.NOTE_WINDOW:
                continue
            skyNote = next(
                (s for s in self.editing.chart.skyNotes if s.id == note.id), None
            )
            if skyNote is None:
                continue
            lane = self.getSkyLaneAt(skyNote, currentBeat, note.curveType)
            x = self.laneToX(lane)
            y = self.positionYToY(
                self.getSkyPositionYAt(skyNote, currentBeat, note.curveType)
            )
            w = max(1, note.width) * self._laneWidth()
            h = Const.NOTE_WIDTH
            if 0 <= pos.x() - x <= w and abs(pos.y() - y) <= h:
                return note, skyNote

        # ロングノーツのスカイノーツ
        for longNote in self.editing.chart.longNotes:
            if len(longNote.steps) < 2:
                continue
            skyNote = self.editing.longNoteSkyNote(longNote)
            if skyNote is None:
                continue
            startNote = next(
                (n for n in self.editing.chart.notes if n.id == longNote.steps[0]),
                None,
            )
            endNote = next(
                (n for n in self.editing.chart.notes if n.id == longNote.steps[-1]),
                None,
            )
            if startNote is None or endNote is None:
                continue
            if not (startNote.beat <= currentBeat <= endNote.beat):
                continue
            lane = self.getSkyLaneAt(skyNote, currentBeat, startNote.curveType)
            x = self.laneToX(lane)
            y = self.positionYToY(
                self.getSkyPositionYAt(skyNote, currentBeat, startNote.curveType)
            )
            w = max(1, startNote.width) * self._laneWidth()
            h = Const.NOTE_WIDTH
            if 0 <= pos.x() - x <= w and abs(pos.y() - y) <= h:
                return startNote, skyNote
        return None, None

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        note, skyNote = self._hitSkyNote(event.pos())
        if skyNote is not None:
            self.draggingNote = note
            self.draggingSkyNote = skyNote

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.draggingSkyNote is None:
            return
        currentBeat = self.getCurrentBeat()
        # 縦移動のみ → positionY（0.5ごとに吸い付き、Shiftで無視）
        positionY = self.yToPositionY(event.pos().y())
        noSnap = (self.chartView is not None and self.chartView.forceNoSnap) or bool(
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        )
        if not noSnap:
            positionY = round(positionY * 2) / 2

        # 選択中のknotがあればそこを、無ければ最近傍/同拍を更新
        idx = self.editing.selectedKnotIndex
        knots = self.draggingSkyNote.floatings
        if idx is not None and 0 <= idx < len(knots):
            knots[idx].positionY = positionY
        else:
            self.setSkyPositionYAt(self.draggingSkyNote, currentBeat, positionY)

        if self.chartView is not None:
            self.chartView.skyKnotsChanged.emit()
            self.chartView.update()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self.draggingNote = None
        self.draggingSkyNote = None
