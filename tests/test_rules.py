"""Every rule kind, the pipeline, persistence and the Windows name check."""

import time
from datetime import datetime
from pathlib import Path

import pytest

from batch_file_manager.core.rules import (
    RULES, Case, Date, Extension, FolderName, Insert, Item, Move, Name, Numbering, Remove, Replace, Spaces, Template,
    apply_rules, from_dicts, to_dicts, validate_name,
)


def item(name: str, folder: Path = Path("/root/Sub"), index: int = 0, is_dir: bool = False) -> Item:
    stem, ext = (name, "") if is_dir else (name.rsplit(".", 1)[0], "." + name.rsplit(".", 1)[1]) if "." in name[1:] else (name, "")
    return Item(folder / name, index, stem, ext, is_dir, mtime=1_700_000_000.0, ctime=1_600_000_000.0, atime=1_650_000_000.0)


def run(rule, name: str, **kw) -> str:
    return apply_rules([rule], [item(name, **kw)])[0]


def test_item_from_path_splits_like_pathlib(tmp_path: Path):
    f = tmp_path / "report.final.PDF"
    f.write_text("x")
    (tmp_path / ".hidden").write_text("x")
    d = tmp_path / "folder.v2"
    d.mkdir()
    assert (Item.from_path(f, 0).stem, Item.from_path(f, 0).ext) == ("report.final", ".PDF")
    assert (Item.from_path(tmp_path / ".hidden", 1).stem, Item.from_path(tmp_path / ".hidden", 1).ext) == (".hidden", "")
    assert (Item.from_path(d, 2).stem, Item.from_path(d, 2).ext, Item.from_path(d, 2).is_dir) == ("folder.v2", "", True)


# --- Replace -------------------------------------------------------------------
def test_replace_plain_is_case_insensitive_and_literal():
    assert run(Replace(find="img_", replace="Photo "), "IMG_001.jpg") == "Photo 001.jpg"
    assert run(Replace(find="a.c", replace="x"), "abc a.c.txt") == "abc x.txt"
    assert run(Replace(find="a", replace="x", match_case=True), "aAa.txt") == "xAx.txt"
    assert run(Replace(find="a", replace="x", first_only=True), "aaa.txt") == "xaa.txt"
    assert run(Replace(find="a", replace="\\"), "a.txt") == "\\.txt"
    assert run(Replace(), "same.txt") == "same.txt"


def test_replace_regex_groups_and_scope():
    assert run(Replace(find=r"(\d+)-(\d+)", replace=r"\2-\1", regex=True), "12-34.txt") == "34-12.txt"
    assert run(Replace(find="t", replace="z", scope="ext"), "t.txt") == "t.zxz"
    assert run(Replace(find="t", replace="z", scope="both"), "t.txt") == "z.zxz"
    assert run(Replace(find="x", replace="z", scope="ext"), "noext") == "noext"


def test_bad_regex_surfaces_as_value_error():
    with pytest.raises(ValueError, match="invalid regex"):
        run(Replace(find="(", regex=True), "a.txt")


# --- Name / Case / Spaces / Move -------------------------------------------------
def test_name_modes():
    assert run(Name(mode="keep"), "abc.txt") == "abc.txt"
    assert run(Name(mode="remove"), "abc.txt") == ".txt"
    assert run(Name(mode="fixed", text="x"), "abc.txt") == "x.txt"
    assert run(Name(mode="reverse"), "abc.txt") == "cba.txt"


def test_case_modes_and_exceptions():
    assert run(Case(mode="lower"), "My FILE.TXT") == "my file.TXT"
    assert run(Case(mode="upper", scope="both"), "My FILE.txt") == "MY FILE.TXT"
    assert run(Case(mode="title"), "the quick-brown fox_v2.txt") == "The Quick-Brown Fox_V2.txt"
    assert run(Case(mode="sentence"), "HELLO WORLD.txt") == "Hello world.txt"
    assert run(Case(mode="sentence"), "_HELLO.txt") == "_Hello.txt"
    assert run(Case(mode="sentence"), "123.txt") == "123.txt"
    assert run(Case(mode="invert"), "aBc.txt") == "AbC.txt"
    assert run(Case(mode="title", exceptions="of, the NASA"), "history of the nasa program.txt") == "History of the NASA Program.txt"


