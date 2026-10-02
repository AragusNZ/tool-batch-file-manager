"""Rename rules. Each is a dataclass; ``apply_rules`` runs an ordered list of them over the items.

A rule maps ``(stem, ext)`` to ``(stem, ext)``. Folders have ``ext == ""`` so every rule sees their whole
name as the stem. The rule set round-trips through ``to_dicts``/``from_dicts`` for settings and presets.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import ClassVar

POSITIONS = ("prefix", "suffix", "at")
SCOPES = ("name", "ext", "both")


@dataclass
class Item:
    path: Path
    index: int  # 0-based position in the preview; what Numbering counts
    stem: str
    ext: str  # includes the dot, or ""
    is_dir: bool
    mtime: float
    ctime: float = 0.0
    atime: float = 0.0

    @classmethod
    def from_path(cls, path: Path, index: int) -> Item:
        st = path.lstat()
        is_dir = path.is_dir()
        stem, ext = (path.name, "") if is_dir else _split(path.name)
        return cls(path, index, stem, ext, is_dir, st.st_mtime, st.st_ctime, st.st_atime)


def _split(name: str) -> tuple[str, str]:
    """``Path.suffix`` semantics without a Path: a leading dot alone is not an extension."""
    dot = name.rfind(".")
    return (name, "") if dot <= 0 else (name[:dot], name[dot:])


def _insert(stem: str, text: str, position: str, index: int) -> str:
    if position == "prefix":
        return text + stem
    if position == "suffix":
        return stem + text
    return stem[:index] + text + stem[index:]


def _scoped(rule, stem: str, ext: str, fn) -> tuple[str, str]:
    """Run ``fn`` on the stem, the extension (sans dot) or both, per ``rule.scope``."""
    if rule.scope in ("name", "both"):
        stem = fn(stem)
    if rule.scope in ("ext", "both") and ext:
        ext = "." + fn(ext[1:])
    return stem, ext


# --- the rules ---------------------------------------------------------------
@dataclass
class Replace:
    kind: ClassVar[str] = "replace"
    label: ClassVar[str] = "Replace"
    choices: ClassVar[dict] = {"scope": SCOPES}
    hint: ClassVar[str] = "Find text (or a regex with \\1 groups) and replace it."
    find: str = ""
    replace: str = ""
    regex: bool = False
    match_case: bool = False
    first_only: bool = False
    scope: str = "name"
    enabled: bool = True

    def apply(self, stem: str, ext: str, item: Item) -> tuple[str, str]:
        if not self.find:
            return stem, ext
        pattern = re.compile(
            self.find if self.regex else re.escape(self.find), 0 if self.match_case else re.IGNORECASE
        )
        repl = self.replace if self.regex else self.replace.replace("\\", "\\\\")
        return _scoped(self, stem, ext, lambda s: pattern.sub(repl, s, count=1 if self.first_only else 0))

    def summary(self) -> str:
        return f'Replace {"/" if self.regex else ""}{self.find!r} → {self.replace!r}'


@dataclass
class Name:
    kind: ClassVar[str] = "name"
    label: ClassVar[str] = "Name"
    choices: ClassVar[dict] = {"mode": ("keep", "remove", "fixed", "reverse")}
    hint: ClassVar[str] = "Keep, drop, replace or reverse the whole name."
    mode: str = "keep"
    text: str = ""
    enabled: bool = True

    def apply(self, stem: str, ext: str, item: Item) -> tuple[str, str]:
        if self.mode == "remove":
            return "", ext
        if self.mode == "fixed":
            return self.text, ext
        if self.mode == "reverse":
            return stem[::-1], ext
        return stem, ext

    def summary(self) -> str:
        return f"Name: {self.mode}" + (f" {self.text!r}" if self.mode == "fixed" else "")


def _title(s: str) -> str:
    return re.sub(r"[^\W_]+", lambda m: m.group(0)[:1].upper() + m.group(0)[1:].lower(), s)


def _sentence(s: str) -> str:
    low = s.lower()
    m = re.search(r"[^\W_]", low)
    return low if m is None else low[: m.start()] + low[m.start()].upper() + low[m.start() + 1 :]


CASES = {
    "lower": str.lower,
    "upper": str.upper,
    "title": _title,
    "sentence": _sentence,
    "invert": str.swapcase,
}


@dataclass
class Case:
    kind: ClassVar[str] = "case"
    label: ClassVar[str] = "Case"
    choices: ClassVar[dict] = {"mode": tuple(CASES), "scope": SCOPES}
    hint: ClassVar[str] = "Change letter case. Exceptions are words left exactly as typed."
    mode: str = "lower"
    exceptions: str = ""  # words kept as typed, separated by spaces or commas
    scope: str = "name"
    enabled: bool = True

    def apply(self, stem: str, ext: str, item: Item) -> tuple[str, str]:
        convert = CASES[self.mode]
        keep = {w.lower(): w for w in re.split(r"[\s,]+", self.exceptions) if w}

        def fn(s: str) -> str:
            out = convert(s)
            if keep:  # put excepted words back as typed, matched case-insensitively on word boundaries
                out = re.sub(
                    r"[^\W_]+", lambda m: keep.get(m.group(0).lower(), m.group(0)), out
                )
            return out

        return _scoped(self, stem, ext, fn)

    def summary(self) -> str:
        return f"Case: {self.mode}"


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


@dataclass
class Remove:
    kind: ClassVar[str] = "remove"
    label: ClassVar[str] = "Remove"
    choices: ClassVar[dict] = {}
    hint: ClassVar[str] = "Strip characters: by count, by position (1-based), by kind, or crop around a text."
    first_n: int = 0
    last_n: int = 0
    from_pos: int = 0  # 1-based, inclusive; 0 = off
    to_pos: int = 0  # 1-based, inclusive
    chars: str = ""  # every occurrence of each character
    words: str = ""  # every occurrence of each word (space/comma separated), case-insensitive
    digits: bool = False
    symbols: bool = False  # anything not a letter, digit or whitespace
    accents: bool = False
    lead_dots: bool = False
    crop_before: str = ""  # drop everything before (and including) this text
    crop_after: str = ""  # drop everything after (and including) this text
    enabled: bool = True

    def apply(self, stem: str, ext: str, item: Item) -> tuple[str, str]:
        s = stem
        if self.first_n > 0:
            s = s[self.first_n :]
        if self.last_n > 0:
            s = s[: -self.last_n]
        if self.from_pos > 0 and self.to_pos >= self.from_pos:
            s = s[: self.from_pos - 1] + s[self.to_pos :]
        if self.chars:
            s = s.translate({ord(c): None for c in self.chars})
        for word in (w for w in re.split(r"[\s,]+", self.words) if w):
            s = re.sub(re.escape(word), "", s, flags=re.IGNORECASE)
        if self.digits:
            s = re.sub(r"\d", "", s)
        if self.symbols:
            s = re.sub(r"[^\w\s]|_", "", s)
        if self.accents:
            s = _strip_accents(s)
        if self.lead_dots:
            s = s.lstrip(".")
        if self.crop_before and (i := s.lower().find(self.crop_before.lower())) >= 0:
            s = s[i + len(self.crop_before) :]
        if self.crop_after and (i := s.lower().find(self.crop_after.lower())) >= 0:
            s = s[:i]
        return s, ext

    def summary(self) -> str:
        on = [f.name for f in fields(self) if f.name != "enabled" and getattr(self, f.name)]
        return "Remove: " + (", ".join(on) if on else "nothing")


@dataclass
class Spaces:
    kind: ClassVar[str] = "spaces"
    label: ClassVar[str] = "Spaces"
    choices: ClassVar[dict] = {}
    hint: ClassVar[str] = "Tidy whitespace, or swap spaces for another character."
    trim: bool = True
    collapse: bool = True
    replace_with: str = ""  # blank = leave spaces alone
    word_space: bool = False  # "CamelCase" -> "Camel Case", runs first
    enabled: bool = True

    def apply(self, stem: str, ext: str, item: Item) -> tuple[str, str]:
        s = stem
        if self.word_space:
            s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s)
        if self.collapse:
            s = re.sub(r"\s{2,}", " ", s)
        if self.trim:
            s = s.strip()
        if self.replace_with:
            s = s.replace(" ", self.replace_with)
        return s, ext

    def summary(self) -> str:
        return "Spaces" + (f" → {self.replace_with!r}" if self.replace_with else "")


@dataclass
class Move:
    kind: ClassVar[str] = "move"
    label: ClassVar[str] = "Move / copy"
    choices: ClassVar[dict] = {}
    hint: ClassVar[str] = "Move or copy N characters from one end of the name to the other."
    count: int = 1
    from_start: bool = True  # take the chunk from the start (else the end)
    to_start: bool = False  # put it at the start (else the end)
    copy: bool = False  # leave the original chunk in place
    enabled: bool = True

    def apply(self, stem: str, ext: str, item: Item) -> tuple[str, str]:
        n = min(max(self.count, 0), len(stem))
        if n == 0:
            return stem, ext
        chunk, rest = (stem[:n], stem[n:]) if self.from_start else (stem[-n:], stem[:-n])
        body = stem if self.copy else rest
        return (chunk + body if self.to_start else body + chunk), ext

    def summary(self) -> str:
        verb = "Copy" if self.copy else "Move"
        return f"{verb} {self.count} from {'start' if self.from_start else 'end'} to {'start' if self.to_start else 'end'}"


@dataclass
class Insert:
    kind: ClassVar[str] = "insert"
    label: ClassVar[str] = "Insert"
    choices: ClassVar[dict] = {"position": POSITIONS}
    hint: ClassVar[str] = "Add text at the start, the end, or a position (0-based)."
    text: str = ""
    position: str = "prefix"
    index: int = 0
    enabled: bool = True

    def apply(self, stem: str, ext: str, item: Item) -> tuple[str, str]:
        return _insert(stem, self.text, self.position, self.index), ext

    def summary(self) -> str:
        return f"Insert {self.text!r} as {self.position}"


DATE_SOURCES = ("modified", "created", "accessed", "now")


@dataclass
class Date:
    kind: ClassVar[str] = "date"
    label: ClassVar[str] = "Date"
    choices: ClassVar[dict] = {"source": DATE_SOURCES, "position": POSITIONS}
    hint: ClassVar[str] = "Add a date in strftime format, e.g. %Y-%m-%d or %Y%m%d_%H%M."
    source: str = "modified"
    format: str = "%Y-%m-%d"
    position: str = "prefix"
    index: int = 0
    separator: str = " "
    enabled: bool = True

    def apply(self, stem: str, ext: str, item: Item) -> tuple[str, str]:
        text = format_date(self.source, self.format, item)
        text = text + self.separator if self.position == "prefix" else self.separator + text
        return _insert(stem, text, self.position, self.index), ext

    def summary(self) -> str:
        return f"Date ({self.source}) {self.format} as {self.position}"


def format_date(source: str, fmt: str, item: Item) -> str:
    stamp = {"modified": item.mtime, "created": item.ctime, "accessed": item.atime}.get(source)
    when = datetime.now() if stamp is None else datetime.fromtimestamp(stamp)
    return when.strftime(fmt)


@dataclass
class FolderName:
    kind: ClassVar[str] = "folder"
    label: ClassVar[str] = "Folder name"
    choices: ClassVar[dict] = {"position": ("prefix", "suffix")}
    hint: ClassVar[str] = "Add the parent folder's name; levels 2 adds the grandparent too."
    position: str = "prefix"
    levels: int = 1  # 1 = parent, 2 = grandparent/parent, ...
    separator: str = " "
    enabled: bool = True

    def apply(self, stem: str, ext: str, item: Item) -> tuple[str, str]:
        names = [p.name for p in item.path.parents[: max(self.levels, 1)] if p.name][::-1]
        text = self.separator.join(names)
        if not text:
            return stem, ext
        text = text + self.separator if self.position == "prefix" else self.separator + text
        return _insert(stem, text, self.position, 0), ext

    def summary(self) -> str:
        return f"Folder name as {self.position}"


@dataclass
class Numbering:
    kind: ClassVar[str] = "numbering"
    label: ClassVar[str] = "Numbering"
    choices: ClassVar[dict] = {"position": POSITIONS}
    hint: ClassVar[str] = "Add a counter in preview order. Pad is the minimum number of digits."
    position: str = "suffix"
    index: int = 0
    start: int = 1
    step: int = 1
    pad: int = 0  # minimum digits
    separator: str = " "
    reset_per_folder: bool = False
    enabled: bool = True

    def apply(self, stem: str, ext: str, item: Item) -> tuple[str, str]:
        return self.apply_numbered(stem, ext, item.index)

    def apply_numbered(self, stem: str, ext: str, counter: int) -> tuple[str, str]:
        text = str(self.start + counter * self.step).zfill(self.pad)
        text = text + self.separator if self.position == "prefix" else self.separator + text
        return _insert(stem, text, self.position, self.index), ext

    def summary(self) -> str:
        return f"Number from {self.start} step {self.step} as {self.position}"


EXT_MODES = ("same", "lower", "upper", "title", "set", "remove", "append")


@dataclass
class Extension:
    kind: ClassVar[str] = "extension"
    label: ClassVar[str] = "Extension"
    choices: ClassVar[dict] = {"mode": EXT_MODES}
    hint: ClassVar[str] = "Change the extension. Folders are left alone."
    mode: str = "lower"
    value: str = ""
    enabled: bool = True

    def apply(self, stem: str, ext: str, item: Item) -> tuple[str, str]:
        if item.is_dir or self.mode == "same":
            return stem, ext
        if self.mode == "remove":
            return stem, ""
        value = self.value.strip().lstrip(".")
        if self.mode == "set":
            return stem, f".{value}" if value else ""
        if self.mode == "append":
            return stem, ext + (f".{value}" if value else "")
        return stem, ("." + CASES[self.mode](ext[1:])) if ext else ext

    def summary(self) -> str:
        return f"Extension: {self.mode}" + (f" {self.value!r}" if self.mode in ("set", "append") else "")


class _Tokens(dict):
    """format_map mapping: ``{date}`` with a default format, ``{date:%fmt}`` with a custom one."""

    def __init__(self, item: Item, stem: str, ext: str):
        super().__init__(name=stem, ext=ext.lstrip("."), n=item.index + 1, parent=item.path.parent.name)
        self._item = item

    def __missing__(self, key: str) -> str:
        if key == "date":
            return _DateToken(self._item)
        raise KeyError(key)


class _DateToken:
    def __init__(self, item: Item):
        self._item = item

    def __format__(self, spec: str) -> str:
        return format_date("modified", spec or "%Y-%m-%d", self._item)


@dataclass
class Template:
    kind: ClassVar[str] = "template"
    label: ClassVar[str] = "Template"
    choices: ClassVar[dict] = {}
    hint: ClassVar[str] = "Tokens: {name} {ext} {n} {n:03} {parent} {date} {date:%Y%m%d}. {n} counts from 1."
    pattern: str = "{name}"
    enabled: bool = True

    def apply(self, stem: str, ext: str, item: Item) -> tuple[str, str]:
        tokens = _Tokens(item, stem, ext)
        try:
            out = self.pattern.format_map(tokens)
        except (KeyError, ValueError, IndexError) as exc:
            raise ValueError(f"bad template: {exc}") from exc
        if "{ext" in self.pattern:  # the template placed the extension itself
            return _split(out) if not item.is_dir else (out, "")
        return out, ext

    def summary(self) -> str:
        return f"Template {self.pattern!r}"


RULES: dict[str, type] = {
    r.kind: r for r in (Replace, Name, Case, Remove, Spaces, Move, Insert, Date, FolderName, Numbering, Extension, Template)
}
Rule = Replace | Name | Case | Remove | Spaces | Move | Insert | Date | FolderName | Numbering | Extension | Template


# --- running and persisting -------------------------------------------------
def apply_rules(rules: list[Rule], items: list[Item]) -> list[str]:
    """New leaf name for every item, rules applied in order. Raises ``ValueError`` for a rule that cannot run."""
    counters: dict[Path, int] = {}
    out: list[str] = []
    for item in items:
        stem, ext = item.stem, item.ext
        for rule in rules:
            if not rule.enabled:
                continue
            if isinstance(rule, Numbering):
                key = item.path.parent if rule.reset_per_folder else Path()
                n = counters.get(key, 0)
                counters[key] = n + 1
                stem, ext = rule.apply_numbered(stem, ext, n)
                continue
            try:
                stem, ext = rule.apply(stem, ext, item)
            except re.error as exc:
                raise ValueError(f"{rule.label}: invalid regex: {exc}") from exc
        out.append(stem + ext)
    return out


def to_dicts(rules: list[Rule]) -> list[dict]:
    return [{"kind": r.kind, **asdict(r)} for r in rules]


def from_dicts(data: list[dict]) -> list[Rule]:
    """Rebuild rules from ``to_dicts`` output. Unknown kinds and fields are dropped, not fatal."""
    rules: list[Rule] = []
    for entry in data:
        cls = RULES.get(entry.get("kind", ""))
        if cls is None:
            continue
        names = {f.name for f in fields(cls)}
        rules.append(cls(**{k: v for k, v in entry.items() if k in names}))
    return rules


# --- Windows name rules -------------------------------------------------------
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$", re.IGNORECASE)


def validate_name(name: str) -> str | None:
    """Why ``name`` cannot be a Windows file name, or None when it can. Applied on every platform."""
    if not name:
        return "empty name"
    if name in (".", ".."):
        return "name is . or .."
    if m := _BAD_CHARS.search(name):
        ch = m.group(0)
        return f"contains {ch!r}" if ch.isprintable() else "contains a control character"
    if name[-1] in ". ":
        return "ends with a dot or space"
    if _RESERVED.match(_split(name)[0]):
        return "reserved device name"
    if len(name) > 255:
        return "longer than 255 characters"
    return None
