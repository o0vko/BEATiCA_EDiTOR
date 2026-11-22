import enum
from dataclasses import dataclass, field
from pathlib import Path

from objects.note import Layer, LongNote, Note, SkyNote
from objects.types import FixedInteger


class Difficulty(enum.Enum):
    NORMAL = 0  # 2本指易
    HARD = 1  # 2本指難
    MASTER = 2  # 多指
    STELLAR = 4  # STELLAR譜面はカオスすぎる


@dataclass(kw_only=True)
class Chart:
    version: int
    id: str
    difficultyType: Difficulty
    difficulty: FixedInteger
    notes: list[Note] = field(default_factory=list)
    longNotes: list[LongNote] = field(default_factory=list)
    skyNotes: list[SkyNote] = field(default_factory=list)
    layers: list[Layer] = field(default_factory=list)

    def export(self, path: Path):
        with open(path, "wb") as f:
            # マジックバイト&バージョンを挿入する
            f.write(b"BEATiCA")
            f.write(self.version.to_bytes(byteorder="little"))

            # 譜面情報を書き込む
            f.write(self.id.encode("utf-8"))
            f.write(self.difficultyType.value.to_bytes(byteorder="little"))
            f.write(self.difficulty.major.to_bytes(byteorder="little"))
            f.write(self.difficulty.minor.to_bytes(byteorder="little"))

            # ノーツ情報を書き込む
            f.write(len(self.notes).to_bytes(byteorder="little"))
            for note in self.notes:
                f.writelines(note.toBytes())

            f.write(len(self.longNotes).to_bytes(byteorder="little"))
            for longNote in self.longNotes:
                f.writelines(longNote.toBytes())

            f.write(len(self.skyNotes).to_bytes(byteorder="little"))
            for skyNote in self.skyNotes:
                f.writelines(skyNote.toBytes())

            f.write(len(self.layers).to_bytes(byteorder="little"))
            for layer in self.layers:
                f.writelines(layer.toBytes())
