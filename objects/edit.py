from dataclasses import dataclass, field
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


@dataclass(kw_only=True)
class EditingChart:
    chart: Chart
    actions: list[Action] = field(default_factory=list)
    actionsRev: list[Action] = field(default_factory=list)

    def pushAction(self, action: Action):
        self.actions.append(action)
        self.actionsRev.clear()

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
            return True
        return False

    def undo(self):
        action = self.actions.pop()
        self.actionsRev.insert(0, action)
        self.processActions(action)

    def redo(self):
        action = self.actionsRev.pop(0)
        self.actions.insert(0, action)
        self.processActions(action, True)
