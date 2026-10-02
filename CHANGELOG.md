# Changelog

All notable changes to this project are documented here, in
[Keep a Changelog](https://keepachangelog.com) format.

## [Unreleased]

### Fixed

- Path order is the same on every platform: case-insensitive, a folder before its contents. It was
  case-sensitive on Linux and case-insensitive on Windows, which made the test suite fail on the Windows
  release build.

## [1.0.0] - 2026-10-02

### Fixed

- Controls no longer crop at smaller window sizes: the window's minimum now comes from its content
  instead of a fixed size, so the rule editor's fields and hint always get their full height.

### Changed

- Clearer layout: section headers sit above their cards, the tool tab has its own framed area, the
  Rename / Undo row lives inside the Preview card, and the rules / preview boundary is a draggable
  splitter that is remembered between runs. Up / Down are arrow buttons.
- The log pane is gone. A finished job reports its outcome in the status bar ("Renamed 12 item(s)");
  a failed one opens a dialog with the full list of what was and was not renamed under Show Details.
  The full transcript still goes to `BatchFileManager.log`, now one click away at **Help > Open Log
  File**.

### Added

- **Excluding** in the Folder panel: a second glob or regex that drops matching names, and skips a matching
  folder with everything inside it.
- **Presets** on the Rename tab: save the current rule list under a name, load it back, delete it.
- **Order** and **Reverse** over the preview — by path, natural name or date modified — so Numbering and
  `{n}` count in the order you want. **Hide unchanged** shows only rows that change or have a problem.
  Double-clicking a row opens its folder in Explorer.
- The installer adds **Open in Batch File Manager** to the right-click menu of folders (optional; under
  *Show more options* on Windows 11).
- First version. A **Folder** panel scopes every tool to one folder, optionally with subfolders, to files,
  folders or both, filtered by a glob or regex on the name.
- **Rename** tool: an ordered list of rules — Replace (text or regex), Name, Case, Remove, Spaces,
  Move / copy, Insert, Date, Folder name, Numbering, Extension and Template — with a live preview. Rows that
  would clash, overwrite an existing file or break Windows naming rules are shown in red and block the
  Rename button; nothing is renamed around a problem. Swaps and case-only renames work in one pass, and
  folders are renamed after the files inside them.
- **Detect pattern** on the Rename tab reads the names in scope and offers their commonest shapes as
  ready-made regexes, each with how many names it covers; picking one adds a Replace rule to edit.
- **Undo last rename** reverses the previous run, survives a restart, and undoing twice redoes.
- Light, dark and system themes; the window reopens where it was closed; the rule list is remembered.
- Update check against GitHub on start (**Help > Check on Startup** turns it off) and on demand.
- A folder passed on the command line or via **Send to > Batch File Manager** opens the app scoped to it.
