"""Platform-agnostic guard predicates, shared by the Claude and Cursor adapters.

This file is the single home for every hard block in this repo. It is COPIED, verbatim and
drift-linted, into each plugin's hooks/ dir by bin/cursor-build -- it is never imported
across directories. A marketplace `directory` install resolves ${CLAUDE_PLUGIN_ROOT}
wherever it lands the plugin, so the repo root is not a reliable ancestor; a sys.path hop
would be a bet on the install layout. A copy has no runtime dependency on layout at all.

The load-bearing change from the four guards this replaces: `deny()` no longer exists.
It used to be called from inside every predicate, which welded the Claude wire format and
sys.exit into the policy logic -- so no predicate could be reused across platforms or
tested at all. Predicates now RETURN a Deny; adapters decide what a Deny means on the wire.
That is what makes hooks/test_guard_core.py possible, and these regexes had no tests.

Guard sets are per channel and composed, not inherited. laravel-workspace must NOT
get laravel-core's bare-runner block -- there are no composer scripts above the packages, so
the block would have nothing to redirect to. Composition is what lets git_tag_release exist
once while that divergence stays deliberate.
"""

import json
import os
import re
import shlex
from dataclasses import dataclass


@dataclass(frozen=True)
class Call:
    """One normalized tool call. Built by the adapter; read by the predicates.

    Construct via `shell()` or `write()` -- they own the path normalization that was
    duplicated, identically, in three of the four guards.
    """
    kind: str          # "shell" | "write"
    cwd: str
    command: str = ""  # shell
    path: str = ""     # write -- repo-relative, forward slashes, already normalized
    content: str = ""  # write -- "" means THE PLATFORM DID NOT TELL US, not "empty file"


@dataclass(frozen=True)
class Deny:
    reason: str
    rule: str   # stable id, e.g. "release-boundary". Lets ai-agents-lint assert that every
                # guard reachable on one platform is reachable on the other.


@dataclass(frozen=True)
class Ask(Deny):
    """A verdict the OPERATOR resolves, not the agent -- adapters turn it into an
    interactive prompt instead of a block.

    A subclass rather than a field on Deny so every existing construction site is
    untouched and a mistyped decision string cannot exist. `check()` treats it exactly
    like a Deny (first verdict wins); only the two adapters care about the difference.
    `bare_composer_update` is the one guard that returns it: a bare `composer update` is
    sometimes exactly right, so the verdict is a redirect the operator can wave through,
    not a block.
    """


def shell(command: str, cwd: str = "") -> Call:
    return Call(kind="shell", command=command or "", cwd=cwd or os.getcwd())


def write(file_path: str, cwd: str = "", content: str = "") -> Call:
    """Normalize a write target to a repo-relative, forward-slashed path."""
    cwd = cwd or os.getcwd()
    try:
        rel = os.path.relpath(os.path.realpath(file_path), os.path.realpath(cwd))
    except ValueError:
        rel = file_path
    return Call(kind="write", path=rel.replace(os.sep, "/"), content=content or "", cwd=cwd)


# --- shipping status --------------------------------------------------------

def shipping_status(cwd):
    """Read the repo's SHIPPING_STATUS file.

    The file is the single source of truth, in BOTH tools -- for this guard, for the model
    (the `shipping-status` skill), and for `dt registry sync`, which derives
    the register's Shipping column from it. There is no marker and no second copy.

    This function needs no portability work and that is the point: it opens one plain file
    with no tool-specific path in it.

    A MISSING file means Shipped. This fails CLOSED, deliberately: the absent-file case gets
    the careful regime -- bootstrap migrations frozen -- rather than the permissive one. An
    unshipped repo states so explicitly; silence is not permission. Anything that is not
    exactly `Unshipped` reads as Shipped for the same reason: a typo, an empty file, or an
    unreadable one must not silently unlock the schema.
    """
    try:
        with open(os.path.join(cwd, "SHIPPING_STATUS"), encoding="utf-8") as fh:
            if fh.read().strip() == "Unshipped":
                return "Unshipped"
    except OSError:
        pass
    return "Shipped"


# --- project type -----------------------------------------------------------

def dev_tools_type(cwd):
    """The repo's declared project type, from .dev-tools/config.json.

    Read, never inferred. The type decides which `dt` surface a repo actually has, and a
    guard that guessed it from the directory layout would point a host at a `dt workspace`
    command that does not apply to it. Anything missing, unreadable or undeclared returns ""
    -- an absent declaration is not a package.
    """
    try:
        with open(os.path.join(cwd, ".dev-tools", "config.json"), encoding="utf-8") as fh:
            declared = json.load(fh).get("type")
    except (OSError, ValueError, AttributeError):
        return ""
    return declared if isinstance(declared, str) else ""


# --- shared predicates ------------------------------------------------------

