from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from objects.chart import Chart
from objects.note import Note


@dataclass(kw_only=True)
class Action:
    type: Literal["note_place", "note_remove"]
    data: Any


@dataclass(kw_only=True)
class NoteAction(Action):
    type: Literal["note_place", "note_remove"]
    data: Note


class EditMode(Enum):
    SELECT = 0
    TAP_NOTE = 1
    TRACE_NOTE = 2
    LONG_NOTE = 3
    LONG_NOTE_CONNECTOR = 4
    EVENT = 5


@dataclass(kw_only=True)
class EditingChart:
    chart: Chart
    selectedNotes: list[Note] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    actionsRev: list[Action] = field(default_factory=list)
    editMode: EditMode = EditMode.SELECT
    nextNoteId: int = field(init=False, default=0)

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
            if action.type == "note_place":
                if not redo:
                    self.chart.notes.remove(action.data)
                else:
                    self.chart.notes.append(action.data)
            elif action.type == "note_remove":
                if redo:
                    self.chart.notes.remove(action.data)
                else:
                    self.chart.notes.append(action.data)

            self.chart.notes.sort(key=lambda n: n.beat)
            return True
        return False
