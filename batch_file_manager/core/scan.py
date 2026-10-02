"""Which items a tool acts on: one folder, optionally its subfolders, filtered by a name pattern."""

import os
import re
from dataclasses import dataclass
from fnmatch import translate
from pathlib import Path

KINDS = ("files", "folders", "both")


@dataclass(frozen=True)
class ScopeSpec:
    folder: Path
    recurse: bool = False
    kinds: str = "files"  # one of KINDS
    pattern: str = ""  # blank matches everything
    regex: bool = False  # pattern is a regular expression (searched), else a glob (whole name)
    match_case: bool = False


def compile_pattern(spec: ScopeSpec) -> re.Pattern:
    """The name filter as a compiled regex. Raises ``ValueError`` for a bad regex."""
    flags = 0 if spec.match_case else re.IGNORECASE
    if not spec.pattern.strip():
        return re.compile("", flags)
    if spec.regex:
        try:
            return re.compile(spec.pattern, flags)
        except re.error as exc:
            raise ValueError(f"invalid regex: {exc}") from exc
    return re.compile(translate(spec.pattern), flags)


def scan(spec: ScopeSpec) -> list[Path]:
    """Every file and/or folder in scope whose leaf name matches, sorted by path. Symlinks are not followed."""
    if spec.kinds not in KINDS:
        raise ValueError(f"kinds must be one of {KINDS}")
    pattern = compile_pattern(spec)
    matches = pattern.search if spec.regex else pattern.match  # fnmatch's translate anchors with \Z itself
    want_files, want_dirs = spec.kinds != "folders", spec.kinds != "files"
    found: list[Path] = []
    for root, dirs, files in os.walk(spec.folder):
        base = Path(root)
        if want_dirs:
            found.extend(base / d for d in dirs if matches(d))
        if want_files:
            found.extend(base / f for f in files if matches(f))
        if not spec.recurse:
            break
    return sorted(found)
