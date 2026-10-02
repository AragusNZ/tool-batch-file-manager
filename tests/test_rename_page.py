"""The Rename tool page: rule list editing, live preview, Rename and Undo through the window."""

import json
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit, QMessageBox, QSpinBox

from batch_file_manager import app as app_module
from batch_file_manager.app import MainWindow
from batch_file_manager.core.rules import Case, Extension, Insert, Numbering, Replace, Template
from batch_file_manager.tools import rename as rename_module
from batch_file_manager.tools.rename import RenamePage
from batch_file_manager.ui.rule_editors import RuleEditor
from batch_file_manager.ui.scope import ScopePanel
from tests.test_app import wait_job, wait_scan


def rows(page: RenamePage) -> list[tuple[str, str, str]]:
    return [tuple(page.table.item(i, c).text() for c in (1, 2, 3)) for i in range(page.table.rowCount())]


def test_add_edit_reorder_tick_remove_and_persist(qapp, tree: Path):
    page = RenamePage()
    assert page.rule_list.count() == 0 and not page.remove_button.isEnabled() and not page.clear_button.isEnabled()
    page.add_rule(Replace(find="a", replace="b"))
    page.add_rule(Case(mode="upper"))
    assert [page.rule_list.item(i).text() for i in range(2)] == ["Replace 'a' → 'b'", "Case: upper"]
    assert page.rule_list.currentRow() == 1 and page.editors.currentIndex() == 2
    assert page.up_button.isEnabled() and not page.down_button.isEnabled()
    page.move_rule(-1)
    assert [r.kind for r in page.rules] == ["case", "replace"] and page.rule_list.currentRow() == 0
    assert page.editors.currentWidget().rule is page.rules[0]
    page.move_rule(-1)  # already at the top: no-op
    assert [r.kind for r in page.rules] == ["case", "replace"]
    page.rule_list.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert page.rules[0].enabled is False
    saved = json.loads(app_module.settings().value("rename/rules"))
    assert [d["kind"] for d in saved] == ["case", "replace"] and saved[0]["enabled"] is False
    # a fresh page restores the list, nothing selected
    again = RenamePage()
    assert [r.kind for r in again.rules] == ["case", "replace"] and again.rule_list.currentRow() == -1
    assert again.rule_list.item(0).checkState() == Qt.CheckState.Unchecked and again.editors.currentIndex() == 0
    page.rule_list.setCurrentRow(1)
    page.remove_rule()
    assert [r.kind for r in page.rules] == ["case"] and page.editors.count() == 2
    page.clear_rules()
    assert page.rules == [] and page.editors.count() == 1 and page.rule_list.currentRow() == -1
    page.remove_rule()  # nothing selected: no-op
    page.move_rule(1)


def test_corrupt_saved_rules_are_ignored(qapp):
    app_module.settings().setValue("rename/rules", "{not json")
    assert RenamePage().rules == []


def test_editor_widgets_follow_the_field_types_and_update_summary(qapp):
    page = RenamePage()
    page.add_rule(Numbering())
    editor: RuleEditor = page.editors.currentWidget()
    w = editor._widgets
    assert isinstance(w["position"], QComboBox) and isinstance(w["start"], QSpinBox)
    assert isinstance(w["separator"], QLineEdit) and isinstance(w["reset_per_folder"], QCheckBox)
    assert "enabled" not in w
    w["start"].setValue(7)
    w["position"].setCurrentText("prefix")
    w["reset_per_folder"].setChecked(True)
    w["separator"].setText("_")
    assert page.rules[0] == Numbering(position="prefix", start=7, separator="_", reset_per_folder=True)
    assert page.rule_list.item(0).text() == "Number from 7 step 1 as prefix"
    page.add_rule(Replace())
    page.editors.currentWidget()._widgets["regex"].setChecked(True)
    assert page.rules[1].regex is True


def test_preview_shows_statuses_and_gates_the_button(qapp, tree: Path):
    page = RenamePage()
    page.set_items(sorted(tree.iterdir()), tree)
    assert not page.rename_button.isEnabled() and page.summary.text() == "0 to rename, 4 unchanged, 0 problem(s)"
    page.add_rule(Extension(mode="lower"))
    page.refresh()
    assert rows(page) == [("Sub", "Sub", ""), ("a.txt", "a.txt", ""), ("b.txt", "b.txt", ""), ("photo.JPG", "photo.jpg", "rename")]
    assert page.table.item(0, 0).text() == "" and page.rename_button.text() == "Rename 1 item(s)"
    assert page.rename_button.isEnabled()
    page.add_rule(Replace(find="^.$", replace="x", regex=True))
    page.refresh()
    conflicts = [r for r in rows(page) if r[2] == "conflict"]
    assert len(conflicts) == 2 and not page.rename_button.isEnabled() and "2 problem(s)" in page.summary.text()
    assert page.table.item(1, 2).toolTip() == "two items would get this name"
    page.rules[1].find = "("
    page.refresh()
    assert page.summary.text().startswith("Rule error:") and page.table.rowCount() == 0
    assert not page.rename_button.isEnabled() and page.rename_button.text() == "Rename"
    page.set_items([tree / "Sub" / "c.TXT"], tree)
    page.clear_rules()
    page.add_rule(Insert(text="x"))
    page.refresh()
    assert page.table.item(0, 0).text() == "Sub"


