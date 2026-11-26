import enum
import struct
from dataclasses import dataclass

from objects.types import FixedInteger


class NoteFlag(enum.Enum):
    none = 0
    trace = 1
    damage = 2
    longNote = 3


class FlickType(enum.Enum):
    none = 0
    up = 1
    down = 2
    left = 3
    right = 4


class CurveType(enum.Enum):
    linear = 0
    easeIn = 1
    easeOut = 2
    easeInOut = 3
    easeOutIn = 4


@dataclass(kw_only=True)
class Change:
    beat: float
    bpm: float
    timeSignature: FixedInteger
    speedRate: float

    def toBytes(self) -> list[bytes]:
        return [
            struct.pack("<f", self.beat),
            struct.pack("<f", self.bpm),
            self.timeSignature.major.to_bytes(4, "little"),
            self.timeSignature.minor.to_bytes(4, "little"),
            struct.pack("<f", self.speedRate),
        ]


@dataclass(kw_only=True)
class Layer:
    id: int
    skyNote: int
    changes: list[Change]

    def toBytes(self) -> list[bytes]:
        return [
            self.id.to_bytes(4, "little"),
            self.skyNote.to_bytes(4, "little"),
            len(self.changes).to_bytes(length=4, byteorder="little"),
            *[data for changes in self.changes for data in changes.toBytes()],
        ]


@dataclass(kw_only=True)
class LongNote:
    id: int
    skyNote: int
    steps: list[int]  # 途中のノーツID（開始・終了ノーツも含む全てのノーツID）

    def toBytes(self) -> list[bytes]:
        return [
            self.id.to_bytes(4, "little"),
            self.skyNote.to_bytes(4, "little"),
            len(self.steps).to_bytes(4, "little"),
        ] + [step.to_bytes(4, "little") for step in self.steps]


@dataclass(kw_only=True)
class SkyNoteFloating:
    beat: float
    lane: float
    positionY: float  # 浮動位置のY座標（5.0でちょうど1）
    # この点から次の点までの補間に使う曲線（lane と positionY で独立に指定）
    laneCurveType: CurveType = CurveType.linear
    positionYCurveType: CurveType = CurveType.linear

    def toBytes(self) -> list[bytes]:
        return [
            struct.pack("<f", self.beat),
            struct.pack("<f", self.lane),
            struct.pack("<f", self.positionY),
            self.laneCurveType.value.to_bytes(4, "little"),
            self.positionYCurveType.value.to_bytes(4, "little"),
        ]


@dataclass(kw_only=True)
class SkyNote:
    id: int
    floatings: list[SkyNoteFloating]  # x5

    def toBytes(self) -> list[bytes]:
        return [
            self.id.to_bytes(4, "little"),
            len(self.floatings).to_bytes(4, "little"),
            *[data for floating in self.floatings for data in floating.toBytes()],
        ]


@dataclass(kw_only=True)
class Note:
    id: int
    beat: float
    lane: float
    width: float
    curveType: CurveType
    flickType: FlickType
    flag: NoteFlag
    layer: int
    skyNote: int

    def toBytes(self) -> list[bytes]:
        return [
            self.id.to_bytes(4, "little"),
            struct.pack("<f", self.beat),
            struct.pack("<f", self.lane),
            struct.pack("<f", self.width),
            self.curveType.value.to_bytes(4, "little"),
            self.flickType.value.to_bytes(4, "little"),
            self.flag.value.to_bytes(4, "little"),
            self.layer.to_bytes(4, "little"),
            self.skyNote.to_bytes(4, "little"),
        ]
