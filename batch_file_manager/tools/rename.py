"""The Rename tool: an ordered list of rules, a live preview of what they do, and Rename / Undo."""

import json
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QByteArray, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPushButton, QScrollArea, QSplitter, QStackedWidget, QTableWidget,
    QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from batch_file_manager.core.pattern import infer_patterns
from batch_file_manager.core.plan import Planned, apply_renames, plan_renames, read_journal, undo, write_journal
from batch_file_manager.core.rules import RULES, Item, Replace, Rule, from_dicts, to_dicts
from batch_file_manager.core.scan import ORDERS, order_paths
from batch_file_manager.ui.rule_editors import RuleEditor
from batch_file_manager.ui.settings import settings

DEBOUNCE_MS = 250
STATUS_TEXT = {"ok": "rename", "unchanged": "", "invalid": "invalid", "conflict": "conflict"}
ORDER_LABELS = {"path": "Path", "name": "Name", "modified": "Date modified"}


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
        self.presets_button = QToolButton(text="Presets", popupMode=QToolButton.ToolButtonPopupMode.InstantPopup)
        self.presets_menu = QMenu(self.presets_button)
        self.presets_menu.aboutToShow.connect(self._build_presets_menu)
        self.presets_button.setMenu(self.presets_menu)
        self.detect_button = QToolButton(text="Detect pattern", popupMode=QToolButton.ToolButtonPopupMode.InstantPopup)
        self.detect_menu = QMenu(self.detect_button)
        self.detect_menu.aboutToShow.connect(self._build_detect_menu)
        self.detect_button.setMenu(self.detect_menu)
        self.remove_button = QPushButton("Remove", clicked=self.remove_rule)
        self.up_button = QToolButton(arrowType=Qt.ArrowType.UpArrow, toolTip="Move up", clicked=lambda: self.move_rule(-1))
        self.down_button = QToolButton(arrowType=Qt.ArrowType.DownArrow, toolTip="Move down", clicked=lambda: self.move_rule(1))
        self.clear_button = QPushButton("Clear", clicked=self.clear_rules)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        for b in (add, self.presets_button, self.detect_button, self.remove_button, self.up_button, self.down_button, self.clear_button):
            bar.addWidget(b)
        bar.addStretch()
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)  # every card already pads 12
        left.setSpacing(8)
        left.addLayout(bar)
        left.addWidget(self.rule_list)

        # The hint lives outside the editor form: a wrapped label inside QFormLayout inside a QStackedWidget
        # never gets its height-for-width, so it was cut off. A plain box layout honours it.
        self.hint = QLabel("", wordWrap=True)
        self.hint.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        self.editors = QStackedWidget()
        placeholder = QLabel("Add a rule, or select one to edit it.", alignment=Qt.AlignmentFlag.AlignCenter)
        placeholder.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        self.editors.addWidget(placeholder)
        # The scroll area keeps the tallest editor from setting the floor of the whole row; it only scrolls
        # when the window is genuinely tiny.
        scroll = QScrollArea(widgetResizable=True, frameShape=QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        scroll.setWidget(self.editors)
        self.editors.setAutoFillBackground(False)
        editor_box = QGroupBox("Rule")
        editor_layout = QVBoxLayout(editor_box)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(8)
        editor_layout.addWidget(self.hint)
        editor_layout.addWidget(scroll)

        rules_row = QHBoxLayout()
        rules_row.setContentsMargins(0, 0, 0, 0)
        rules_row.setSpacing(12)
        rules_box = QGroupBox("Rules, in order")
        rules_box.setLayout(left)
        rules_row.addWidget(rules_box, stretch=3)
        rules_row.addWidget(editor_box, stretch=2)
        rules_widget = QWidget()
        rules_widget.setLayout(rules_row)

        # --- preview
        self.order = QComboBox()
        for order in ORDERS:
            self.order.addItem(ORDER_LABELS[order], order)
        saved_order = settings().value("rename/order", "path")
        self.order.setCurrentIndex(ORDERS.index(saved_order) if saved_order in ORDERS else 0)
        self.reverse = QCheckBox("Reverse", checked=settings().value("rename/reverse", False, type=bool))
        self.hide_unchanged = QCheckBox("Hide unchanged", checked=settings().value("rename/hide_unchanged", False, type=bool))
        self.order.currentIndexChanged.connect(self._view_changed)
        self.reverse.toggled.connect(self._view_changed)
        self.hide_unchanged.toggled.connect(self._view_changed)
        view = QHBoxLayout()
        view.setSpacing(8)
        view.addWidget(QLabel("Order:"))
        view.addWidget(self.order)
        view.addWidget(self.reverse)
        view.addStretch()
        view.addWidget(self.hide_unchanged)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Folder", "Current name", "New name", ""])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide()
        self.table.itemDoubleClicked.connect(self._open_row)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        preview_box = QGroupBox("Preview")
        preview_layout = QVBoxLayout(preview_box)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(8)
        preview_layout.addLayout(view)
        preview_layout.addWidget(self.table)

        # --- actions: the preview's own footer
        self.summary = QLabel("")
        self.undo_button = QPushButton("Undo last rename", clicked=self.undo)
        self.undo_button.setEnabled(bool(read_journal()))
        self.rename_button = QPushButton("Rename", enabled=False, clicked=self.rename)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(self.summary, stretch=1)
        actions.addWidget(self.undo_button)
        actions.addWidget(self.rename_button)
        preview_layout.addLayout(actions)

        self.splitter = QSplitter(Qt.Orientation.Vertical, childrenCollapsible=False)
        self.splitter.addWidget(rules_widget)
        self.splitter.addWidget(preview_box)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 3)
        if state := settings().value("rename/splitter"):
            self.splitter.restoreState(QByteArray(state))
        self.splitter.splitterMoved.connect(lambda *_: settings().setValue("rename/splitter", self.splitter.saveState()))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

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
        self.hint.setText(self.rules[row].hint if 0 <= row < len(self.rules) else "")
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

    # --- presets -------------------------------------------------------------------
    def _presets(self) -> dict[str, list[dict]]:
        try:
            data = json.loads(settings().value("rename/presets", "{}"))
        except (ValueError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _store_presets(self, presets: dict[str, list[dict]]) -> None:
        settings().setValue("rename/presets", json.dumps(presets))

    def save_preset(self, name: str) -> None:
        """Store the current rules under ``name``, replacing a preset of that name. Blank is a no-op."""
        name = name.strip()
        if not name:
            return
        self._store_presets({**self._presets(), name: to_dicts(self.rules)})

    def load_preset(self, name: str) -> None:
        """Replace the current rules with the preset's. An unknown name is a no-op."""
        data = self._presets().get(name)
        if data is None:
            return
        self.clear_rules()
        for rule in from_dicts(data):
            self.add_rule(rule)
        self.rule_list.setCurrentRow(-1)

    def delete_preset(self, name: str) -> None:
        presets = self._presets()
        presets.pop(name, None)
        self._store_presets(presets)

    def _save_preset_dialog(self) -> None:
        name, ok = QInputDialog.getText(self, "Save preset", "Preset name:")
        if ok:
            self.save_preset(name)

    def _build_presets_menu(self) -> None:
        menu, names = self.presets_menu, sorted(self._presets())
        menu.clear()
        for name in names:
            menu.addAction(name, lambda name=name: self.load_preset(name))
        if names:
            menu.addSeparator()
        menu.addAction("Save as...", self._save_preset_dialog).setEnabled(bool(self.rules))
        delete = menu.addMenu("Delete")
        delete.setEnabled(bool(names))
        for name in names:
            delete.addAction(name, lambda name=name: self.delete_preset(name))

    # --- detect pattern ------------------------------------------------------------
    def _build_detect_menu(self) -> None:
        """The commonest name shapes in scope as regexes; picking one adds a no-op Replace rule to edit."""
        menu = self.detect_menu
        menu.clear()
        stems = [Item.from_path(p, 0).stem for p in self._paths]
        found = infer_patterns(stems)
        if not found:
            menu.addAction("No repeating pattern in scope").setEnabled(False)
        for regex, repl, count in found:
            text = f"{regex}    {count} of {len(stems)}".replace("&", "&&")
            menu.addAction(text, lambda regex=regex, repl=repl: self.add_rule(Replace(find=regex, replace=repl, regex=True)))

    # --- preview -------------------------------------------------------------------
    def set_items(self, paths: list[Path], root: Path | None) -> None:
        self._paths, self._root = paths, root
        self.refresh()

    def _view_changed(self) -> None:
        settings().setValue("rename/order", self.order.currentData())
        settings().setValue("rename/reverse", self.reverse.isChecked())
        settings().setValue("rename/hide_unchanged", self.hide_unchanged.isChecked())
        self.refresh()

    def _open_row(self, cell: QTableWidgetItem) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._rows[cell.row()].src.parent)))

    def refresh(self) -> None:
        """Recompute the plan and redraw the table. Runs on the UI thread."""
        # ponytail: plan on the UI thread; move it to a Worker if a >50k-item folder stalls.
        try:
            paths = order_paths(self._paths, self.order.currentData(), self.reverse.isChecked())
            self._rows = plan_renames(paths, self.rules)
            error = ""
        except ValueError as exc:
            self._rows, error = [], str(exc)
        palette = self.palette()
        red, grey = palette.brightText().color(), palette.placeholderText().color()
        hide = self.hide_unchanged.isChecked()
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
            self.table.setRowHidden(i, hide and row.status == "unchanged")
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

        def done() -> str:
            if journal:
                write_journal(journal)
            self.undo_button.setEnabled(bool(read_journal()))
            return f"{'Put back' if label == 'Undo' else 'Renamed'} {len(journal)} item(s)"

        self.job_requested.emit(label, fn, done)
