import math
from array import array

from PySide6 import QtMultimedia
from PySide6.QtCore import (
    QElapsedTimer,
    QPoint,
    QPointF,
    QRect,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
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
    QGestureEvent,
    QHBoxLayout,
    QLabel,
    QMenu,
    QScrollArea,
    QSpinBox,
    QWidget,
)

from etc import constants as Const
from objects.edit import (
    EditingChart,
    EditMode,
    LongNoteAction,
    NoteAction,
    SkyNoteAction,
)
from objects.note import (
    Change,
    CurveType,
    FlickType,
    LongNote,
    Note,
    NoteFlag,
    SkyNote,
    SkyNoteFloating,
)
from objects.types import FixedInteger


class ChartViewWidget(QWidget):
    # ノーツ選択変更シグナル
    noteSelectionChanged = Signal()
    # 表示設定（ズーム倍率・スナップ分割数・レーン区切り数）変更シグナル
    viewSettingsChanged = Signal(float, int, int)
    # スカイノーツのknotが変更された（リスト再表示用）
    skyKnotsChanged = Signal()
    # クリップボードが変更された（ペースト可否の更新用）
    clipboardChanged = Signal()

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

        # ノーツ配置・通過時のタップ音
        self.noteTap = QtMultimedia.QSoundEffect(self)
        self.noteTap.setSource(
            QUrl.fromLocalFile(str(Const.SOUNDS_PATH / "perfect.wav"))
        )
        self.noteTap.setVolume(1.0)

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
        self.prevNoteCheckTime = 0.0
        self.internalPlaying = False
        # タッチ用: スナップ無視トグル
        self.forceNoSnap = False

        # タッチ用: ピンチズーム・長押しコンテキスト
        self.grabGesture(Qt.GestureType.PinchGesture)
        self.longPressTimer = QTimer(self)
        self.longPressTimer.setSingleShot(True)
        self.longPressTimer.setInterval(500)
        self.longPressTimer.timeout.connect(self.onLongPress)
        self.longPressPos: QPoint | None = None

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
        self.knotRects: list[tuple[int, QRect]] = []
        self.draggingKnotIndex: int | None = None

        # コピー/ペースト・ドラッグ選択
        self.clipboard: list[dict] = []
        self.rubberStart: QPoint | None = None
        self.rubberRect: QRect | None = None

        # ドラッグ用
        self.draggingNoteIds: set[int] = set()
        self.dragStartPos: QPoint | None = None
        self.dragStartBeats: dict[int, float] = {}
        self.dragStartLanes: dict[int, float] = {}
        self.dragMoved: bool = False
        self.pressNoteId: int | None = None
        self.pressConvertFlick: bool = False

        # リサイズ用
        self.resizingNoteId: int | None = None
        self.resizeEdge: str | None = None  # 'left' or 'right'
        self.resizeStartWidth: float = 0.0
        self.resizeStartLane: float = 0.0
        self.resizeStartX: float = 0.0

        self.tapNotePixMap = QPixmap(Const.IMAGES_PATH / "tap_note.png")
        self.traceNotePixMap = QPixmap(Const.IMAGES_PATH / "trace_note.png")
        self.longNotePixMap = QPixmap(Const.IMAGES_PATH / "long_note.png")
        self.longNoteConnectorPixMap = QPixmap(
            Const.IMAGES_PATH / "long_note_connector.png"
        )
        self.flickNotePixMap = QPixmap(Const.IMAGES_PATH / "flick_note.png")
        self.flickTraceNotePixMap = QPixmap(Const.IMAGES_PATH / "flick_trace_note.png")
        self.flickNoteArrowPixMap = QPixmap(Const.IMAGES_PATH / "flick_note_arrow.png")
        self.skyNotePixMap = QPixmap(Const.IMAGES_PATH / "sky_note.png")
        self.skyTraceNotePixMap = QPixmap(Const.IMAGES_PATH / "sky_trace_note.png")

        # 表示倍率（縦方向のズーム）とスナップ（1拍あたりの分割数）
        self.pixelsPerSecond: float = Const.PIXELS_PER_SECOND
        self.snap: int = 4
        # レーンの区切り数（表示上の縦グリッドの分割数）
        self.laneDivision: int = Const.LANE_COUNT

        # ホバー プレビュー用
        self.hoverLane: float | None = None
        self.hoverBeat: float | None = None
        self.hoverEventBeat: float | None = None
        self.hoverLongNoteStart: tuple[float, float] | None = None

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
        # 音源が無くても最低 MIN_MEASURES 小節分は確保する
        timelineDuration = max(
            duration,
            chartEnd + offset,
            self.getMinTimelineDuration(),
        )
        height = max(
            viewport.height(),
            math.ceil(timelineDuration * self.pixelsPerSecond + 100),
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
        return height - 50 - time * self.pixelsPerSecond

    def getYPointFromTime(self, time: float) -> float:
        return self.getYPointFromTimeAtHeight(time, self.height())

    def getTimeFromYPoint(self, y: float) -> float:
        return (self.height() - 50 - y) / self.pixelsPerSecond

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

    def getMinTimelineDuration(self) -> float:
        """最低限確保する譜面長（秒）。先頭から MIN_MEASURES 小節分。"""
        changes = sorted(self.editing.chart.globalChanges, key=lambda c: c.beat)
        if not changes:
            return 0.0

        ts = changes[0].timeSignature
        measureStep = ts.major * (4 / ts.minor)
        targetBeat = changes[0].beat + Const.MIN_MEASURES * measureStep

        try:
            return self.getTimeFromBeat(targetBeat) + self.getOffsetSeconds()
        except ValueError:
            return 0.0

    def getYPointFromBeat(self, beat: float) -> float:
        return self.getYPointFromTime(
            self.getTimeFromBeat(beat) + self.getOffsetSeconds()
        )

    def getBeatFromYPoint(self, y: float) -> float:
        return self.getBeatFromTime(self.getTimeFromYPoint(y) - self.getOffsetSeconds())

    def snapBeat(self, beat: float) -> float:
        """小節内の分割数（self.snap）にスナップする"""
        changes = sorted(self.editing.chart.globalChanges, key=lambda c: c.beat)
        if not changes:
            step = 1.0 / self.snap
            return round(beat / step) * step

        # 対象拍が属するChange（小節の基準）を決定
        active = changes[0]
        for change in changes:
            if change.beat <= beat + 1e-9:
                active = change
            else:
                break

        ts = active.timeSignature
        beatStep = 4 / ts.minor  # 1拍の長さ
        measureStep = ts.major * beatStep  # 1小節の長さ
        step = measureStep / self.snap  # 1区切りの長さ

        k = round((beat - active.beat) / step)
        return active.beat + k * step

    def snapLane(self, lane: float) -> float:
        """レーン区切り（self.laneDivision）のグリッドに吸着する"""
        division = max(1, self.laneDivision)
        step = Const.LANE_COUNT / division
        return round(lane / step) * step

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

    def event(self, event):
        # ピンチズーム
        if isinstance(event, QGestureEvent):
            pinch = event.gesture(Qt.GestureType.PinchGesture)
            if pinch is not None and pinch.state() == Qt.GestureState.GestureUpdated:
                scale = pinch.scaleFactor()
                if scale and scale != 1.0:
                    factor = 1.0 + (scale - 1.0) * 0.2
                    self.zoomByFactor(factor)
                event.accept()
                return True
        return super().event(event)

    def onLongPress(self):
        if self.longPressPos is not None:
            self.showContextMenu(self.longPressPos, self.mapToGlobal(self.longPressPos))
        self.longPressPos = None

    def wheelEvent(self, event):
        """Ctrl+ホイールで縦ズーム、Shift+ホイールでスナップ変更"""
        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return

        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoomBy(delta)
        elif event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.cycleSnap(1 if delta > 0 else -1)
        else:
            super().wheelEvent(event)

    def zoomBy(self, delta: int):
        """ホイールの上下で表示倍率を変更（ビューポート上端の位置を維持）"""
        factor = Const.ZOOM_STEP if delta > 0 else 1.0 / Const.ZOOM_STEP
        self.zoomByFactor(factor)

    def zoomByFactor(self, factor: float):
        newPps = self.pixelsPerSecond * factor
        newPps = max(
            Const.PIXELS_PER_SECOND * Const.ZOOM_MIN,
            min(Const.PIXELS_PER_SECOND * Const.ZOOM_MAX, newPps),
        )
        if abs(newPps - self.pixelsPerSecond) < 1e-6:
            return

        # 現在のビューポート上端が示す time を保持する
        bar = self.scrollArea.verticalScrollBar()
        timeTop = self.getTimeFromYPoint(bar.value())

        self.pixelsPerSecond = newPps
        self.syncWidth()

        bar.setValue(
            max(
                bar.minimum(),
                min(bar.maximum(), round(self.getYPointFromTime(timeTop))),
            )
        )
        self.emitViewSettings()
        self.update()

    def cycleSnap(self, direction: int):
        """スナップ分割数を候補順に切り替える"""
        options = Const.SNAP_OPTIONS
        if self.snap in options:
            index = options.index(self.snap)
        else:
            index = min(range(len(options)), key=lambda i: abs(options[i] - self.snap))
        index = max(0, min(len(options) - 1, index + direction))
        self.snap = options[index]
        self.emitViewSettings()
        self.update()

    def emitViewSettings(self):
        self.viewSettingsChanged.emit(
            self.getZoomFactor(), self.snap, self.laneDivision
        )

    def getZoomFactor(self) -> float:
        return self.pixelsPerSecond / Const.PIXELS_PER_SECOND

    def setZoomFactor(self, factor: float):
        """コンボボックス等からズーム倍率を設定"""
        newPps = Const.PIXELS_PER_SECOND * factor
        newPps = max(
            Const.PIXELS_PER_SECOND * Const.ZOOM_MIN,
            min(Const.PIXELS_PER_SECOND * Const.ZOOM_MAX, newPps),
        )
        if abs(newPps - self.pixelsPerSecond) < 1e-6:
            return
        self.pixelsPerSecond = newPps
        self.syncWidth()
        self.emitViewSettings()
        self.update()

    def setSnapValue(self, snap: int):
        """コンボボックス等からスナップ分割数を設定"""
        self.snap = max(1, int(snap))
        self.emitViewSettings()
        self.update()

    def setLaneDivision(self, division: int):
        """コンボボックスからレーン区切り数を設定"""
        self.laneDivision = max(1, int(division))
        self.emitViewSettings()
        self.update()

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
        # 内部クロックが主。音源の再生状態変化で位置はリセットしない
        self.rawPositionMs = self.player.position()
        self.waitingForPosition = True
        self.update()

    def hasAudioSource(self) -> bool:
        source = self.player.source()
        return not source.isEmpty() and source.isLocalFile()

    def getTimelineEnd(self) -> float:
        """音源の長さと譜面の終了位置の大きい方（秒）"""
        duration = self.player.duration() / 1000.0
        chartEnd = self.getChartEndTime() + self.getOffsetSeconds()
        return max(duration, chartEnd)

    def togglePlay(self):
        if self.internalPlaying:
            self.pause()
        else:
            self.play()

    def play(self):
        if self.internalPlaying:
            return
        self.internalPlaying = True

        # 末尾に居る場合は先頭に戻す
        end = self.getTimelineEnd()
        if end > 0 and self.smoothTime >= end - 0.001:
            self.smoothTime = 0.0
            self.prevNoteCheckTime = 0.0
            self.lastSeekY = None

        self.waitingForPosition = True
        self.prevNoteCheckTime = self.smoothTime
        self.tickClock.restart()

        # 音源があれば内部時間に合わせて再生を開始
        if self.hasAudioSource():
            self.player.setPosition(round(self.smoothTime * 1000))
            self.player.play()

        self.seekTimer.start()

    def pause(self):
        if not self.internalPlaying:
            return
        self.internalPlaying = False
        self.seekTimer.stop()

        if self.hasAudioSource():
            self.player.pause()

        self.update()

    def syncSmoothPosition(self):
        self.rawPositionMs = self.player.position()
        self.smoothTime = self.rawPositionMs / 1000.0
        self.tickClock.restart()

    def seekTo(self, timeSec: float):
        """指定秒へシーク（音源なしでも内部クロックを更新）"""
        self.smoothTime = max(0.0, timeSec)
        self.prevNoteCheckTime = self.smoothTime
        self.waitingForPosition = True
        self.lastSeekY = None
        self.tickClock.restart()

        if self.hasAudioSource():
            self.player.setPosition(round(self.smoothTime * 1000))

        self.update()

    def updateSeek(self):
        elapsed = self.tickClock.restart() / 1000.0

        # 内部クロックを主時計として前進させる
        self.smoothTime += elapsed
        snapped = False

        playerPlaying = self.hasAudioSource() and (
            self.player.playbackState()
            == QtMultimedia.QMediaPlayer.PlaybackState.PlayingState
        )

        if playerPlaying:
            # 音源は緊急時の補正用。大きくずれたときだけ実測位置に合わせる
            audioTime = self.player.position() / 1000.0
            drift = audioTime - self.smoothTime
            if abs(drift) > Const.AUDIO_RESYNC_THRESHOLD:
                self.smoothTime = audioTime
                snapped = True

        # タイムライン末尾で停止
        end = self.getTimelineEnd()
        if end > 0 and self.smoothTime >= end:
            self.smoothTime = end
            self.pause()

        y = round(self.getYPointFromTime(self.smoothTime))

        # 三角マーカー（高さ±6）も再描画されるよう余白を広めに取る
        margin = 8
        if self.lastSeekY is not None:
            top = min(self.lastSeekY, y) - margin
            bottom = max(self.lastSeekY, y) + margin

            self.update(
                0,
                top,
                self.width(),
                bottom - top,
            )
        else:
            self.update(0, y - margin, self.width(), margin * 2)

        self.lastSeekY = y
        self.followSeek(y)
        self.playNotesCrossed(snapped)

    def playNotesCrossed(self, snapped: bool):
        """再生中に再生位置がノーツを通過したらタップ音を鳴らす"""
        cur = self.smoothTime
        prev = self.prevNoteCheckTime
        self.prevNoteCheckTime = cur

        if snapped or not self.internalPlaying:
            return

        # 前方への通常進行のみ（シークジャンプや巻き戻しは除外）
        if cur <= prev or cur - prev > 0.5:
            return

        try:
            offset = self.getOffsetSeconds()
            for note in self.editing.chart.notes:
                noteTime = self.getTimeFromBeat(note.beat) + offset
                if prev < noteTime <= cur:
                    self.noteTap.play()
                    break
        except ValueError:
            pass

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
        if Const.DEBUG_HITBOX:
            print(
                f"[DEBUG] mousePressEvent: pos={event.pos()}, mode={self.editing.editMode}"
            )

        # 長押しでコンテキストメニュー（タッチ/ペン向け、マウスでも可）
        if event.button() == Qt.MouseButton.LeftButton:
            self.longPressPos = event.pos()
            self.longPressTimer.start()

        # 右クリックはコンテキストメニュー（contextMenuEvent）に任せる
        if event.button() == Qt.MouseButton.RightButton:
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return

        # 押下状態をリセット
        self.dragMoved = False
        self.pressNoteId = None
        self.pressConvertFlick = False

        modifiers = event.modifiers()
        noSnap = self.forceNoSnap or bool(
            modifiers & Qt.KeyboardModifier.ShiftModifier
        )

        # knotハンドルのクリック判定（SELECTモードのみ）
        if self.editing.editMode == EditMode.SELECT:
            for idx, rect in self.knotRects:
                if rect.contains(event.pos()):
                    self.draggingKnotIndex = idx
                    self.editing.selectedKnotIndex = idx
                    self.skyKnotsChanged.emit()
                    return

        # イベント矩形のクリック判定（SELECTモードのみ）
        if self.editing.editMode == EditMode.SELECT:
            for idx, rect in self.eventRects:
                if rect.contains(event.pos()):
                    self.editGlobalChange(idx)
                    return

        # ノーツ矩形のクリック判定（全モード共通）
        clickedNoteId = None
        hitMargin = 8  # 判定領域を広げる（px）
        for id, rect in self.noteRects:
            hitRect = rect.adjusted(
                -hitMargin, -Const.NOTE_HEIGHT, hitMargin, Const.NOTE_HEIGHT
            )
            if hitRect.contains(event.pos()):
                clickedNoteId = id
                break

        if clickedNoteId is not None:
            clickedNote = next(
                (n for n in self.editing.chart.notes if n.id == clickedNoteId), None
            )
            if clickedNote:
                rect = next(r for i, r in self.noteRects if i == clickedNoteId)
                edgeThreshold = 5
                nearLeft = abs(event.pos().x() - rect.left()) <= edgeThreshold
                nearRight = abs(event.pos().x() - rect.right()) <= edgeThreshold

                # 端を掴んだらリサイズ（全モード）
                if nearLeft or nearRight:
                    self.startResize(
                        clickedNoteId,
                        "left" if nearLeft else "right",
                        rect,
                        event.pos(),
                    )
                    self.update()
                    return

                # 本体を掴んだら選択＆ドラッグ（全モード）
                if modifiers & (
                    Qt.KeyboardModifier.ControlModifier
                    | Qt.KeyboardModifier.ShiftModifier
                ):
                    if clickedNote not in self.editing.selectedNotes:
                        self.editing.selectedNotes.append(clickedNote)
                else:
                    self.editing.selectedNotes = [clickedNote]

                self.noteSelectionChanged.emit()

                self.pressNoteId = clickedNoteId
                # FLICKモードでトレースノーツ: クリック(無ドラッグ)でフリック化する候補
                if (
                    self.editing.editMode == EditMode.FLICK_NOTE
                    and clickedNote.flag == NoteFlag.trace
                    and clickedNote.flickType == FlickType.none
                ):
                    self.pressConvertFlick = True

                self.startDrag(clickedNoteId, event.pos())
                self.update()
            return

        # ノーツが無い → モード別の処理
        if self.editing.editMode == EditMode.SELECT:
            # 空白クリック: 選択解除＋ドラッグ選択の開始（クリックならシーク）
            self.editing.selectedNotes.clear()
            self.noteSelectionChanged.emit()
            self.rubberStart = event.pos()
            self.rubberRect = None
            self.update()
        elif self.editing.editMode == EditMode.TAP_NOTE:
            self.placeNoteWithResize(event, NoteFlag.none, FlickType.none, noSnap)
        elif self.editing.editMode == EditMode.TRACE_NOTE:
            self.placeNoteWithResize(event, NoteFlag.trace, FlickType.none, noSnap)
        elif self.editing.editMode == EditMode.FLICK_NOTE:
            self.placeNoteWithResize(event, NoteFlag.none, FlickType.up, noSnap)
        elif self.editing.editMode == EditMode.SKY_NOTE:
            self.placeSkyNote(event, noSnap)
        elif self.editing.editMode == EditMode.EVENT:
            lane = math.floor(self.getLaneFromXPoint(event.x()))

            if 0 <= lane <= Const.LANE_COUNT - 1:
                beat = self.getBeatFromYPoint(event.y())
                beat = self.snapBeat(beat)

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
            noteWidth = 4.0
            rawLane = self.getLaneFromXPoint(event.x()) - noteWidth / 2
            lane = rawLane if noSnap else self.snapLane(rawLane)
            lane = max(0, min(Const.LANE_COUNT - noteWidth, lane))

            if 0 <= lane <= Const.LANE_COUNT - 1:
                beat = self.getBeatFromYPoint(event.y())
                beat = beat if noSnap else self.snapBeat(beat)

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
            self.addLongNoteConnector(event.pos(), noSnap)
            self.update()

    def placeNoteWithResize(
        self,
        event: QMouseEvent,
        flag: NoteFlag,
        flick: FlickType,
        noSnap: bool = False,
    ):
        """ノーツを配置し、そのままドラッグで幅を変更できるよう右エッジを掴む"""
        noteWidth = 4.0
        rawLane = self.getLaneFromXPoint(event.x()) - noteWidth / 2
        lane = rawLane if noSnap else self.snapLane(rawLane)
        lane = max(0, min(Const.LANE_COUNT - noteWidth, lane))

        beat = self.getBeatFromYPoint(event.y())
        beat = beat if noSnap else self.snapBeat(beat)

        newId = self.editing.nextNoteId
        self.editing.pushAction(
            NoteAction(
                type="note_place",
                data=Note(
                    id=newId,
                    beat=beat,
                    lane=lane,
                    width=4.0,
                    curveType=CurveType.linear,
                    flickType=flick,
                    flag=flag,
                    layer=0,
                    skyNote=0,
                ),
            )
        )
        self.editing.nextNoteId += 1

        # 右エッジを掴んだ状態にして、ドラッグで幅変更可能にする
        self.startResize(newId, "right", QRect(), event.pos())
        self.update()

    def placeSkyNote(self, event: QMouseEvent, noSnap: bool = False):
        """スカイノーツを配置（ノーツと同一idのSkyNoteも作成）"""
        noteWidth = 4.0
        rawLane = self.getLaneFromXPoint(event.x()) - noteWidth / 2
        lane = rawLane if noSnap else self.snapLane(rawLane)
        lane = max(0, min(Const.LANE_COUNT - noteWidth, lane))

        beat = self.getBeatFromYPoint(event.y())
        beat = beat if noSnap else self.snapBeat(beat)

        newId = self.editing.nextNoteId

        # 浮動点は初期1つ（配置位置）
        floatings = [SkyNoteFloating(beat=beat, lane=lane, positionY=0.0)]
        skyNote = SkyNote(id=newId, floatings=floatings)

        note = Note(
            id=newId,
            beat=beat,
            lane=lane,
            width=4.0,
            curveType=CurveType.linear,
            flickType=FlickType.none,
            flag=NoteFlag.none,
            layer=0,
            skyNote=newId,  # ノーツidとスカイノーツidを一致させる
        )

        self.editing.pushAction(
            NoteAction(type="note_place", data=note, skyNote=skyNote)
        )
        self.editing.nextNoteId += 1
        self.update()

    def _buildSkyNote(self, note: Note) -> SkyNote:
        """ノーツ用のSkyNoteを作成（knotは初期1つ）

        スカイノーツは常にアンカーノーツ（通常ノーツは自身、ロングノーツは
        始点）のidで識別する。
        """
        anchor = note
        if note.flag == NoteFlag.longNote:
            longNote = self._longNoteContaining(note)
            if longNote is not None and longNote.steps:
                anchor = next(
                    (
                        n
                        for n in self.editing.chart.notes
                        if n.id == longNote.steps[0]
                    ),
                    note,
                )

        return SkyNote(
            id=anchor.id,
            floatings=[
                SkyNoteFloating(
                    beat=anchor.beat, lane=anchor.lane, positionY=0.0
                )
            ],
        )

    def _longNoteContaining(self, note: Note) -> LongNote | None:
        """noteが属するロングノーツを返す（steps所属で判定）"""
        return next(
            (ln for ln in self.editing.chart.longNotes if note.id in ln.steps),
            None,
        )

    def _isSkyNote(self, note: Note) -> bool:
        return self.editing.skyNoteOf(note) is not None

    def _longNoteOf(self, note: Note) -> LongNote | None:
        # スカイノーツはロングノーツ本体に紐づくため、どのステップを選択して
        # いても（始点・終点・コネクター）所属するロングノーツを返す
        return self._longNoteContaining(note)

    def attachSkyNoteToSelection(self):
        """選択ノーツにスカイノーツを付ける（通常/ロングで同じ規則）"""
        for note in list(self.editing.selectedNotes):
            # ロングノーツは本体にスカイノーツが付くため、note.skyNote ではなく
            # 所属ロングノーツの状態で判定する
            if self._isSkyNote(note):
                continue
            skyNote = self._buildSkyNote(note)
            longNote = self._longNoteOf(note)
            self.editing.pushAction(
                SkyNoteAction(
                    type="sky_place", data=skyNote, note=note, longNote=longNote
                )
            )
        self.noteSelectionChanged.emit()
        self.skyKnotsChanged.emit()
        self.update()

    def detachSkyNoteFromSelection(self):
        """選択ノーツからスカイノーツを外す（通常/ロングで同じ規則）"""
        for note in list(self.editing.selectedNotes):
            skyNote = self.editing.skyNoteOf(note)
            if skyNote is None:
                continue
            longNote = self._longNoteOf(note)
            self.editing.pushAction(
                SkyNoteAction(
                    type="sky_remove", data=skyNote, note=note, longNote=longNote
                )
            )
        self.noteSelectionChanged.emit()
        self.skyKnotsChanged.emit()
        self.update()

    def _currentBeatSafe(self) -> float:
        try:
            return self.getBeatFromTime(self.smoothTime)
        except ValueError:
            return 0.0

    def addKnot(self):
        """選択スカイノーツに現在の再生位置のknotを追加"""
        note, skyNote = self.editing.selectedSkyNote()
        if skyNote is None:
            return
        beat = self.snapBeat(self._currentBeatSafe())
        lane = self.snapLane(note.lane)
        lane = max(0, min(Const.LANE_COUNT - 1, lane))
        skyNote.floatings.append(SkyNoteFloating(beat=beat, lane=lane, positionY=0.0))
        skyNote.floatings.sort(key=lambda f: f.beat)
        self.editing.selectedKnotIndex = next(
            (
                i
                for i, f in enumerate(skyNote.floatings)
                if abs(f.beat - beat) < 1e-6 and abs(f.lane - lane) < 1e-6
            ),
            len(skyNote.floatings) - 1,
        )
        self.skyKnotsChanged.emit()
        self.update()

    def removeKnot(self, index: int):
        """選択スカイノーツのknotを削除（最低1点は残す）"""
        _note, skyNote = self.editing.selectedSkyNote()
        if skyNote is None or len(skyNote.floatings) <= 1:
            return
        if 0 <= index < len(skyNote.floatings):
            skyNote.floatings.pop(index)
            if self.editing.selectedKnotIndex is not None:
                if self.editing.selectedKnotIndex >= len(skyNote.floatings):
                    self.editing.selectedKnotIndex = len(skyNote.floatings) - 1
                elif self.editing.selectedKnotIndex > index:
                    self.editing.selectedKnotIndex -= 1
        self.skyKnotsChanged.emit()
        self.update()

    def removeSelectedKnot(self):
        idx = self.editing.selectedKnotIndex
        if idx is not None:
            self.removeKnot(idx)

    def setSkyKnotCurve(
        self,
        index: int,
        laneCurve: CurveType | None,
        positionCurve: CurveType | None,
    ):
        """選択スカイノーツのknotの補間曲線を更新（lane/Y 個別、None=自動）"""
        _note, skyNote = self.editing.selectedSkyNote()
        if skyNote is None or not (0 <= index < len(skyNote.floatings)):
            return
        floating = skyNote.floatings[index]
        floating.laneCurveType = laneCurve
        floating.positionYCurveType = positionCurve
        self.skyKnotsChanged.emit()
        self.update()

    def drawRubber(self, painter: QPainter):
        if self.rubberRect is None:
            return
        painter.save()
        painter.setPen(QPen(QColor("#4af"), 1, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(74, 170, 255, 60))
        painter.drawRect(self.rubberRect)
        painter.restore()

    def drawKnotHandles(self, painter: QPainter):
        """選択スカイノーツのknotをハンドルとして描画"""
        self.knotRects.clear()
        note, skyNote = self.editing.selectedSkyNote()
        if skyNote is None or note is None:
            return
        size = 8
        # knot同士をbeat順で線で繋ぐ
        ordered = sorted(skyNote.floatings, key=lambda f: f.beat)
        if len(ordered) >= 2:
            painter.setPen(QPen(QColor("#0ff"), 1, Qt.PenStyle.DashLine))
            path = QPainterPath()
            first = True
            for f in ordered:
                px = self.getXPointFromLane(f.lane)
                py = self.getYPointFromBeat(f.beat)
                if first:
                    path.moveTo(px, py)
                    first = False
                else:
                    path.lineTo(px, py)
            painter.drawPath(path)

        for i, f in enumerate(skyNote.floatings):
            x = round(self.getXPointFromLane(f.lane))
            y = round(self.getYPointFromBeat(f.beat))
            rect = QRect(x - size // 2, y - size // 2, size, size)
            self.knotRects.append((i, rect))
            painter.setPen(QPen(QColor("#0ff"), 1))
            painter.setBrush(QColor(0, 255, 255, 120))
            painter.drawRect(rect)

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

    def startResize(self, noteId: int, edge: str, rect: QRect, mousePos: QPoint):
        """リサイズ開始"""
        note = next((n for n in self.editing.chart.notes if n.id == noteId), None)
        if note is None:
            return

        self.resizingNoteId = noteId
        self.resizeEdge = edge  # 'left' or 'right'
        self.resizeStartWidth = note.width
        self.resizeStartLane = note.lane
        self.resizeStartX = mousePos.x()
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        if Const.DEBUG_HITBOX:
            print(
                f"[DEBUG] mouseMoveEvent: pos={event.pos()}, resizing={self.resizingNoteId}, edge={self.resizeEdge}, dragging={self.draggingNoteIds}"
            )

        # 長押し中に動いたらキャンセル
        if (
            self.longPressPos is not None
            and (event.pos() - self.longPressPos).manhattanLength() > 10
        ):
            self.longPressTimer.stop()
            self.longPressPos = None

        # knotのドラッグ（beat=縦, lane=横）
        if self.draggingKnotIndex is not None:
            note, skyNote = self.editing.selectedSkyNote()
            if skyNote is None or not (
                0 <= self.draggingKnotIndex < len(skyNote.floatings)
            ):
                self.draggingKnotIndex = None
            else:
                knot = skyNote.floatings[self.draggingKnotIndex]
                noSnap = self.forceNoSnap or bool(
                    event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                )
                rawBeat = self.getBeatFromYPoint(event.pos().y())
                knot.beat = rawBeat if noSnap else self.snapBeat(rawBeat)
                rawLane = self.getLaneFromXPoint(event.pos().x())
                lane = rawLane if noSnap else self.snapLane(rawLane)
                knot.lane = max(0, min(Const.LANE_COUNT - 1, lane))
                self.skyKnotsChanged.emit()
                self.update()
                return

        # ドラッグ選択（ラバーバンド）
        if self.rubberStart is not None:
            self.rubberRect = QRect(self.rubberStart, event.pos()).normalized()
            self.update()
            return

        # リサイズ処理（全モード）
        if self.resizingNoteId is not None and self.resizeEdge is not None:
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
            noSnap = self.forceNoSnap or bool(
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            )

            if self.resizeEdge == "left":
                # 左端を動かす: lane変更 + width変更（元の位置を基準に計算）
                newX = self.resizeStartX + deltaX
                rawLane = self.getLaneFromXPoint(newX)
                newLane = rawLane if noSnap else self.snapLane(rawLane)
                newLane = max(0, min(Const.LANE_COUNT - 1, newLane))
                widthChange = self.resizeStartLane - newLane
                newWidth = self.resizeStartWidth + widthChange
                if Const.DEBUG_HITBOX:
                    print(
                        f"[DEBUG] LEFT resize: newX={newX}, newLane={newLane}, startLane={self.resizeStartLane}, widthChange={widthChange}, newWidth={newWidth}"
                    )
                if newWidth >= 1:
                    note.lane = newLane
                    note.width = newWidth
            else:  # 'right'
                # 右端を動かす: widthのみ変更
                newRightX = self.resizeStartX + deltaX
                rawRightLane = self.getLaneFromXPoint(newRightX)
                newRightLane = rawRightLane if noSnap else self.snapLane(rawRightLane)
                newRightLane = max(note.lane, min(Const.LANE_COUNT, newRightLane))
                newWidth = newRightLane - note.lane
                if Const.DEBUG_HITBOX:
                    print(
                        f"[DEBUG] RIGHT resize: newRightX={newRightX}, newRightLane={newRightLane}, newWidth={newWidth}"
                    )
                if newWidth >= 1:
                    note.width = newWidth

            self.update()
            return

        # リサイズ/ドラッグしていない場合はホバープレビュー更新＆カーソル変更
        if self.resizingNoteId is None and (
            not self.draggingNoteIds or self.dragStartPos is None
        ):
            self.updateHoverPreview(event.pos(), event.modifiers())
            self.updateCursor(event.pos())
            return

        # 通常のドラッグ処理（全モード）
        if self.draggingNoteIds and self.dragStartPos is not None:
            # クリックとドラッグを区別する小さな閾値
            if not self.dragMoved:
                dx = event.pos().x() - self.dragStartPos.x()
                dy = event.pos().y() - self.dragStartPos.y()
                if abs(dx) < 3 and abs(dy) < 3:
                    return
                self.dragMoved = True

            # Y方向の移動 → beat変更
            deltaBeat = self.getBeatFromYPoint(
                event.pos().y()
            ) - self.getBeatFromYPoint(self.dragStartPos.y())

            # X方向の移動 → lane変更
            deltaLane = self.getLaneFromXPoint(
                event.pos().x()
            ) - self.getLaneFromXPoint(self.dragStartPos.x())

            # 基準ノーツ（最小ID）をグリッドに吸着させ、その差分を全ノーツへ適用
            refId = min(self.draggingNoteIds)
            if self.forceNoSnap or (
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            ):
                # Shift押下（またはタッチのスナップ無視）はスナップ無視
                snappedDeltaBeat = deltaBeat
                snappedDeltaLane = deltaLane
            else:
                refNewBeat = self.dragStartBeats[refId] + deltaBeat
                snappedDeltaBeat = (
                    self.snapBeat(refNewBeat) - self.dragStartBeats[refId]
                )
                refNewLane = self.dragStartLanes[refId] + deltaLane
                snappedDeltaLane = (
                    self.snapLane(refNewLane) - self.dragStartLanes[refId]
                )

            # 全選択ノーツを移動
            for note in self.editing.chart.notes:
                if note.id in self.draggingNoteIds:
                    note.beat = self.dragStartBeats[note.id] + snappedDeltaBeat
                    newLane = self.dragStartLanes[note.id] + snappedDeltaLane
                    # 幅分を考慮して右端がレーンをはみ出さないようにクランプ
                    maxLane = Const.LANE_COUNT - max(1, note.width)
                    note.lane = max(
                        0,
                        min(
                            maxLane,
                            newLane,
                        ),
                    )

            self.editing.chart.notes.sort(key=lambda n: n.beat)
            self.update()
            return

    def updateHoverPreview(self, pos: QPoint, modifiers=None):
        """マウス位置に基づいてホバープレビュー位置を更新"""
        lane = self.snapLane(self.getLaneFromXPoint(pos.x()))
        lane = max(0, min(Const.LANE_COUNT - 1, lane))

        if 0 <= lane <= Const.LANE_COUNT - 1:
            beat = self.getBeatFromYPoint(pos.y())
            beat = self.snapBeat(beat)

            mode = self.editing.editMode

            if mode in (
                EditMode.TAP_NOTE,
                EditMode.TRACE_NOTE,
                EditMode.FLICK_NOTE,
                EditMode.SKY_NOTE,
                EditMode.EVENT,
            ):
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
        self.resizeStartLane = 0.0
        self.resizeStartX = 0.0

    def mouseReleaseEvent(self, event: QMouseEvent):
        if Const.DEBUG_HITBOX:
            print(
                f"[DEBUG] mouseReleaseEvent: pos={event.pos()}, resizing={self.resizingNoteId}, dragging={self.draggingNoteIds}"
            )
        if event.button() == Qt.MouseButton.LeftButton:
            if self.longPressTimer.isActive():
                self.longPressTimer.stop()
            self.longPressPos = None
            if self.rubberStart is not None:
                # ドラッグ選択の確定（動いていなければシーク）
                if self.rubberRect is None:
                    self.seekTo(self.getTimeFromYPoint(event.pos().y()))
                else:
                    rect = self.rubberRect
                    rectById = {id: nr for id, nr in self.noteRects}
                    self.editing.selectedNotes = [
                        n
                        for n in self.editing.chart.notes
                        if n.id in rectById and rect.intersects(rectById[n.id])
                    ]
                    self.noteSelectionChanged.emit()
                self.rubberStart = None
                self.rubberRect = None
                self.update()
                return
            if self.draggingKnotIndex is not None:
                self.draggingKnotIndex = None
                self.update()
                return
            if self.resizingNoteId is not None:
                self.cancelResize()
            elif self.draggingNoteIds:
                # ドラッグ無しでトレースノーツをクリック → トレースフリック化
                if self.pressConvertFlick and not self.dragMoved:
                    note = next(
                        (
                            n
                            for n in self.editing.chart.notes
                            if n.id == self.pressNoteId
                        ),
                        None,
                    )
                    if (
                        note
                        and note.flag == NoteFlag.trace
                        and note.flickType == FlickType.none
                    ):
                        note.flickType = FlickType.up
                self.draggingNoteIds.clear()
                self.dragStartPos = None
                self.dragStartBeats.clear()
                self.dragStartLanes.clear()
            self.pressNoteId = None
            self.pressConvertFlick = False
            self.dragMoved = False
            self.update()

    def deleteNoteAt(self, pos: QPoint):
        """指定位置のノーツを削除"""
        hitMargin = 8
        for id, rect in self.noteRects:
            hitRect = rect.adjusted(-hitMargin, -hitMargin, hitMargin, hitMargin)
            if hitRect.contains(pos):
                note = next((n for n in self.editing.chart.notes if n.id == id), None)
                if note:
                    self._removeNote(note)
                return

    # --- 編集操作（メニュー/コンテキストメニュー共用） ---
    def _removeNote(self, note: Note):
        """ノーツを削除（スカイノーツも同時）"""
        longNote = self._longNoteContaining(note)
        if longNote is not None:
            # ロングノーツは一部だけ消すと不整合になるため本体ごと削除する
            stepNotes = [
                step
                for step in (
                    next(
                        (n for n in self.editing.chart.notes if n.id == stepId),
                        None,
                    )
                    for stepId in longNote.steps
                )
                if step is not None
            ]
            skyNote = self.editing.longNoteSkyNote(longNote)
            self.editing.pushAction(
                LongNoteAction(
                    type="long_note_remove",
                    data=longNote,
                    notes=stepNotes,
                    skyNote=skyNote,
                )
            )
            return

        skyNote = next(
            (s for s in self.editing.chart.skyNotes if s.id == note.id), None
        )
        if skyNote is not None:
            self.editing.pushAction(
                SkyNoteAction(type="sky_remove", data=skyNote, note=note)
            )
        self.editing.pushAction(NoteAction(type="note_remove", data=note))

    def deleteSelectedNotes(self):
        removedLongNotes = set()
        for note in list(self.editing.selectedNotes):
            longNote = self._longNoteContaining(note)
            if longNote is not None:
                # 同じロングノーツの重複選択では一度だけ削除する
                if longNote.id in removedLongNotes:
                    continue
                removedLongNotes.add(longNote.id)
            self._removeNote(note)
        self.editing.selectedNotes.clear()
        self.noteSelectionChanged.emit()
        self.onChartChanged()

    def selectAllNotes(self):
        self.editing.selectedNotes = list(self.editing.chart.notes)
        self.noteSelectionChanged.emit()
        self.update()

    def applyModeToSelection(self, mode: EditMode):
        """選択ノーツにモードの種類を適用（スカイの解除/付与含む）"""
        if not self.editing.selectedNotes:
            return
        if mode == EditMode.SKY_NOTE:
            self.attachSkyNoteToSelection()
            return
        if mode in (EditMode.TAP_NOTE, EditMode.TRACE_NOTE, EditMode.FLICK_NOTE):
            # スカイノーツなら解除
            self.detachSkyNoteFromSelection()
            for note in self.editing.selectedNotes:
                if mode == EditMode.TAP_NOTE:
                    note.flag = NoteFlag.none
                    note.flickType = FlickType.none
                elif mode == EditMode.TRACE_NOTE:
                    note.flag = NoteFlag.trace
                    note.flickType = FlickType.none
                elif mode == EditMode.FLICK_NOTE:
                    note.flickType = FlickType.up
        self.noteSelectionChanged.emit()
        self.onChartChanged()

    def copySelectedNotes(self):
        self.clipboard = [
            {
                "beat": n.beat,
                "lane": n.lane,
                "width": n.width,
                "curveType": n.curveType,
                "flickType": n.flickType,
                "flag": n.flag,
                "layer": n.layer,
            }
            for n in self.editing.selectedNotes
            if n.flag != NoteFlag.longNote
        ]
        self.clipboardChanged.emit()

    def pasteNotes(self):
        if not self.clipboard:
            return
        baseBeat = self._currentBeatSafe()
        minBeat = min(item["beat"] for item in self.clipboard)
        newIds = []
        for item in self.clipboard:
            newId = self.editing.nextNoteId
            self.editing.nextNoteId += 1
            note = Note(
                id=newId,
                beat=item["beat"] - minBeat + baseBeat,
                lane=item["lane"],
                width=item["width"],
                curveType=item["curveType"],
                flickType=item["flickType"],
                flag=item["flag"],
                layer=item["layer"],
                skyNote=0,
            )
            self.editing.pushAction(NoteAction(type="note_place", data=note))
            newIds.append(newId)
        self.editing.selectedNotes = [
            n for n in self.editing.chart.notes if n.id in newIds
        ]
        self.noteSelectionChanged.emit()
        self.onChartChanged()

    def undo(self):
        self.editing.undo()
        self._afterHistoryChange()

    def redo(self):
        self.editing.redo()
        self._afterHistoryChange()

    def _afterHistoryChange(self):
        self.editing.selectedNotes = [
            n for n in self.editing.selectedNotes if n in self.editing.chart.notes
        ]
        self.noteSelectionChanged.emit()
        self.onChartChanged()

    def deleteEventAt(self, pos: QPoint):
        """イベント（グローバルチェンジ）を削除（beat0は不可）"""
        for idx, rect in self.eventRects:
            if rect.contains(pos):
                change = sorted(
                    enumerate(self.editing.chart.globalChanges),
                    key=lambda c: c[1].beat,
                )[idx][1]
                if abs(change.beat) < 1e-6:
                    return  # 初期のbeat0イベントは削除不可
                self.editing.chart.globalChanges.remove(change)
                self.onChartChanged()
                return

    def contextMenuEvent(self, event):
        self.showContextMenu(event.pos(), event.globalPos())

    def selectNoteAt(self, pos: QPoint):
        """指定位置のノーツを選択（コンテクストメニュー用）"""
        hitMargin = 8
        for id, rect in self.noteRects:
            hitRect = rect.adjusted(
                -hitMargin, -Const.NOTE_HEIGHT, hitMargin, Const.NOTE_HEIGHT
            )
            if hitRect.contains(pos):
                note = next(
                    (n for n in self.editing.chart.notes if n.id == id), None
                )
                if note and note not in self.editing.selectedNotes:
                    self.editing.selectedNotes = [note]
                    self.noteSelectionChanged.emit()
                    self.update()
                return

    def showContextMenu(self, localPos: QPoint, globalPos: QPoint):
        # 右クリック位置に選択できるノーツがあれば選択してから開く
        self.selectNoteAt(localPos)
        menu = QMenu(self)
        menu.addAction("元に戻す", self.undo)
        menu.addAction("やり直し", self.redo)
        menu.addSeparator()

        hasSelection = bool(self.editing.selectedNotes)
        hasClipboard = bool(self.clipboard)

        copyAction = menu.addAction("コピー", self.copySelectedNotes)
        copyAction.setEnabled(hasSelection)
        pasteAction = menu.addAction("ペースト", self.pasteNotes)
        pasteAction.setEnabled(hasClipboard)
        selectAllAction = menu.addAction("全て選択", self.selectAllNotes)
        selectAllAction.setEnabled(bool(self.editing.chart.notes))

        # イベント矩形の上なら「削除」でイベント削除、それ以外はノーツ削除
        onEvent = any(rect.contains(localPos) for _, rect in self.eventRects)
        deleteAction = menu.addAction("削除")
        if onEvent:
            deleteAction.setEnabled(True)
            deleteAction.triggered.connect(lambda: self.deleteEventAt(localPos))
        else:
            deleteAction.setEnabled(hasSelection)
            deleteAction.triggered.connect(self.deleteSelectedNotes)

        menu.exec(globalPos)

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
        self, startBeat: float, endBeat: float, startLane: float, endLane: float
    ):
        """ロングノーツを配置（始点・終点のみ、間は描画で繋ぐ）"""
        # 開始ノーツ作成
        startNote = Note(
            id=self.editing.nextNoteId,
            beat=startBeat,
            lane=startLane,
            width=4.0,
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
            width=4.0,
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
            skyNote=0,
            steps=[startId, endId],
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

    def addLongNoteConnector(self, pos: QPoint, noSnap: bool = False):
        """ロングノーツの台形クリックで支点（コネクター）を追加"""
        # クリック位置の beat/lane を計算
        lane = math.floor(self.getLaneFromXPoint(pos.x()))
        if not (0 <= lane <= Const.LANE_COUNT - 1):
            return

        beat = self.getBeatFromYPoint(pos.y())
        beat = self.snapBeat(beat)

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
            insertBeat = insertBeat if noSnap else self.snapBeat(insertBeat)

            # X座標から lane を求める（台形の左右方向）
            # 上下で線形補間
            leftX = startX - startHalfW + t * (endX - endHalfW - (startX - startHalfW))
            rightX = startX + startHalfW + t * (endX + endHalfW - (startX + startHalfW))
            laneRatio = (pos.x() - leftX) / (rightX - leftX) if rightX != leftX else 0.5
            laneRatio = max(0.0, min(1.0, laneRatio))
            rawInsertLane = startNote.lane + laneRatio * (endNote.lane - startNote.lane)
            insertLane = rawInsertLane if noSnap else self.snapLane(rawInsertLane)
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
                width=4.0,
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
        totalWidth = Const.NOTE_WIDTH * Const.LANE_COUNT
        division = max(1, self.laneDivision)
        for i in range(division + 1):
            isOdd = i % 2 != 0
            if isOdd:
                painter.setPen(QPen(QColor("#888"), 1))
            else:
                painter.setPen(QPen(QColor("#ddd"), 1))

            point = round(center + totalWidth * i / division)
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

                # スナップは「小節内の区切り数」。1区切り = 小節長 / snap
                subStep = measureStep / self.snap

                first = math.ceil((segmentStart - change.beat) / subStep)
                last = math.floor((segmentEnd - change.beat) / subStep)

                leftX = round(self.getXPointFromLane(0))
                rightX = round(self.getXPointFromLane(16))

                for n in range(first, last + 1):
                    beat = change.beat + n * subStep
                    y = round(self.getYPointFromBeat(beat))

                    if n % self.snap == 0:
                        # 小節線
                        painter.setPen(QPen(QColor("#ddd"), 2))
                    elif (n * ts.major) % self.snap == 0:
                        # 拍線
                        painter.setPen(QPen(QColor("#888"), 1))
                    else:
                        # スナップの補助線（薄い灰色）
                        painter.setPen(QPen(QColor("#3a3a3a"), 1))

                    painter.drawLine(leftX, y, rightX, y)

    def drawMeasureLabels(self, painter: QPainter, center: float):
        """左側に小節番号と拍番号を表示する"""
        visibleRect = self.visibleRegion().boundingRect()
        if visibleRect.isEmpty():
            return

        visStart = self.getBeatFromYPoint(visibleRect.bottom())
        visEnd = self.getBeatFromYPoint(visibleRect.top())

        changes = sorted(self.editing.chart.globalChanges, key=lambda c: c.beat)
        if not changes:
            return

        # ラベルはレーンの2つ分左（lane -2）付近に表示
        labelRight = round(center) - 2 * Const.NOTE_WIDTH
        if labelRight <= 4:
            return
        # 小節番号は拍番号のすぐ左に右寄せ
        measureRight = labelRight - 18

        painter.save()
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)

        baseMeasure = 0
        for i, change in enumerate(changes):
            ts = change.timeSignature
            beatStep = 4 / ts.minor
            measureStep = ts.major * beatStep
            segStart = change.beat
            segEnd = changes[i + 1].beat if i + 1 < len(changes) else visEnd

            s = max(segStart, visStart)
            e = min(segEnd, visEnd)
            if s <= e:
                # 小節番号（左側）
                firstM = math.ceil((s - segStart) / measureStep - 1e-9)
                lastM = math.floor((e - segStart) / measureStep + 1e-9)
                for k in range(firstM, lastM + 1):
                    y = round(self.getYPointFromBeat(segStart + k * measureStep))
                    painter.setPen(QColor("#ddd"))
                    painter.drawText(
                        QRect(0, y - 7, measureRight, 14),
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                        str(baseMeasure + k + 1),
                    )

                # 拍番号（右側・小節線含む全ての拍）
                firstB = math.ceil((s - segStart) / beatStep - 1e-9)
                lastB = math.floor((e - segStart) / beatStep + 1e-9)
                for n in range(firstB, lastB + 1):
                    beatInMeasure = n % ts.major
                    y = round(self.getYPointFromBeat(segStart + n * beatStep))
                    painter.setPen(QColor("#888"))
                    painter.drawText(
                        QRect(0, y - 6, labelRight, 12),
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                        str(beatInMeasure + 1),
                    )

            # 次セグメントのために小節数を加算（最終セグメント以外）
            if i + 1 < len(changes):
                baseMeasure += max(0, round((segEnd - segStart) / measureStep))

        painter.restore()

    def drawNotes(self, painter: QPainter):
        self.noteRects.clear()
        if not self.tapNotePixMap.isNull():
            selectedIds = {n.id for n in self.editing.selectedNotes}
            skyNoteIds = {s.id for s in self.editing.chart.skyNotes}
            # スカイノーツ付きロングノーツの全ステップID（始点・終点・コネクター）
            longSkyNoteIds: set[int] = set()
            for ln in self.editing.chart.longNotes:
                if self.editing.longNoteSkyNote(ln) is not None:
                    longSkyNoteIds.update(ln.steps)

            for note in sorted(
                self.editing.chart.notes,
                key=lambda c: c.beat,
            ):
                isSelected = note.id in selectedIds
                isSkyNote = note.id in skyNoteIds

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
                        if isSkyNote:
                            # スカイノーツはフリックも同じテクスチャ
                            if note.flag == NoteFlag.trace:
                                pixmap = (
                                    self.skyTraceNotePixMap
                                    if not self.skyTraceNotePixMap.isNull()
                                    else self.skyNotePixMap
                                )
                            else:
                                pixmap = (
                                    self.skyNotePixMap
                                    if not self.skyNotePixMap.isNull()
                                    else self.tapNotePixMap
                                )
                        elif note.flickType != FlickType.none:
                            if note.flag == NoteFlag.trace:
                                pixmap = (
                                    self.flickTraceNotePixMap
                                    if not self.flickTraceNotePixMap.isNull()
                                    else self.flickNotePixMap
                                )
                            else:
                                pixmap = (
                                    self.flickNotePixMap
                                    if not self.flickNotePixMap.isNull()
                                    else self.tapNotePixMap
                                )
                        elif note.flag == NoteFlag.none:
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

                            # スカイノーツ付きロングノーツはスカイのテクスチャ
                            if note.id in longSkyNoteIds:
                                fallback = pixmap
                                if note.flag == NoteFlag.trace:
                                    pixmap = (
                                        self.skyTraceNotePixMap
                                        if not self.skyTraceNotePixMap.isNull()
                                        else fallback
                                    )
                                else:
                                    pixmap = (
                                        self.skyNotePixMap
                                        if not self.skyNotePixMap.isNull()
                                        else fallback
                                    )
                            # 始点/終点のトレースはトレーステクスチャ（台形は不変）
                            elif (
                                isLongNoteEndpoint
                                and note.flag == NoteFlag.trace
                                and not self.traceNotePixMap.isNull()
                            ):
                                pixmap = self.traceNotePixMap

                        painter.drawPixmap(
                            rect,
                            pixmap,
                        )

                        # フリックノーツは方向矢印を重ねて描画（スカイノーツは除く）
                        if note.flickType != FlickType.none and not isSkyNote:
                            self.drawFlickArrow(painter, rect, note.flickType)

                        # デバッグ: 当たり判定を薄く表示
                        if Const.DEBUG_HITBOX:
                            hitMargin = 8
                            hitRect = rect.adjusted(
                                -hitMargin, -hitMargin, hitMargin, hitMargin
                            )
                            painter.setPen(QPen(QColor(255, 0, 0), 2))
                            painter.setBrush(Qt.BrushStyle.NoBrush)
                            painter.drawRect(hitRect)
                            # エッジ判定範囲（塗りつぶし）
                            edgeThreshold = 5
                            leftEdge = rect.adjusted(-edgeThreshold, 0, 0, 0)
                            rightEdge = rect.adjusted(0, 0, edgeThreshold, 0)
                            painter.setPen(Qt.PenStyle.NoPen)
                            painter.setBrush(QColor(0, 255, 0, 128))
                            painter.drawRect(leftEdge)
                            painter.drawRect(rightEdge)

        # ロングノーツ描画
        if not self.longNotePixMap.isNull():
            for longNote in self.editing.chart.longNotes:
                self.drawLongNote(painter, longNote)

    def drawFlickArrow(self, painter: QPainter, rect: QRect, flickType: FlickType):
        """フリックノーツの方向矢印をノーツから離して大きく描画"""
        if self.flickNoteArrowPixMap.isNull():
            return

        angle = {
            FlickType.up: 0,
            FlickType.right: 45,
            FlickType.down: 180,
            FlickType.left: 315,
        }.get(flickType, 0)

        size = Const.NOTE_WIDTH * 2
        offset = Const.NOTE_WIDTH * 1.5
        center = rect.center()

        painter.save()
        # 位置はupと同じ（ノーツの真上）で、向きだけ変える
        painter.translate(center.x(), center.y() - offset)
        painter.rotate(angle)
        target = QRect(round(-size / 2), round(-size / 2), size, size)
        painter.drawPixmap(target, self.flickNoteArrowPixMap)
        painter.restore()

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

        # 曲線タイプに応じたパス生成
        path = self._buildLongNotePath(stepNotes, stepPoints)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setOpacity(0.5)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(Qt.PenStyle.NoPen)

        if not self.longNotePixMap.isNull():
            # テクスチャブラシを作成（全体の平均幅でスケーリング）
            totalWidth = sum(n.width for n in stepNotes) * Const.NOTE_WIDTH
            avgWidth = totalWidth / len(stepPoints)
            totalHeight = abs(stepPoints[-1][1] - stepPoints[0][1])
            if totalHeight == 0:
                totalHeight = 1

            # スカイノーツ付きロングノーツはスカイのテクスチャ
            brushPixmap = self.longNotePixMap
            if self.editing.longNoteSkyNote(longNote) is not None:
                startFlag = stepNotes[0].flag
                if startFlag == NoteFlag.trace and not self.skyTraceNotePixMap.isNull():
                    brushPixmap = self.skyTraceNotePixMap
                elif not self.skyNotePixMap.isNull():
                    brushPixmap = self.skyNotePixMap

            textureBrush = QBrush(brushPixmap)
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
            painter.setBrush(QColor(64, 156, 255, 128))
            painter.drawPath(path)

        painter.restore()

        # 選択ハイライト（全体の輪郭）
        isSelected = longNote.id in {n.id for n in self.editing.selectedNotes}
        if isSelected:
            painter.save()
            painter.setPen(QPen(QColor("#ff0"), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            painter.restore()

    def _buildLongNotePath(self, stepNotes: list, stepPoints: list) -> QPainterPath:
        """曲線タイプに応じたロングノーツのパスを構築（MikuMikuWorld方式）"""
        path = QPainterPath()

        if len(stepPoints) < 2:
            return path

        # 最初のセグメントの左上から開始
        x0, y0, w0 = stepPoints[0]
        path.moveTo(x0 - w0, y0)

        # 全ステップ間を描画
        for i in range(len(stepPoints) - 1):
            x0, y0, w0 = stepPoints[i]
            x1, y1, w1 = stepPoints[i + 1]

            # 各セグメントの始点ノーツのcurveTypeを使用
            curveType = stepNotes[i].curveType
            easeFunc = self._getEaseFunction(curveType)

            # 分割数を決定
            if curveType == CurveType.linear:
                steps = 1
            else:
                segmentHeight = abs(y1 - y0)
                steps = max(8, min(25, int(segmentHeight / 12)))

            # 上辺: 始点の左端から終点の左端へ
            for step in range(1, steps + 1):
                t = step / steps
                y = y0 + (y1 - y0) * t
                centerX = x0 + (x1 - x0) * easeFunc(t)
                halfW = w0 + (w1 - w0) * t
                leftX = centerX - halfW
                path.lineTo(leftX, y)

            # 終点の右端へ
            path.lineTo(x1 + w1, y1)

            # 下辺: 終点の右端から始点の右端へ
            for step in range(steps - 1, -1, -1):
                t = step / steps
                y = y0 + (y1 - y0) * t
                centerX = x0 + (x1 - x0) * easeFunc(t)
                halfW = w0 + (w1 - w0) * t
                rightX = centerX + halfW
                path.lineTo(rightX, y)

        # 始点の左上へ戻る
        x0, y0, w0 = stepPoints[0]
        path.lineTo(x0 - w0, y0)
        path.closeSubpath()

        return path

    def _getEaseFunction(self, curveType: CurveType):
        """曲線タイプに応じたイージング関数を返す（MikuMikuWorld方式）"""
        if curveType == CurveType.linear:
            return lambda t: t
        elif curveType == CurveType.easeIn:
            return lambda t: t * t
        elif curveType == CurveType.easeOut:
            return lambda t: 1 - (1 - t) * (1 - t)
        elif curveType == CurveType.easeInOut:
            # 前半: easeIn(0, 0.5, t*2), 後半: easeOut(0.5, 1, t*2-1)
            return lambda t: (
                self._easeIn(0.0, 0.5, t * 2)
                if t < 0.5
                else self._easeOut(0.5, 1.0, t * 2 - 1)
            )
        elif curveType == CurveType.easeOutIn:
            # 前半: easeOut(0, 0.5, t*2), 後半: easeIn(0.5, 1, t*2-1)
            return lambda t: (
                self._easeOut(0.0, 0.5, t * 2)
                if t < 0.5
                else self._easeIn(0.5, 1.0, t * 2 - 1)
            )
        else:
            return lambda t: 0

    def _lerp(self, start: float, end: float, percentage: float) -> float:
        return start + percentage * (end - start)

    def _easeIn(self, start: float, end: float, ratio: float) -> float:
        return self._lerp(start, end, ratio * ratio)

    def _easeOut(self, start: float, end: float, ratio: float) -> float:
        return self._lerp(start, end, 1 - (1 - ratio) * (1 - ratio))

    def drawSeek(self, painter: QPainter, center: float):
        y = round(self.getYPointFromTime(self.smoothTime))
        leftX = round(center)
        rightX = round(center + Const.NOTE_WIDTH * Const.LANE_COUNT)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        # 赤い線（lane0から右端まで）
        painter.setPen(QPen(QColor("#f00"), 1))
        painter.drawLine(leftX, y, rightX, y)

        # 左端に三角マーカー（右向き）
        size = 6
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#f00"))
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(leftX, y),
                    QPointF(leftX - size, y - size),
                    QPointF(leftX - size, y + size),
                ]
            )
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
        self.drawMeasureLabels(painter, center)
        self.drawNotes(painter)
        self.drawKnotHandles(painter)
        self.drawRubber(painter)
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

        if mode in (
            EditMode.TAP_NOTE,
            EditMode.TRACE_NOTE,
            EditMode.FLICK_NOTE,
            EditMode.SKY_NOTE,
        ):
            # 通常ノーツプレビュー
            if mode == EditMode.TAP_NOTE:
                pixmap = self.tapNotePixMap
            elif mode == EditMode.TRACE_NOTE:
                pixmap = self.traceNotePixMap
            elif mode == EditMode.FLICK_NOTE:
                pixmap = (
                    self.flickNotePixMap
                    if not self.flickNotePixMap.isNull()
                    else self.tapNotePixMap
                )
            else:  # EditMode.SKY_NOTE
                pixmap = (
                    self.skyNotePixMap
                    if not self.skyNotePixMap.isNull()
                    else self.tapNotePixMap
                )
            rect = QRect(
                round(self.getXPointFromLane(self.hoverLane)),
                round(self.getYPointFromBeat(self.hoverBeat) - Const.NOTE_HEIGHT / 2),
                round(4 * Const.NOTE_WIDTH),
                Const.NOTE_HEIGHT,
            )
            painter.drawPixmap(rect, pixmap)

            if mode == EditMode.FLICK_NOTE:
                self.drawFlickArrow(painter, rect, FlickType.up)

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
            # ロングノーツプレビュー（通常ノーツと同じ幅=4で描画）
            previewWidth = 4 * Const.NOTE_WIDTH
            halfPreviewWidth = previewWidth / 2
            if mode == EditMode.LONG_NOTE_CONNECTOR:
                # コネクタープレビュー（マウス位置に半透明コネクターノーツ）
                rect = QRect(
                    round(self.getXPointFromLane(self.hoverLane)),
                    round(
                        self.getYPointFromBeat(self.hoverBeat) - Const.NOTE_HEIGHT / 2
                    ),
                    round(previewWidth),
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
                    round(previewWidth),
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
                    round(previewWidth),
                    Const.NOTE_HEIGHT,
                )
                painter.drawPixmap(
                    endRect,
                    self.longNotePixMap
                    if not self.longNotePixMap.isNull()
                    else self.tapNotePixMap,
                )

                # 台形プレビュー（半透明・テクスチャ）
                startX = self.getXPointFromLane(startLane) + halfPreviewWidth
                startY = self.getYPointFromBeat(startBeat)
                endX = self.getXPointFromLane(endLane) + halfPreviewWidth
                endY = self.getYPointFromBeat(endBeat)

                points = [
                    QPointF(startX - halfPreviewWidth, startY),
                    QPointF(startX + halfPreviewWidth, startY),
                    QPointF(endX + halfPreviewWidth, endY),
                    QPointF(endX - halfPreviewWidth, endY),
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
                        .scale(1.0 / previewWidth, 1.0 / (endY - startY))
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
                    round(previewWidth),
                    Const.NOTE_HEIGHT,
                )
                painter.drawPixmap(
                    rect,
                    self.longNotePixMap
                    if not self.longNotePixMap.isNull()
                    else self.tapNotePixMap,
                )

        painter.restore()
