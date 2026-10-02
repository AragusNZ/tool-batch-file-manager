"""Which items a tool acts on: one folder, optionally its subfolders, filtered by a name pattern; and their order."""

import os
import re
from dataclasses import dataclass
from fnmatch import translate
from pathlib import Path

KINDS = ("files", "folders", "both")
ORDERS = ("path", "name", "modified")


@dataclass(frozen=True)
class ScopeSpec:
    folder: Path
    recurse: bool = False
    kinds: str = "files"  # one of KINDS
    pattern: str = ""  # blank matches everything
    regex: bool = False  # pattern and exclude are regular expressions (searched), else globs (whole name)
    match_case: bool = False
    exclude: str = ""  # names to leave out; an excluded folder is not entered either. Blank excludes nothing


def compile_pattern(text: str, regex: bool, match_case: bool) -> re.Pattern:
    """A name filter as a compiled regex. Raises ``ValueError`` for a bad regex."""
    flags = 0 if match_case else re.IGNORECASE
    if not text.strip():
        return re.compile("", flags)
    if regex:
        try:
            return re.compile(text, flags)
        except re.error as exc:
            raise ValueError(f"invalid regex: {exc}") from exc
    return re.compile(translate(text), flags)


def scan(spec: ScopeSpec) -> list[Path]:
    """Every file and/or folder in scope whose leaf name matches, sorted by path. Symlinks are not followed."""
    if spec.kinds not in KINDS:
        raise ValueError(f"kinds must be one of {KINDS}")
    pattern = compile_pattern(spec.pattern, spec.regex, spec.match_case)
    matches = pattern.search if spec.regex else pattern.match  # fnmatch's translate anchors with \Z itself
    if spec.exclude.strip():
        excluded = compile_pattern(spec.exclude, spec.regex, spec.match_case)
        skipped = excluded.search if spec.regex else excluded.match
    else:
        skipped = lambda name: None  # noqa: E731
    want_files, want_dirs = spec.kinds != "folders", spec.kinds != "files"
    found: list[Path] = []
    for root, dirs, files in os.walk(spec.folder):
        base = Path(root)
        dirs[:] = [d for d in dirs if not skipped(d)]
        files = [f for f in files if not skipped(f)]
        if want_dirs:
            found.extend(base / d for d in dirs if matches(d))
        if want_files:
            found.extend(base / f for f in files if matches(f))
        if not spec.recurse:
            break
    return sorted(found, key=path_key)


def path_key(p: Path) -> list[str]:
    """Sort key for paths: case-insensitive, parent before children, the same on every platform."""
    return [part.casefold() for part in p.parts]


def _natural(name: str) -> list:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name.lower())]


def order_paths(paths: list[Path], order: str = "path", reverse: bool = False) -> list[Path]:
    """``paths`` in preview order: by path, by leaf name (natural: IMG_2 before IMG_10) or by modified time."""
    if order == "name":
        key = lambda p: (_natural(p.name), path_key(p))  # noqa: E731
    elif order == "modified":
        key = lambda p: (p.lstat().st_mtime, path_key(p))  # noqa: E731
    else:
        key = path_key
    return sorted(paths, key=key, reverse=reverse)
