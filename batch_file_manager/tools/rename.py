"""The Rename tool: an ordered list of rules, a live preview of what they do, and Rename / Undo."""

import json
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem, QMenu, QMessageBox,
    QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from batch_file_manager.core.plan import Planned, apply_renames, plan_renames, read_journal, undo, write_journal
from batch_file_manager.core.rules import RULES, Rule, from_dicts, to_dicts
from batch_file_manager.ui.rule_editors import RuleEditor
from batch_file_manager.ui.settings import settings

DEBOUNCE_MS = 250
STATUS_TEXT = {"ok": "rename", "unchanged": "", "invalid": "invalid", "conflict": "conflict"}


class RenamePage(QWidget):
    """``set_items`` feeds it; it asks the window to run a job via ``job_requested(label, fn, done)``.

    ``fn`` runs on a worker thread with ``(log, progress, cancelled)``; ``done`` runs on the UI thread after.
    """

    job_requested = Signal(str, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._paths: list[Path] = []
        self._root: Path | None = None
        self._rows: list[Planned] = []
        self.rules: list[Rule] = []

        # --- rules: list on the left, the selected rule's editor on the right
        self.rule_list = QListWidget()
        self.rule_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.rule_list.currentRowChanged.connect(self._show_editor)
        self.rule_list.itemChanged.connect(self._tick_changed)
        add = QToolButton(text="Add rule", popupMode=QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(add)
        for kind, cls in RULES.items():
            menu.addAction(cls.label, lambda kind=kind: self.add_rule(RULES[kind]()))
        add.setMenu(menu)
        self.remove_button = QPushButton("Remove", clicked=self.remove_rule)
        self.up_button = QPushButton("Up", clicked=lambda: self.move_rule(-1))
        self.down_button = QPushButton("Down", clicked=lambda: self.move_rule(1))
        self.clear_button = QPushButton("Clear", clicked=self.clear_rules)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        for b in (add, self.remove_button, self.up_button, self.down_button, self.clear_button):
            bar.addWidget(b)
        bar.addStretch()
        left = QVBoxLayout()
        left.setSpacing(8)
        left.addLayout(bar)
        left.addWidget(self.rule_list)

        self.editors = QStackedWidget()
        placeholder = QLabel("Add a rule, or select one to edit it.", alignment=Qt.AlignmentFlag.AlignCenter)
        placeholder.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        self.editors.addWidget(placeholder)
        editor_box = QGroupBox("Rule")
        editor_layout = QVBoxLayout(editor_box)
        editor_layout.addWidget(self.editors)
        editor_layout.addStretch()

        rules_row = QHBoxLayout()
        rules_row.setSpacing(12)
        rules_box = QGroupBox("Rules, in order")
        rules_box.setLayout(left)
        rules_row.addWidget(rules_box, stretch=3)
        rules_row.addWidget(editor_box, stretch=2)

        # --- preview
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Folder", "Current name", "New name", ""])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        preview_box = QGroupBox("Preview")
        preview_layout = QVBoxLayout(preview_box)
        preview_layout.addWidget(self.table)

        # --- actions
        self.summary = QLabel("")
        self.undo_button = QPushButton("Undo last rename", clicked=self.undo)
        self.undo_button.setEnabled(bool(read_journal()))
        self.rename_button = QPushButton("Rename", enabled=False, clicked=self.rename)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(self.summary, stretch=1)
        actions.addWidget(self.undo_button)
        actions.addWidget(self.rename_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addLayout(rules_row, stretch=2)
        layout.addWidget(preview_box, stretch=3)
        layout.addLayout(actions)

        self._timer = QTimer(self, singleShot=True, interval=DEBOUNCE_MS)
        self._timer.timeout.connect(self.refresh)
        self._load_rules()
        self._refresh_rule_buttons()

    # --- rules -------------------------------------------------------------------
    def add_rule(self, rule: Rule) -> None:
        self.rules.append(rule)
        item = QListWidgetItem(rule.summary())
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if rule.enabled else Qt.CheckState.Unchecked)
        self.rule_list.addItem(item)
        editor = RuleEditor(rule)
        editor.changed.connect(self._rule_edited)
        self.editors.addWidget(editor)
        self.rule_list.setCurrentRow(self.rule_list.count() - 1)
        self._rules_changed()

    def remove_rule(self) -> None:
        row = self.rule_list.currentRow()
        if row < 0:
            return
        del self.rules[row]
        self.rule_list.takeItem(row)
        editor = self.editors.widget(row + 1)
        self.editors.removeWidget(editor)
        editor.deleteLater()
        self._rules_changed()

    def move_rule(self, delta: int) -> None:
        row = self.rule_list.currentRow()
        new = row + delta
        if row < 0 or not 0 <= new < len(self.rules):
            return
        self.rules[row], self.rules[new] = self.rules[new], self.rules[row]
        item = self.rule_list.takeItem(row)
        self.rule_list.insertItem(new, item)
        editor = self.editors.widget(row + 1)
        self.editors.removeWidget(editor)
        self.editors.insertWidget(new + 1, editor)
        self.rule_list.setCurrentRow(new)
        self._rules_changed()

    def clear_rules(self) -> None:
        self.rules.clear()
        self.rule_list.clear()
        while self.editors.count() > 1:
            editor = self.editors.widget(1)
            self.editors.removeWidget(editor)
            editor.deleteLater()
        self._rules_changed()

    def _show_editor(self, row: int) -> None:
        self.editors.setCurrentIndex(row + 1 if row >= 0 else 0)
        self._refresh_rule_buttons()

    def _tick_changed(self, item: QListWidgetItem) -> None:
        row = self.rule_list.row(item)
        if 0 <= row < len(self.rules):
            self.rules[row].enabled = item.checkState() == Qt.CheckState.Checked
            self._rules_changed()

    def _rule_edited(self) -> None:
        row = self.rule_list.currentRow()
        if row >= 0:
            self.rule_list.item(row).setText(self.rules[row].summary())
        self._rules_changed()

    def _rules_changed(self) -> None:
        settings().setValue("rename/rules", json.dumps(to_dicts(self.rules)))
        self._refresh_rule_buttons()
        self._timer.start()

    def _refresh_rule_buttons(self) -> None:
        row, n = self.rule_list.currentRow(), self.rule_list.count()
        self.remove_button.setEnabled(row >= 0)
        self.up_button.setEnabled(row > 0)
        self.down_button.setEnabled(0 <= row < n - 1)
        self.clear_button.setEnabled(n > 0)

    def _load_rules(self) -> None:
        try:
            saved = from_dicts(json.loads(settings().value("rename/rules", "[]")))
        except (ValueError, TypeError):
            saved = []
        for rule in saved:
            self.add_rule(rule)
        self.rule_list.setCurrentRow(-1)

    # --- preview -------------------------------------------------------------------
    def set_items(self, paths: list[Path], root: Path | None) -> None:
        self._paths, self._root = paths, root
        self.refresh()

    def refresh(self) -> None:
        """Recompute the plan and redraw the table. Runs on the UI thread."""
        # ponytail: plan on the UI thread; move it to a Worker if a >50k-item folder stalls.
        try:
            self._rows = plan_renames(self._paths, self.rules)
            error = ""
        except ValueError as exc:
            self._rows, error = [], str(exc)
        palette = self.palette()
        red, grey = palette.brightText().color(), palette.placeholderText().color()
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(self._rows))
        for i, row in enumerate(self._rows):
            folder = str(row.src.parent.relative_to(self._root)) if self._root else str(row.src.parent)
            cells = [folder if folder != "." else "", row.src.name, row.name, STATUS_TEXT[row.status]]
            for col, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                if row.status in ("invalid", "conflict"):
                    cell.setForeground(red)
                    cell.setToolTip(row.note)
                elif row.status == "unchanged":
                    cell.setForeground(grey)
                self.table.setItem(i, col, cell)
        self.table.setUpdatesEnabled(True)
        counts = {s: sum(1 for r in self._rows if r.status == s) for s in STATUS_TEXT}
        problems = counts["invalid"] + counts["conflict"]
        if error:
            self.summary.setText(f"Rule error: {error}")
        else:
            self.summary.setText(f"{counts['ok']} to rename, {counts['unchanged']} unchanged, {problems} problem(s)")
        self.rename_button.setText(f"Rename {counts['ok']} item(s)" if counts["ok"] else "Rename")
        self.rename_button.setEnabled(counts["ok"] > 0 and problems == 0 and not error)

    # --- jobs -------------------------------------------------------------------
    def rename(self) -> None:
        rows = [r for r in self._rows if r.status == "ok"]
        answer = QMessageBox.question(self, "Rename", f"Rename {len(rows)} item(s)?\n\nUndo is available afterwards.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start("Rename", lambda log, progress, cancelled, out: apply_renames(rows, log, progress, cancelled, out))

    def undo(self) -> None:
        journal = read_journal()
        if not journal:
            self.undo_button.setEnabled(False)
            return
        answer = QMessageBox.question(self, "Undo", f"Put {len(journal)} item(s) back under their previous names?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start("Undo", lambda log, progress, cancelled, out: undo(journal, log, progress, cancelled, out))

    def _start(self, label: str, work: Callable) -> None:
        """Run ``work`` on the worker; whatever it managed to rename is journaled even if some rows failed."""
        journal: list = []

        def fn(log, progress, cancelled) -> None:
            work(log, progress, cancelled, journal)

        def done() -> None:
            if journal:
                write_journal(journal)
            self.undo_button.setEnabled(bool(read_journal()))

        self.job_requested.emit(label, fn, done)