_TAG_CREATE = re.compile(
    r"\bgit\s+tag\s+"
    r"(?!-l\b|--list\b|-n|--contains\b|--no-contains\b|--points-at\b|--sort\b"
    r"|--merged\b|--no-merged\b|-d\b|--delete\b)\S"
)
_TAG_PUSH = re.compile(r"\bgit\s+push\b[^;&|]*(--tags\b|--follow-tags\b|refs/tags/|\sv\d+\.\d+)")
_GH_RELEASE = re.compile(r"\bgh\s+release\s+(create|edit|delete|upload)\b")

# The release surface, spelled the way the CLI actually spells it (`dt workspace --help`,
# `dt git --help`). `dt workspace git release` has never existed -- the workspace subcommands are
# `git commit|version|rename` plus the `patch|minor|major` shorthands for `git version` -- but the
# name stays matched so a future alias cannot open a hole. `:laravel` / `:frontend` stack suffixes
# are accepted because `dt workspace:laravel git version` is the same command.
#
# `rewire` is that same pipeline with a headless session inserted before ci, so it commits, tags
# and pushes every package in the workspace and belongs here. Its read-only `--plan` is swept up
# with it deliberately: a carve-out would have to be right about where the flag sits in the line,
# and being wrong about that reopens the whole release surface to save the operator one command.
WORKSPACE_RELEASE_RE = (
    r"\bdt\s+workspace(?::\w+)?\s+((git\s+)?(version|release)|patch|minor|major|rewire)\b"
)
TOOLKIT_RELEASE_RE = (
    r"\bdt\s+(git\s+(version|release|github-release)|patch|minor|major)\b"
)


def git_tag_release(call):
    """Tag creation and GitHub releases are operator-only. Reads stay allowed.

    This block used to exist in THREE copies -- laravel-core, frontend-core, and
    laravel-workspace -- each carrying a comment saying "There is no mechanism to
    consolidate these -- do not try." That was true when a plugin could not import another.
    Copying the core into every plugin is the mechanism. It reached three copies while the
    comment said not to fix it, which is the argument, not against it.
    """
    if call.kind != "shell":
        return None
    c = call.command
    if _TAG_CREATE.search(c) or _TAG_PUSH.search(c) or _GH_RELEASE.search(c):
        return Deny(
            "Blocked: creating a tag or a GitHub release is operator-only. Say which "
            "command the user should run and stop. Reading tags is fine (`git tag -l`).",
            rule="release-boundary-tags",
        )
    return None


def composer_release(call):
    """`composer version:*|release` and the workspace orchestrator's release."""
    if call.kind != "shell":
        return None
    if re.search(r"\bcomposer\s+(version:(patch|minor|major)|release)\b", call.command) \
       or re.search(WORKSPACE_RELEASE_RE, call.command) \
       or re.search(TOOLKIT_RELEASE_RE, call.command):
        return Deny(
            "Blocked: version bumps and releases are operator-only. Say which command "
            "the user should run and stop.",
            rule="release-boundary-composer",
        )
    return None


def npm_release(call):
    if call.kind != "shell":
        return None
    if re.search(r"\bnpm\s+(version|publish)\b", call.command):
        return Deny(
            "Blocked: version bumps and publishes are operator-only. Say which command "
            "the user should run and stop.",
            rule="release-boundary-npm",
        )
    return None


# --- coding-core ------------------------------------------------------------

# A numbered release heading. `## [Unreleased]` is deliberately NOT matched -- writing
# bullets under it is ordinary work, and it is the only changelog edit an agent makes.
RELEASE_HEADING = re.compile(r"^##\s*\[?v?\d+\.\d+\.\d+", re.M)
# A semver `version` field in a manifest. Everything else in the file stays editable.
VERSION_FIELD = re.compile(r'"version"\s*:\s*"v?\d+\.\d+\.\d+')


def version_write(call):
    """The file-write half of release-boundary. The shell half blocks the release COMMANDS;
    this blocks writing their OUTPUT by hand, which achieves the same thing and did.

    Scoped to files that ALREADY EXIST, which is what keeps `scaffold` working -- a new
    package legitimately writes `VERSION` 0.1.0 and a fresh composer.json. The harm is
    bumping, not creating. CHANGELOG.md needs no such check: a fresh changelog carries only
    `## [Unreleased]`, so the heading pattern cannot fire on one.

    Why a guard and not the rule alone: `promote_changelog_unreleased` in dev-tools returns
    SUCCESS and changes nothing when `## [<ver>]` is already present, so an invented heading
    makes the operator's next real bump skip promotion SILENTLY and strand the notes.
    """
    if call.kind != "write":
        return None
    name = call.path.rsplit("/", 1)[-1]

    if name == "CHANGELOG.md":
        if not RELEASE_HEADING.search(call.content):
            return None
    elif name == "VERSION":
        if not os.path.exists(os.path.join(call.cwd, call.path)):
            return None
    elif name in ("composer.json", "package.json"):
        if not VERSION_FIELD.search(call.content):
            return None
        if not os.path.exists(os.path.join(call.cwd, call.path)):
            return None
    else:
        return None

    return Deny(
        "Blocked: version numbers are operator-only. `dt patch|minor|major` derives "
        "the next number from VERSION and writes the heading, the date, VERSION and the manifest's "
        "`version` field itself. A number written by hand names a release that does not "
        "exist, and the operator's next real bump then skips promotion silently. Add "
        "bullets under `## [Unreleased]` and stop; say which command the user should run.",
        rule="release-boundary-version-write",
    )


