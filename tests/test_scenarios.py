"""tools/smoke.py's scenarios, offscreen. Add a Scenario there and it runs here too."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from batch_file_manager.app import MainWindow
from tools import smoke


@pytest.mark.parametrize("scenario", smoke.SCENARIOS, ids=lambda s: s.name)
def test_scenario(scenario: smoke.Scenario, qapp, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    smoke.run(scenario, MainWindow(), tmp_path / "tree")


def test_every_scenario_either_expects_a_tree_or_a_block():
    for s in smoke.SCENARIOS:
        assert bool(s.expect) != bool(s.blocked), s.name
