"""Batch File Manager - batch rename files and folders."""

from pathlib import Path

# The root VERSION file is the only version source. The exe carries it: build.ps1 passes
# --add-data VERSION, which lands it beside the bundled package in the unpack directory.
try:
    __version__ = (Path(__file__).resolve().parent.parent / "VERSION").read_text(encoding="utf-8").strip()
except OSError:  # VERSION not shipped alongside the package
    __version__ = "0.0.0"
