"""MainWindow wiring: scope drives the scan, jobs run on the worker, errors reach the log."""

from pathlib import Path

import pytest
from PySide6.QtGui import QCloseEvent

from batch_file_manager import app as app_module
from batch_file_manager.app import MainWindow
from batch_file_manager.core.scan import ScopeSpec


def wait_scan(w: MainWindow, qapp) -> None:
    w.scope._timer.stop()
    w._scope_changed(w.scope.spec())
    worker = w._scan_worker
    assert worker is not None and worker.wait(10000)
    qapp.processEvents()


def wait_job(w: MainWindow, qapp) -> None:
    worker = w._worker
    assert worker is not None and worker.wait(10000)
    qapp.processEvents()
    if w._scan_worker is not None:  # a finished job rescans
        assert w._scan_worker.wait(10000)
        qapp.processEvents()


def test_choosing_a_folder_scans_and_feeds_the_pages(qapp, tree: Path):
    w = MainWindow()
    assert w.pages[0]._paths == [] and w.tabs.tabText(0) == "Rename"
    assert w.scope.set_folder(tree) and not w.scope.set_folder(tree / "a.txt")
    wait_scan(w, qapp)
    assert [p.name for p in w._paths] == ["a.txt", "b.txt", "photo.JPG"]
    assert w.pages[0]._paths == w._paths and w.pages[0].table.rowCount() == 3
    assert w.scope.summary.text() == "3 item(s) in scope"
    assert app_module.settings().value("last_dir") == str(tree)
    assert w.statusBar().currentMessage() == "3 item(s) in scope"


def test_scope_is_remembered_between_runs(qapp, tree: Path):
    w = MainWindow()
    w.scope.set_folder(tree)
    w.scope.recurse.setChecked(True)
    w.scope.kinds.setCurrentIndex(2)
    wait_scan(w, qapp)
    again = MainWindow()
    assert again.scope.folder.text() == str(tree) and again.scope.recurse.isChecked()
    assert again.scope.kinds.currentData() == "both"
    wait_scan(again, qapp)
    assert len(again._paths) == 7


def test_bad_regex_shows_in_the_summary_not_a_dialog(qapp, tree: Path):
    w = MainWindow()
    w.scope.set_folder(tree)
    w.scope.mode.setCurrentIndex(1)
    w.scope.pattern.setText("(")
    wait_scan(w, qapp)
    assert w.scope.summary.text().startswith("invalid regex") and w._paths == []


def test_a_scope_change_mid_scan_scans_again(qapp, tree: Path):
    w = MainWindow()
    w.scope.set_folder(tree)
    w.scope._timer.stop()
    w._scope_changed(w.scope.spec())
    first = w._scan_worker
    w.scope.recurse.setChecked(True)
    w.scope._timer.stop()
    w._scope_changed(w.scope.spec())  # ignored while a scan is running, but remembered
    assert w._scan_worker is first
    assert first.wait(10000)
    qapp.processEvents()
    second = w._scan_worker
    assert second is not None and second is not first and second.wait(10000)
    qapp.processEvents()
    assert len(w._paths) == 5


def test_job_runs_on_worker_then_done_then_rescan(qapp, tree: Path):
    seen: dict = {}
    w = MainWindow()
    w.scope.set_folder(tree)
    wait_scan(w, qapp)

    def fn(log, progress, cancelled):
        log("from worker")
        progress(1, 2)
        (tree / "new.txt").write_text("n")
        seen["cancelled"] = cancelled()

    w.run_job("T", fn, lambda: seen.setdefault("done", True))
    assert not w.tabs.isEnabled() and not w.scope.isEnabled() and not w.cancel_button.isHidden()
    w.run_job("ignored", fn, None)  # one job at a time
    wait_job(w, qapp)
    text = w.log_view.toPlainText()
    assert "--- T ---" in text and "from worker" in text and "ignored" not in text and text.rstrip().endswith("done")
    assert seen == {"cancelled": False, "done": True}
    assert w.tabs.isEnabled() and w.cancel_button.isHidden() and w._worker is None
    assert [p.name for p in w._paths] == ["a.txt", "b.txt", "new.txt", "photo.JPG"]
    assert w.statusBar().currentMessage() == "4 item(s) in scope"
    assert w.progress.maximum() == 2 and w.progress.value() == 1


def test_job_error_reaches_log_and_cancel_flags_the_worker(qapp, tree: Path):
    import threading

    gate = threading.Event()
    w = MainWindow()
    w.scope.set_folder(tree)
    wait_scan(w, qapp)

    def fn(log, progress, cancelled):
        gate.wait(5)
        raise RuntimeError("bad thing")

    w.run_job("T", fn, None)
    w.cancel_button.click()
    assert not w.cancel_button.isEnabled() and w._worker.isInterruptionRequested()
    gate.set()
    wait_job(w, qapp)
    assert "ERROR: bad thing" in w.log_view.toPlainText() and "cancelling" in w.log_view.toPlainText()


