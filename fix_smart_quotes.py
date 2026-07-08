#!/usr/bin/env python3
"""Replace unicode smart quotes with standard ASCII quotes in all .toml files."""

import os
import re
import sys

REPLACEMENTS = {
    "‘": "'",   # left single quotation mark
    "’": "'",   # right single quotation mark
    "‚": "'",   # single low-9 quotation mark
    "‛": "'",   # single high-reversed-9 quotation mark
    "“": '"',   # left double quotation mark
    "”": '"',   # right double quotation mark
    "„": '"',   # double low-9 quotation mark
    "‟": '"',   # double high-reversed-9 quotation mark
    "‹": "'",   # single left-pointing angle quotation mark
    "›": "'",   # single right-pointing angle quotation mark
    "«": '"',   # left-pointing double angle quotation mark «
    "»": '"',   # right-pointing double angle quotation mark »
}

TRANS = str.maketrans(REPLACEMENTS)


TITLE_RE = re.compile(
    r"""^(source_title)\s*=\s*(?:"(.*)""|"(.*)"|'(.*)')\s*$"""
)


def fix_source_titles(text: str) -> str:
    lines = text.split("\n")
    for i, line in enumerate(lines):
        m = TITLE_RE.match(line)
        if not m:
            continue
        key = m.group(1)
        value = m.group(2) if m.group(2) is not None else (m.group(3) if m.group(3) is not None else m.group(4))
        value = value.replace('"', "'")
        lines[i] = f'{key}="{value}"'
    return "\n".join(lines)


def fix_file(path: str) -> bool:
    with open(path, "r", encoding="utf-8") as f:
        original = f.read()

    fixed = original.translate(TRANS)
    fixed = fix_source_titles(fixed)

    if fixed != original:
        with open(path, "w", encoding="utf-8") as f:
            f.write(fixed)
        return True
    return False


def main():
    root = os.path.dirname(os.path.abspath(__file__))
    changed = 0
    scanned = 0

    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            if not name.endswith(".toml"):
                continue
            scanned += 1
            path = os.path.join(dirpath, name)
            if fix_file(path):
                changed += 1

    print(f"Scanned {scanned} files, fixed {changed}")


if __name__ == "__main__":
    main()
