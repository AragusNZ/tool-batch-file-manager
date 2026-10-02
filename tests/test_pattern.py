"""infer_patterns: shapes, widths, literals, groups and the identity replacement."""

import re

from batch_file_manager.core.pattern import infer_patterns


def test_fixed_width_digits_and_constant_prefix():
    stems = ["IMG_0001", "IMG_0002", "IMG_0003", "notes"]
    assert infer_patterns(stems) == [(r"^IMG_(\d{4})$", r"IMG_\1", 3)]


def test_variable_width_digits_and_variable_words():
    stems = ["Holiday 2024 - Beach", "Holiday 2024 - Mountains", "Holiday 24 - Lake"]
    (regex, repl, n), = infer_patterns(stems)
    assert regex == r"^Holiday\ (\d+)\ \-\ ([A-Za-z]+)$" and repl == r"Holiday \1 - \2" and n == 3
    assert all(re.sub(regex, repl, s) == s for s in stems)


def test_unicode_letters_get_the_wide_class():
    (regex, repl, _), = infer_patterns(["café-1", "thé-2"])
    assert regex == r"^([^\W\d_]+)\-(\d{1})$" and re.sub(regex, repl, "café-1") == "café-1"


def test_singletons_dropped_ordering_and_limit():
    stems = ["a1", "a2", "x-1", "x-2", "x-3", "lonely"]
    got = infer_patterns(stems)
    assert [(r, n) for r, _, n in got] == [(r"^x\-(\d{1})$", 3), (r"^a(\d{1})$", 2)]
    assert len(infer_patterns(stems, limit=1)) == 1
    assert infer_patterns(["one", "two"]) == [(r"^([A-Za-z]+)$", r"\1", 2)]
    assert infer_patterns([]) == [] and infer_patterns(["solo"]) == []


def test_specials_are_escaped_in_the_regex_and_literal_in_the_replacement():
    stems = ["a&b (1)", "a&b (2)", "c.d\\1", "c.d\\2"]
    got = {r: p for r, p, _ in infer_patterns(stems)}
    assert got[r"^a\&b\ \((\d{1})\)$"] == r"a&b (\1)"
    assert re.sub(r"^c\.d\\(\d{1})$", got[r"^c\.d\\(\d{1})$"], "c.d\\1") == "c.d\\1"
