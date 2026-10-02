import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """a.txt b.txt Sub/c.TXT Sub/Deep/d.txt, with a few extra kinds for the filters."""
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    (tmp_path / "photo.JPG").write_text("j")
    sub = tmp_path / "Sub"
    sub.mkdir()
    (sub / "c.TXT").write_text("c")
    deep = sub / "Deep"
    deep.mkdir()
    (deep / "d.txt").write_text("d")
    return tmp_path


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def log():
    """Collecting logger: call it, then inspect ``log.lines``."""
    lines: list[str] = []

    def _log(msg: str) -> None:
        lines.append(msg)

    _log.lines = lines  # type: ignore[attr-defined]
    return _log


SETTINGS_KEYS = ("geometry", "last_dir", "recurse", "kinds", "check_updates", "theme", "rename/rules")


@pytest.fixture(autouse=True)
def _clean_settings():
    """Keep test runs out of the real QSettings, and out of each other's."""
    from batch_file_manager.ui.settings import settings

    for key in SETTINGS_KEYS:
        settings().remove(key)
    yield
    for key in SETTINGS_KEYS:
        settings().remove(key)


@pytest.fixture(autouse=True)
def journal_file(tmp_path_factory, monkeypatch):
    """Point the undo journal at a scratch file so tests never touch the real one."""
    from batch_file_manager.core import plan
    from batch_file_manager.tools import rename

    path = tmp_path_factory.mktemp("journal") / "journal.json"
    monkeypatch.setattr(plan, "JOURNAL", path)
    monkeypatch.setattr(rename, "read_journal", lambda p=path: plan.read_journal(p))
    monkeypatch.setattr(rename, "write_journal", lambda j, p=path: plan.write_journal(j, p))
    return path
