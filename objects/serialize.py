"""譜面の読み込み・保存を一箇所にまとめたモジュール（JSON形式）。"""

import json
import struct
from pathlib import Path

from objects.chart import Chart, Difficulty
from objects.note import (
    Change,
    CurveType,
    FlickType,
    Layer,
    LongNote,
    Note,
    NoteFlag,
    SkyNote,
    SkyNoteFloating,
)
from objects.types import FixedInteger

# --- 本番バイナリ(.bea)のバージョン ---
# 1: 初期（読み込み不可。id の長さを持たないため）
# 2: id の長さを前置、スカイノーツの knot に lane/positionY それぞれの
#    curveType を追加
BEA_SIGNATURE = b"BEATiCA"
BEA_VERSION = 2


class BeaVersionError(ValueError):
    """読み込めないバージョンの .bea ファイル"""


def _fixed(d: dict) -> FixedInteger:
    return FixedInteger(major=d["major"], minor=d["minor"])


def _fixedDict(v: FixedInteger) -> dict:
    return {"major": v.major, "minor": v.minor}


def chartToDict(chart: Chart) -> dict:
    return {
        "version": chart.version,
        "id": chart.id,
        "difficultyType": chart.difficultyType.name,
        "difficulty": _fixedDict(chart.difficulty),
        "offset": chart.offset,
        "notes": [
            {
                "id": n.id,
                "beat": n.beat,
                "lane": n.lane,
                "width": n.width,
                "curveType": n.curveType.name,
                "flickType": n.flickType.name,
                "flag": n.flag.name,
                "layer": n.layer,
                "skyNote": n.skyNote,
            }
            for n in chart.notes
        ],
        "longNotes": [
            {"id": ln.id, "skyNote": ln.skyNote, "steps": list(ln.steps)}
            for ln in chart.longNotes
        ],
        "skyNotes": [
            {
                "id": s.id,
                "floatings": [
                    {
                        "beat": f.beat,
                        "lane": f.lane,
                        "positionY": f.positionY,
                        "laneCurveType": f.laneCurveType.name,
                        "positionYCurveType": f.positionYCurveType.name,
                    }
                    for f in s.floatings
                ],
            }
            for s in chart.skyNotes
        ],
        "layers": [
            {
                "id": layer.id,
                "skyNote": layer.skyNote,
                "changes": [
                    {
                        "beat": c.beat,
                        "bpm": c.bpm,
                        "timeSignature": _fixedDict(c.timeSignature),
                        "speedRate": c.speedRate,
                    }
                    for c in layer.changes
                ],
            }
            for layer in chart.layers
        ],
        "globalChanges": [
            {
                "beat": c.beat,
                "bpm": c.bpm,
                "timeSignature": _fixedDict(c.timeSignature),
                "speedRate": c.speedRate,
            }
            for c in chart.globalChanges
        ],
    }


def chartFromDict(d: dict) -> Chart:
    return Chart(
        version=d.get("version", 1),
        id=d["id"],
        difficultyType=Difficulty[d["difficultyType"]],
        difficulty=_fixed(d["difficulty"]),
        offset=d["offset"],
        notes=[
            Note(
                id=n["id"],
                beat=n["beat"],
                lane=n["lane"],
                width=n["width"],
                curveType=CurveType[n["curveType"]],
                flickType=FlickType[n["flickType"]],
                flag=NoteFlag[n["flag"]],
                layer=n["layer"],
                skyNote=n["skyNote"],
            )
            for n in d.get("notes", [])
        ],
        longNotes=[
            LongNote(id=ln["id"], skyNote=ln["skyNote"], steps=list(ln["steps"]))
            for ln in d.get("longNotes", [])
        ],
        skyNotes=[
            SkyNote(
                id=s["id"],
                floatings=[
                    SkyNoteFloating(
                        beat=f["beat"],
                        lane=f["lane"],
                        positionY=f["positionY"],
                        laneCurveType=CurveType[f.get("laneCurveType", "linear")],
                        positionYCurveType=CurveType[
                            f.get("positionYCurveType", "linear")
                        ],
                    )
                    for f in s["floatings"]
                ],
            )
            for s in d.get("skyNotes", [])
        ],
        layers=[
            Layer(
                id=layer["id"],
                skyNote=layer["skyNote"],
                changes=[
                    Change(
                        beat=c["beat"],
                        bpm=c["bpm"],
                        timeSignature=_fixed(c["timeSignature"]),
                        speedRate=c["speedRate"],
                    )
                    for c in layer["changes"]
                ],
            )
            for layer in d.get("layers", [])
        ],
        globalChanges=[
            Change(
                beat=c["beat"],
                bpm=c["bpm"],
                timeSignature=_fixed(c["timeSignature"]),
                speedRate=c["speedRate"],
            )
            for c in d.get("globalChanges", [])
        ],
    )