# --- laravel-core -----------------------------------------------------------

def bare_runners(call):
    """Bare runners skip the setup the composer scripts do, and the scripts are what CI runs.

    Deliberately does NOT match `composer test|stan|lint` -- the sanctioned paths do not
    contain these literal strings. test_guard_core.py pins that, because a guard that denies
    `composer test` makes the whole channel unusable and a positive-only test would pass.
    """
    if call.kind != "shell":
        return None
    if re.search(r"\bvendor/bin/(pest|phpunit|pint|phpstan)\b", call.command) \
       or re.search(r"(^|[;&|]\s*)phpunit\b", call.command):
        return Deny(
            "Blocked: this bypasses the setup the composer scripts do, and the "
            "scripts are what CI runs. Use `composer test` / `composer stan` / "
            "`composer lint` (filter tests with `composer test -- --filter Name`).",
            rule="bare-runners",
        )
    return None


_COMPOSER_UPDATE = re.compile(r"(^|[;&|]\s*)composer\s+update\b")
_DT_WORKSPACE = re.compile(r"\bdt\s+workspace(?::\w+)?\b")


def bare_composer_update(call):
    """A bare `composer update` in a workspace package writes no CHANGELOG entry for the bump.

    `dt workspace composer update <pkg>` runs the same composer command, then logs every
    registered aragusnz dependency whose locked version moved under `## [Unreleased]` >
    `### Internal`. Run composer directly and nothing records it -- which is how
    dependency-bump releases ended up with empty version headings.

    Ask, not Deny. `composer update laravel/framework` has nothing to do with workspace
    dependencies and is a fine thing to run; only the operator knows which this is. A block
    here would be wrong more often than right.

    Packages only. A host declares `laravel-host` in .dev-tools/config.json and has no
    `dt workspace` surface at all, so the redirect would name a command it does not have.
    """
    if call.kind != "shell":
        return None
    if not _COMPOSER_UPDATE.search(call.command):
        return None
    # `dt workspace composer update` contains the matched string and is the sanctioned path.
    if _DT_WORKSPACE.search(call.command):
        return None
    if dev_tools_type(call.cwd) != "laravel-package":
        return None
    return Ask(
        "This writes no CHANGELOG entry for the dependency bump. Use "
        "`dt workspace composer update <package>` from the workspace root -- it runs the "
        "same update, then logs every aragusnz dependency whose version moved under "
        "## [Unreleased] > ### Internal. Approve this only if the update targets a "
        "third-party dependency, where there is nothing to log.",
        rule="vendor-bump-changelog",
    )


def generated_openapi(call):
    if call.kind != "write":
        return None
    if re.search(r"(^|/)docs/openapi/openapi\.ya?ml$", call.path):
        return Deny(
            "Blocked: docs/openapi/openapi.yaml is generated -- an edit here is "
            "overwritten by the next build. Edit the sources under docs/openapi/ and "
            "run `composer dev openapi merge` (a host can run `composer dev openapi "
            "all` to lint and audit in the same pass).",
            rule="generated-openapi",
        )
    return None


def frozen_bootstrap_migrations(call):
    """Bootstrap `{AAAA}_*` migrations freeze once the repo reads as Shipped."""
    if call.kind != "write":
        return None
    if not re.match(r"^database/migrations/", call.path):
        return None
    if shipping_status(call.cwd) != "Shipped":
        return None
    base = os.path.basename(call.path)
    if not (re.match(r"^\d{4}_", base) and not re.match(r"^20\d{2}_", base)):
        return None
    # Name the missing file when that is the cause. Absence reads as Shipped, so without
    # this the block looks like a wrong verdict rather than a wrong repo.
    if not os.path.exists(os.path.join(call.cwd, "SHIPPING_STATUS")):
        return Deny(
            f"Blocked: this repo has no SHIPPING_STATUS file, which reads as Shipped, so "
            f"bootstrap migrations are frozen. `{base}` is a bootstrap `{{AAAA}}_*` "
            f"migration. If this repo is pre-production, create a SHIPPING_STATUS file "
            f"containing `Unshipped`. If it is live, create a dated migration instead. "
            f"See the `shipping-status` skill.",
            rule="frozen-bootstrap-migrations",
        )
    return Deny(
        f"Blocked: this repo is Shipped, so bootstrap migrations are frozen. `{base}` is a "
        f"bootstrap `{{AAAA}}_*` migration. Create a dated migration instead. See the "
        f"`shipping-status` skill.",
        rule="frozen-bootstrap-migrations",
    )


# --- laravel-host -------------------------------------------------------

