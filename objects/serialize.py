"""譜面の読み込み・保存を一箇所にまとめたモジュール（JSON形式）。"""

import json
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
                        beat=f["beat"], lane=f["lane"], positionY=f["positionY"]
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
