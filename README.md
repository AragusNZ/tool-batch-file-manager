# Batch File Manager

Small Windows desktop tool for batch jobs on files and folders. Pick a folder, build a list of rules, watch
the preview, press Rename. Undo if you change your mind.

No account, no upload: everything happens on your own machine. The only thing it asks the internet is
whether a newer version is out, and nothing about your files goes with it.

## Install

Download the latest **`BatchFileManager-<version>-setup.exe`** from
[Releases](https://github.com/AragusNZ/tool-batch-file-manager/releases) and run it.

- It installs per-user into `%LOCALAPPDATA%\Programs\Batch File Manager` and never asks for admin rights.
- Windows 10 or 11, 64-bit. Nothing else to install.
- Windows will warn about the publisher. That is expected, and [what to do](#windows-security-warnings) is
  below.
- `BatchFileManager-<version>.zip` is the same program as a plain folder, for a machine where installers
  are blocked. Unzip it anywhere and run `BatchFileManager.exe`.
- To update: on start it checks GitHub for a newer release and offers to open the download page.
  **Help > Check for Updates** asks any time; untick **Help > Check on Startup** to stop the automatic
  check. Run the new `setup.exe` over the top — it upgrades in place and keeps your settings.
- Right-click a folder in Explorer and choose **Send to > Batch File Manager** to open it straight away.
- To remove it: **Settings > Apps > Installed apps > Batch File Manager > Uninstall**.

Verify a download against `SHA256SUMS.txt` from the same release:

```
Get-FileHash .\BatchFileManager-<version>-setup.exe -Algorithm SHA256
```

## The folder

The **Folder** panel at the top decides what every tool works on.

- **Browse...** or drop a folder onto the panel.
- **Include subfolders** goes all the way down.
- **Apply to** — files, folders, or both. With *both* and subfolders on, a folder and the files inside it
  can be renamed in the same pass; the files go first, then the folder.
- **Only names matching** narrows the list: a glob like `*.jpg` or `IMG_????.*` (matching the whole
  name), or switch to **Regex** for a pattern searched anywhere in the name, like `^\d{4}-`. Both ignore
  case unless **Match case** is ticked.

The line underneath says how many items are in scope.

## Rename

Rules run top to bottom. **Add rule** opens the menu, each rule shows its own settings on the right, and
the preview updates as you type. Tick a rule off to skip it without deleting it; **Up** and **Down**
reorder. Your rule list is remembered between runs.

| Rule | What it does |
|---|---|
| **Replace** | Find text and replace it. Tick *Regex* for a regular expression; `\1` in the replacement is the first group. *Scope* picks the name, the extension or both. |
| **Name** | Keep, remove, set to fixed text, or reverse the whole name. |
| **Case** | lower, UPPER, Title, Sentence or iNVERT. *Exceptions* are words left exactly as typed, such as `of the NASA`. |
| **Remove** | Strip the first or last N characters, a range of positions, listed characters or words, all digits, all symbols, accents, leading dots; or crop everything before or after a piece of text. |
| **Spaces** | Trim, collapse double spaces, swap spaces for `_` or `-`, or put a space before capitals in `CamelCase`. |
| **Move / copy** | Move or copy N characters from one end of the name to the other. |
| **Insert** | Add text at the start, the end, or a position. |
| **Date** | Add the modified, created or accessed date, or today, in any `strftime` format: `%Y-%m-%d`, `%Y%m%d_%H%M`... |
| **Folder name** | Add the parent folder's name; *levels* 2 adds the grandparent too. |
| **Numbering** | Add a counter in preview order with a start, step and minimum digits; optionally restart in each folder. |
| **Extension** | Lower, upper or title-case the extension, set it, remove it or append another. |
| **Template** | Build the name from tokens: `{name}` `{ext}` `{n}` `{n:03}` `{parent}` `{date}` `{date:%Y%m%d}`. |

The preview lists every item in scope with its new name. Grey rows are unchanged. Red rows are problems —
hover for the reason — and the **Rename** button stays off until there are none:

- two items would end up with the same name;
- the new name is already taken by something not in this batch;
- the name is not allowed on Windows: `< > : " / \ | ? *`, a trailing dot or space, `CON`, `NUL`, `COM1`
  and friends, or longer than 255 characters.

Nothing is renamed around a problem for you. Fix the rules, then rename. Swapping two names (`a`↔`b`) and
changing only the case of a name both work in one pass.

**Rename** asks once, then does the lot. The status bar counts progress and **Cancel** stops after the
current folder. Each rename is written to the log pane; a file that could not be renamed is reported there
and the rest still go through.

**Undo last rename** puts everything from the last run back under its previous names, including the files
inside a folder that was renamed. Undo is remembered across restarts, and undoing an undo redoes it.

## Windows security warnings

The program is not code-signed, so Windows does not know the publisher yet:

- **SmartScreen** ("Windows protected your PC"): click **More info**, then **Run anyway**.
- A browser may say the download "isn't commonly downloaded": choose to keep it.

Check the `SHA256SUMS.txt` hash if you want certainty that the file is the one published.

## Problems

Errors show in red in the log pane. Full details go to `BatchFileManager.log` in your temp folder —
**Help > About** shows the exact path. Please attach it to a GitHub issue.

## Licence

MIT. See `LICENSE`.
