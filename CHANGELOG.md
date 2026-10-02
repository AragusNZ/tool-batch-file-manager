# Changelog

All notable changes to this project are documented here, in
[Keep a Changelog](https://keepachangelog.com) format.

## [Unreleased]

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
- **Undo last rename** reverses the previous run, survives a restart, and undoing twice redoes.
- Light, dark and system themes; the window reopens where it was closed; the rule list is remembered.
- Update check against GitHub on start (**Help > Check on Startup** turns it off) and on demand.
- A folder passed on the command line or via **Send to > Batch File Manager** opens the app scoped to it.