def saveChart(chart: Chart, path: Path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(chartToDict(chart), f, ensure_ascii=False, indent=2)


def loadChart(path: Path) -> Chart:
    with open(path, "r", encoding="utf-8") as f:
        return chartFromDict(json.load(f))


# --- プロジェクトファイル（.beaproj: JSON, BGMパス保持） ---
def saveProject(chart: Chart, path: Path, bgm_path: str | None = None):
    d = chartToDict(chart)
    d["bgm"] = bgm_path or ""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def loadProject(path: Path) -> tuple[Chart, str]:
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    bgm = d.get("bgm", "") or ""
    return chartFromDict(d), bgm


# --- 本番バイナリ（.bea: BGMパス無し） ---
def saveBinary(chart: Chart, path: Path):
    chart.export(path)


def _writeStr(f, value: str) -> None:
    data = value.encode("utf-8")
    f.write(len(data).to_bytes(4, "little"))
    f.write(data)


def _readStr(f) -> str:
    (size,) = struct.unpack("<I", f.read(4))
    return f.read(size).decode("utf-8")


def _writeCurve(f, curve: CurveType) -> None:
    f.write(curve.value.to_bytes(4, "little"))


def _readCurve(f) -> CurveType:
    (value,) = struct.unpack("<I", f.read(4))
    try:
        return CurveType(value)
    except ValueError:
        return CurveType.linear


def writeBinary(chart: Chart, path: Path) -> None:
    """バージョン付きで .bea を書き出す（読み込み側は version で分岐する）"""
    with open(path, "wb") as f:
        f.write(BEA_SIGNATURE)
        f.write(BEA_VERSION.to_bytes(4, "little"))

        _writeStr(f, chart.id)
        f.write(chart.difficultyType.value.to_bytes(4, "little"))
        f.write(chart.difficulty.major.to_bytes(4, "little"))
        f.write(chart.difficulty.minor.to_bytes(4, "little"))
        f.write(struct.pack("<f", chart.offset))

        f.write(len(chart.notes).to_bytes(4, "little"))
        for note in chart.notes:
            f.writelines(note.toBytes())

        f.write(len(chart.longNotes).to_bytes(4, "little"))
        for longNote in chart.longNotes:
            f.writelines(longNote.toBytes())

        f.write(len(chart.skyNotes).to_bytes(4, "little"))
        for skyNote in chart.skyNotes:
            f.writelines(skyNote.toBytes())

        f.write(len(chart.layers).to_bytes(4, "little"))
        for layer in chart.layers:
            f.writelines(layer.toBytes())

        f.write(len(chart.globalChanges).to_bytes(4, "little"))
        for change in chart.globalChanges:
            f.writelines(change.toBytes())


def readBinary(path: Path) -> Chart:
    """バージョンを見て読み込み分岐する .bea ローダー"""
    with open(path, "rb") as f:
        signature = f.read(len(BEA_SIGNATURE))
        if signature != BEA_SIGNATURE:
            raise BeaVersionError(f"{path.name}: 対応する譜面ファイルではありません")
        (version,) = struct.unpack("<I", f.read(4))

        if version > BEA_VERSION:
            raise BeaVersionError(
                f"{path.name}: 新しいバージョン(v{version})の譜面です。"
                f"このアプリ(v{BEA_VERSION})では開けません"
            )
        if version < 2:
            raise BeaVersionError(
                f"{path.name}: バージョン1の譜面は読み込めません。"
                "再エクスポートしてください"
            )

        chart_id = _readStr(f)
        (difficulty_type,) = struct.unpack("<I", f.read(4))
        major, minor = struct.unpack("<II", f.read(8))
        (offset,) = struct.unpack("<f", f.read(4))

        (note_count,) = struct.unpack("<I", f.read(4))
        notes = []
        for _ in range(note_count):
            note_id, beat, lane, width = struct.unpack("<Ifff", f.read(16))
            curve_raw, flick_raw, flag_raw, layer, sky_note = struct.unpack(
                "<IIIiI", f.read(20)
            )
            notes.append(
                Note(
                    id=note_id,
                    beat=beat,
                    lane=lane,
                    width=width,
                    curveType=_curveFromValue(curve_raw),
                    flickType=_flickFromValue(flick_raw),
                    flag=_flagFromValue(flag_raw),
                    layer=layer,
                    skyNote=sky_note,
                )
            )

        (long_count,) = struct.unpack("<I", f.read(4))
        long_notes = []
        for _ in range(long_count):
            long_id, sky_note, step_count = struct.unpack("<III", f.read(12))
            steps = list(struct.unpack(f"<{step_count}I", f.read(4 * step_count)))
            long_notes.append(LongNote(id=long_id, skyNote=sky_note, steps=steps))

        (sky_count,) = struct.unpack("<I", f.read(4))
        sky_notes = []
        for _ in range(sky_count):
            sky_id, floating_count = struct.unpack("<II", f.read(8))
            floatings = []
            for _ in range(floating_count):
                beat, lane, position_y = struct.unpack("<fff", f.read(12))
                lane_curve, position_curve = struct.unpack("<II", f.read(8))
                floatings.append(
                    SkyNoteFloating(
                        beat=beat,
                        lane=lane,
                        positionY=position_y,
                        laneCurveType=_curveFromValue(lane_curve),
                        positionYCurveType=_curveFromValue(position_curve),
                    )
                )
            sky_notes.append(SkyNote(id=sky_id, floatings=floatings))

        (layer_count,) = struct.unpack("<I", f.read(4))
        layers = []
        for _ in range(layer_count):
            layer_id, layer_sky = struct.unpack("<II", f.read(8))
            (change_count,) = struct.unpack("<I", f.read(4))
            changes = [_readChange(f) for _ in range(change_count)]
            layers.append(Layer(id=layer_id, skyNote=layer_sky, changes=changes))

        (global_count,) = struct.unpack("<I", f.read(4))
        global_changes = [_readChange(f) for _ in range(global_count)]

    try:
        difficulty = Difficulty(difficulty_type)
    except ValueError as e:
        raise BeaVersionError(f"{path.name}: 未知の難易度タイプです") from e

    return Chart(
        version=version,
        id=chart_id,
        difficultyType=difficulty,
        difficulty=FixedInteger(major=major, minor=minor),
        offset=offset,
        notes=notes,
        longNotes=long_notes,
        skyNotes=sky_notes,
        layers=layers,
        globalChanges=global_changes,
    )


def _readChange(f) -> Change:
    beat, bpm, major, minor, speed = struct.unpack("<ffIIf", f.read(20))
    return Change(
        beat=beat,
        bpm=bpm,
        timeSignature=FixedInteger(major=major, minor=minor),
        speedRate=speed,
    )


def _curveFromValue(value: int) -> CurveType:
    try:
        return CurveType(value)
    except ValueError:
        return CurveType.linear


def _flickFromValue(value: int) -> FlickType:
    try:
        return FlickType(value)
    except ValueError:
        return FlickType.none


def _flagFromValue(value: int) -> NoteFlag:
    try:
        return NoteFlag(value)
    except ValueError:
        return NoteFlag.none


def loadBinary(path: Path) -> Chart:
    return readBinary(path)
