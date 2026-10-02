# Contributing

Batch File Manager is a Windows desktop tool built on PySide6. The window is Qt; everything that touches a
file is the Python standard library. It ships as a PyInstaller `--onedir` build wrapped in an Inno Setup
installer. The project structure, build and release pipeline are the same as
[pdf-helper](https://github.com/AragusNZ/tool-pdf-helper).

[README.md](README.md) is the user-facing half of this document. [AGENTS.md](AGENTS.md) is the same ground
compressed for coding agents.

## Run from source

Python 3.12. Linux/WSL works for development — you need WSLg for the window — but the exe can only be built
on Windows.

```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m batch_file_manager [folder]
```

On Windows: `py -3 -m venv .venv` and `.venv\Scripts\activate`, the rest is the same.

## Tests

```
pytest            # the whole gate
pytest --cov      # coverage report
```

CI fails under 95% coverage (`.github/workflows/check.yml`), so a new rule or module lands with its test.

Qt runs offscreen: `tests/conftest.py` sets `QT_QPA_PLATFORM=offscreen`, and the `qapp` fixture is the
single `QApplication` for the session. Never construct a second one. Two autouse fixtures keep tests out of
your real settings and undo journal: `_clean_settings` wipes the app's QSettings keys, `journal_file` points
the journal at a scratch file.

## Smoke test

`tools/smoke.py` holds `SCENARIOS`: each builds a scratch tree, scopes the real window to it, adds rules,
renames, checks where every file ended up, undoes, and checks the tree is back. The same list runs two ways:

```
python tools/smoke.py              # visible window under WSLg; pauses so you can watch each step
python tools/smoke.py -k swap      # only matching scenarios; --pause 0 runs flat out
pytest tests/test_scenarios.py     # offscreen, part of the gate
```

Every new rule, scope option or tool behaviour gets a `Scenario`. A scenario either names the expected
tree after the rename (`expect`) or the summary text that must block the Rename button (`blocked`).

## Layout

```
batch_file_manager/
  app.py          the window: Folder panel, tool tabs, log, status bar, jobs on the worker, update check
  core/           pure Python, no Qt import anywhere
    scan.py       ScopeSpec + scan(): the items in scope; order_paths() for the preview order
    rules.py      the rule dataclasses, apply_rules(), validate_name(), to_dicts()/from_dicts()
    plan.py       plan_renames() -> Planned rows; apply_renames() two-phase, deepest folder first; journal + undo
    update.py     GitHub latest-release check
    pattern.py    infer_patterns(): regex + identity replacement for the commonest name shapes in scope
  tools/rename.py the Rename tab: rule list, rule editor, preview table, Rename / Undo
  ui/             Qt only: scope panel, rule_editors, theme, worker, settings
  assets/         icon.ico and the SVGs it is generated from
tools/make_icon.py  regenerates assets/icon.ico from the SVGs
tools/smoke.py    end-to-end scenarios through the real window (see Smoke test)
tests/            pytest, one file per core module plus test_app / test_rename_page / test_ui / test_scenarios
packaging/batch-file-manager.iss  the Inno Setup installer, compiled by build.ps1
```

`core/` is importable from a script or a test with no Qt in sight; that separation is the point of the
split, not a stylistic preference.

## How a rename happens

1. `scan(ScopeSpec)` lists the items: one folder, optionally recursive, files/folders/both, leaf names
   filtered by a glob or regex, minus an exclude pattern in the same form (an excluded folder is not
   entered). `order_paths` then puts them in the preview order the Rename tab asked for.
2. `apply_rules(rules, items)` runs the enabled rules in order over every item and returns the new leaf
   names. Rules see `(stem, ext)`; a folder's whole name is its stem.
3. `plan_renames(paths, rules)` turns those into `Planned` rows with a status: `ok`, `unchanged`, `invalid`
   (Windows name rules, applied on every platform) or `conflict` (two rows want one name, or the name is
   taken on disk by something not in the batch — compared case-insensitively, as NTFS does). Any problem
   disables Rename. Nothing is ever auto-numbered around a clash.
4. `apply_renames(rows, ...)` groups `ok` rows by directory and works deepest directory first, so a folder
   moves only after its children have. Within a directory every source is renamed to a `~bfm-<uuid>` temp
   name, then to its target. That single path handles swaps (`a`↔`b`) and case-only renames without special
   cases. A failing row is logged and the batch continues; the count is raised at the end.
5. The journal — `(where it is now, where it was)` pairs, rebased when a parent folder moves — is written
   to `%TEMP%\BatchFileManager-undo.json`. `undo()` feeds it back through `apply_renames`, and writes its own
   journal, so Undo twice is Redo.

## Adding a rule

A rule is a dataclass in `core/rules.py`:

```python
@dataclass
class Reverse:
    kind: ClassVar[str] = "reverse"
    label: ClassVar[str] = "Reverse"           # the Add rule menu entry
    choices: ClassVar[dict] = {}               # field name -> options, for combo boxes
    hint: ClassVar[str] = "Reverse the name."  # one line above the form
    enabled: bool = True                       # the tick in the rule list

    def apply(self, stem: str, ext: str, item: Item) -> tuple[str, str]:
        return stem[::-1], ext

    def summary(self) -> str:                  # the rule list row
        return "Reverse"
```

Add it to `RULES` and the `Rule` union, and it gets a menu entry, an editor and persistence for free:
`ui/rule_editors.py` builds the form from the dataclass fields (`bool` → checkbox, `int` → spin box, `str`
→ line edit, a name listed in `choices` → combo box). Test it in `tests/test_rules.py`.

A rule that must see the whole batch — `Numbering` is the one case — gets special handling in
`apply_rules`; prefer a per-item `apply` when you can.

## Adding a tool

A tool is a `QWidget` with `set_items(paths: list[Path], root: Path)` and a
`job_requested = Signal(str, object, object)` emitting `(label, fn, done)`. `fn(log, progress, cancelled)`
runs on the worker thread and must not touch Qt; `done()` runs on the UI thread when it finishes, and the
window rescans the scope afterwards. Append `(label, cls)` to `TOOLS` in `app.py`. There is no base class
yet — add one when the second tool shows what they share.

## Conventions that bite

- **No Qt outside `ui/`, `tools/` and `app.py`.** Worker-thread code importing PySide6 widgets is the bug
  this layout exists to prevent.
- **Tracebacks go to `BatchFileManager.log`** in the system temp folder — the exe has no console, so an
  exception that only reaches stderr is an exception nobody ever sees.
- **The icon is generated.** After editing `batch_file_manager/assets/icon.svg` or `icon-16.svg`, run
  `python tools/make_icon.py` and commit `assets/icon.ico`.
- **Never hardcode or bump the version.** The root `VERSION` file is the only source; the package reads it
  and `build.ps1` bundles it. A bump is the operator's `dt patch`.
- **Record visible changes** in `CHANGELOG.md` under `## [Unreleased]`, in
  [Keep a Changelog](https://keepachangelog.com) form.

## Build the exe

Always built with Windows Python — PyInstaller cannot cross-compile.

- From WSL: `./build.sh`. It calls the Windows `py` launcher; the venv and build directory go to
  `%LOCALAPPDATA%\batch-file-manager`, because pip over `\\wsl.localhost` is unusably slow.
- From Windows: double-click `build.cmd`, or run `build.ps1`.

Inno Setup 6 builds the installer: `winget install JRSoftware.InnoSetup`. Without it the build still runs
and just skips that one step.

Output in `dist\`:

| File | What it is |
|---|---|
| `BatchFileManager\BatchFileManager.exe` + `_internal\` | the app itself, a `--onedir` build |
| `BatchFileManager-<version>-setup.exe` | the installer — what you hand to anyone else |
| `BatchFileManager-<version>.zip` | the same folder zipped, for a machine that cannot run an installer |
| `SHA256SUMS.txt` | checksums of both |

### Why the build looks the way it does

The exe is unsigned, so everything Windows reads as trust or as an antivirus heuristic is deliberate. Do
not undo one of these to shorten the build:

- **`--onedir`, not `--onefile`.** A onefile bootloader unpacks a Python runtime into `%TEMP%` on every
  launch, which is the PyInstaller behaviour antivirus flags hardest.
- **`--noupx`.** The other heuristic.
- **`--version-file`**, generated from `VERSION`. Without it the exe has no publisher string at all.
- **`PrivilegesRequired=lowest`** in `packaging/batch-file-manager.iss`. Per-user install, no UAC.
- **`AppId` in the `.iss` is fixed forever.** It is what makes the next version upgrade this one in place.

## Releasing

1. Bump `VERSION` — the operator's `dt patch`, not a hand edit in a feature PR.
2. Rename `## [Unreleased]` in `CHANGELOG.md` to `## [<version>] - <date>` and open a fresh
   `## [Unreleased]` above it.
3. Push a `v<version>` tag. `.github/workflows/release.yml` runs `pytest`, builds on a Windows runner and
   publishes the installer, zip and checksums as a GitHub release.

Never cut a release by copying `dist\` around: SmartScreen tracks reputation per file hash and per download
source, so a hand-copied exe starts from zero every time.

## Pull requests

- `pytest` green, coverage at or above 95%.
- A `CHANGELOG.md` entry under `## [Unreleased]` for anything a user would notice.
- No version bump in the diff.
- No new dependency for something the standard library already does. The runtime dependency list is
  PySide6 and nothing else; keep it that way unless a tool genuinely cannot be written without one.

## Licence

MIT, `Copyright (c) AragusNZ` — deliberately yearless, so there is nothing to bump. `build.ps1` stamps the
same wording into the exe's `LegalCopyright` field. Do not put a personal name or a year in either place.
