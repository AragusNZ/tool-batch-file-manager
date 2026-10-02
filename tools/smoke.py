"""End-to-end scenarios driven through the real window.

    python tools/smoke.py            # visible window, pauses so you can watch each step
    python tools/smoke.py -k swap    # only scenarios whose name contains "swap"
    pytest tests/test_scenarios.py   # the same scenarios, offscreen, in the gate

Each scenario builds a scratch tree, scopes the window to it, adds its rules, renames, checks where every
file ended up, undoes, and checks the tree is back exactly. Add a Scenario to SCENARIOS for every new rule,
scope option or tool behaviour - that list is the manual smoke test, automated.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from batch_file_manager import app as app_module  # noqa: E402
from batch_file_manager.core import plan as plan_module  # noqa: E402
from batch_file_manager.core.rules import (  # noqa: E402
    Case, Extension, FolderName, Insert, Move, Name, Numbering, Remove, Replace, Rule, Spaces, Template,
)
from batch_file_manager.tools import rename as rename_module  # noqa: E402

TREE = ["a.txt", "b.txt", "photo.JPG", "Sub/c.TXT", "Sub/Deep/d.txt"]  # files; folders come from the paths


@dataclass
class Scenario:
    name: str
    rules: list[Rule]
    expect: dict[str, str | None]  # after Rename: relative path -> which original file is now there (None = folder)
    recurse: bool = False
    kinds: str = "files"
    pattern: str = ""
    regex: bool = False
    blocked: str = ""  # expected substring of the summary when Rename must stay disabled; expect is then ignored
    detect_replace: str = ""  # pick the top Detect pattern entry, then set its replacement to this
    tree: list[str] = field(default_factory=lambda: list(TREE))


FOLDERS_UNCHANGED = {"Sub": None, "Sub/Deep": None, "Sub/c.TXT": "Sub/c.TXT", "Sub/Deep/d.txt": "Sub/Deep/d.txt"}

SCENARIOS: list[Scenario] = [
    Scenario(
        "swap a and b",
        [Replace(find="^a$", replace="TMP", regex=True), Replace(find="^b$", replace="a", regex=True),
         Replace(find="^TMP$", replace="b", regex=True)],
        {"a.txt": "b.txt", "b.txt": "a.txt", "photo.JPG": "photo.JPG", **FOLDERS_UNCHANGED},
    ),
    Scenario(
        "case-only rename of the extension",
        [Extension(mode="lower")],
        {"a.txt": "a.txt", "b.txt": "b.txt", "photo.jpg": "photo.JPG", **FOLDERS_UNCHANGED},
    ),
    Scenario(
        "numbering template across folders, files and folders both",
        [Template(pattern="{n:02}-{name}")],
        {"01-Sub": None, "01-Sub/02-Deep": None, "01-Sub/02-Deep/03-d.txt": "Sub/Deep/d.txt",
         "01-Sub/04-c.TXT": "Sub/c.TXT", "05-a.txt": "a.txt", "06-b.txt": "b.txt", "07-photo.JPG": "photo.JPG"},
        recurse=True, kinds="both",
    ),
    Scenario(
        "numbering restarts in each folder",
        [Numbering(position="prefix", separator="_", pad=2, reset_per_folder=True)],
        {"Sub": None, "Sub/Deep": None, "Sub/Deep/01_d.txt": "Sub/Deep/d.txt", "Sub/01_c.TXT": "Sub/c.TXT",
         "01_a.txt": "a.txt", "02_b.txt": "b.txt", "03_photo.JPG": "photo.JPG"},
        recurse=True,
    ),
    Scenario(
        "glob filter limits the batch",
        [Insert(text="x")],
        {"xa.txt": "a.txt", "xb.txt": "b.txt", "photo.JPG": "photo.JPG", **FOLDERS_UNCHANGED},
        pattern="*.txt",
    ),
    Scenario(
        "regex filter with match case picks the upper-case extension",
        [Case(mode="upper")],
        {"a.txt": "a.txt", "b.txt": "b.txt", "PHOTO.JPG": "photo.JPG", **FOLDERS_UNCHANGED},
        pattern=r"\.JPG$", regex=True,
    ),
    Scenario(
        "folders only, nested",
        [Insert(text="Renamed-")],
        {"Renamed-Sub": None, "Renamed-Sub/Renamed-Deep": None, "Renamed-Sub/Renamed-Deep/d.txt": "Sub/Deep/d.txt",
         "Renamed-Sub/c.TXT": "Sub/c.TXT", "a.txt": "a.txt", "b.txt": "b.txt", "photo.JPG": "photo.JPG"},
        recurse=True, kinds="folders",
    ),
    Scenario(
        "folder name on a filtered file in a subfolder",
        [FolderName(position="suffix", separator="-"), Name(mode="reverse")],
        {"a.txt": "a.txt", "b.txt": "b.txt", "photo.JPG": "photo.JPG", "Sub": None, "Sub/Deep": None,
         "Sub/buS-c.TXT": "Sub/c.TXT", "Sub/Deep/d.txt": "Sub/Deep/d.txt"},
        recurse=True, pattern="c*",
    ),
    Scenario(
        "remove, spaces and move in order",
        [Remove(digits=True), Spaces(replace_with="_"), Move(count=1, from_start=True, to_start=False)],
        {"ile_onef.txt": "file 1 one.txt", "ile_twof.txt": "file 2 two.txt"},
        tree=["file 1 one.txt", "file 2 two.txt"],
    ),
    Scenario(
        "detect pattern feeds a replace rule",
        [],
        {"Photo-0001.jpg": "IMG_0001.jpg", "Photo-0002.jpg": "IMG_0002.jpg", "Photo-0003.jpg": "IMG_0003.jpg",
         "notes.txt": "notes.txt"},
        tree=["IMG_0001.jpg", "IMG_0002.jpg", "IMG_0003.jpg", "notes.txt"], detect_replace=r"Photo-\1",
    ),
    Scenario(
        "disabled rule is skipped",
        [Insert(text="SKIP", enabled=False), Insert(text="y", position="suffix")],
        {"ay.txt": "a.txt", "by.txt": "b.txt", "photoy.JPG": "photo.JPG", **FOLDERS_UNCHANGED},
    ),
    # --- must stay blocked -------------------------------------------------------------
    Scenario("two files would collide", [Replace(find="^.$", replace="x", regex=True)], {}, blocked="2 problem(s)"),
    Scenario("target already exists on disk (case-insensitive)", [Name(mode="fixed", text="PHOTO"), Extension(mode="set", value="jpg")],
             {}, pattern="a.txt", blocked="1 problem(s)"),
    Scenario("reserved windows name", [Name(mode="fixed", text="CON")], {}, blocked="problem(s)"),
    Scenario("nothing changes", [Replace(find="zzz", replace="y")], {}, blocked="0 to rename"),
    Scenario("broken regex", [Replace(find="(", regex=True)], {}, blocked="Rule error"),
]


# --- harness ---------------------------------------------------------------------------
def build_tree(root: Path, files: list[str]) -> None:
    for rel in files:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rel)  # the content says which original file this is, wherever it ends up


def snapshot(root: Path) -> dict[str, str | None]:
    return {
        p.relative_to(root).as_posix(): (None if p.is_dir() else p.read_text()) for p in sorted(root.rglob("*"))
    }


def isolate(scratch: Path) -> None:
    """Keep the run out of the real settings and undo journal."""
    from PySide6.QtCore import QSettings

    ini = scratch / "settings.ini"
    app_module.settings = rename_module.settings = lambda: QSettings(str(ini), QSettings.Format.IniFormat)
    journal = scratch / "undo.json"
    plan_module.JOURNAL = journal
    rename_module.read_journal = lambda p=journal: plan_module.read_journal(p)
    rename_module.write_journal = lambda j, p=journal: plan_module.write_journal(j, p)
    QMessageBox.question = lambda *a, **k: QMessageBox.StandardButton.Yes
    app_module.MainWindow._report_failure = lambda self, label, message: print(f"      {label} failed: {message}")


def wait_for(getter, pause: int = 0) -> None:
    """Spin the event loop until the worker ``getter`` returns is gone."""
    while getter() is not None:
        QTest.qWait(10)
    QTest.qWait(pause)


def run(scenario: Scenario, window: app_module.MainWindow, root: Path, pause: int = 0) -> None:
    """Drive one scenario through the window's widgets. Raises AssertionError with the first mismatch."""
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir()
    build_tree(root, scenario.tree)
    before = snapshot(root)
    page: rename_module.RenamePage = window.pages[0]

    scope = window.scope
    scope.recurse.setChecked(scenario.recurse)
    scope.kinds.setCurrentIndex(["files", "folders", "both"].index(scenario.kinds))
    scope.mode.setCurrentIndex(1 if scenario.regex else 0)
    scope.match_case.setChecked(scenario.regex)
    scope.pattern.setText(scenario.pattern)
    scope.set_folder(root)
    scope._timer.stop()
    window._scope_changed(scope.spec())
    wait_for(lambda: window._scan_worker, pause)

    page.clear_rules()
    for rule in scenario.rules:
        page.add_rule(rule)
        QTest.qWait(pause // 2)
    if scenario.detect_replace:
        page._build_detect_menu()
        page.detect_menu.actions()[0].trigger()
        page.rules[-1].replace = scenario.detect_replace
        page._rule_edited()
        QTest.qWait(pause // 2)
    page._timer.stop()
    page.refresh()
    QTest.qWait(pause)

    if scenario.blocked:
        assert not page.rename_button.isEnabled(), f"Rename should be disabled: {page.summary.text()}"
        assert scenario.blocked in page.summary.text(), f"summary {page.summary.text()!r} lacks {scenario.blocked!r}"
        return
    assert page.rename_button.isEnabled(), f"Rename disabled: {page.summary.text()}"

    page.rename()
    wait_for(lambda: window._worker)
    wait_for(lambda: window._scan_worker, pause)
    after = snapshot(root)
    assert after == scenario.expect, f"after rename:\n  got      {after}\n  expected {scenario.expect}"
    assert page.undo_button.isEnabled(), "Undo should be available"

    page.undo()
    wait_for(lambda: window._worker)
    wait_for(lambda: window._scan_worker, pause)
    assert snapshot(root) == before, f"undo did not restore the tree:\n  got {snapshot(root)}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-k", default="", help="only scenarios whose name contains this text")
    parser.add_argument("--pause", type=int, default=600, help="ms to linger on each step so you can watch (0 = flat out)")
    args = parser.parse_args()

    scratch = Path(tempfile.mkdtemp(prefix="bfm-smoke-"))
    isolate(scratch)
    app = QApplication.instance() or QApplication(sys.argv)
    window = app_module.MainWindow()
    window.show()
    failed = 0
    for scenario in (s for s in SCENARIOS if args.k.lower() in s.name.lower()):
        window.statusBar().showMessage(scenario.name)
        try:
            run(scenario, window, scratch / "tree", args.pause)
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {scenario.name}\n      {exc}")
        else:
            print(f"ok    {scenario.name}")
    print(f"\n{failed} failed" if failed else "\nall scenarios passed")
    QTest.qWait(args.pause * 2)
    window.close()
    shutil.rmtree(scratch, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
