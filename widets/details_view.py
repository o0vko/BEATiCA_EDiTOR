from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from objects.chart import Difficulty
from objects.edit import EditingChart


class DetailsViewWidget(QWidget):
    chartChanged = Signal()

    def __init__(self, editing: EditingChart):
        super().__init__()
        self.editing: EditingChart = editing

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

        self.difficultyMajor = QLineEdit(str(self.editing.chart.difficulty.major))
        self.difficultyMinor = QLineEdit(str(self.editing.chart.difficulty.minor))

        self.difficultyMajor.textChanged.connect(
            lambda i: setattr(self.editing.chart.difficulty, "major", int(i))
        )
        self.difficultyMinor.textChanged.connect(
            lambda i: setattr(self.editing.chart.difficulty, "minor", int(i))
        )

        self.difficulty.addWidget(self.difficultyMajor)
        self.difficulty.addWidget(QLabel("/"))
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

        self.setLayout(layout)

    def onOffsetChanged(self, value: float):
        self.editing.chart.offset = value
        self.chartChanged.emit()