def test_close_refused_while_busy(qapp, tree: Path):
    import threading

    gate = threading.Event()
    w = MainWindow()
    w.scope.set_folder(tree)
    wait_scan(w, qapp)
    w.run_job("T", lambda log, progress, cancelled: gate.wait(5), None)
    ev = QCloseEvent()
    w.closeEvent(ev)
    assert not ev.isAccepted() and "still working" in w.log_view.toPlainText()
    gate.set()
    wait_job(w, qapp)
    ev = QCloseEvent()
    w.closeEvent(ev)
    assert ev.isAccepted()


def test_window_geometry_survives_a_restart(qapp):
    w = MainWindow()
    w.setGeometry(40, 50, 780, 580)  # inside the offscreen screen, which clamps anything larger
    w.closeEvent(QCloseEvent())
    assert app_module.settings().value("geometry")
    assert MainWindow().size() == w.size()


def test_theme_menu_sets_and_remembers(qapp, monkeypatch):
    applied: list[str] = []
    monkeypatch.setattr(app_module, "apply_scheme", applied.append)
    w = MainWindow()
    try:
        w._set_theme("Dark")
        assert applied == ["Dark"] and app_module.settings().value("theme") == "Dark"
        app_module._follow_system_scheme(None)
        assert applied == ["Dark"]  # not following the system while forced
        app_module.settings().setValue("theme", "System")
        app_module._follow_system_scheme(None)
        assert applied == ["Dark", "System"]
    finally:
        app_module.settings().remove("theme")


# --- updates (carried from the pdf-helper skeleton) --------------------------------
def _check(w: MainWindow, qapp, manual: bool) -> None:
    w._check_updates(manual=manual)
    worker = w._update_worker
    assert worker is not None and worker.wait(10000)
    qapp.processEvents()


def _stub_update(monkeypatch, latest):
    seen: dict = {"opened": [], "info": []}

    def fetch():
        if isinstance(latest, Exception):
            raise latest
        return latest

    monkeypatch.setattr(app_module, "latest_version", fetch)
    monkeypatch.setattr(app_module.QMessageBox, "question", lambda *a: app_module.QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(app_module.QMessageBox, "information", lambda *a: seen["info"].append(a[-1]))
    monkeypatch.setattr(app_module.QDesktopServices, "openUrl", lambda url: seen["opened"].append(url.toString()))
    return seen


def test_newer_release_opens_the_download_page(qapp, monkeypatch):
    seen = _stub_update(monkeypatch, "999.0.0")
    w = MainWindow()
    _check(w, qapp, manual=False)
    assert seen["opened"] == [app_module.RELEASES_URL] and w._update_worker is None


def test_up_to_date_speaks_only_when_asked(qapp, monkeypatch):
    seen = _stub_update(monkeypatch, app_module.__version__)
    w = MainWindow()
    _check(w, qapp, manual=False)
    assert seen["info"] == []
    _check(w, qapp, manual=True)
    assert len(seen["info"]) == 1 and "up to date" in seen["info"][0] and seen["opened"] == []


def test_update_failure_logged_only_when_asked(qapp, monkeypatch):
    _stub_update(monkeypatch, OSError("offline"))
    w = MainWindow()
    _check(w, qapp, manual=False)
    assert "update check failed" not in w.log_view.toPlainText()
    _check(w, qapp, manual=True)
    assert "ERROR: update check failed: offline" in w.log_view.toPlainText()


def test_startup_check_toggle_is_remembered(qapp):
    w = MainWindow()
    assert w.startup_check.isChecked()
    w.startup_check.setChecked(False)
    assert not app_module.check_on_startup() and not MainWindow().startup_check.isChecked()


def test_close_waits_for_a_running_update_check(qapp, monkeypatch):
    import threading

    release = threading.Event()
    _stub_update(monkeypatch, None)
    monkeypatch.setattr(app_module, "latest_version", lambda: release.wait(5) and app_module.__version__)
    w = MainWindow()
    w._check_updates(manual=False)
    worker = w._update_worker
    w._check_updates(manual=True)  # a second click while one is in flight is ignored
    assert w._update_worker is worker
    threading.Timer(0.2, release.set).start()
    ev = QCloseEvent()
    w.closeEvent(ev)
    assert ev.isAccepted() and worker.isFinished()
    qapp.processEvents()


def test_about_names_the_log_file(qapp, monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(app_module.QMessageBox, "about", lambda parent, title, text: seen.append(text))
    MainWindow()._about()
    assert str(app_module.LOG_FILE) in seen[0] and app_module.__version__ in seen[0]