def artisan_test(call):
    """Host-only: packages have no artisan, they run on Testbench."""
    if call.kind != "shell":
        return None
    if re.search(r"(^|[;&|]\s*|\bexec\s+\w+\s+)php\s+artisan\s+test\b", call.command):
        return Deny(
            "Blocked: this bypasses test isolation. Use `composer test` from the repo "
            "root (filter with `composer test -- --filter=Name`). It starts the test "
            "database, clears config cache, and applies the isolation env vars that "
            "`php artisan test` skips. See docs/reference/testing-isolation.md.",
            rule="artisan-test",
        )
    return None


# --- frontend-core ---------------------------------------------------------

def generated_css(call):
    """The token generators emit BOTH stylesheets and a TS module, so match on the
    `.generated.` marker rather than the extension -- a host's `colors-hex.generated.ts` is
    overwritten by the same command that overwrites its `theme-colors.generated.css`."""
    if call.kind != "write":
        return None
    if re.search(r"\.generated\.(css|ts)$", call.path):
        return Deny(
            "Blocked: this file is generated from the design tokens. Edit the source and "
            "run its generator: a colour in the host's `brands/semantic-colors.json`, then "
            "`npm run generate:theme` there; the spacing or type scale in `@aragusnz/utils` "
            "`src/tokens/scale.json`, then `npm run generate:css` in that repo.",
            rule="generated-css",
        )
    return None


def platform_bleed(call):
    """Tailwind and the `@/` alias are web-only and always a bug in React Native code.

    Two shapes carry that code: `apps/mobile/` in a host, and `src/mobile/` in a module
    package repo. Both are matched by path because both are unambiguously the mobile half
    of a repo that also holds web code.

    `src/mobile/` also covers the mobile kit, which lives in `@aragusnz/utils` beside the web
    kit. Widening this predicate to every `src/` would deny className in every web package.

    Content-based: the file path alone cannot reveal it. `not call.content` is the
    platform-did-not-tell-us case, and it must not be read as an empty file -- absent
    content means we have nothing to judge, so we allow rather than block blind.
    """
    if call.kind != "write" or not call.content:
        return None
    if not (call.path.startswith("apps/mobile/") or call.path.startswith("src/mobile/")):
        return None
    if re.search(r'className\s*=\s*["\'{]', call.content):
        return Deny(
            "Blocked: `className` is web-only. This is React Native — use StyleSheet "
            "with design tokens, and MobileButton/TextField from @aragusnz/utils/mobile. "
            "A Tailwind class in mobile code is always a bug.",
            rule="platform-bleed-classname",
        )
    if re.search(r'from\s+["\']@/', call.content) or re.search(r'import\s+["\']@/', call.content):
        return Deny(
            "Blocked: the `@/` alias does not exist in mobile code. Use a relative "
            "import, or `@aragusnz/*` for shared packages.",
            rule="platform-bleed-alias",
        )
    return None


# --- laravel-workspace ----------------------------------------------

def workspace_write(call):
    """`dt workspace git release|commit` write across every package repo in dependency order."""
    if call.kind != "shell":
        return None
    # `git` is optional so the pre-regroup bare form stays denied too, and `release` stays
    # matched although the CLI has no such subcommand -- a future alias must not open a hole.
    if re.search(WORKSPACE_RELEASE_RE, call.command) \
       or re.search(r"\bdt\s+workspace(?::\w+)?\s+(git\s+)?commit\b", call.command):
        return Deny(
            "Blocked: `dt workspace git version` (and its `patch|minor|major` shorthands) and "
            "`dt workspace git commit` are operator-only -- they write across every package repo "
            "in dependency order. Say which command the user should run and stop.",
            rule="release-boundary-workspace",
        )
    if re.search(TOOLKIT_RELEASE_RE, call.command):
        return Deny(
            "Blocked: `dt git version|release|github-release` and the `dt patch|minor|major` "
            "shorthands are operator-only -- they tag and release a single repo. Say which "
            "command the user should run and stop.",
            rule="release-boundary-toolkit",
        )
    return None


def per_package_release_at_root(call):
    """The per-package release commands, run from the root, name the wrong procedure."""
    if call.kind != "shell":
        return None
    if re.search(r"\bcomposer\s+(version:(patch|minor|major)|release)\b", call.command) \
       or re.search(r"\bnpm\s+(version|publish)\b", call.command):
        return Deny(
            "Blocked: version bumps and releases are operator-only. For workspace-wide work "
            "the command is `dt workspace git version`, not the per-package one -- say which "
            "the user should run and stop.",
            rule="release-boundary-workspace-per-package",
        )
    return None


def cross_repo_git(call):
    if call.kind != "shell":
        return None
    if re.search(r"\bgit\s+-C\s+\S+\s+(commit|push|tag|reset\s+--hard)\b", call.command) \
       or re.search(r"\bfor\b[^;]*\bin\b[^;]*\*/[^;]*;[^;]*\bgit\b[^;]*\b(commit|push)\b", call.command):
        return Deny(
            "Blocked: cross-repo commits from the workspace root. Each package folder is its "
            "own repo -- a root commit never covers a package change. Name the repo that owns "
            "the change and let the user commit it there.",
            rule="cross-repo-git",
        )
    return None


