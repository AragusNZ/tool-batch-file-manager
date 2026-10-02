# batch-file-manager

**Project type:** python-tool

<!-- The marker line above is parsed by the wiring tool. Keep the exact format.
     Shipping status is NOT declared here — it lives in the SHIPPING_STATUS file,
     which is the only source of truth. A missing file reads as Shipped. -->

Conventions load automatically from `~/dev/ai-agents`:

- **Claude**: channel rules via `.claude/rules/`, skills/agents via the `python-tool@aragusnz` plugin.
- **Cursor**: rules, skills, agents and the guard via `.cursor/`.

Both are generated from one source; edit `~/dev/ai-agents`, never the delivered files.

## What this is

A Windows desktop tool for batch jobs on files and folders. The user picks a folder (optionally with its
subfolders, filtered by a name pattern) and a tool tab acts on everything in scope. The only tool so far is
**Rename**: an ordered list of rules, a live preview, conflict checking, two-phase apply and undo. PySide6
for the window; nothing but the standard library for the work. Distributed as a PyInstaller onedir build
wrapped in an Inno Setup installer, cut by the `release` workflow on a `v*` tag. Structure and build are
lifted from `~/tools/pdf-helper`.

`README.md` is user-facing only and `build.ps1` copies it into the shipped build, so nothing about building
or contributing belongs in it. `CONTRIBUTING.md` is the human long form of this file.

## Layout

```
batch_file_manager/
  app.py          the window: Folder panel, tool tabs, log, status bar, jobs on the worker, update check
  core/           pure Python, no Qt import anywhere
    scan.py       ScopeSpec + scan(): the items in scope
    rules.py      the rule dataclasses, apply_rules(), validate_name(), to_dicts()/from_dicts()
    plan.py       plan_renames() -> Planned rows; apply_renames() two-phase, deepest folder first; journal + undo
    update.py     GitHub latest-release check
  tools/rename.py the Rename tab: rule list, generic rule editor, preview table, Rename / Undo
  ui/             Qt only: scope panel, rule_editors (one form built from any rule dataclass), theme, worker, settings
  assets/         icon.ico and the SVGs it is generated from
tools/make_icon.py  regenerates assets/icon.ico from the SVGs
tests/            pytest, one file per core module plus test_app / test_rename_page / test_ui
packaging/batch-file-manager.iss  the Inno Setup installer, compiled by build.ps1
```

The exe is unsigned, so everything about the build that Windows reads as trust or as an antivirus heuristic
is deliberate: `--onedir` (not onefile), `--noupx`, the `--version-file` resource `build.ps1` generates from
`VERSION`, and `PrivilegesRequired=lowest` in the `.iss`. Do not undo one of those to shorten the build.

`VERSION` at the root is the only version source. `batch_file_manager/__init__.py` reads it and `build.ps1`
bundles it into the exe. Never hardcode it, and never bump it — a bump is the operator's `dt patch`.

## Adding a rule

1. Add a dataclass to `core/rules.py` with `kind`, `label`, `choices`, `hint` ClassVars, an `enabled` field,
   `apply(stem, ext, item) -> (stem, ext)` and `summary()`. Field types drive the editor: `bool` → checkbox,
   `int` → spin box, `str` → line edit, a name in `choices` → combo box. No UI code is needed.
2. Add it to `RULES` and the `Rule` union. It appears in the Add rule menu in that order.
3. Test it in `tests/test_rules.py`; the round-trip test covers every class in `RULES`.

## Adding a tool

A tool is a `QWidget` with `set_items(paths, root)` and a `job_requested(label, fn, done)` signal. `fn`
runs on the worker thread with `(log, progress, cancelled)` and must not touch Qt; `done` runs on the UI
thread afterwards, then the window rescans. Append `(label, cls)` to `TOOLS` in `app.py`.

## Conventions that bite

- **No Qt outside `ui/`, `tools/` and `app.py`.** `core/` is plain Python that runs headless under pytest.
- **Nothing is auto-renamed around a problem.** A conflicting or invalid new name disables Rename; the user
  fixes the rules. `fresh()`-style ` (2)` numbering does not exist here on purpose.
- **Renames are leaf-only and two-phase per directory**, deepest directory first. That one path handles
  swaps, case-only renames on NTFS, and folders whose children are also being renamed. Keep it that way.
- **The undo journal** is `%TEMP%\BatchFileManager-undo.json`, written after every Rename and every Undo.
- **Tracebacks go to `BatchFileManager.log`** in the system temp folder — the exe has no console.
- **Tests run offscreen.** `tests/conftest.py` sets `QT_QPA_PLATFORM=offscreen`, the `qapp` fixture is the
  single `QApplication`, and autouse fixtures clear QSettings and redirect the journal for every test.
- **The icon is generated.** After editing `icon.svg` or `icon-16.svg`, run `python tools/make_icon.py`.

## Verify

```
. .venv/bin/activate
pytest                     # the whole gate; --cov for a coverage report
```

CI fails under 95% coverage.

The exe is built with Windows Python (PyInstaller cannot cross-compile): `./build.sh` from WSL, or
`build.cmd` / `build.ps1` from Windows.
