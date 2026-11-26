import enum
from dataclasses import dataclass, field
from pathlib import Path

from objects.note import Change, Layer, LongNote, Note, SkyNote
from objects.types import FixedInteger


class Difficulty(enum.Enum):
    NORMAL = 0  # 2本指易
    HARD = 1  # 2本指難
    MASTER = 2  # 多指
    STELLAR = 4  # STELLAR譜面はカオスすぎる


@dataclass(kw_only=True)
class Chart:
    version: int = 1
    id: str
    difficultyType: Difficulty
    difficulty: FixedInteger
    offset: float
    notes: list[Note] = field(default_factory=list)
    longNotes: list[LongNote] = field(default_factory=list)
    skyNotes: list[SkyNote] = field(default_factory=list)
    layers: list[Layer] = field(default_factory=list)
    globalChanges: list[Change] = field(default_factory=list)

    def export(self, path: Path):
        # 読み込み側が version で分岐できるよう、書き込みも serialize に集約する
        from objects.serialize import writeBinary

        writeBinary(self, path)
