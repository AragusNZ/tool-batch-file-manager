"""Scope: folder, depth, kinds and the name filter."""

from pathlib import Path

import pytest

from batch_file_manager.core.scan import ScopeSpec, scan


def names(paths: list[Path], root: Path) -> list[str]:
    return [p.relative_to(root).as_posix() for p in paths]


def test_top_level_files_only_by_default(tree: Path):
    assert names(scan(ScopeSpec(tree)), tree) == ["a.txt", "b.txt", "photo.JPG"]


def test_recurse_and_kinds(tree: Path):
    assert names(scan(ScopeSpec(tree, recurse=True)), tree) == [
        "Sub/Deep/d.txt", "Sub/c.TXT", "a.txt", "b.txt", "photo.JPG",
    ]
    assert names(scan(ScopeSpec(tree, recurse=True, kinds="folders")), tree) == ["Sub", "Sub/Deep"]
    assert names(scan(ScopeSpec(tree, kinds="both")), tree) == ["Sub", "a.txt", "b.txt", "photo.JPG"]


def test_glob_is_whole_name_and_case_insensitive_by_default(tree: Path):
    assert names(scan(ScopeSpec(tree, recurse=True, pattern="*.txt")), tree) == ["Sub/Deep/d.txt", "Sub/c.TXT", "a.txt", "b.txt"]
    assert names(scan(ScopeSpec(tree, recurse=True, pattern="*.txt", match_case=True)), tree) == ["Sub/Deep/d.txt", "a.txt", "b.txt"]
    assert scan(ScopeSpec(tree, pattern="a")) == []  # a glob must match the whole name


def test_regex_is_searched(tree: Path):
    assert names(scan(ScopeSpec(tree, pattern="^[ab]", regex=True)), tree) == ["a.txt", "b.txt"]
    assert names(scan(ScopeSpec(tree, pattern="jpg$", regex=True)), tree) == ["photo.JPG"]
    assert scan(ScopeSpec(tree, pattern="JPG$", regex=True, match_case=True)) == [tree / "photo.JPG"]


def test_bad_regex_and_bad_kind_raise(tree: Path):
    with pytest.raises(ValueError, match="invalid regex"):
        scan(ScopeSpec(tree, pattern="(", regex=True))
    with pytest.raises(ValueError, match="kinds"):
        scan(ScopeSpec(tree, kinds="everything"))


def test_symlinked_folders_are_listed_but_not_followed(tree: Path):
    (tree / "link").symlink_to(tree / "Sub", target_is_directory=True)
    found = names(scan(ScopeSpec(tree, recurse=True, kinds="both")), tree)
    assert "link" in found and "link/c.TXT" not in found