# A register cell holding a version (`1.7.12`) or a shipping status. These are the two
# generated columns; everything else in the row is hand-maintained.
GENERATED_CELL = re.compile(r"\|\s*(\d+\.\d+\.\d+|Shipped|Unshipped)\s*\|")


def generated_register_columns(call):
    """Scoped to the two generated columns, not the file.

    Tier, description, migration band and the notes are hand-maintained, and
    `onboard-package` adds a whole row -- blocking the path outright would break the
    workspace's own documented procedure.
    """
    if call.kind != "write":
        return None
    if not re.search(r"(^|/)\.packages-docs/PACKAGES_REGISTER\.md$", call.path):
        return None
    if not GENERATED_CELL.search(call.content):
        return None
    return Deny(
        "Blocked: the Version and Shipping columns of PACKAGES_REGISTER.md are "
        "generated -- `dt registry sync [packages…]` derives them from "
        "each package's composer.json and SHIPPING_STATUS, and overwrites a hand-edit "
        "on the next bump. Change the source, or run `dt registry sync`. Onboarding a "
        "package: leave those two cells as a placeholder and let sync fill them. The "
        "row's other columns are yours to edit.",
        rule="generated-register-columns",
    )


# --- global -----------------------------------------------------------------
# Not a channel guard. Wired once in ~/.claude/settings.json via hooks/rm_scope_guard.py, so
# it also covers ~ and unwired checkouts -- which is where an unscoped rm does the damage.

_SEPARATORS = {";", "&&", "||", "|", "&"}
_RUNTIME_EXPANSION = re.compile(r"[$`]")


def rm_scope(call):
    """`rm` is ordinary work inside the project and a disaster outside it.

    Returns "allow", a Deny, or None -- three states, not the Deny|None contract `check()`
    expects, so this sits outside GUARD_SETS and gets its own adapter. That is also why
    ai-agents-lint's plugin/GUARD_SETS parity is untouched: this guard has no channel.

    The ALLOW verdict is the load-bearing part. It replaces the blanket `Bash(rm -rf *)` deny
    that used to sit in permissions.deny, and it lives here rather than in permissions.allow
    on purpose: a hook that is missing, broken, or raising exits 0, so rm degrades to the
    normal permission prompt. An allow rule in settings would have degraded to silently
    permitted instead.

    ponytail: a token walk, not a shell parser. `rm` is only recognised in command position,
    so `xargs rm`, `find -exec rm`, and `sudo rm` fall through to the prompt rather than being
    judged; `$VAR` targets are denied rather than resolved. Every unhandled shape lands on
    "prompt" or "deny", never on "allow". Reach for bashlex only if that ever bites.
    """
    if call.kind != "shell" or not re.search(r"\brm\b", call.command):
        return None

    root = os.path.realpath(os.environ.get("CLAUDE_PROJECT_DIR") or call.cwd)
    if root == os.path.sep or root == os.path.realpath(os.path.expanduser("~")):
        return Deny(
            f"Blocked: this session is rooted at `{root}`, so there is no project boundary "
            f"for `rm` to stay inside. Run it yourself if you mean it.",
            rule="rm-scope",
        )

    # A project may name sibling checkouts it is allowed to delete inside -- set per project,
    # never globally, so an unwired checkout keeps the plain project boundary.
    roots = [root, *(
        os.path.realpath(os.path.expanduser(p))
        for p in os.environ.get("RM_SCOPE_EXTRA_ROOTS", "").split(os.pathsep) if p
    )]

    cwd, targets = os.path.realpath(call.cwd), 0
    for line in call.command.splitlines():
        try:
            tokens = shlex.split(line, comments=True)
        except ValueError as exc:
            return Deny(
                f"Blocked: this command contains `rm` and could not be parsed safely "
                f"({exc}). Split it into simpler commands.",
                rule="rm-scope",
            )
        mode, end_of_flags = "cmd", False
        for token in tokens:
            if token in _SEPARATORS:
                mode, end_of_flags = "cmd", False
            elif mode == "cmd":
                mode = {"rm": "rm", "cd": "cd"}.get(token, "args")
            elif mode == "cd":
                cwd = os.path.realpath(os.path.join(cwd, os.path.expanduser(token)))
                mode = "args"
            elif mode == "rm":
                if token == "--":
                    end_of_flags = True
                elif not end_of_flags and token.startswith("-"):
                    pass
                else:
                    verdict = _rm_target(token, cwd, roots)
                    if verdict:
                        return verdict
                    targets += 1

    # `rm` matched the regex but no target resolved -- an unhandled shape. Fall through to the
    # normal permission prompt rather than guessing in either direction.
    return "allow" if targets else None


