"""From scanned paths and rules to a checked plan, and from a plan to renamed files - with a way back."""

from __future__ import annotations

import json
import logging
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from batch_file_manager.core.rules import Item, Rule, apply_rules, validate_name

JOURNAL = Path(tempfile.gettempdir()) / "BatchFileManager-undo.json"
log = logging.getLogger(__name__)

Journal = list[tuple[Path, Path]]  # (where it is now, where it was)


@dataclass
class Planned:
    src: Path
    dst: Path  # == src when the row is not going anywhere
    status: str  # ok | unchanged | invalid | conflict
    name: str = ""  # the new leaf name as the rules produced it, valid or not
    note: str = ""


def plan_renames(paths: list[Path], rules: list[Rule]) -> list[Planned]:
    """One row per path, in order. Raises ``ValueError`` when a rule itself is broken (bad regex, bad template)."""
    items = [Item.from_path(p, i) for i, p in enumerate(paths)]
    rows: list[Planned] = []
    for item, name in zip(items, apply_rules(rules, items)):
        if reason := validate_name(name):
            rows.append(Planned(item.path, item.path, "invalid", name, reason))
        elif name == item.path.name:
            rows.append(Planned(item.path, item.path, "unchanged", name))
        else:
            rows.append(Planned(item.path, item.path.parent / name, "ok", name))
    sources = {_key(r.src) for r in rows}
    targets: dict[str, int] = {}
    for row in rows:
        if row.status != "invalid":  # an unchanged row still occupies its name
            targets[_key(row.dst)] = targets.get(_key(row.dst), 0) + 1
    for row in rows:
        if row.status != "ok":
            continue
        if targets[_key(row.dst)] > 1:
            row.status, row.note = "conflict", "two items would get this name"
        elif _key(row.dst) not in sources and _exists(row.dst):
            row.status, row.note = "conflict", "a file with this name already exists"
    return rows


def _key(path: Path) -> str:
    return str(path).lower()  # Windows compares names case-insensitively; so does this plan everywhere


def _exists(path: Path) -> bool:
    """Case-insensitive existence check, so a plan made on Linux predicts what Windows will do."""
    if path.exists() or path.is_symlink():
        return True
    try:
        return any(p.name.lower() == path.name.lower() for p in path.parent.iterdir())
    except OSError:
        return False


def apply_renames(
    rows: list[Planned],
    log_line: Callable[[str], None],
    progress: Callable[[int, int], None] = lambda done, total: None,
    cancelled: Callable[[], bool] = lambda: False,
    journal: Journal | None = None,
) -> Journal:
    """Rename every ``ok`` row. Returns the journal that undoes it; raises at the end if any row failed.

    Pass ``journal`` to receive what was renamed even when the call raises.

    Deepest directory first, so a folder moves only after everything inside it has. Within a directory
    every source goes to a temporary name first, then to its target: that one path handles swaps
    (a<->b) and case-only renames on a case-insensitive disk without special cases.
    """
    # ponytail: whole-dir two-phase even for a single rename; cheap, and it is what makes swaps correct.
    todo = [r for r in rows if r.status == "ok"]
    by_dir: dict[Path, list[Planned]] = {}
    for row in todo:
        by_dir.setdefault(row.src.parent, []).append(row)
    journal = [] if journal is None else journal
    failed = done = 0
    total = len(todo)
    for folder in sorted(by_dir, key=lambda p: (-len(p.parts), str(p))):
        if cancelled():
            log_line(f"cancelled: {done} of {total} renamed")
            break
        staged: list[tuple[Path, Planned]] = []
        for row in by_dir[folder]:
            tmp = folder / f"~bfm-{uuid.uuid4().hex}"
            try:
                row.src.rename(tmp)
            except OSError as exc:
                log.exception("stage %s", row.src)
                log_line(f"ERROR: {row.src.name}: {exc.strerror or exc}")
                failed += 1
                done += 1
                progress(done, total)
            else:
                staged.append((tmp, row))
        for tmp, row in staged:
            dst = folder / row.dst.name  # always a rename within one directory
            try:
                tmp.rename(dst)
            except OSError as exc:
                log.exception("rename %s -> %s", row.src, row.dst)
                log_line(f"ERROR: {row.src.name} -> {row.dst.name}: {exc.strerror or exc}")
                tmp.rename(row.src)  # put it back under its own name
                failed += 1
            else:
                if dst.is_dir():  # children were renamed first; they now live under the new folder name
                    journal[:] = [(_rebase(now, row.src, dst), before) for now, before in journal]
                journal.append((dst, row.src))
                log_line(f"{row.src.name} -> {dst.name}")
            done += 1
            progress(done, total)
    if failed:
        raise RuntimeError(f"{failed} of {total} rename(s) failed")
    return journal


def _rebase(path: Path, old_parent: Path, new_parent: Path) -> Path:
    try:
        return new_parent / path.relative_to(old_parent)
    except ValueError:
        return path


def undo(
    journal: Journal,
    log_line: Callable[[str], None],
    progress: Callable[[int, int], None] = lambda done, total: None,
    cancelled: Callable[[], bool] = lambda: False,
    out: Journal | None = None,
) -> Journal:
    """Reverse a journal. Returns the journal of the undo itself, so undoing twice redoes."""
    rows = [Planned(now, before, "ok") for now, before in journal]
    return apply_renames(rows, log_line, progress, cancelled, out)


def write_journal(journal: Journal, path: Path = JOURNAL) -> None:
    path.write_text(json.dumps([{"from": str(a), "to": str(b)} for a, b in journal], indent=1), encoding="utf-8")


def read_journal(path: Path = JOURNAL) -> Journal:
    """The last journal, or [] when there is none or it is unreadable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [(Path(e["from"]), Path(e["to"])) for e in data]
    except (OSError, ValueError, KeyError, TypeError):
        return []