def test_rename_then_undo_through_the_window(qapp, tree: Path, monkeypatch, journal_file: Path):
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    w = MainWindow()
    page: RenamePage = w.pages[0]
    assert not page.undo_button.isEnabled()
    w.scope.set_folder(tree)
    w.scope.recurse.setChecked(True)
    w.scope.kinds.setCurrentIndex(2)
    wait_scan(w, qapp)
    page.clear_rules()
    page.add_rule(Template(pattern="{n:02}-{name}"))
    page.refresh()
    assert page.rename_button.isEnabled()
    page.rename()
    wait_job(w, qapp)
    # preview order is path order: Sub, Sub/Deep, Sub/Deep/d.txt, Sub/c.TXT, a.txt, b.txt, photo.JPG
    assert sorted(p.name for p in tree.iterdir()) == ["00-Sub", "04-a.txt", "05-b.txt", "06-photo.JPG"]
    assert (tree / "00-Sub" / "01-Deep" / "02-d.txt").exists() and (tree / "00-Sub" / "03-c.TXT").exists()
    assert page.undo_button.isEnabled() and journal_file.exists()
    assert "a.txt -> 04-a.txt" in w.log_view.toPlainText()
    assert [r[0] for r in rows(page)][-1] == "06-photo.JPG"  # the preview follows the rescan
    page.clear_rules()
    page.undo()
    wait_job(w, qapp)
    assert sorted(p.name for p in tree.iterdir()) == ["Sub", "a.txt", "b.txt", "photo.JPG"]
    assert (tree / "Sub" / "Deep" / "d.txt").read_text() == "d"
    assert page.undo_button.isEnabled()  # undoing the undo redoes


def test_declining_the_confirmation_does_nothing(qapp, tree: Path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
    started: list = []
    page = RenamePage()
    page.job_requested.connect(lambda *a: started.append(a))
    page.set_items([tree / "a.txt"], tree)
    page.add_rule(Insert(text="x"))
    page.refresh()
    page.rename()
    rename_module.write_journal([(tree / "a.txt", tree / "z.txt")])
    page.undo()
    assert started == []


def test_undo_with_no_journal_disables_the_button(qapp):
    page = RenamePage()
    page.undo_button.setEnabled(True)
    page.undo()
    assert not page.undo_button.isEnabled()


def test_partial_failure_still_journals_what_was_renamed(qapp, tree: Path, monkeypatch, journal_file: Path):
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    real = Path.rename

    def flaky(self, target):
        if target.name == "xb.txt":
            raise OSError(13, "Permission denied")
        return real(self, target)

    monkeypatch.setattr(Path, "rename", flaky)
    w = MainWindow()
    page: RenamePage = w.pages[0]
    w.scope.set_folder(tree)
    w.scope.pattern.setText("?.txt")
    wait_scan(w, qapp)
    page.clear_rules()
    page.add_rule(Insert(text="x"))
    page.refresh()
    page.rename()
    wait_job(w, qapp)
    text = w.log_view.toPlainText()
    assert "ERROR: b.txt -> xb.txt: Permission denied" in text and "ERROR: 1 of 2 rename(s) failed" in text
    assert [(a.name, b.name) for a, b in rename_module.read_journal()] == [("xa.txt", "a.txt")]
    assert page.undo_button.isEnabled()


# --- ScopePanel on its own -------------------------------------------------------
class _Drop:
    def __init__(self, paths: list[Path]):
        from PySide6.QtCore import QMimeData, QUrl

        self._mime = QMimeData()
        self._mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
        self.accepted = False

    def mimeData(self):
        return self._mime

    def acceptProposedAction(self):
        self.accepted = True


def test_scope_panel_accepts_a_dropped_folder_only(qapp, tree: Path):
    panel = ScopePanel()
    assert panel.spec() is None
    ev = _Drop([tree / "a.txt"])
    panel.dragEnterEvent(ev)
    panel.dropEvent(ev)
    assert not ev.accepted and panel.folder.text() == ""
    ev = _Drop([tree / "a.txt", tree / "Sub"])
    panel.dragEnterEvent(ev)
    assert ev.accepted
    panel.dropEvent(ev)
    assert panel.folder.text() == str(tree / "Sub") and panel.spec().folder == tree / "Sub"
    panel.restore(True, "nonsense")
    assert panel.recurse.isChecked() and panel.kinds.currentData() == "files"


def test_scope_panel_browse_uses_the_dialog(qapp, tree: Path, monkeypatch):
    from batch_file_manager.ui import scope as scope_module

    asked: list[str] = []
    monkeypatch.setattr(
        scope_module.QFileDialog, "getExistingDirectory", lambda parent, title, start: asked.append(start) or str(tree)
    )
    panel = ScopePanel()
    panel.browse()
    assert panel.folder.text() == str(tree) and asked == [str(Path.home())]
    monkeypatch.setattr(scope_module.QFileDialog, "getExistingDirectory", lambda parent, title, start: asked.append(start) or "")
    panel.browse()
    assert panel.folder.text() == str(tree) and asked[-1] == str(tree)