# One topic file in a repo's own TODO folder, which may be another repo's. The standing exception
# in the `workspace-boundary` rule already lets any session write these; `todo-location` tells it
# to delete the file once its last item goes, so the delete has to be reachable too. Narrow on
# purpose: one `.md` leaf directly under `todo/`. The folder itself, the `config.json` beside it,
# `actions/`, and everything else in `.dev-tools/` stay on the ordinary boundary check.
_REPO_TODO_FILE = re.compile(r"/\.dev-tools/todo/[^/]+\.md$")


def _rm_target(token, cwd, roots):
    """A Deny if this `rm` target sits outside every root in `roots`, else None. realpath, so
    a symlink out of the project (a path-repository under vendor/, a workspace link under
    node_modules/) resolves to where it actually points. `roots[0]` is the project itself; any
    others came from RM_SCOPE_EXTRA_ROOTS. Each root guards its own top level -- naming one as
    the target is still the whole-checkout mistake, wherever it sits."""
    if _RUNTIME_EXPANSION.search(token):
        return Deny(
            f"Blocked: `rm` target `{token}` expands at runtime, so its real path cannot be "
            f"checked against the project boundary. Name the path literally.",
            rule="rm-scope",
        )
    target = os.path.realpath(os.path.join(cwd, os.path.expanduser(token)))
    if _REPO_TODO_FILE.search(target):
        return None
    for root in roots:
        if target == root:
            return Deny(
                f"Blocked: `{token}` resolves to the checkout root itself (`{root}`). That is "
                f"the whole repo -- name what inside it should go.",
                rule="rm-scope",
            )
        if target.startswith(root + os.sep):
            return None
    return Deny(
        f"Blocked: `{token}` resolves to `{target}`, outside the project (`{roots[0]}`). "
        f"`rm` is allowed inside the project only -- run it yourself if you mean it.",
        rule="rm-scope",
    )


# --- stash discipline --------------------------------------------------------
# In EVERY channel's guard set AND wired globally (~/.claude/settings.json via
# hooks/stash_guard.py), so unwired checkouts are covered too. Double coverage in a wired
# project is harmless -- same predicate, same verdict. Unlike rm_scope this returns only
# Deny|None, which is what makes GUARD_SETS membership safe: check() reads any non-None
# as a Deny.

_GIT_VALUE_FLAGS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}


def stash_discipline(call):
    """The stash list is shared mutable state across every agent in a checkout.

    An anonymous `git stash` cannot be recalled by name, and a bare `git stash pop` grabs
    whatever is on top -- possibly another agent's work. So: push must carry a message,
    pop/apply/drop must name an explicit ref, and `clear` (which wipes everyone's entries)
    is denied outright. `list`/`show` and non-stash git stay untouched.

    ponytail: a token walk like rm_scope, not a shell parser. `sudo git stash` and aliases
    fall through to the normal prompt; nothing unhandled lands on a quiet pass-through of a
    stash write.
    """
    if call.kind != "shell" or "stash" not in call.command:
        return None
    for line in call.command.splitlines():
        if "stash" not in line or "git" not in line:
            continue
        try:
            tokens = shlex.split(line, comments=True)
        except ValueError as exc:
            return Deny(
                f"Blocked: this command touches `git stash` and could not be parsed safely "
                f"({exc}). Split it into simpler commands.",
                rule="stash-discipline",
            )
        for args in _stash_invocations(tokens):
            verdict = _stash_verdict(args)
            if verdict:
                return verdict
    return None


def _stash_invocations(tokens):
    """Yield the argument list of each `git [flags] stash …` invocation in `tokens`."""
    mode, skip_value, current = "cmd", False, None
    for token in tokens:
        if token in _SEPARATORS:
            if current is not None:
                yield current
            mode, skip_value, current = "cmd", False, None
        elif current is not None:
            current.append(token)
        elif mode == "cmd":
            mode = "git" if token == "git" else "args"
        elif mode == "git":
            if skip_value:
                skip_value = False
            elif token == "stash":
                current = []
            elif token in _GIT_VALUE_FLAGS:
                skip_value = True
            elif token.startswith("-"):
                pass
            else:
                mode = "args"
    if current is not None:
        yield current


def _stash_verdict(args):
    action, rest = "push", args
    if args and not args[0].startswith("-"):
        action, rest = args[0], args[1:]
    if action == "clear":
        return Deny(
            "Blocked: `git stash clear` deletes every stash in this checkout, including "
            "other agents' work. Drop your own entries one at a time, by ref.",
            rule="stash-discipline",
        )
    if action in ("pop", "apply", "drop"):
        if any(t and not t.startswith("-") for t in rest):
            return None
        return Deny(
            f"Blocked: `git stash {action}` with no stash ref acts on whatever is on top -- "
            f"possibly another agent's stash. Run `git stash list`, find YOUR named entry, "
            f"then name that exact ref: `git stash {action} 'stash@{{n}}'` or "
            f"`git stash apply 'stash^{{/<slug>}}'`.",
            rule="stash-discipline",
        )
    if action in ("push", "save") and not _stash_named(action, rest):
        return Deny(
            "Blocked: unnamed stash. Agents share this checkout's stash list, and an "
            "anonymous entry cannot be recalled by name. Use "
            '`git stash push -m "<task-slug>"`.',
            rule="stash-discipline",
        )
    return None


