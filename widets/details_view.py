from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from etc import constants as Const
from objects.chart import Difficulty
from objects.edit import EditingChart
from objects.note import CurveType, FlickType, NoteFlag


class DetailsViewWidget(QWidget):
    chartChanged = Signal()
    zoomChanged = Signal(float)
    snapChanged = Signal(int)
    laneDivisionChanged = Signal(int)
    attachSkyNoteRequested = Signal()
    detachSkyNoteRequested = Signal()
    addKnotRequested = Signal()
    removeKnotRequested = Signal()
    # 選択中knotの補間曲線（lane用とpositionY用）を変更。None は「自動」
    skyKnotCurveChanged = Signal(int, object, object)

    def __init__(self, editing: EditingChart):
        super().__init__()
        self.editing: EditingChart = editing

        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.tabs = QTabWidget()

        # 譜面プロパティタブ
        self.setupChartTab()
        self.tabs.addTab(self.chartTab, "譜面プロパティ")

        # ノーツプロパティタブ
        self.setupNoteTab()
        self.tabs.addTab(self.noteTab, "ノーツプロパティ")

        # 表示設定タブ
        self.setupViewTab()
        self.tabs.addTab(self.viewTab, "表示設定")

        layout.addWidget(self.tabs)
        self.setLayout(layout)

    @staticmethod
    def _scrollable(layout) -> QScrollArea:
        """タブ内容をスクロール可能にする。

        スカイノーツの knot 一覧が現れると縦に伸び、スクロール出来ないと
        ウィジェットからはみ出す（タブ切替で再レイアウトされるまで直らない）。
        """
        content = QWidget()
        content.setLayout(layout)
        area = QScrollArea()
        area.setWidget(content)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        return area

    def setupViewTab(self):
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # ズーム（入力で直接指定）
        zoomLabel = QLabel("ズーム (縦方向)")
        self.zoomSpin = QDoubleSpinBox()
        self.zoomSpin.setRange(Const.ZOOM_MIN, Const.ZOOM_MAX)
        self.zoomSpin.setDecimals(2)
        self.zoomSpin.setSingleStep(0.1)
        self.zoomSpin.setValue(1.0)
        self.zoomSpin.valueChanged.connect(self.onZoomChanged)
        layout.addWidget(zoomLabel)
        layout.addWidget(self.zoomSpin)

        # スナップ
        snapLabel = QLabel("スナップ (小節内の区切り数)")
        self.snapCombo = QComboBox()
        for snap in Const.SNAP_OPTIONS:
            self.snapCombo.addItem(f"1/{snap}", snap)
        self.snapCombo.activated.connect(self.onSnapComboActivated)
        layout.addWidget(snapLabel)
        layout.addWidget(self.snapCombo)

        # レーン区切り
        laneLabel = QLabel("レーン区切り")
        self.laneDivisionCombo = QComboBox()
        for division in Const.LANE_DIVISIONS:
            self.laneDivisionCombo.addItem(str(division), division)
        self.laneDivisionCombo.activated.connect(self.onLaneDivisionActivated)
        layout.addWidget(laneLabel)
        layout.addWidget(self.laneDivisionCombo)

        self.viewTab = self._scrollable(layout)

    def onZoomChanged(self, value: float):
        self.zoomChanged.emit(value)

    def onSnapComboActivated(self, index: int):
        self.snapChanged.emit(self.snapCombo.itemData(index))

    def onLaneDivisionActivated(self, index: int):
        self.laneDivisionChanged.emit(self.laneDivisionCombo.itemData(index))

    def updateViewSettings(self, zoom: float, snap: int, laneDivision: int):
        """ホイール等での変更を入力欄/コンボへ反映（再帰防止）"""
        self.zoomSpin.blockSignals(True)
        self.zoomSpin.setValue(zoom)
        self.zoomSpin.blockSignals(False)
        for combo, value in (
            (self.snapCombo, snap),
            (self.laneDivisionCombo, laneDivision),
        ):
            index = combo.findData(value)
            if index >= 0:
                combo.blockSignals(True)
                combo.setCurrentIndex(index)
                combo.blockSignals(False)

    def setupChartTab(self):
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        songIdLabel = QLabel("楽曲ID")
        self.songId = QLineEdit(text=self.editing.chart.id)
        self.songId.textChanged.connect(lambda v: setattr(self.editing.chart, "id", v))

        difficultyTypeLabel = QLabel("難易度タイプ")
        self.difficultyType = QComboBox()
        for difficulty in Difficulty:
            self.difficultyType.addItem(difficulty.name.capitalize(), difficulty.value)
        self.difficultyType.activated.connect(
            lambda i: setattr(
                self.editing.chart, "difficultyType", tuple(Difficulty)[i]
            )
        )

        difficultyLabel = QLabel("難易度")
        self.difficulty = QHBoxLayout()

        self.difficultyMajor = QSpinBox()
        self.difficultyMajor.setRange(0, 999)
        self.difficultyMajor.setValue(self.editing.chart.difficulty.major)
        self.difficultyMinor = QSpinBox()
        self.difficultyMinor.setRange(1, 999)
        self.difficultyMinor.setValue(self.editing.chart.difficulty.minor)

        self.difficultyMajor.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.difficultyMinor.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

        self.difficultyMajor.valueChanged.connect(
            lambda v: setattr(self.editing.chart.difficulty, "major", v)
        )
        self.difficultyMinor.valueChanged.connect(
            lambda v: setattr(self.editing.chart.difficulty, "minor", v)
        )

        self.difficulty.addWidget(self.difficultyMajor)
        self.difficulty.addWidget(QLabel("."))
        self.difficulty.addWidget(self.difficultyMinor)

        offsetLabel = QLabel("オフセット (ms)")
        self.offset = QDoubleSpinBox()
        self.offset.setRange(-60000.0, 60000.0)
        self.offset.setDecimals(1)
        self.offset.setSingleStep(1.0)
        self.offset.setValue(self.editing.chart.offset)
        self.offset.setToolTip("音源の先頭から0拍目までの時間")
        self.offset.valueChanged.connect(self.onOffsetChanged)

        layout.addWidget(songIdLabel)
        layout.addWidget(self.songId)
        layout.addWidget(difficultyTypeLabel)
        layout.addWidget(self.difficultyType)
        layout.addWidget(difficultyLabel)
        layout.addLayout(self.difficulty)
        layout.addWidget(offsetLabel)
        layout.addWidget(self.offset)

        self.chartTab = self._scrollable(layout)

    def setupNoteTab(self):
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 選択ノーツ情報
        self.noteInfoLabel = QLabel("ノーツを選択してください")
        layout.addWidget(self.noteInfoLabel)

        # beat
        self.beatLabel = QLabel("拍 (beat)")
        beatLabel = self.beatLabel
        self.beatSpin = QDoubleSpinBox()
        self.beatSpin.setRange(-9999.0, 9999.0)
        self.beatSpin.setDecimals(3)
        self.beatSpin.setSingleStep(0.25)
        self.beatSpin.valueChanged.connect(self.onBeatChanged)
        layout.addWidget(beatLabel)
        layout.addWidget(self.beatSpin)

        # lane
        self.laneLabel = QLabel("レーン (lane)")
        laneLabel = self.laneLabel
        self.laneSpin = QDoubleSpinBox()
        self.laneSpin.setRange(0.0, Const.LANE_COUNT - 1)
        self.laneSpin.setDecimals(0)
        self.laneSpin.setSingleStep(1.0)
        self.laneSpin.valueChanged.connect(self.onLaneChanged)
        layout.addWidget(laneLabel)
        layout.addWidget(self.laneSpin)

        # width
        self.widthLabel = QLabel("幅 (width)")
        widthLabel = self.widthLabel
        self.widthSpin = QDoubleSpinBox()
        self.widthSpin.setRange(1.0, Const.LANE_COUNT)
        self.widthSpin.setDecimals(0)
        self.widthSpin.setSingleStep(1.0)
        self.widthSpin.valueChanged.connect(self.onWidthChanged)
        layout.addWidget(widthLabel)
        layout.addWidget(self.widthSpin)

        # トレース
        self.traceCheck = QCheckBox("トレース")
        self.traceCheck.toggled.connect(self.onTraceChanged)
        layout.addWidget(self.traceCheck)

        # フリックの方向
        self.flickTypeLabel = QLabel("フリックの方向")
        flickTypeLabel = self.flickTypeLabel
        self.flickTypeCombo = QComboBox()
        for flick in FlickType:
            self.flickTypeCombo.addItem(flick.name, flick)
        self.flickTypeCombo.activated.connect(self.onFlickTypeChanged)
        layout.addWidget(flickTypeLabel)
        layout.addWidget(self.flickTypeCombo)

        # ロングノーツ曲線種類
        self.curveTypeLabel = QLabel("ロングノーツ曲線種類")
        curveTypeLabel = self.curveTypeLabel
        self.curveTypeCombo = QComboBox()
        for curve in CurveType:
            self.curveTypeCombo.addItem(curve.name, curve)
        self.curveTypeCombo.activated.connect(self.onCurveTypeChanged)
        layout.addWidget(curveTypeLabel)
        layout.addWidget(self.curveTypeCombo)

        # スカイノーツの付与/解除
        self.attachSkyButton = QPushButton("スカイノーツを付ける")
        self.attachSkyButton.clicked.connect(self.attachSkyNoteRequested.emit)
        layout.addWidget(self.attachSkyButton)

        self.detachSkyButton = QPushButton("スカイノーツを外す")
        self.detachSkyButton.clicked.connect(self.detachSkyNoteRequested.emit)
        layout.addWidget(self.detachSkyButton)

        # スカイノーツのknot（制御点）一覧
        self.knotLabel = QLabel("スカイノーツ制御点 (knot)")
        layout.addWidget(self.knotLabel)
        self.knotList = QListWidget()
        self.knotList.itemSelectionChanged.connect(self.onKnotSelectionChanged)
        layout.addWidget(self.knotList)

        # knot から次の knot への補間曲線（lane と positionY を個別に指定）
        self.knotLaneCurveLabel = QLabel("スカイ曲線 (lane)")
        self.knotLaneCurveCombo = QComboBox()
        self._fillKnotCurveCombo(self.knotLaneCurveCombo)
        self.knotLaneCurveCombo.activated.connect(self.onKnotCurveChanged)
        layout.addWidget(self.knotLaneCurveLabel)
        layout.addWidget(self.knotLaneCurveCombo)

        self.knotPositionCurveLabel = QLabel("スカイ曲線 (Y)")
        self.knotPositionCurveCombo = QComboBox()
        self._fillKnotCurveCombo(self.knotPositionCurveCombo)
        self.knotPositionCurveCombo.activated.connect(self.onKnotCurveChanged)
        layout.addWidget(self.knotPositionCurveLabel)
        layout.addWidget(self.knotPositionCurveCombo)

        knotButtonRow = QHBoxLayout()
        self.addKnotButton = QPushButton("追加")
        self.addKnotButton.clicked.connect(self.addKnotRequested.emit)
        self.removeKnotButton = QPushButton("削除")
        self.removeKnotButton.clicked.connect(self.onRemoveKnotClicked)
        knotButtonRow.addWidget(self.addKnotButton)
        knotButtonRow.addWidget(self.removeKnotButton)
        layout.addLayout(knotButtonRow)

        self.noteTab = self._scrollable(layout)

        # 非スカイ時に幅が半分にならないよう横方向はExpandedに固定
        for w in (
            self.beatSpin,
            self.laneSpin,
            self.widthSpin,
            self.flickTypeCombo,
            self.curveTypeCombo,
            self.knotList,
        ):
            w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def onRemoveKnotClicked(self):
        row = self.knotList.currentRow()
        if row >= 0:
            self.removeKnotRequested.emit()

    @staticmethod
    def _fillKnotCurveCombo(combo: QComboBox):
        """先頭に「自動（ノーツに追従）」= None を置く"""
        combo.addItem("自動 (ノーツに追従)", None)
        for curve in CurveType:
            combo.addItem(curve.name, curve)

    def onKnotSelectionChanged(self):
        row = self.knotList.currentRow()
        self.editing.selectedKnotIndex = row if row >= 0 else None
        self.refreshKnotCurveControls()

    def onKnotCurveChanged(self, index: int):
        row = self.editing.selectedKnotIndex
        if row is None or row < 0:
            return
        laneCurve = self.knotLaneCurveCombo.itemData(index)
        positionCurve = self.knotPositionCurveCombo.itemData(index)
        self.skyKnotCurveChanged.emit(row, laneCurve, positionCurve)

    def refreshKnotCurveControls(self):
        """選択中knotの補間曲線コンボを現在値に合わせる"""
        _note, skyNote = self.editing.selectedSkyNote()
        row = self.editing.selectedKnotIndex
        floatings = skyNote.floatings if skyNote is not None else []
        enabled = bool(floatings) and row is not None and 0 <= row < len(floatings)
        for combo in (self.knotLaneCurveCombo, self.knotPositionCurveCombo):
            combo.setEnabled(enabled)
        if not enabled:
            return
        floating = floatings[row]
        for combo, curve in (
            (self.knotLaneCurveCombo, floating.laneCurveType),
            (self.knotPositionCurveCombo, floating.positionYCurveType),
        ):
            combo.blockSignals(True)
            # None(自動)は先頭項目、それ以外は名前で選択
            index = 0 if curve is None else combo.findData(curve)
            combo.setCurrentIndex(max(index, 0))
            combo.blockSignals(False)

    def refreshKnotList(self):
        """選択スカイノーツのknot一覧を更新"""
        self.knotList.blockSignals(True)
        self.knotList.clear()
        _note, skyNote = self.editing.selectedSkyNote()
        if skyNote is not None:
            for i, f in enumerate(skyNote.floatings):
                lane_curve = f.laneCurveType.name if f.laneCurveType else "auto"
                position_curve = (
                    f.positionYCurveType.name if f.positionYCurveType else "auto"
                )
                self.knotList.addItem(
                    f"#{i}  beat={f.beat:.3f}  lane={f.lane:.2f}  Y={f.positionY:.2f}"
                    f"  [{lane_curve}/{position_curve}]"
                )
            idx = self.editing.selectedKnotIndex
            if idx is not None and 0 <= idx < self.knotList.count():
                self.knotList.setCurrentRow(idx)
        self.knotList.blockSignals(False)
        self.refreshKnotCurveControls()

    def onBeatChanged(self, value: float):
        for note in self.editing.selectedNotes:
            note.beat = value
        self.editing.chart.notes.sort(key=lambda n: n.beat)
        self.chartChanged.emit()

    def onLaneChanged(self, value: float):
        for note in self.editing.selectedNotes:
            note.lane = value
        self.chartChanged.emit()

    def onWidthChanged(self, value: float):
        for note in self.editing.selectedNotes:
            note.width = value
        self.chartChanged.emit()

    def _containingLongNote(self, note):
        return next(
            (ln for ln in self.editing.chart.longNotes if note.id in ln.steps),
            None,
        )

    def _noteHasSky(self, note) -> bool:
        """通常/ロングノーツ alike で「アンカーノーツのid」により判定"""
        return self.editing.skyNoteOf(note) is not None

    def _isConnector(self, note) -> bool:
        ln = self._containingLongNote(note)
        if ln is None or len(ln.steps) < 2:
            return False
        return note.id != ln.steps[0] and note.id != ln.steps[-1]

    def onTraceChanged(self, checked: bool):
        for note in self.editing.selectedNotes:
            # 中継点（コネクター）はトレース非対応
            if self._isConnector(note):
                continue
            note.flag = NoteFlag.trace if checked else NoteFlag.none
        self.chartChanged.emit()

    def onFlickTypeChanged(self, index: int):
        flick = self.flickTypeCombo.itemData(index)
        for note in self.editing.selectedNotes:
            note.flickType = flick
        self.chartChanged.emit()

    def onOffsetChanged(self, value: float):
        self.editing.chart.offset = value
        self.chartChanged.emit()

    def onCurveTypeChanged(self, index: int):
        curve = self.curveTypeCombo.itemData(index)
        # 選択中のロングノーツの始点ノーツのcurveTypeを変更
        selectedIds = {n.id for n in self.editing.selectedNotes}
        for longNote in self.editing.chart.longNotes:
            if longNote.steps and longNote.steps[0] in selectedIds:
                startNote = next(
                    (n for n in self.editing.chart.notes if n.id == longNote.steps[0]),
                    None,
                )
                if startNote:
                    startNote.curveType = curve
        self.chartChanged.emit()

    def updateNoteInfo(self):
        """選択ノーツの情報を更新"""
        selected = self.editing.selectedNotes
        if not selected:
            self.noteInfoLabel.setText("ノーツを選択してください")
            self.setEnabledNoteControls(False)
            self.setNoteControlsVisible(False)
            return

        self.setEnabledNoteControls(True)
        self.setNoteControlsVisible(True)

        # 先頭ノーツの値を表示（シグナルを止めて再帰を防ぐ）
        first = selected[0]
        for widget, value in (
            (self.beatSpin, first.beat),
            (self.laneSpin, first.lane),
            (self.widthSpin, first.width),
        ):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)

        self.traceCheck.blockSignals(True)
        self.traceCheck.setChecked(first.flag == NoteFlag.trace)
        self.traceCheck.blockSignals(False)

        self.flickTypeCombo.blockSignals(True)
        self.flickTypeCombo.setCurrentText(first.flickType.name)
        self.flickTypeCombo.blockSignals(False)

        # スカイノーツの付与/解除ボタンの有効/無効
        anySky = any(self._noteHasSky(n) for n in selected)
        allSky = all(self._noteHasSky(n) for n in selected)
        self.attachSkyButton.setEnabled(not allSky)
        self.detachSkyButton.setEnabled(anySky)

        # knot一覧の更新とボタン制御（スカイノーツ時のみ表示）
        _, skyNote = self.editing.selectedSkyNote()
        hasSky = skyNote is not None
        # 「付ける」はスカイノーツ時は非表示
        self.attachSkyButton.setVisible(not hasSky)
        self.detachSkyButton.setVisible(anySky)
        self.knotLabel.setVisible(hasSky)
        self.knotList.setVisible(hasSky)
        self.knotLaneCurveLabel.setVisible(hasSky)
        self.knotLaneCurveCombo.setVisible(hasSky)
        self.knotPositionCurveLabel.setVisible(hasSky)
        self.knotPositionCurveCombo.setVisible(hasSky)
        self.addKnotButton.setVisible(hasSky)
        self.removeKnotButton.setVisible(hasSky)
        self.addKnotButton.setEnabled(hasSky)
        self.removeKnotButton.setEnabled(hasSky and len(skyNote.floatings) > 1)
        self.refreshKnotList()

        # ロングノーツが選択されているか確認（steps所属で判定）
        longNotes = [n for n in selected if self._containingLongNote(n) is not None]
        # 中継点（コネクター）ではトレースチェックを非表示
        self.traceCheck.setVisible(not self._isConnector(first))
        showCurve = bool(longNotes) or hasSky
        self.curveTypeLabel.setVisible(showCurve)
        self.curveTypeCombo.setVisible(showCurve)
        if longNotes:
            self.noteInfoLabel.setText(
                f"選択中: {len(selected)}ノーツ (ロングノーツ: {len(longNotes)})"
            )
            self.curveTypeCombo.setEnabled(True)
            self.curveTypeCombo.blockSignals(True)
            self.curveTypeCombo.setCurrentText(longNotes[0].curveType.name)
            self.curveTypeCombo.blockSignals(False)
        else:
            self.noteInfoLabel.setText(f"選択中: {len(selected)}ノーツ")
            self.curveTypeCombo.setEnabled(hasSky)

    def setNoteControlsVisible(self, visible: bool):
        for w in (
            self.beatLabel,
            self.beatSpin,
            self.laneLabel,
            self.laneSpin,
            self.widthLabel,
            self.widthSpin,
            self.traceCheck,
            self.flickTypeLabel,
            self.flickTypeCombo,
            self.curveTypeLabel,
            self.curveTypeCombo,
            self.attachSkyButton,
            self.detachSkyButton,
            self.knotLabel,
            self.knotList,
            self.knotLaneCurveLabel,
            self.knotLaneCurveCombo,
            self.knotPositionCurveLabel,
            self.knotPositionCurveCombo,
            self.addKnotButton,
            self.removeKnotButton,
        ):
            w.setVisible(visible)

    def setEnabledNoteControls(self, enabled: bool):
        for widget in (
            self.beatSpin,
            self.laneSpin,
            self.widthSpin,
            self.traceCheck,
            self.flickTypeCombo,
            self.attachSkyButton,
            self.detachSkyButton,
            self.knotList,
            self.addKnotButton,
            self.removeKnotButton,
        ):
            widget.setEnabled(enabled)
        self.curveTypeCombo.setEnabled(
            enabled
            and any(n.flag == NoteFlag.longNote for n in self.editing.selectedNotes)
        )