def test_spaces():
    assert run(Spaces(), "  a   b .txt") == "a b.txt"
    assert run(Spaces(trim=False, collapse=False), "  a   b .txt") == "  a   b .txt"
    assert run(Spaces(replace_with="_"), "a b c.txt") == "a_b_c.txt"
    assert run(Spaces(word_space=True), "myCamelCase2Go.txt") == "my Camel Case2 Go.txt"


def test_move_and_copy():
    assert run(Move(count=3), "abcdef.txt") == "defabc.txt"
    assert run(Move(count=2, from_start=False, to_start=True), "abcdef.txt") == "efabcd.txt"
    assert run(Move(count=2, copy=True), "abcd.txt") == "abcdab.txt"
    assert run(Move(count=2, from_start=False, to_start=True, copy=True), "abcd.txt") == "cdabcd.txt"
    assert run(Move(count=10), "ab.txt") == "ab.txt"
    assert run(Move(count=0), "ab.txt") == "ab.txt"


# --- Remove -------------------------------------------------------------------
def test_remove_counts_and_positions():
    assert run(Remove(first_n=2), "abcdef.txt") == "cdef.txt"
    assert run(Remove(last_n=2), "abcdef.txt") == "abcd.txt"
    assert run(Remove(from_pos=2, to_pos=3), "abcdef.txt") == "adef.txt"
    assert run(Remove(from_pos=3, to_pos=2), "abcdef.txt") == "abcdef.txt"  # inverted range is off
    assert run(Remove(first_n=10), "abc.txt") == ".txt"


def test_remove_by_kind():
    assert run(Remove(chars="-_"), "a-b_c.txt") == "abc.txt"
    assert run(Remove(words="copy, FINAL"), "Report final Copy.txt") == "Report  .txt"
    assert run(Remove(digits=True), "a1b22.txt") == "ab.txt"
    assert run(Remove(symbols=True), "a-b_c (1)!.txt") == "abc 1.txt"
    assert run(Remove(accents=True), "café naïve.txt") == "cafe naive.txt"
    assert run(Remove(lead_dots=True), "..a.b.txt") == "a.b.txt"
    assert run(Remove(crop_before=" - "), "Artist - Title.mp3") == "Title.mp3"
    assert run(Remove(crop_after=" ("), "Title (Live).mp3") == "Title.mp3"
    assert run(Remove(crop_before="zzz"), "a.txt") == "a.txt"
    assert run(Remove(), "a.txt") == "a.txt"
    assert Remove().summary() == "Remove: nothing" and "digits" in Remove(digits=True).summary()


# --- Insert / Date / Folder / Numbering ------------------------------------------
def test_insert_positions():
    assert run(Insert(text="X"), "abc.txt") == "Xabc.txt"
    assert run(Insert(text="X", position="suffix"), "abc.txt") == "abcX.txt"
    assert run(Insert(text="X", position="at", index=1), "abc.txt") == "aXbc.txt"
    assert run(Insert(text="X", position="at", index=99), "abc.txt") == "abcX.txt"


def test_date_sources_and_placement():
    modified = datetime.fromtimestamp(1_700_000_000.0).strftime("%Y-%m-%d")
    created = datetime.fromtimestamp(1_600_000_000.0).strftime("%Y%m%d")
    accessed = datetime.fromtimestamp(1_650_000_000.0).strftime("%Y")
    assert run(Date(), "a.txt") == f"{modified} a.txt"
    assert run(Date(source="created", format="%Y%m%d", position="suffix", separator="_"), "a.txt") == f"a_{created}.txt"
    assert run(Date(source="accessed", format="%Y", position="at", index=1, separator=""), "ab.txt") == f"a{accessed}b.txt"
    assert run(Date(source="now", format="%Y"), "a.txt") == f"{time.strftime('%Y')} a.txt"


def test_folder_name_levels():
    assert run(FolderName(), "a.txt", folder=Path("/root/Sub")) == "Sub a.txt"
    assert run(FolderName(position="suffix", levels=2, separator="-"), "a.txt", folder=Path("/root/Sub")) == "a-root-Sub.txt"
    assert run(FolderName(levels=5), "a.txt", folder=Path("/root/Sub")) == "root Sub a.txt"
    assert run(FolderName(), "a.txt", folder=Path("/")) == "a.txt"