def _stash_named(action, rest):
    if action == "save":
        return any(t and not t.startswith("-") for t in rest)
    prev = None
    for token in rest:
        if token.startswith("--message=") and len(token) > len("--message="):
            return True
        if prev in ("-m", "--message") and token:
            return True
        prev = token
    return False


# --- guard sets -------------------------------------------------------------
# Per unit, composed. Every unit in a project's stack is enabled at once and PreToolUse
# hooks compose, so a predicate belongs in the LOWEST unit where it is universally true --
# stated once there rather than repeated in each set above it. Adding a unit means adding a
# set here; the emitter and the parity lint both read this dict, so a unit with no set is
# loud rather than silent.
#
# The stack a project gets is `project-core` + the channel's declared `bases` + the channel
# (see units_of() in dev-tools' cmd/agents/py/_config_lib.py). Every entry below is reachable
# from every channel that needs it, by construction.

GUARD_SETS = {
    # Enabled in every wired project, whatever its channel. `stash_discipline` was repeated
    # in all five sets below; the stash list is shared mutable state in any repo, code or not.
    "project-core": [
        stash_discipline,
    ],
    # Every code channel, Laravel and frontend alike. `git_tag_release` was repeated in four
    # sets: tagging is operator-only in any code repo, and the rule that says so
    # (release-boundary) lives in this layer too.
    "coding-core": [
        git_tag_release,
        version_write,
    ],
    "laravel-core": [
        bare_runners,
        bare_composer_update,
        composer_release,
        generated_openapi,
        frozen_bootstrap_migrations,
    ],
    "laravel-host": [
        artisan_test,
    ],
    "frontend-core": [
        npm_release,
        generated_css,
        platform_bleed,
    ],
    "frontend-workspace": [
        npm_release,
        cross_repo_git,
    ],
    "laravel-workspace": [
        workspace_write,
        per_package_release_at_root,
        cross_repo_git,
        generated_register_columns,
    ],
}


def check(call, guards):
    """First Deny wins. None means nothing objected -- NOT that the call is approved;
    it proceeds through the platform's normal permission flow."""
    for guard in guards:
        verdict = guard(call)
        if verdict is not None:
            return verdict
    return None


# --- platform adapters ------------------------------------------------------
# The only platform-specific code in this file. Each plugin's guard.py is three lines that
# call one of these with its channel name -- there is no fifth copy of the payload parsing.
#
# ON FAILING OPEN. Both adapters catch Exception and let the call through, loudly, on stderr.
# That is deliberate and it is the mitigation for the plan's highest-damage risk: this file is
# copied into ~5 plugins across 33 repos, and on Cursor it runs with failClosed: true. Without
# the catch, one bad payload shape or one traceback denies EVERY write in EVERY session --
# a fleet-wide lockout from a typo. The existing guards already took this position for
# malformed JSON ("never break the session on a malformed payload"); this generalises it.
#
# The two mechanisms cover different failures and you need both: failClosed catches the hook
# not RUNNING; this catches it running BADLY. A guard that crashes is a guard that is absent,
# and an absent guard should be noisy, not fatal.


def _emit_and_exit(payload, code=0):
    import json as _json
    import sys as _sys
    _json.dump(payload, _sys.stdout)
    _sys.exit(code)


def _fail_open(exc, platform):
    import sys as _sys
    import traceback as _tb
    print(f"guard_core: {platform} adapter raised, failing OPEN -- {exc!r}", file=_sys.stderr)
    _tb.print_exc(file=_sys.stderr)
    _sys.exit(0)


def claude_main(channel):
    """PreToolUse adapter. Reads Claude's payload; emits hookSpecificOutput."""
    import json as _json
    import sys as _sys
    try:
        try:
            payload = _json.load(_sys.stdin)
        except (_json.JSONDecodeError, ValueError):
            _sys.exit(0)  # never break the session on a malformed payload

        tool = payload.get("tool_name", "")
        ti = payload.get("tool_input") or {}
        cwd = payload.get("cwd") or os.getcwd()

        if tool == "Bash":
            call = shell(ti.get("command", "") or "", cwd)
        elif tool in ("Edit", "Write", "NotebookEdit"):
            fp = ti.get("file_path") or ti.get("notebook_path") or ""
            if not fp:
                _sys.exit(0)
            # Write sends `content`; Edit sends `new_string`.
            call = write(fp, cwd, ti.get("content") or ti.get("new_string") or "")
        else:
            _sys.exit(0)

        verdict = check(call, GUARD_SETS.get(channel, []))
        if verdict:
            _emit_and_exit({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask" if isinstance(verdict, Ask) else "deny",
                "permissionDecisionReason": verdict.reason,
            }})
        _sys.exit(0)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 -- see ON FAILING OPEN above
        _fail_open(exc, "claude")


