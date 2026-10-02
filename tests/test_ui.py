"""Theme, worker and the version file, run offscreen."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication

import batch_file_manager
from batch_file_manager.ui import theme
from batch_file_manager.ui.worker import Worker


def test_version_comes_from_the_version_file():
    root = Path(batch_file_manager.__file__).resolve().parent.parent
    assert batch_file_manager.__version__ == (root / "VERSION").read_text().strip() != "0.0.0"


def test_asset_path_points_into_the_package():
    assert theme.asset_path("icon.ico") == Path(batch_file_manager.__file__).resolve().parent / "assets" / "icon.ico"
    assert theme.asset_path("icon.ico").exists()


def test_stylesheet_adds_the_control_look_only_under_fusion():
    assert "QGroupBox" in theme.stylesheet("windows11") and "QPushButton" not in theme.stylesheet("windows11")
    assert "QTabWidget::pane" in theme.stylesheet("windows11")
    assert "QPushButton" in theme.stylesheet("Fusion")


def test_apply_scheme_sets_palette_and_scheme(qapp):
    try:
        theme.apply_scheme("Dark")
        assert qapp.palette().color(theme.R.Window) == QColor(theme.DARK[theme.R.Window])
        assert qapp.palette().color(theme.QPalette.ColorGroup.Disabled, theme.R.Text) == QColor(theme.DARK["disabled"])
        theme.apply_scheme("Light")
        assert qapp.palette().color(theme.R.Window) == QColor(theme.LIGHT[theme.R.Window])
        theme.apply_scheme("System")
        assert QGuiApplication.styleHints().colorScheme() in (Qt.ColorScheme.Unknown, Qt.ColorScheme.Light, Qt.ColorScheme.Dark)
    finally:
        theme.apply_scheme("System")


def test_apply_scheme_without_an_app_is_a_no_op(monkeypatch):
    monkeypatch.setattr(theme.QApplication, "instance", staticmethod(lambda: None))
    theme.apply_scheme("Dark")


def test_worker_reports_failure_and_finishes(qapp):
    failures: list[str] = []
    w = Worker(lambda: (_ for _ in ()).throw(ValueError("nope")))
    w.failed.connect(failures.append)
    w.start()
    assert w.wait(5000)
    qapp.processEvents()
    assert failures == ["nope"]
    w = Worker(lambda: (_ for _ in ()).throw(ValueError()))
    w.failed.connect(failures.append)
    w.start()
    assert w.wait(5000)
    qapp.processEvents()
    assert failures == ["nope", "ValueError"]
