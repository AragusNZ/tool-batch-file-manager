"""Infer a Find regex from the names in scope: group stems by shape, offer the commonest shapes as regexes."""

from __future__ import annotations

import re
from collections import Counter

_TOKEN = re.compile(r"\d+|[^\W\d_]+|.")


def _shape(tokens: list[str]) -> tuple[str, ...]:
    return tuple("D" if t.isdigit() else "A" if t.isalpha() else t for t in tokens)


def infer_patterns(stems: list[str], limit: int = 5) -> list[tuple[str, str, int]]:
    """``(regex, identity replacement, count)`` for the commonest name shapes, most common first.

    Digit runs are always captured, ``(\\d{4})`` when every name agrees on the width, else ``(\\d+)``.
    Letter runs are a literal when every name has the same word there, else a captured ``([A-Za-z]+)``.
    Everything else is an escaped literal. The replacement puts the groups back, so the rule starts as a
    no-op. Shapes seen only once are left out.
    """
    # ponytail: shape grouping; names with a different word count land in separate groups.
    tokenised = [_TOKEN.findall(s) for s in stems]
    groups: dict[tuple[str, ...], list[list[str]]] = {}
    for tokens in tokenised:
        groups.setdefault(_shape(tokens), []).append(tokens)
    counts = Counter({shape: len(members) for shape, members in groups.items() if len(members) > 1})
    return [_pattern(groups[shape]) + (n,) for shape, n in counts.most_common(limit)]


def _pattern(members: list[list[str]]) -> tuple[str, str]:
    regex, repl, group = [], [], 0
    for column in zip(*members):
        first = column[0]
        if first.isdigit():
            widths = {len(t) for t in column}
            group += 1
            regex.append(rf"(\d{{{widths.pop()}}})" if len(widths) == 1 else r"(\d+)")
            repl.append(rf"\{group}")
        elif first.isalpha() and len(set(column)) > 1:
            group += 1
            regex.append("([A-Za-z]+)" if all(t.isascii() for t in column) else r"([^\W\d_]+)")
            repl.append(rf"\{group}")
        else:
            regex.append(re.escape(first))
            repl.append(first.replace("\\", "\\\\"))
    return "^" + "".join(regex) + "$", "".join(repl)