def test_numbering_counts_in_preview_order_and_can_reset_per_folder():
    items = [item("a.txt", Path("/x")), item("b.txt", Path("/x"), 1), item("c.txt", Path("/y"), 2)]
    assert apply_rules([Numbering(start=10, step=5, pad=3)], items) == ["a 010.txt", "b 015.txt", "c 020.txt"]
    assert apply_rules([Numbering(reset_per_folder=True, position="prefix", separator="-")], items) == ["1-a.txt", "2-b.txt", "1-c.txt"]
    assert run(Numbering(position="at", index=1, separator=""), "ab.txt") == "a1b.txt"


# --- Extension / Template ----------------------------------------------------------
def test_extension_modes():
    assert run(Extension(), "a.TXT") == "a.txt"
    assert run(Extension(mode="upper"), "a.txt") == "a.TXT"
    assert run(Extension(mode="title"), "a.jpeg") == "a.Jpeg"
    assert run(Extension(mode="same"), "a.TXT") == "a.TXT"
    assert run(Extension(mode="set", value=".md"), "a.txt") == "a.md"
    assert run(Extension(mode="set", value=""), "a.txt") == "a"
    assert run(Extension(mode="remove"), "a.txt") == "a"
    assert run(Extension(mode="append", value="bak"), "a.txt") == "a.txt.bak"
    assert run(Extension(mode="lower"), "noext") == "noext"
    assert run(Extension(mode="set", value="x"), "Folder", is_dir=True) == "Folder"


def test_template_tokens():
    modified = datetime.fromtimestamp(1_700_000_000.0)
    assert run(Template(pattern="{parent}-{n:03}-{name}"), "a.txt", index=4) == "Sub-004-a.txt"
    assert run(Template(pattern="{name}.{ext}.bak"), "a.txt") == "a.txt.bak"
    assert run(Template(pattern="{date} {name}"), "a.txt") == f"{modified:%Y-%m-%d} a.txt"
    assert run(Template(pattern="{date:%Y%m%d}"), "a.txt") == f"{modified:%Y%m%d}.txt"
    assert run(Template(pattern="{name}.{ext}"), "Dir", is_dir=True) == "Dir."
    with pytest.raises(ValueError, match="bad template"):
        run(Template(pattern="{nope}"), "a.txt")
    with pytest.raises(ValueError, match="bad template"):
        run(Template(pattern="{name"), "a.txt")


# --- pipeline, persistence -------------------------------------------------------
def test_rules_run_in_order_and_disabled_ones_are_skipped():
    rules = [Replace(find="a", replace="b"), Case(mode="upper"), Insert(text="x", enabled=False)]
    assert apply_rules(rules, [item("a.txt")]) == ["B.txt"]
    rules[1].enabled = False
    assert apply_rules(rules, [item("a.txt")]) == ["b.txt"]


def test_round_trip_through_dicts_and_summaries():
    rules = [cls() for cls in RULES.values()]
    rules[0].find, rules[0].regex = "x", True
    data = to_dicts(rules)
    assert [d["kind"] for d in data] == list(RULES) and data[0]["find"] == "x"
    back = from_dicts(data)
    assert back == rules
    assert from_dicts([{"kind": "nope"}, {"kind": "insert", "text": "p", "bogus": 1}]) == [Insert(text="p")]
    assert all(isinstance(r.summary(), str) and r.summary() for r in rules)
    assert "/'x'" in rules[0].summary()


@pytest.mark.parametrize(
    "name, reason",
    [
        ("ok.txt", None), ("", "empty"), (".", ". or .."), ("a<b", "'<'"), ("a\x01b", "control"), ("a.", "dot or space"),
        ("a ", "dot or space"), ("CON", "reserved"), ("con.txt", "reserved"), ("LPT9.doc", "reserved"), ("CONS", None),
        ("x" * 256, "longer"), ("ünïcode.txt", None),
    ],
)
def test_validate_name(name, reason):
    got = validate_name(name)
    assert (got is None) if reason is None else (got is not None and reason in got)
