from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from objects.chart import Chart
from objects.note import LongNote, Note, NoteFlag, SkyNote

ActionType = Literal[
    "note_place", "note_remove", "long_note_remove", "sky_place", "sky_remove"
]


@dataclass(kw_only=True)
class Action:
    type: ActionType
    data: Any


@dataclass(kw_only=True)
class NoteAction(Action):
    data: Note
    # スカイノーツの場合、ノーツと同一idのSkyNoteを一緒に扱う
    skyNote: SkyNote | None = None


@dataclass(kw_only=True)
class LongNoteAction(Action):
    """ロングノーツをまとめて削除/復元する（始点・終点・支点のノーツごと）"""

    data: LongNote
    notes: list[Note]
    skyNote: SkyNote | None = None


@dataclass(kw_only=True)
class SkyNoteAction(Action):
    """既存ノーツへのスカイノーツ付与/解除"""

    data: SkyNote
    note: Note
    # ロングノーツの場合はLongNote.skyNoteを更新する
    longNote: LongNote | None = None


class EditMode(Enum):
    SELECT = 0
    TAP_NOTE = 1
    TRACE_NOTE = 2
    LONG_NOTE = 3
    LONG_NOTE_CONNECTOR = 4
    EVENT = 5
    FLICK_NOTE = 6
    SKY_NOTE = 7


@dataclass(kw_only=True)
class EditingChart:
    chart: Chart
    selectedNotes: list[Note] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    actionsRev: list[Action] = field(default_factory=list)
    editMode: EditMode = EditMode.SELECT
    nextNoteId: int = field(init=False, default=0)
    # 編集中のスカイノーツの選択中knotインデックス
    selectedKnotIndex: int | None = None

    def selectedSkyNote(self):
        """選択ノーツに紐づくSkyNoteとノーツを返す（無ければ(None, None)）"""
        for note in self.selectedNotes:
            if note.flag == NoteFlag.longNote:
                # ロングノーツのスカイノーツは本体(LongNote.skyNote)に紐づく。
                # 始点以外（終点・コネクター）を選択していても判定できるようにする。
                longNote = next(
                    (ln for ln in self.chart.longNotes if note.id in ln.steps),
                    None,
                )
                if longNote is not None and longNote.skyNote:
                    skyNote = next(
                        (s for s in self.chart.skyNotes if s.id == longNote.skyNote),
                        None,
                    )
                    if skyNote is not None:
                        return note, skyNote
            else:
                skyNote = next(
                    (s for s in self.chart.skyNotes if s.id == note.id), None
                )
                if skyNote is not None:
                    return note, skyNote
        return None, None

    def __post_init__(self):
        self.nextNoteId = (
            max(
                (note.id for note in self.chart.notes),
                default=-1,
            )
            + 1
        )

    def pushAction(self, action: Action):
        self.actions.append(action)
        self.actionsRev.clear()
        self.processActions(action, True)

    def loadChart(self, chart: Chart):
        """譜面を読み込み、履歴と選択をリセット"""
        self.chart = chart
        self.selectedNotes = []
        self.actions.clear()
        self.actionsRev.clear()
        self.selectedKnotIndex = None
        self.nextNoteId = max((note.id for note in chart.notes), default=-1) + 1

    def undo(self):
        action = self.actions.pop()
        self.actionsRev.insert(0, action)
        self.processActions(action)

    def redo(self):
        action = self.actionsRev.pop(0)
        self.actions.insert(0, action)
        self.processActions(action, True)

    def processActions(self, action: Action, redo: bool = False) -> bool:
        if isinstance(action, NoteAction):
            # スカイノーツのSkyNoteもノーツと同じタイミングで追加/削除する
            skyNote = action.skyNote

            def addSkyNote():
                if skyNote is not None and all(
                    s.id != skyNote.id for s in self.chart.skyNotes
                ):
                    self.chart.skyNotes.append(skyNote)

            def removeSkyNote():
                if skyNote is not None:
                    self.chart.skyNotes[:] = [
                        s for s in self.chart.skyNotes if s.id != skyNote.id
                    ]

            if action.type == "note_place":
                if not redo:
                    self.chart.notes.remove(action.data)
                    removeSkyNote()
                else:
                    self.chart.notes.append(action.data)
                    addSkyNote()
            elif action.type == "note_remove":
                if redo:
                    self.chart.notes.remove(action.data)
                    removeSkyNote()
                else:
                    self.chart.notes.append(action.data)
                    addSkyNote()

            self.chart.notes.sort(key=lambda n: n.beat)
            return True
        if isinstance(action, LongNoteAction):
            # ロングノーツは本体と全ステップのノーツを同一操作で扱う
            stepIds = {note.id for note in action.notes}
            if redo:
                self.chart.longNotes[:] = [
                    ln for ln in self.chart.longNotes if ln.id != action.data.id
                ]
                self.chart.notes[:] = [
                    n for n in self.chart.notes if n.id not in stepIds
                ]
                if action.skyNote is not None:
                    self.chart.skyNotes[:] = [
                        s for s in self.chart.skyNotes if s.id != action.skyNote.id
                    ]
            else:
                if all(ln.id != action.data.id for ln in self.chart.longNotes):
                    self.chart.longNotes.append(action.data)
                for note in action.notes:
                    if all(n.id != note.id for n in self.chart.notes):
                        self.chart.notes.append(note)
                if action.skyNote is not None and all(
                    s.id != action.skyNote.id for s in self.chart.skyNotes
                ):
                    self.chart.skyNotes.append(action.skyNote)

            self.chart.notes.sort(key=lambda n: n.beat)
            return True
        if isinstance(action, SkyNoteAction):
            skyNote = action.data
            note = action.note
            longNote = action.longNote

            doAdd = (action.type == "sky_place" and redo) or (
                action.type == "sky_remove" and not redo
            )

            if doAdd:
                if all(s.id != skyNote.id for s in self.chart.skyNotes):
                    self.chart.skyNotes.append(skyNote)
                if longNote is not None:
                    longNote.skyNote = skyNote.id
                else:
                    note.skyNote = skyNote.id
            else:
                self.chart.skyNotes[:] = [
                    s for s in self.chart.skyNotes if s.id != skyNote.id
                ]
                if longNote is not None:
                    longNote.skyNote = 0
                else:
                    note.skyNote = 0
            return True
        return False
