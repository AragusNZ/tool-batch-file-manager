"""Plan statuses, two-phase apply, folders deepest-first, journal and undo."""

from pathlib import Path

import pytest

from batch_file_manager.core.plan import Planned, apply_renames, plan_renames, read_journal, undo, write_journal
from batch_file_manager.core.rules import Case, Extension, Name, Replace, Template
from batch_file_manager.core.scan import ScopeSpec, scan


def listing(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


def statuses(rows: list[Planned]) -> dict[str, str]:
    return {r.src.name: r.status for r in rows}


def test_statuses(tree: Path):
    paths = scan(ScopeSpec(tree))  # a.txt b.txt photo.JPG
    rows = plan_renames(paths, [Replace(find="a", replace="b")])
    assert statuses(rows) == {"a.txt": "conflict", "b.txt": "unchanged", "photo.JPG": "unchanged"}
    assert rows[0].note == "two items would get this name"
    rows = plan_renames(paths, [Extension(mode="set", value="JPG"), Replace(find="photo", replace="A")])
    assert statuses(rows) == {"a.txt": "conflict", "b.txt": "ok", "photo.JPG": "conflict"}  # a.JPG vs A.JPG
    assert rows[2].note == "two items would get this name"
    rows = plan_renames([tree / "a.txt"], [Replace(find="a", replace="Sub"), Extension(mode="remove")])
    assert rows[0].status == "conflict" and "already exists" in rows[0].note
    rows = plan_renames([tree / "a.txt"], [Replace(find="a", replace="CON")])
    assert rows[0].status == "invalid" and rows[0].note == "reserved device name"
    rows = plan_renames([tree / "a.txt"], [Name(mode="remove"), Extension(mode="remove")])
    assert rows[0].status == "invalid" and rows[0].note == "empty name" and rows[0].dst == tree / "a.txt"
    rows = plan_renames([tree / "a.txt"], [Replace(find="a", replace="x/y")])
    assert rows[0].status == "invalid" and rows[0].name == "x/y.txt" and rows[0].dst == tree / "a.txt"


def test_existing_target_is_matched_case_insensitively(tree: Path):
    rows = plan_renames([tree / "a.txt"], [Replace(find="a", replace="PHOTO"), Extension(mode="set", value="jpg")])
    assert rows[0].status == "conflict"  # photo.JPG is there; Windows would refuse


def test_a_broken_rule_raises(tree: Path):
    with pytest.raises(ValueError):
        plan_renames([tree / "a.txt"], [Template(pattern="{nope}")])


def test_swap_and_case_only_rename(tree: Path, log):
    rows = plan_renames([tree / "a.txt", tree / "b.txt", tree / "photo.JPG"], [
        Replace(find="^a$", replace="TMP", regex=True), Replace(find="^b$", replace="a", regex=True),
        Replace(find="^TMP$", replace="b", regex=True), Extension(),
    ])
    assert all(r.status == "ok" for r in rows)
    journal = apply_renames(rows, log)
    assert (tree / "a.txt").read_text() == "b" and (tree / "b.txt").read_text() == "a"
    assert (tree / "photo.jpg").exists() and not any(p.name.startswith("~bfm-") for p in tree.iterdir())
    assert [(a.name, b.name) for a, b in journal] == [("b.txt", "a.txt"), ("a.txt", "b.txt"), ("photo.jpg", "photo.JPG")]
    assert log.lines == ["a.txt -> b.txt", "b.txt -> a.txt", "photo.JPG -> photo.jpg"]


def test_folders_rename_after_their_children_and_undo_restores(tree: Path, log):
    before = listing(tree)
    paths = scan(ScopeSpec(tree, recurse=True, kinds="both"))
    rows = plan_renames(paths, [Case(mode="upper"), Extension(mode="upper")])
    progress: list[tuple[int, int]] = []
    journal = apply_renames(rows, log, lambda d, t: progress.append((d, t)))
    assert listing(tree) == ["A.TXT", "B.TXT", "PHOTO.JPG", "SUB", "SUB/C.TXT", "SUB/DEEP", "SUB/DEEP/D.TXT"]
    assert progress[-1] == (len(paths), len(paths)) and len(progress) == len(paths)
    # the journal names where things are now, after their parents moved
    assert {a.relative_to(tree).as_posix() for a, _ in journal} == set(listing(tree))
    undone = undo(journal, log)
    assert listing(tree) == before
    assert {a.relative_to(tree).as_posix() for a, _ in undone} == set(before)
    assert (tree / "Sub" / "Deep" / "d.txt").read_text() == "d"


def test_one_failure_continues_and_is_counted(tree: Path, log, monkeypatch):
    rows = plan_renames([tree / "a.txt", tree / "b.txt"], [Replace(find="^", replace="x", regex=True)])
    real = Path.rename

    def flaky(self, target):
        if target.name == "xb.txt":
            raise OSError(13, "Permission denied")
        return real(self, target)

    monkeypatch.setattr(Path, "rename", flaky)
    journal: list = []
    with pytest.raises(RuntimeError, match="1 of 2"):
        apply_renames(rows, log, journal=journal)
    assert (tree / "xa.txt").exists() and (tree / "b.txt").exists()  # b was put back under its own name
    assert [(a.name, b.name) for a, b in journal] == [("xa.txt", "a.txt")]
    assert any(l.startswith("ERROR: b.txt -> xb.txt") for l in log.lines)


def test_staging_failure_is_counted(tree: Path, log, monkeypatch):
    rows = plan_renames([tree / "a.txt"], [Replace(find="a", replace="z")])
    monkeypatch.setattr(Path, "rename", lambda self, target: (_ for _ in ()).throw(OSError(13, "busy")))
    with pytest.raises(RuntimeError, match="1 of 1"):
        apply_renames(rows, log)
    assert log.lines == ["ERROR: a.txt: busy"] and (tree / "a.txt").exists()


def test_cancel_stops_between_folders(tree: Path, log):
    paths = scan(ScopeSpec(tree, recurse=True))
    rows = plan_renames(paths, [Replace(find="^", replace="x", regex=True)])
    calls = iter([False, True, True])
    apply_renames(rows, log, cancelled=lambda: next(calls))
    assert (tree / "Sub" / "Deep" / "xd.txt").exists() and (tree / "a.txt").exists()
    assert log.lines[-1] == "cancelled: 1 of 5 renamed"


def test_journal_round_trip_and_missing_file(tmp_path: Path):
    path = tmp_path / "j.json"
    assert read_journal(path) == []
    write_journal([(tmp_path / "new.txt", tmp_path / "old.txt")], path)
    assert read_journal(path) == [(tmp_path / "new.txt", tmp_path / "old.txt")]
    path.write_text("not json")
    assert read_journal(path) == []
    path.write_text('[{"from": "x"}]')
    assert read_journal(path) == []
