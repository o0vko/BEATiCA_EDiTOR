import enum
import struct
from dataclasses import dataclass

from objects.types import FixedInteger


class NoteType(enum.Enum):
    none = 0
    damage = 1


class NoteFlag(enum.Enum):
    none = 0
    trace = 1
    longNote = 2


class FlickType(enum.Enum):
    none = 0
    left = 1
    right = 2
    up = 3
    down = 4


class CurveType(enum.Enum):
    linear = 0
    easeIn = 1
    easeOut = 2
    easeInOut = 3
    easeOutIn = 4


@dataclass(kw_only=True)
class Layer:
    id: int
    bpm: int
    beat: FixedInteger
    speedRate: float
    skyNote: int

    def toBytes(self) -> list[bytes]:
        return [
            self.id.to_bytes(4, "little"),
            self.bpm.to_bytes(4, "little"),
            self.beat.major.to_bytes(4, "little"),
            self.beat.minor.to_bytes(4, "little"),
            struct.pack("<f", self.speedRate),
            self.skyNote.to_bytes(4, "little"),
        ]


@dataclass(kw_only=True)
class LongNote:
    id: int
    curveType: CurveType
    steps: list[int]

    def toBytes(self) -> list[bytes]:
        return [
            self.id.to_bytes(4, "little"),
            self.curveType.value.to_bytes(byteorder="little"),
            len(self.steps).to_bytes(4, "little"),
        ] + [step.to_bytes(4, "little") for step in self.steps]


@dataclass(kw_only=True)
class SkyNote:
    id: int
    floating: float  # x5

    def toBytes(self) -> list[bytes]:
        return [
            self.id.to_bytes(4, "little"),
            struct.pack("<f", self.floating),
        ]


@dataclass(kw_only=True)
class Note:
    id: int
    beat: float
    lane: float
    width: float
    type: NoteType
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
            self.type.value.to_bytes(byteorder="little"),
            self.curveType.value.to_bytes(byteorder="little"),
            self.flickType.value.to_bytes(byteorder="little"),
            self.flag.value.to_bytes(byteorder="little"),
            self.layer.to_bytes(4, "little"),
            self.skyNote.to_bytes(4, "little"),
        ]
