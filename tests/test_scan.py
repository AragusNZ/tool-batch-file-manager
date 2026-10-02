"""Scope: folder, depth, kinds and the name filter."""

import os
from pathlib import Path

import pytest

from batch_file_manager.core.scan import ScopeSpec, order_paths, scan


def names(paths: list[Path], root: Path) -> list[str]:
    return [p.relative_to(root).as_posix() for p in paths]


def test_top_level_files_only_by_default(tree: Path):
    assert names(scan(ScopeSpec(tree)), tree) == ["a.txt", "b.txt", "photo.JPG"]


def test_recurse_and_kinds(tree: Path):
    assert names(scan(ScopeSpec(tree, recurse=True)), tree) == [
        "a.txt", "b.txt", "photo.JPG", "Sub/c.TXT", "Sub/Deep/d.txt",
    ]
    assert names(scan(ScopeSpec(tree, recurse=True, kinds="folders")), tree) == ["Sub", "Sub/Deep"]
    assert names(scan(ScopeSpec(tree, kinds="both")), tree) == ["a.txt", "b.txt", "photo.JPG", "Sub"]


def test_glob_is_whole_name_and_case_insensitive_by_default(tree: Path):
    assert names(scan(ScopeSpec(tree, recurse=True, pattern="*.txt")), tree) == ["a.txt", "b.txt", "Sub/c.TXT", "Sub/Deep/d.txt"]
    assert names(scan(ScopeSpec(tree, recurse=True, pattern="*.txt", match_case=True)), tree) == ["a.txt", "b.txt", "Sub/Deep/d.txt"]
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


def test_exclude_drops_names_and_prunes_folders(tree: Path):
    assert names(scan(ScopeSpec(tree, exclude="*.jpg")), tree) == ["a.txt", "b.txt"]
    assert names(scan(ScopeSpec(tree, recurse=True, kinds="both", exclude="sub")), tree) == ["a.txt", "b.txt", "photo.JPG"]
    assert names(scan(ScopeSpec(tree, recurse=True, kinds="both", exclude="sub", match_case=True)), tree) == [
        "a.txt", "b.txt", "photo.JPG", "Sub", "Sub/c.TXT", "Sub/Deep", "Sub/Deep/d.txt",
    ]
    assert names(scan(ScopeSpec(tree, recurse=True, pattern="^[a-d]", exclude="^d", regex=True)), tree) == ["a.txt", "b.txt", "Sub/c.TXT"]
    assert names(scan(ScopeSpec(tree, exclude="   ")), tree) == ["a.txt", "b.txt", "photo.JPG"]
    with pytest.raises(ValueError, match="invalid regex"):
        scan(ScopeSpec(tree, exclude="(", regex=True))


def test_order_paths(tmp_path: Path):
    paths = []
    for i, name in enumerate(["IMG_10.jpg", "img_2.jpg", "b/IMG_1.jpg", "a.txt"]):
        p = tmp_path / name
        p.parent.mkdir(exist_ok=True)
        p.write_text("x")
        os.utime(p, (0, 1_700_000_000 - i))  # IMG_10 newest, a.txt oldest
        paths.append(p)
    assert names(order_paths(paths), tmp_path) == ["a.txt", "b/IMG_1.jpg", "IMG_10.jpg", "img_2.jpg"]
    assert names(order_paths(paths, "name"), tmp_path) == ["a.txt", "b/IMG_1.jpg", "img_2.jpg", "IMG_10.jpg"]
    assert names(order_paths(paths, "modified"), tmp_path) == ["a.txt", "b/IMG_1.jpg", "img_2.jpg", "IMG_10.jpg"]
    assert names(order_paths(paths, "modified", reverse=True), tmp_path) == ["IMG_10.jpg", "img_2.jpg", "b/IMG_1.jpg", "a.txt"]
    assert names(order_paths(paths, "nonsense"), tmp_path) == names(order_paths(paths), tmp_path)


def test_symlinked_folders_are_listed_but_not_followed(tree: Path):
    (tree / "link").symlink_to(tree / "Sub", target_is_directory=True)
    found = names(scan(ScopeSpec(tree, recurse=True, kinds="both")), tree)
    assert "link" in found and "link/c.TXT" not in found
