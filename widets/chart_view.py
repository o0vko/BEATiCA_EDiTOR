import math
from array import array

from PySide6 import QtMultimedia
from PySide6.QtCore import QElapsedTimer, QPoint, QPointF, QRect, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSpinBox,
    QWidget,
)

from etc import constants as Const
from objects.edit import EditingChart, EditMode, NoteAction
from objects.note import Change, CurveType, FlickType, LongNote, Note, NoteFlag
from objects.types import FixedInteger


class ChartViewWidget(QWidget):
    # 再生中、シークバーをビューポートのどの高さに固定するか（0.0=上端, 1.0=下端）
    PLAYHEAD_VIEWPORT_RATIO = 0.8
    # 波形の解像度（PIXELS_PER_SECOND が 100 なので 10ms = 1px）
    WAVEFORM_BUCKET_SECONDS = 0.01

    def __init__(
        self,
        editing: EditingChart,
        scrollArea: QScrollArea,
        player: QtMultimedia.QMediaPlayer,
    ):
        super().__init__()
        self.editing: EditingChart = editing
        self.scrollArea = scrollArea
        self.player = player

        self.setMouseTracking(True)

        self.seekTimer = QTimer(self)
        self.seekTimer.setTimerType(Qt.TimerType.PreciseTimer)
        self.seekTimer.setInterval(16)  # 約60FPS
        self.seekTimer.timeout.connect(self.updateSeek)
        self.player.playbackStateChanged.connect(self.onPlaybackStateChanged)
        self.player.durationChanged.connect(self.onDurationChanged)
        self.lastSeekY = None

        # 実測位置はバックエンドの更新間隔が粗いので、その間を経過時間で補間する
        self.tickClock = QElapsedTimer()
        self.tickClock.start()
        self.rawPositionMs = 0
        self.smoothTime = 0.0
        self.waitingForPosition = True

        # 波形表示
        self.waveformPeaks = array("f")
        self.waveformPending = array("f")
        self.waveformPendingType = ""
        self.waveformMaxPeak = 0.0
        self.waveformGain = 1.0
        self.waveformRedrawClock = QElapsedTimer()
        self.waveformRedrawClock.start()
        self.audioDecoder: QtMultimedia.QAudioDecoder | None = None
        self.player.sourceChanged.connect(self.onSourceChanged)

        # 編集用
        self.eventRects: list[tuple[int, QRect]] = []
        self.noteRects: list[tuple[int, QRect]] = []

        # ドラッグ用
        self.draggingNoteIds: set[int] = set()
        self.dragStartPos: QPoint | None = None
        self.dragStartBeats: dict[int, float] = {}
        self.dragStartLanes: dict[int, float] = {}

        # リサイズ用
        self.resizingNoteId: int | None = None
        self.resizeEdge: str | None = None  # 'left' or 'right'
        self.resizeStartWidth: float = 0.0
        self.resizeStartX: float = 0.0

        self.tapNotePixMap = QPixmap(Const.IMAGES_PATH / "tap_note.png")
        self.traceNotePixMap = QPixmap(Const.IMAGES_PATH / "trace_note.png")
        self.longNotePixMap = QPixmap(Const.IMAGES_PATH / "long_note.png")
        self.longNoteConnectorPixMap = QPixmap(
            Const.IMAGES_PATH / "long_note_connector.png"
        )

        self.subdivision: int = 4

        # ホバー プレビュー用
        self.hoverLane: int | None = None
        self.hoverBeat: float | None = None
        self.hoverEventBeat: float | None = None
        self.hoverLongNoteStart: tuple[float, int] | None = None

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
        viewport = self.scrollArea.viewport()

        duration = self.player.duration() / 1000.0
        offset = self.getOffsetSeconds()
        chartEnd = self.getChartEndTime()

        # 音源と譜面の両方が収まる高さ + 上下の余白
        timelineDuration = max(duration, chartEnd + offset)
        height = max(
            viewport.height(),
            math.ceil(timelineDuration * Const.PIXELS_PER_SECOND + 100),
        )

        oldHeight = self.height()
        self.setMinimumSize(viewport.width(), height)
        self.resize(viewport.width(), height)

        # 高さが変わった場合、シークバーの表示位置を維持するためスクロールを補正
        if oldHeight != height:
            self.compensateSeekScroll(oldHeight, height)

    def compensateSeekScroll(self, oldHeight: int, newHeight: int):
        """ウィジェット高さ変更時にシークバーのビューポート内位置を維持する"""
        bar = self.scrollArea.verticalScrollBar()
        if bar.isSliderDown():
            return

        # 現在のスムーズタイムでの Y 座標（旧・新）
        oldY = round(self.getYPointFromTimeAtHeight(self.smoothTime, oldHeight))
        newY = round(self.getYPointFromTimeAtHeight(self.smoothTime, newHeight))

        delta = newY - oldY
        if delta != 0:
            target = bar.value() + delta
            target = max(bar.minimum(), min(bar.maximum(), target))
            bar.setValue(target)

    def getYPointFromTimeAtHeight(self, time: float, height: int) -> float:
        return height - 50 - time * Const.PIXELS_PER_SECOND

    def getYPointFromTime(self, time: float) -> float:
        return self.getYPointFromTimeAtHeight(time, self.height())

    def getTimeFromYPoint(self, y: float) -> float:
        return (self.height() - 50 - y) / Const.PIXELS_PER_SECOND

    def getOffsetSeconds(self) -> float:
        return self.editing.chart.offset / 1000.0

    def getChartEndTime(self) -> float:
        beats = [note.beat for note in self.editing.chart.notes]
        beats += [change.beat for change in self.editing.chart.globalChanges]

        if not beats:
            return 0.0

        try:
            return self.getTimeFromBeat(max(beats))
        except ValueError:
            return 0.0

    def getYPointFromBeat(self, beat: float) -> float:
        return self.getYPointFromTime(
            self.getTimeFromBeat(beat) + self.getOffsetSeconds()
        )

    def getBeatFromYPoint(self, y: float) -> float:
        return self.getBeatFromTime(self.getTimeFromYPoint(y) - self.getOffsetSeconds())

    def snapBeat(self, beat: float, subdivision: float = 4) -> float:
        return round(beat * subdivision) / subdivision

    def getTimeFromBeat(self, beat: float) -> float:
        changes = sorted(
            self.editing.chart.globalChanges,
            key=lambda c: c.beat,
        )

        if not changes:
            raise ValueError("No global changes")

        elapsed = 0.0

        for i, change in enumerate(changes):
            if change.beat >= beat:
                break

            nextBeat = changes[i + 1].beat if i + 1 < len(changes) else beat

            endBeat = min(beat, nextBeat)

            elapsed += (endBeat - change.beat) * 60.0 / change.bpm

        return elapsed

    def getBeatFromTime(self, targetTime: float) -> float:
        changes = sorted(
            self.editing.chart.globalChanges,
            key=lambda c: c.beat,
        )

        if not changes:
            raise ValueError("No global changes")

        elapsed = 0.0

        for i, change in enumerate(changes):
            nextChange = changes[i + 1] if i + 1 < len(changes) else None

            if nextChange is None:
                return change.beat + ((targetTime - elapsed) * change.bpm / 60.0)

            duration = (nextChange.beat - change.beat) * 60.0 / change.bpm

            if targetTime <= elapsed + duration:
                return change.beat + ((targetTime - elapsed) * change.bpm / 60.0)

            elapsed += duration

        return 0.0

    def getLaneFromXPoint(self, point: float) -> float:
        if not (parent := self.parentWidget()):
            raise SystemError()

        center = (parent.width() / 2) - (Const.NOTE_WIDTH * (Const.LANE_COUNT / 2))

        return (point - center) / Const.NOTE_WIDTH

    def onResized(self, pos: int, index: int):
        self.syncWidth()

    def onDurationChanged(self, duration: int):
        self.syncWidth()

    def onSourceChanged(self, url: QUrl):
        self.stopWaveformDecode()

        self.waveformPeaks = array("f")
        self.waveformPending = array("f")
        self.waveformPendingType = ""
        self.waveformMaxPeak = 0.0
        self.waveformGain = 1.0
        self.update()

        if url.isEmpty() or not url.isLocalFile():
            return

        decoder = QtMultimedia.QAudioDecoder(self)
        decoder.bufferReady.connect(self.onWaveformBuffer)
        decoder.finished.connect(self.onWaveformFinished)
        decoder.error.connect(self.onWaveformError)
        self.audioDecoder = decoder

        decoder.setSource(url)
        decoder.start()

    def stopWaveformDecode(self):
        if self.audioDecoder is None:
            return

        self.audioDecoder.stop()
        self.audioDecoder.deleteLater()
        self.audioDecoder = None

    def onWaveformBuffer(self):
        decoder = self.audioDecoder

        if decoder is None or self.sender() is not decoder:
            return

        buffer = decoder.read()

        if not buffer.isValid():
            return

        fmt = buffer.format()

        match fmt.sampleFormat():
            case QtMultimedia.QAudioFormat.SampleFormat.Float:
                typecode, scale, bias = "f", 1.0, 0.0
            case QtMultimedia.QAudioFormat.SampleFormat.Int16:
                typecode, scale, bias = "h", 1 / 32768, 0.0
            case QtMultimedia.QAudioFormat.SampleFormat.Int32:
                typecode, scale, bias = "i", 1 / 2147483648, 0.0
            case QtMultimedia.QAudioFormat.SampleFormat.UInt8:
                typecode, scale, bias = "B", 1 / 128, 128.0
            case _:
                return

        samples = array(typecode)
        samples.frombytes(buffer.constData())

        if typecode != self.waveformPendingType:
            self.waveformPending = array(typecode)
            self.waveformPendingType = typecode
        elif len(self.waveformPending):
            samples = self.waveformPending + samples

        channels = max(1, fmt.channelCount())
        sampleRate = fmt.sampleRate()

        if sampleRate <= 0:
            return

        framesPerBucket = max(1, round(sampleRate * Const.WAVEFORM_BUCKET_SECONDS))
        samplesPerBucket = framesPerBucket * channels
        bucketCount = len(samples) // samplesPerBucket

        for i in range(bucketCount):
            chunk = samples[i * samplesPerBucket : (i + 1) * samplesPerBucket]
            low = min(chunk)
            high = max(chunk)

            if bias:
                peak = max(abs(low - bias), abs(high - bias)) * scale
            else:
                peak = max(abs(low), abs(high)) * scale

            peak = min(peak, 1.0)
            self.waveformPeaks.append(peak)
            self.waveformMaxPeak = max(self.waveformMaxPeak, peak)

        self.waveformPending = samples[bucketCount * samplesPerBucket :]

        if self.waveformRedrawClock.elapsed() >= 100:
            self.waveformRedrawClock.restart()
            self.update()

    def onWaveformFinished(self):
        decoder = self.audioDecoder

        if decoder is None or self.sender() is not decoder:
            return

        if self.waveformMaxPeak > 0:
            self.waveformGain = min(1.0 / self.waveformMaxPeak, 8.0)

        self.waveformPending = array(self.waveformPendingType or "f")
        self.waveformRedrawClock.restart()
        self.update()

    def onWaveformError(self, error):
        decoder = self.audioDecoder

        if decoder is None or self.sender() is not decoder:
            return

        print(f"波形のデコードに失敗しました: {error} {decoder.errorString()}")

    def onChartChanged(self):
        self.syncWidth()
        self.update()

    def onPlaybackStateChanged(self, state):
        self.syncSmoothPosition()
        self.waitingForPosition = True

        if state == QtMultimedia.QMediaPlayer.PlaybackState.PlayingState:
            self.seekTimer.start()
        else:
            self.seekTimer.stop()
            self.update()

    def syncSmoothPosition(self):
        self.rawPositionMs = self.player.position()
        self.smoothTime = self.rawPositionMs / 1000.0
        self.tickClock.restart()

    def updateSeek(self):
        elapsed = self.tickClock.restart() / 1000.0
        positionMs = self.player.position()
        rawTime = positionMs / 1000.0
        snapped = False

        if positionMs != self.rawPositionMs:
            previousPositionMs = self.rawPositionMs
            self.rawPositionMs = positionMs
            self.waitingForPosition = False

            if positionMs < previousPositionMs or rawTime > self.smoothTime:
                # シークで戻った場合、または実測位置が補間値より進んだ場合
                self.smoothTime = rawTime
                snapped = True

        if (
            not snapped
            and not self.waitingForPosition
            and self.player.playbackState()
            == QtMultimedia.QMediaPlayer.PlaybackState.PlayingState
        ):
            # 実測位置が更新されるまでの間を経過時間で埋める
            self.smoothTime += elapsed

        y = round(self.getYPointFromTime(self.smoothTime))

        if self.lastSeekY is not None:
            top = min(self.lastSeekY, y) - 2
            bottom = max(self.lastSeekY, y) + 2

            self.update(
                0,
                top,
                self.width(),
                bottom - top,
            )
        else:
            self.update(0, y - 2, self.width(), 5)

        self.lastSeekY = y
        self.followSeek(y)

    def followSeek(self, y: float):
        bar = self.scrollArea.verticalScrollBar()

        # ユーザーがスクロールバーを操作している間は邪魔しない
        if bar.isSliderDown():
            return

        viewportHeight = self.scrollArea.viewport().height()
        target = round(y - viewportHeight * Const.PLAYHEAD_VIEWPORT_RATIO)
        target = max(bar.minimum(), min(bar.maximum(), target))

        if bar.value() != target:
            bar.setValue(target)

    def mousePressEvent(self, event: QMouseEvent):
        if self.editing.editMode == EditMode.SELECT:
            if event.button() == Qt.MouseButton.RightButton:
                # 右クリックでノーツ削除
                self.deleteNoteAt(event.pos())
                return

            if event.button() != Qt.MouseButton.LeftButton:
                return

            modifiers = event.modifiers()

            # イベント矩形のクリック判定
            for idx, rect in self.eventRects:
                if rect.contains(event.pos()):
                    self.editGlobalChange(idx)
                    return

            # ノーツ矩形のクリック判定 → 選択＆ドラッグ開始
            clickedNoteId = None
            hitMargin = 8  # 判定領域を広げる（px）
            for id, rect in self.noteRects:
                hitRect = rect.adjusted(-hitMargin, -Const.NOTE_HEIGHT, hitMargin, Const.NOTE_HEIGHT)
                if hitRect.contains(event.pos()):
                    clickedNoteId = id
                    break

            if clickedNoteId is not None:
                clickedNote = next(
                    (n for n in self.editing.chart.notes if n.id == clickedNoteId), None
                )
                if clickedNote:
                    # エッジ判定（左右端から5px以内ならリサイズモード）
                    rect = next(r for i, r in self.noteRects if i == clickedNoteId)
                    edgeThreshold = 5
                    if (
                        abs(event.pos().x() - rect.left()) <= edgeThreshold
                        or abs(event.pos().x() - rect.right()) <= edgeThreshold
                    ):
                        if abs(event.pos().x() - rect.left()) <= edgeThreshold:
                            self.startResize(clickedNoteId, "left", rect)
                        else:
                            self.startResize(clickedNoteId, "right", rect)
                        return

                    # Ctrl/Shift 押下で選択追加、それ以外は選択置き換え
                    if modifiers & (
                        Qt.KeyboardModifier.ControlModifier
                        | Qt.KeyboardModifier.ShiftModifier
                    ):
                        if clickedNote not in self.editing.selectedNotes:
                            self.editing.selectedNotes.append(clickedNote)
                    else:
                        self.editing.selectedNotes = [clickedNote]

                    self.startDrag(clickedNoteId, event.pos())
                    self.update()
                return

            # 空白クリック → 選択解除してシーク
            self.editing.selectedNotes.clear()
            self.update()
            lane = math.floor(self.getLaneFromXPoint(event.x()))

            if 0 <= lane <= Const.LANE_COUNT - 1:
                self.player.setPosition(round(self.getTimeFromYPoint(event.y()) * 1000))
                self.updateSeek()
        elif self.editing.editMode == EditMode.TAP_NOTE:
            lane = math.floor(self.getLaneFromXPoint(event.x()))

            if 0 <= lane <= Const.LANE_COUNT - 1:
                beat = self.getBeatFromYPoint(event.y())
                beat = self.snapBeat(beat, self.subdivision / 4)

                self.editing.pushAction(
                    NoteAction(
                        type="note_place",
                        data=Note(
                            id=self.editing.nextNoteId,
                            beat=beat,
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
                self.editing.nextNoteId += 1

                self.update()
        elif self.editing.editMode == EditMode.TRACE_NOTE:
            lane = math.floor(self.getLaneFromXPoint(event.x()))

            if 0 <= lane <= Const.LANE_COUNT - 1:
                beat = self.getBeatFromYPoint(event.y())
                beat = self.snapBeat(beat, self.subdivision / 4)

                self.editing.pushAction(
                    NoteAction(
                        type="note_place",
                        data=Note(
                            id=self.editing.nextNoteId,
                            beat=beat,
                            lane=lane,
                            width=1,
                            curveType=CurveType.linear,
                            flickType=FlickType.none,
                            flag=NoteFlag.trace,
                            layer=0,
                            skyNote=0,
                        ),
                    )
                )
                self.editing.nextNoteId += 1

                self.update()
        elif self.editing.editMode == EditMode.EVENT:
            lane = math.floor(self.getLaneFromXPoint(event.x()))

            if 0 <= lane <= Const.LANE_COUNT - 1:
                beat = self.getBeatFromYPoint(event.y())
                beat = self.snapBeat(beat, self.subdivision / 4)

                # 既に同じ位置にイベントがあるか確認
                existing = next(
                    (
                        c
                        for c in self.editing.chart.globalChanges
                        if abs(c.beat - beat) < 0.001
                    ),
                    None,
                )
                if existing:
                    self.editGlobalChangeAtBeat(beat)
                else:
                    self.placeEvent(beat)

                self.update()
        elif self.editing.editMode == EditMode.LONG_NOTE:
            lane = math.floor(self.getLaneFromXPoint(event.x()))

            if 0 <= lane <= Const.LANE_COUNT - 1:
                beat = self.getBeatFromYPoint(event.y())
                beat = self.snapBeat(beat, self.subdivision / 4)

                if not hasattr(self, "_longNoteStartBeat"):
                    # 最初のクリック：開始位置を記録
                    self._longNoteStartBeat = beat
                    self._longNoteStartLane = lane
                else:
                    # 2回目のクリック：終了位置でロングノーツ確定
                    endBeat = beat
                    endLane = lane
                    startBeat = self._longNoteStartBeat
                    startLane = self._longNoteStartLane

                    if abs(endBeat - startBeat) > 0.001:
                        self.placeLongNote(startBeat, endBeat, startLane, endLane)

                    delattr(self, "_longNoteStartBeat")
                    delattr(self, "_longNoteStartLane")

                self.update()
        elif self.editing.editMode == EditMode.LONG_NOTE_CONNECTOR:
            # ロングノーツの台形クリックで支点（コネクター）を追加
            self.addLongNoteConnector(event.pos())
            self.update()

    def startDrag(self, noteId: int, pos: QPoint):
        """ドラッグ開始"""
        # 対象ノーツを取得
        note = next((n for n in self.editing.chart.notes if n.id == noteId), None)
        if note is None:
            return

        # 現在選択中のノーツをドラッグ対象にする（クリックしたノーツが選択に含まれている前提）
        self.draggingNoteIds = {n.id for n in self.editing.selectedNotes}

        self.dragStartPos = pos
        self.dragStartBeats = {n.id: n.beat for n in self.editing.selectedNotes}
        self.dragStartLanes = {n.id: n.lane for n in self.editing.selectedNotes}

    def startResize(self, noteId: int, edge: str, rect: QRect):
        """リサイズ開始"""
        note = next((n for n in self.editing.chart.notes if n.id == noteId), None)
        if note is None:
            return

        self.resizingNoteId = noteId
        self.resizeEdge = edge  # 'left' or 'right'
        self.resizeStartWidth = note.width
        self.resizeStartX = rect.left() if edge == "left" else rect.right()

    def mouseMoveEvent(self, event: QMouseEvent):
        # リサイズ処理
        if self.resizingNoteId is not None and self.resizeEdge is not None:
            if self.editing.editMode != EditMode.SELECT:
                self.cancelResize()
                return

            note = next(
                (n for n in self.editing.chart.notes if n.id == self.resizingNoteId),
                None,
            )
            if note is None:
                self.cancelResize()
                return

            # マウス位置から新しい幅を計算
            currentX = event.pos().x()
            deltaX = currentX - self.resizeStartX

            if self.resizeEdge == "left":
                # 左端を動かす: lane変更 + width変更
                newLane = self.getLaneFromXPoint(currentX)
                newLane = max(0, min(Const.LANE_COUNT - 1, round(newLane)))
                widthChange = note.lane - newLane
                newWidth = self.resizeStartWidth + widthChange
                if newWidth >= 1:
                    note.lane = newLane
                    note.width = newWidth
            else:  # 'right'
                # 右端を動かす: widthのみ変更
                newRightX = self.resizeStartX + deltaX
                newRightLane = self.getLaneFromXPoint(newRightX)
                newRightLane = max(
                    note.lane, min(Const.LANE_COUNT, round(newRightLane))
                )
                newWidth = newRightLane - note.lane
                if newWidth >= 1:
                    note.width = newWidth

            self.update()
            return

        # リサイズ/ドラッグしていない場合はホバープレビュー更新＆カーソル変更
        if self.resizingNoteId is None and (
            not self.draggingNoteIds or self.dragStartPos is None
        ):
            self.updateHoverPreview(event.pos())
            self.updateCursor(event.pos())
            return

        # 通常のドラッグ処理
        if (
            self.draggingNoteIds
            and self.dragStartPos is not None
            and self.editing.editMode == EditMode.SELECT
        ):
            # Y方向の移動 → beat変更
            deltaBeat = self.getBeatFromYPoint(
                event.pos().y()
            ) - self.getBeatFromYPoint(self.dragStartPos.y())

            # X方向の移動 → lane変更
            deltaLane = self.getLaneFromXPoint(
                event.pos().x()
            ) - self.getLaneFromXPoint(self.dragStartPos.x())

            # スナップ処理
            snappedDeltaBeat = (
                self.snapBeat(deltaBeat, self.subdivision / 4) - deltaBeat
            )
            snappedDeltaLane = round(deltaLane) - deltaLane

            # 全選択ノーツを移動
            for note in self.editing.chart.notes:
                if note.id in self.draggingNoteIds:
                    note.beat = (
                        self.dragStartBeats[note.id] + deltaBeat + snappedDeltaBeat
                    )
                    note.lane = max(
                        0,
                        min(
                            Const.LANE_COUNT - 1,
                            self.dragStartLanes[note.id] + deltaLane + snappedDeltaLane,
                        ),
                    )

            self.editing.chart.notes.sort(key=lambda n: n.beat)
            self.update()
            return

    def updateHoverPreview(self, pos: QPoint):
        """マウス位置に基づいてホバープレビュー位置を更新"""
        lane = math.floor(self.getLaneFromXPoint(pos.x()))

        if 0 <= lane <= Const.LANE_COUNT - 1:
            beat = self.getBeatFromYPoint(pos.y())
            beat = self.snapBeat(beat, self.subdivision / 4)

            mode = self.editing.editMode

            if mode in (EditMode.TAP_NOTE, EditMode.TRACE_NOTE, EditMode.EVENT):
                self.hoverLane = lane
                self.hoverBeat = beat
                if mode == EditMode.EVENT:
                    self.hoverEventBeat = beat
                else:
                    self.hoverEventBeat = None
                self.hoverLongNoteStart = None
            elif mode in (EditMode.LONG_NOTE, EditMode.LONG_NOTE_CONNECTOR):
                self.hoverLane = lane
                self.hoverBeat = beat
                # 始点が設定済みなら終点プレビュー用
                if hasattr(self, "_longNoteStartBeat"):
                    self.hoverLongNoteStart = (
                        self._longNoteStartBeat,
                        self._longNoteStartLane,
                    )
                else:
                    self.hoverLongNoteStart = None
            else:
                self.clearHoverPreview()
                return
        else:
            self.clearHoverPreview()
            return

        self.update()

    def clearHoverPreview(self):
        self.hoverLane = None
        self.hoverBeat = None
        self.hoverEventBeat = None
        self.hoverLongNoteStart = None
        self.update()

    def updateCursor(self, pos: QPoint):
        """マウス位置に応じてカーソルを変更"""
        if self.editing.editMode != EditMode.SELECT:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return

        edgeThreshold = 5
        for noteId, rect in self.noteRects:
            hitRect = rect.adjusted(-8, -Const.NOTE_HEIGHT, 8, Const.NOTE_HEIGHT)
            if hitRect.contains(pos):
                if (
                    abs(pos.x() - rect.left()) <= edgeThreshold
                    or abs(pos.x() - rect.right()) <= edgeThreshold
                ):
                    self.setCursor(Qt.CursorShape.SizeHorCursor)
                    return
                self.setCursor(Qt.CursorShape.PointingHandCursor)
                return

        self.setCursor(Qt.CursorShape.ArrowCursor)

    def cancelResize(self):
        self.resizingNoteId = None
        self.resizeEdge = None
        self.resizeStartWidth = 0
        self.resizeStartX = 0.0

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.resizingNoteId is not None:
                self.cancelResize()
            elif self.draggingNoteIds:
                self.draggingNoteIds.clear()
                self.dragStartPos = None
                self.dragStartBeats.clear()
                self.dragStartLanes.clear()
            self.update()

    def deleteNoteAt(self, pos: QPoint):
        """指定位置のノーツを削除"""
        hitMargin = 8
        for id, rect in self.noteRects:
            hitRect = rect.adjusted(-hitMargin, -hitMargin, hitMargin, hitMargin)
            if hitRect.contains(pos):
                note = next((n for n in self.editing.chart.notes if n.id == id), None)
                if note:
                    self.editing.pushAction(NoteAction(type="note_remove", data=note))
                return

    def editGlobalChange(self, index: int):
        """グローバルチェンジ（BPM/拍子/速度）を編集するダイアログを表示"""
        if index < 0 or index >= len(self.editing.chart.globalChanges):
            return

        # ソート済みリストでのインデックスを元のリストのインデックスに変換
        sorted_changes = sorted(
            enumerate(self.editing.chart.globalChanges),
            key=lambda c: c[1].beat,
        )
        original_idx = sorted_changes[index][0]
        change: Change = self.editing.chart.globalChanges[original_idx]

        dialog = QDialog(self)
        dialog.setWindowTitle(f"イベント編集 (beat={change.beat})")
        dialog.setModal(True)
        layout = QFormLayout(dialog)

        bpmSpin = QDoubleSpinBox()
        bpmSpin.setRange(1.0, 999.0)
        bpmSpin.setDecimals(3)
        bpmSpin.setValue(change.bpm)
        layout.addRow("BPM", bpmSpin)

        # 拍子を「分子/分母」形式で表示（難易度と同じスタイル）
        tsMajorSpin = QSpinBox()
        tsMajorSpin.setRange(1, 16)
        tsMajorSpin.setValue(change.timeSignature.major)

        tsMinorSpin = QSpinBox()
        tsMinorSpin.setRange(1, 16)
        tsMinorSpin.setValue(change.timeSignature.minor)

        tsLayout = QHBoxLayout()
        tsLayout.addWidget(tsMajorSpin)
        tsLayout.addWidget(QLabel("/"))
        tsLayout.addWidget(tsMinorSpin)
        tsLayout.addStretch()

        layout.addRow("拍子", tsLayout)

        speedSpin = QDoubleSpinBox()
        speedSpin.setRange(0.01, 10.0)
        speedSpin.setDecimals(3)
        speedSpin.setSingleStep(0.01)
        speedSpin.setValue(change.speedRate)
        layout.addRow("Speed Rate", speedSpin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            # 変更を適用
            change.bpm = bpmSpin.value()
            change.timeSignature.major = tsMajorSpin.value()
            change.timeSignature.minor = tsMinorSpin.value()
            change.speedRate = speedSpin.value()
            self.update()

    def editGlobalChangeAtBeat(self, beat: float):
        """指定ビートのグローバルチェンジを編集"""
        for i, change in enumerate(self.editing.chart.globalChanges):
            if abs(change.beat - beat) < 0.001:
                self.editGlobalChange(i)
                return

    def placeLongNote(
        self, startBeat: float, endBeat: float, startLane: int, endLane: int
    ):
        """ロングノーツを配置（始点・終点のみ、間は描画で繋ぐ）"""
        # 開始ノーツ作成
        startNote = Note(
            id=self.editing.nextNoteId,
            beat=startBeat,
            lane=startLane,
            width=1,
            curveType=CurveType.linear,
            flickType=FlickType.none,
            flag=NoteFlag.longNote,
            layer=0,
            skyNote=0,
        )
        startId = self.editing.nextNoteId
        self.editing.chart.notes.append(startNote)
        self.editing.nextNoteId += 1

        # 終了ノーツ作成
        endNote = Note(
            id=self.editing.nextNoteId,
            beat=endBeat,
            lane=endLane,
            width=1,
            curveType=CurveType.linear,
            flickType=FlickType.none,
            flag=NoteFlag.longNote,
            layer=0,
            skyNote=0,
        )
        endId = self.editing.nextNoteId
        self.editing.chart.notes.append(endNote)
        self.editing.nextNoteId += 1

        # LongNote 作成（始点・終点のノーツIDのみ保持）
        longNote = LongNote(
            id=self.editing.nextNoteId,
            curveType=CurveType.linear,
            steps=[startId, endId],
            startBeat=startBeat,
        )
        self.editing.chart.longNotes.append(longNote)
        self.editing.nextNoteId += 1

        self.editing.chart.notes.sort(key=lambda n: n.beat)
        self.update()

    def placeEvent(self, beat: float):
        """新しいグローバルチェンジ（イベント）を配置"""
        # 直前のChangeをコピーしてデフォルト値とする
        prevChange = None
        for change in sorted(self.editing.chart.globalChanges, key=lambda c: c.beat):
            if change.beat <= beat:
                prevChange = change
            else:
                break

        if prevChange is None:
            prevChange = Change(
                beat=0.0,
                bpm=120.0,
                timeSignature=FixedInteger(major=4, minor=4),
                speedRate=1.0,
            )

        newChange = Change(
            beat=beat,
            bpm=prevChange.bpm,
            timeSignature=FixedInteger(
                major=prevChange.timeSignature.major,
                minor=prevChange.timeSignature.minor,
            ),
            speedRate=prevChange.speedRate,
        )
        self.editing.chart.globalChanges.append(newChange)
        self.editing.chart.globalChanges.sort(key=lambda c: c.beat)
        self.update()

    def addLongNoteConnector(self, pos: QPoint):
        """ロングノーツの台形クリックで支点（コネクター）を追加"""
        # クリック位置の beat/lane を計算
        lane = math.floor(self.getLaneFromXPoint(pos.x()))
        if not (0 <= lane <= Const.LANE_COUNT - 1):
            return

        beat = self.getBeatFromYPoint(pos.y())
        beat = self.snapBeat(beat, self.subdivision / 4)

        # どのロングノーツの台形がクリックされたか判定
        for longNote in self.editing.chart.longNotes:
            if len(longNote.steps) < 2:
                continue

            startNote = next(
                (n for n in self.editing.chart.notes if n.id == longNote.steps[0]), None
            )
            endNote = next(
                (n for n in self.editing.chart.notes if n.id == longNote.steps[-1]),
                None,
            )
            if not startNote or not endNote:
                continue

            # 始点・終点の座標
            startX = (
                self.getXPointFromLane(startNote.lane)
                + startNote.width * Const.NOTE_WIDTH / 2
            )
            startY = self.getYPointFromBeat(startNote.beat)
            endX = (
                self.getXPointFromLane(endNote.lane)
                + endNote.width * Const.NOTE_WIDTH / 2
            )
            endY = self.getYPointFromBeat(endNote.beat)

            # 台形の4頂点
            startHalfW = startNote.width * Const.NOTE_WIDTH / 2
            endHalfW = endNote.width * Const.NOTE_WIDTH / 2
            points = [
                QPointF(startX - startHalfW, startY),
                QPointF(startX + startHalfW, startY),
                QPointF(endX + endHalfW, endY),
                QPointF(endX - endHalfW, endY),
            ]

            # クリック位置が台形内か判定
            polygon = QPolygonF(points)
            qpf = QPointF(pos.x(), pos.y())
            if not polygon.containsPoint(qpf, Qt.FillRule.OddEvenFill):
                continue

            # クリック位置の beat/lane を計算（台形内での相対位置から補間）
            # Y座標から beat を求める（台形の上下方向）
            t = (pos.y() - startY) / (endY - startY) if endY != startY else 0
            t = max(0.0, min(1.0, t))
            insertBeat = startNote.beat + t * (endNote.beat - startNote.beat)
            insertBeat = self.snapBeat(insertBeat, self.subdivision / 4)

            # X座標から lane を求める（台形の左右方向）
            # 上下で線形補間
            leftX = startX - startHalfW + t * (endX - endHalfW - (startX - startHalfW))
            rightX = startX + startHalfW + t * (endX + endHalfW - (startX + startHalfW))
            laneRatio = (pos.x() - leftX) / (rightX - leftX) if rightX != leftX else 0.5
            laneRatio = max(0.0, min(1.0, laneRatio))
            insertLane = round(
                startNote.lane + laneRatio * (endNote.lane - startNote.lane)
            )
            insertLane = max(0, min(Const.LANE_COUNT - 1, insertLane))

            # 既に同じ位置にノーツがあるかチェック
            existing = next(
                (
                    n
                    for n in self.editing.chart.notes
                    if abs(n.beat - insertBeat) < 0.001 and n.lane == insertLane
                ),
                None,
            )
            if existing:
                return

            # 新しい支点ノーツを作成
            newNote = Note(
                id=self.editing.nextNoteId,
                beat=insertBeat,
                lane=insertLane,
                width=1,
                curveType=CurveType.linear,
                flickType=FlickType.none,
                flag=NoteFlag.longNote,
                layer=0,
                skyNote=0,
            )
            newNoteId = self.editing.nextNoteId
            self.editing.chart.notes.append(newNote)
            self.editing.nextNoteId += 1

            # LongNote の steps に挿入（beat順でソート）
            # beat順でソートし直す
            allStepNotes = [
                (n.beat, n.id)
                for n in self.editing.chart.notes
                if n.id in longNote.steps
            ]
            allStepNotes.append((insertBeat, newNoteId))
            allStepNotes.sort(key=lambda x: x[0])
            longNote.steps = [note_id for _, note_id in allStepNotes]

            self.editing.chart.notes.sort(key=lambda n: n.beat)
            self.update()
            break

    def getXPointFromLane(self, lane: float) -> float:
        if not (parent := self.parentWidget()):
            raise SystemError()

        center = (parent.width() / 2) - (Const.NOTE_WIDTH * (Const.LANE_COUNT / 2))

        return center + lane * Const.NOTE_WIDTH

    def drawWaveform(self, painter: QPainter, center: float, rect: QRect):
        peaks = self.waveformPeaks

        if not peaks:
            return

        laneWidth = Const.NOTE_WIDTH * Const.LANE_COUNT
        laneCenter = center + laneWidth / 2
        maxHalfWidth = laneWidth / 2 - 2

        top = max(0, rect.top())
        bottom = min(self.height() - 1, rect.bottom())

        leftPoints: list[QPointF] = []
        rightPoints: list[QPointF] = []

        for y in range(top, bottom + 1):
            index = int(self.getTimeFromYPoint(y + 0.5) / Const.WAVEFORM_BUCKET_SECONDS)

            if not 0 <= index < len(peaks):
                continue

            halfWidth = min(peaks[index] * self.waveformGain, 1.0) * maxHalfWidth

            leftPoints.append(QPointF(laneCenter - halfWidth, y + 0.5))
            rightPoints.append(QPointF(laneCenter + halfWidth, y + 0.5))

        if len(leftPoints) < 2:
            return

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(64, 156, 255, 90))
        painter.drawPolygon(QPolygonF(leftPoints + rightPoints[::-1]))

    def drawLane(self, painter: QPainter, center: float):
        for x in range(Const.LANE_COUNT + 1):
            isOdd = x % 2 != 0
            if isOdd:
                painter.setPen(QPen(QColor("#888"), 1))
            else:
                painter.setPen(QPen(QColor("#ddd"), 1))

            point = round(center + x * Const.NOTE_WIDTH)
            painter.drawLine(point, 0, point, self.height())

    def drawBeatLine(self, painter: QPainter):
        visibleRect = self.visibleRegion().boundingRect()

        if not visibleRect.isEmpty():
            visibleBeatStart = self.getBeatFromYPoint(visibleRect.bottom())
            visibleBeatEnd = self.getBeatFromYPoint(visibleRect.top())

            changes = sorted(
                self.editing.chart.globalChanges,
                key=lambda c: c.beat,
            )

            for i, change in enumerate(changes):
                ts = change.timeSignature

                # 1拍（拍子の分母に相当する音符）の長さ
                beatStep = 4 / ts.minor

                # 1小節の長さ
                measureStep = ts.major * beatStep

                # 次のChangeまでを描画区間とする
                segmentStart = max(change.beat, visibleBeatStart)
                segmentEnd = (
                    min(changes[i + 1].beat, visibleBeatEnd)
                    if i + 1 < len(changes)
                    else visibleBeatEnd
                )

                if segmentStart > segmentEnd:
                    continue

                first = math.ceil((segmentStart - change.beat) / beatStep)
                last = math.floor((segmentEnd - change.beat) / beatStep)

                for n in range(first, last + 1):
                    beat = change.beat + n * beatStep
                    y = round(self.getYPointFromBeat(beat))

                    # 小節線と通常の拍線を区別
                    isMeasure = n % ts.major == 0

                    painter.setPen(
                        QPen(
                            QColor("#ddd" if isMeasure else "#555"),
                            2 if isMeasure else 1,
                        )
                    )

                    painter.drawLine(
                        round(self.getXPointFromLane(0)),
                        y,
                        round(self.getXPointFromLane(16)),
                        y,
                    )

    def drawNotes(self, painter: QPainter):
        self.noteRects.clear()
        if not self.tapNotePixMap.isNull():
            selectedIds = {n.id for n in self.editing.selectedNotes}

            for note in sorted(
                self.editing.chart.notes,
                key=lambda c: c.beat,
            ):
                isSelected = note.id in selectedIds

                match note.flag:
                    case NoteFlag.none | NoteFlag.trace | NoteFlag.longNote:
                        noteWidth = max(1, note.width) * Const.NOTE_WIDTH
                        rect = QRect(
                            round(self.getXPointFromLane(note.lane)),
                            round(
                                self.getYPointFromBeat(note.beat)
                                - Const.NOTE_HEIGHT / 2
                            ),
                            round(noteWidth),
                            Const.NOTE_HEIGHT,
                        )
                        self.noteRects.append(
                            (
                                note.id,
                                rect,
                            )
                        )

                        # 選択時のハイライト（背後に光る枠）
                        if isSelected:
                            painter.save()
                            painter.setPen(QPen(QColor("#ff0"), 2))
                            painter.setBrush(QColor(255, 255, 0, 40))
                            # ノーツより少し大きい矩形でハイライト
                            highlightRect = rect.adjusted(-3, -3, 3, 3)
                            painter.drawRect(highlightRect)
                            painter.restore()

                        # 適切なピクセルマップを選択
                        if note.flag == NoteFlag.none:
                            pixmap = self.tapNotePixMap
                        elif note.flag == NoteFlag.trace:
                            pixmap = self.traceNotePixMap
                        else:  # NoteFlag.longNote
                            # ロングノーツの始点・終点以外はコネクター用テクスチャを使用
                            isLongNoteEndpoint = False
                            isConnector = False
                            for ln in self.editing.chart.longNotes:
                                if note.id in ln.steps:
                                    if (
                                        note.id == ln.steps[0]
                                        or note.id == ln.steps[-1]
                                    ):
                                        isLongNoteEndpoint = True
                                    else:
                                        isConnector = True
                                    break
                            if isConnector:
                                pixmap = (
                                    self.longNoteConnectorPixMap
                                    if not self.longNoteConnectorPixMap.isNull()
                                    else self.longNotePixMap
                                )
                            else:
                                pixmap = (
                                    self.longNotePixMap
                                    if not self.longNotePixMap.isNull()
                                    else self.tapNotePixMap
                                )

                        painter.drawPixmap(
                            rect,
                            pixmap,
                        )

        # ロングノーツ描画
        if not self.longNotePixMap.isNull():
            for longNote in self.editing.chart.longNotes:
                self.drawLongNote(painter, longNote)

    def drawLongNote(self, painter: QPainter, longNote: LongNote):
        """ロングノーツを描画（全ステップを繋いで一つの連続したロングノーツとして描画）"""
        if len(longNote.steps) < 2:
            return

        # 全ステップのノーツを取得（beat順でソート済み）
        stepNotes = []
        for noteId in longNote.steps:
            note = next((n for n in self.editing.chart.notes if n.id == noteId), None)
            if note:
                stepNotes.append(note)

        if len(stepNotes) < 2:
            return

        # 各ステップの中心座標と半幅を計算
        stepPoints = []
        for note in stepNotes:
            x = self.getXPointFromLane(note.lane) + note.width * Const.NOTE_WIDTH / 2
            y = self.getYPointFromBeat(note.beat)
            halfW = note.width * Const.NOTE_WIDTH / 2
            stepPoints.append((x, y, halfW))

        # 連続したポリゴンを作成（各ステップ間を台形で繋ぐ）
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setOpacity(0.5)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(Qt.PenStyle.NoPen)

        if not self.longNotePixMap.isNull():
            # 全ステップを繋ぐ連続したパスを作成
            path = QPainterPath()

            # 最初の台形の左上から開始
            x0, y0, w0 = stepPoints[0]
            path.moveTo(x0 - w0, y0)

            # 上辺を右へ（最初のノーツの右上へ）
            path.lineTo(x0 + w0, y0)

            # 各ステップ間を台形で繋ぐ
            for i in range(len(stepPoints) - 1):
                x1, y1, w1 = stepPoints[i]
                x2, y2, w2 = stepPoints[i + 1]

                # 現在のステップの右上から次のステップの右上へ
                path.lineTo(x1 + w1, y1)
                # 次のステップの右下へ
                path.lineTo(x2 + w2, y2)

            # 最後のステップの左下へ
            x_last, y_last, w_last = stepPoints[-1]
            path.lineTo(x_last + w_last, y_last)

            # 下辺を左へ戻る
            for i in range(len(stepPoints) - 1, 0, -1):
                x, y, w = stepPoints[i]
                path.lineTo(x - w, y)

            # 最初のステップの左上へ戻る
            x0, y0, w0 = stepPoints[0]
            path.lineTo(x0 - w0, y0)
            path.closeSubpath()

            # テクスチャブラシを作成（全体の平均幅でスケーリング）
            totalWidth = sum(n.width for n in stepNotes) * Const.NOTE_WIDTH
            avgWidth = totalWidth / len(stepPoints)
            totalHeight = abs(stepPoints[-1][1] - stepPoints[0][1])
            if totalHeight == 0:
                totalHeight = 1

            textureBrush = QBrush(self.longNotePixMap)
            textureBrush.setTransform(
                painter.transform()
                .inverted()[0]
                .scale(1.0 / avgWidth, 1.0 / totalHeight)
                if totalHeight != 0
                else painter.transform()
            )
            painter.setBrush(textureBrush)
            painter.setOpacity(0.5)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPath(path)
        else:
            # フォールバック: ポリゴンとして描画
            points = []
            # 上辺
            for i in range(len(stepPoints) - 1):
                x, y, w = stepPoints[i]
                if i == 0:
                    points.append(QPointF(x - w, y))
                points.append(QPointF(x + w, y))
            # 右下
            x, y, w = stepPoints[-1]
            points.append(QPointF(x + w, y))
            # 下辺（逆順）
            for i in range(len(stepPoints) - 1, -1, -1):
                x, y, w = stepPoints[i]
                points.append(QPointF(x - w, y))
            points.append(
                QPointF(stepPoints[0][0] - stepPoints[0][2], stepPoints[0][1])
            )

            painter.setBrush(QColor(64, 156, 255, 128))
            painter.drawPolygon(QPolygonF(points))

        painter.restore()

        # 選択ハイライト（全体の輪郭）
        isSelected = longNote.id in {n.id for n in self.editing.selectedNotes}
        if isSelected:
            painter.save()
            painter.setPen(QPen(QColor("#ff0"), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)

            # 全体の輪郭を描画
            points = []
            for i in range(len(stepPoints) - 1):
                x, y, w = stepPoints[i]
                if i == 0:
                    points.append(QPointF(x - w, y))
                points.append(QPointF(x + w, y))
            x, y, w = stepPoints[-1]
            points.append(QPointF(x + w, y))
            for i in range(len(stepPoints) - 1, -1, -1):
                x, y, w = stepPoints[i]
                points.append(QPointF(x - w, y))
            points.append(
                QPointF(stepPoints[0][0] - stepPoints[0][2], stepPoints[0][1])
            )

            painter.drawPolygon(QPolygonF(points))
            painter.restore()

    def drawSeek(self, painter: QPainter, center: float):
        y = round(self.getYPointFromTime(self.smoothTime))

        # 1pxの線がアンチエイリアスで2pxににじんでちらつくのを防ぐ
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QPen(QColor("#f00"), 1))
        painter.drawLine(
            round(center),
            y,
            round(center + Const.NOTE_WIDTH * Const.LANE_COUNT),
            y,
        )
        painter.restore()

    def drawEvents(self, painter: QPainter):
        self.eventRects.clear()
        visibleRect = self.visibleRegion().boundingRect()

        if not visibleRect.isEmpty():
            # visibleBeatStart = self.getBeatFromYPoint(visibleRect.bottom())
            # visibleBeatEnd = self.getBeatFromYPoint(visibleRect.top())

            for i, change in enumerate(
                sorted(
                    self.editing.chart.globalChanges,
                    key=lambda c: c.beat,
                )
            ):
                y = round(self.getYPointFromBeat(change.beat))
                if not visibleRect.top() <= y <= visibleRect.bottom():
                    continue

                painter.setPen(
                    QPen(
                        QColor("#ddd"),
                    )
                )

                painter.drawLine(
                    round(self.getXPointFromLane(16)),
                    y,
                    round(self.getXPointFromLane(18)),
                    y,
                )

                text = f"{change.bpm}BPM, {change.timeSignature.major}/{change.timeSignature.minor}, x{change.speedRate}"
                metrics = QFontMetrics(painter.font())

                padding = 4
                rectWidth = metrics.horizontalAdvance(text) + padding * 2
                rectHeight = metrics.height() + padding * 2

                rect = QRect(
                    round(self.getXPointFromLane(18)),
                    round(y - rectHeight / 2),
                    rectWidth,
                    rectHeight,
                )
                self.eventRects.append(
                    (
                        i,
                        rect,
                    )
                )

                painter.setPen(QColor("#ff2277"))
                painter.setBrush(QColor("#ff2277"))
                painter.drawRect(rect)

                painter.setPen(QColor("#fff"))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def paintEvent(self, event: QPaintEvent):
        if not (parent := self.parentWidget()) or not (parent.size()):
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 背景を黒で塗りつぶす
        painter.fillRect(self.rect(), QColor("#000"))

        center = (parent.width() / 2) - (Const.NOTE_WIDTH * (Const.LANE_COUNT / 2))
        self.drawWaveform(painter, center, event.rect())
        self.drawLane(painter, center)
        self.drawBeatLine(painter)
        self.drawNotes(painter)
        self.drawHoverPreview(painter, center)
        self.drawSeek(painter, center)

        self.drawEvents(painter)

        painter.end()

    def drawHoverPreview(self, painter: QPainter, center: float):
        """ホバープレビューを描画（半透明のノーツ/イベント/ロングノーツプレビュー）"""
        if self.hoverLane is None or self.hoverBeat is None:
            return

        # プレビュー用の半透明設定
        painter.save()
        painter.setOpacity(0.4)

        mode = self.editing.editMode

        if mode in (EditMode.TAP_NOTE, EditMode.TRACE_NOTE):
            # 通常ノーツプレビュー
            pixmap = (
                self.tapNotePixMap
                if mode == EditMode.TAP_NOTE
                else self.traceNotePixMap
            )
            rect = QRect(
                round(self.getXPointFromLane(self.hoverLane)),
                round(self.getYPointFromBeat(self.hoverBeat) - Const.NOTE_HEIGHT / 2),
                Const.NOTE_WIDTH,
                Const.NOTE_HEIGHT,
            )
            painter.drawPixmap(rect, pixmap)

        elif mode == EditMode.EVENT:
            # イベントプレビュー（点線）
            y = round(self.getYPointFromBeat(self.hoverBeat))
            painter.setPen(QPen(QColor("#ff0"), 1, Qt.PenStyle.DashLine))
            painter.drawLine(
                round(self.getXPointFromLane(16)),
                y,
                round(self.getXPointFromLane(18)),
                y,
            )
            # テキスト
            prevChange = None
            for change in sorted(
                self.editing.chart.globalChanges, key=lambda c: c.beat
            ):
                if change.beat <= self.hoverBeat:
                    prevChange = change
                else:
                    break
            if prevChange:
                text = f"{prevChange.bpm}BPM, {prevChange.timeSignature.major}/{prevChange.timeSignature.minor}, x{prevChange.speedRate}"
            else:
                text = "120BPM, 4/4, x1.0"
            metrics = QFontMetrics(painter.font())
            padding = 4
            rectWidth = metrics.horizontalAdvance(text) + padding * 2
            rectHeight = metrics.height() + padding * 2
            rect = QRect(
                round(self.getXPointFromLane(18)),
                round(y - rectHeight / 2),
                rectWidth,
                rectHeight,
            )
            painter.setPen(QColor("#ff0"))
            painter.setBrush(QColor("#ff0"))
            painter.drawRect(rect)
            painter.setPen(QColor("#000"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

        elif mode in (EditMode.LONG_NOTE, EditMode.LONG_NOTE_CONNECTOR):
            # ロングノーツプレビュー
            if mode == EditMode.LONG_NOTE_CONNECTOR:
                # コネクタープレビュー（マウス位置に半透明コネクターノーツ）
                rect = QRect(
                    round(self.getXPointFromLane(self.hoverLane)),
                    round(
                        self.getYPointFromBeat(self.hoverBeat) - Const.NOTE_HEIGHT / 2
                    ),
                    Const.NOTE_WIDTH,
                    Const.NOTE_HEIGHT,
                )
                pixmap = (
                    self.longNoteConnectorPixMap
                    if not self.longNoteConnectorPixMap.isNull()
                    else self.longNotePixMap
                )
                painter.drawPixmap(rect, pixmap)
            elif hasattr(self, "_longNoteStartBeat"):
                startBeat = self._longNoteStartBeat
                startLane = self._longNoteStartLane
                endBeat = self.hoverBeat
                endLane = self.hoverLane

                # 始点ノーツ（半透明）
                startRect = QRect(
                    round(self.getXPointFromLane(startLane)),
                    round(self.getYPointFromBeat(startBeat) - Const.NOTE_HEIGHT / 2),
                    Const.NOTE_WIDTH,
                    Const.NOTE_HEIGHT,
                )
                painter.drawPixmap(
                    startRect,
                    self.longNotePixMap
                    if not self.longNotePixMap.isNull()
                    else self.tapNotePixMap,
                )

                # 終点ノーツ（半透明）
                endRect = QRect(
                    round(self.getXPointFromLane(endLane)),
                    round(self.getYPointFromBeat(endBeat) - Const.NOTE_HEIGHT / 2),
                    Const.NOTE_WIDTH,
                    Const.NOTE_HEIGHT,
                )
                painter.drawPixmap(
                    endRect,
                    self.longNotePixMap
                    if not self.longNotePixMap.isNull()
                    else self.tapNotePixMap,
                )

                # 台形プレビュー（半透明・テクスチャ）
                startX = self.getXPointFromLane(startLane) + Const.NOTE_WIDTH / 2
                startY = self.getYPointFromBeat(startBeat)
                endX = self.getXPointFromLane(endLane) + Const.NOTE_WIDTH / 2
                endY = self.getYPointFromBeat(endBeat)

                halfW = Const.NOTE_WIDTH / 2
                points = [
                    QPointF(startX - halfW, startY),
                    QPointF(startX + halfW, startY),
                    QPointF(endX + halfW, endY),
                    QPointF(endX - halfW, endY),
                ]

                if not self.longNotePixMap.isNull():
                    path = QPainterPath()
                    path.moveTo(points[0])
                    path.lineTo(points[1])
                    path.lineTo(points[2])
                    path.lineTo(points[3])
                    path.closeSubpath()

                    textureBrush = QBrush(self.longNotePixMap)
                    textureBrush.setTransform(
                        painter.transform()
                        .inverted()[0]
                        .scale(1.0 / Const.NOTE_WIDTH, 1.0 / (endY - startY))
                        if endY != startY
                        else painter.transform()
                    )
                    painter.setBrush(textureBrush)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawPath(path)
                else:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(64, 156, 255, 64))
                    painter.drawPolygon(QPolygonF(points))
            else:
                # 始点プレビューのみ
                rect = QRect(
                    round(self.getXPointFromLane(self.hoverLane)),
                    round(
                        self.getYPointFromBeat(self.hoverBeat) - Const.NOTE_HEIGHT / 2
                    ),
                    Const.NOTE_WIDTH,
                    Const.NOTE_HEIGHT,
                )
                painter.drawPixmap(
                    rect,
                    self.longNotePixMap
                    if not self.longNotePixMap.isNull()
                    else self.tapNotePixMap,
                )

        painter.restore()