def claude_rm_main():
    """PreToolUse adapter for the global rm-scope guard. Bash only, three verdicts.

    Separate from claude_main because this one emits ALLOW. claude_main only ever denies --
    silence there means "nothing objected", which is not the same as "approved". Here silence
    and approval are genuinely different outcomes and the wire has to say which.
    """
    import json as _json
    import sys as _sys
    try:
        try:
            payload = _json.load(_sys.stdin)
        except (_json.JSONDecodeError, ValueError):
            _sys.exit(0)  # never break the session on a malformed payload

        if payload.get("tool_name") != "Bash":
            _sys.exit(0)

        command = (payload.get("tool_input") or {}).get("command", "") or ""
        verdict = rm_scope(shell(command, payload.get("cwd") or os.getcwd()))
        if verdict is None:
            _sys.exit(0)

        allowed = verdict == "allow"
        _emit_and_exit({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow" if allowed else "deny",
            "permissionDecisionReason": (
                "Every `rm` target resolves inside the project." if allowed
                else verdict.reason
            ),
        }})
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 -- see ON FAILING OPEN above
        _fail_open(exc, "claude-rm")


def claude_stash_main():
    """PreToolUse adapter for the global stash-discipline guard. Bash only, deny-only.

    Wired next to claude_rm_main's entry in ~/.claude/settings.json so stash discipline
    holds in ~ and unwired checkouts. In a wired project the channel's guard.py carries the
    same predicate; the two verdicts agree, so the overlap is harmless.
    """
    import json as _json
    import sys as _sys
    try:
        try:
            payload = _json.load(_sys.stdin)
        except (_json.JSONDecodeError, ValueError):
            _sys.exit(0)  # never break the session on a malformed payload

        if payload.get("tool_name") != "Bash":
            _sys.exit(0)

        command = (payload.get("tool_input") or {}).get("command", "") or ""
        verdict = stash_discipline(shell(command, payload.get("cwd") or os.getcwd()))
        if verdict:
            _emit_and_exit({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": verdict.reason,
            }})
        _sys.exit(0)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 -- see ON FAILING OPEN above
        _fail_open(exc, "claude-stash")


def guards_for(channels):
    """The composed guard list for one or more channels, order-preserving and de-duplicated.

    Cursor has ONE .cursor/hooks.json per project, so a wired project passes its base AND its
    channel here (e.g. laravel-core laravel-host) and both guard sets run from a single
    invocation. De-dup matters because git_tag_release is in three sets; without it a project
    on a channel that also carries it would run it twice.
    """
    seen, out = set(), []
    for ch in channels:
        for guard in GUARD_SETS.get(ch, []):
            if guard not in seen:
                seen.add(guard)
                out.append(guard)
    return out


def cursor_main(*channels):
    """Cursor adapter for preToolUse and beforeShellExecution. Channels come from argv.

    Two payload differences from Claude, both load-bearing:
      - beforeShellExecution puts `command` at the TOP LEVEL, not under tool_input.
      - the deny shape is {"permission": "deny"}, and blocking wants exit code 2.

    Shell guards route through beforeShellExecution rather than preToolUse+matcher Shell:
    it is the narrower documented event, it supports "ask", and -- the reason that decides
    it -- the open reports of deny being ignored are specifically about preToolUse on Write.
    The spike confirmed deny IS honoured for Write on this platform, but the split costs
    nothing and keeps the shell blocks off the historically contested path.
    """
    import json as _json
    import sys as _sys
    try:
        try:
            payload = _json.load(_sys.stdin)
        except (_json.JSONDecodeError, ValueError):
            _sys.exit(0)

        event = payload.get("hook_event_name") or payload.get("event") or ""
        cwd = payload.get("cwd") or (payload.get("workspace_roots") or [None])[0] or os.getcwd()

        if event == "beforeShellExecution" or payload.get("command"):
            call = shell(payload.get("command") or "", cwd)
        else:
            ti = payload.get("tool_input") or payload
            fp = ti.get("file_path") or ti.get("path") or ""
            if not fp:
                _sys.exit(0)
            call = write(fp, cwd, ti.get("content") or ti.get("new_string") or "")

        verdict = check(call, guards_for(channels))
        if isinstance(verdict, Ask):
            # `ask` is why the shell guards route through beforeShellExecution -- see above.
            _emit_and_exit({
                "permission": "ask",
                "agent_message": verdict.reason,
                "user_message": f"{verdict.rule}: needs your say-so",
            })
        if verdict:
            _emit_and_exit({
                "permission": "deny",
                "agent_message": verdict.reason,
                "user_message": f"Blocked by {verdict.rule}",
            }, code=2)
        _emit_and_exit({"permission": "allow"})
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 -- see ON FAILING OPEN above
        _fail_open(exc, "cursor")
