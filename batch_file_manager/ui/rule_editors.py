"""One editor form for any rule, built from the rule dataclass: a widget per field, typed by annotation."""

from dataclasses import fields

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QLineEdit, QSpinBox, QWidget

from batch_file_manager.core.rules import Rule

HIDDEN = {"enabled"}  # the list tick owns this one


class RuleEditor(QWidget):
    """Edits ``rule`` in place and emits ``changed`` after every keystroke or click."""

    changed = Signal()

    def __init__(self, rule: Rule, parent=None):
        super().__init__(parent)
        self.rule = rule
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        self._widgets: dict[str, QWidget] = {}
        for f in fields(rule):
            if f.name in HIDDEN:
                continue
            value = getattr(rule, f.name)
            label = f.name.replace("_", " ").capitalize()
            if f.name in rule.choices:
                w = QComboBox()
                w.addItems(list(rule.choices[f.name]))
                w.setCurrentText(value)
                w.currentTextChanged.connect(lambda text, name=f.name: self._set(name, text))
            elif f.type in ("bool", bool):
                w = QCheckBox(label)
                w.setChecked(value)
                w.toggled.connect(lambda on, name=f.name: self._set(name, on))
                label = ""
            elif f.type in ("int", int):
                w = QSpinBox(minimum=-9999, maximum=99999)
                w.setValue(value)
                w.valueChanged.connect(lambda n, name=f.name: self._set(name, n))
            else:
                w = QLineEdit(value)
                w.textChanged.connect(lambda text, name=f.name: self._set(name, text))
            self._widgets[f.name] = w
            form.addRow(f"{label}:" if label else "", w)

    def _set(self, name: str, value) -> None:
        setattr(self.rule, name, value)
        self.changed.emit()
