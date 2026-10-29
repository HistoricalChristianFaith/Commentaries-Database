#!/usr/bin/env python3
"""Extra checks for a fresh-translation import (see ../SKILL.md).

These complement process_jerome_commentary.py --check and audit_jerome_import.py; they are the
checks that were run by hand during the Ezekiel import (#37):

    python3 import_checks.py <Work> continuity   # BEFORE: do the headings follow on from each other?
    python3 import_checks.py <Work> boundaries   # BEFORE: lemma-only sections, sections not opening
                                                 #   with italics, and what opens each piece
    python3 import_checks.py <Work> pieces       # BEFORE: the pieces reassemble exactly into the source
    python3 import_checks.py <Work> notes        # BEFORE: every quotation in WORKS[<Work>]["notes"]
                                                 #   really occurs in the source
    python3 import_checks.py <Work> order        # AFTER: every file holds this work's blocks in
                                                 #   source order (pieces run out of sequence can break it)

<Work> is a key of WORKS in process_jerome_commentary.py (in this folder).
"""
import os
import re
import sys
import tomllib

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)
from process_jerome_commentary import (  # noqa: E402
    FATHER, PROJECT_DIR, SPLIT_CHARS, WORKS, _clean, _norm, load_work, make_units,
    paragraphs_of, source_url_for, unit_html, units_dir_for)
from audit_jerome_import import load_kjv, opening_lemma_end, paragraph_sections  # noqa: E402

HEAD_RE = re.compile(r"(\d+):(\d+)([a-d]?)(?:-(?:(\d+):)?(\d+)([a-d]?))?(?:\s*ff?\.)?")


def parse_heading(h):
    """'12:3b-5' -> ((12, 3, 'b'), (12, 5, '')); None if the heading isn't a verse reference."""
    h = re.sub(r"\s*\(Latin [^)]*\)", "", h)  # Hosea: "14:1-3 (Latin 14:2-4)"
    m = HEAD_RE.fullmatch(h.replace(",", "-").replace(" ", ""))
    if not m:
        return None
    c, v, s, c2, v2, s2 = m.groups()
    lo = (int(c), int(v), s)
    hi = (int(c2) if c2 else int(c), int(v2), s2) if v2 else lo
    return lo, hi


def follows(prev_hi, lo):
    """Does a section starting at `lo` follow on from one ending at `prev_hi`?"""
    pc, pv, ps = prev_hi
    c, v, s = lo
    if (c, v) == (pc, pv):                    # 7:12a -> 7:12b, 7:19c -> (7:19d)
        return bool(ps) and bool(s) and ord(s) == ord(ps) + 1
    if s and s != "a":                        # a new verse starting at its 'b' part
        return False
    return (c, v) == (pc, pv + 1) or (c == pc + 1 and v == 1)


def cmd_continuity(work, pre, secs):
    if work.get("lemma_paragraphs"):
        # Chapter headings only: check that the paragraph lemmas' guessed verses run forward.
        prev = None
        bad = 0
        for s in paragraph_sections(secs, load_kjv(work["book"])):
            if not s["chapter"]:
                continue
            cv = tuple(map(int, s["heading"].split(" ¶")[0].split(":")))
            if prev and cv < prev[1] and s["parent"] is prev[2]:
                print(f"  BACKWARDS: {prev[0]!r} -> {s['heading']!r} (score {s['score']:.2f}): "
                      f"{_clean(s['body'])[:80]!r}")
                bad += 1
            prev = (s["heading"], cv, s["parent"])
        print(f"{bad} backward step(s) in the guessed verses. (Usually a weak guess -- see "
              "audit --headings -- or the Vulgate's order, e.g. Matthew 5:4-5.)")
        return
    prev = None
    bad = 0
    for s in secs:
        if not s["chapter"]:
            continue
        rng = parse_heading(s["heading"])
        if not rng:
            print(f"  unparsed heading: {s['heading']!r}")
            continue
        if prev and not follows(prev[1][1], rng[0]):
            print(f"  DISCONTINUITY: {prev[0]!r} -> {s['heading']!r}")
            bad += 1
        prev = (s["heading"], rng)
    print(f"{bad} discontinuit{'y' if bad == 1 else 'ies'}. (A gap or overlap usually means a "
          "heading is off: compare that lemma's wording with the KJV.)")


def cmd_boundaries(work, pre, secs):
    lemmas = (paragraph_sections(secs, load_kjv(work["book"])) if work.get("lemma_paragraphs")
              else secs)
    for s in lemmas:
        if not s["chapter"]:
            continue
        body = s["body"].strip()
        rest = _clean(body[opening_lemma_end(body):])
        if len(rest) < 60:
            print(f"  lemma-only? [{s['heading']}]: {_clean(body)[:100]!r}")
        if not body.startswith("<i>"):
            print(f"  does not open with italics [{s['heading']}]: {_clean(body)[:100]!r}")
    print("\nWhat opens each piece (a piece must not start mid-lemma):")
    for u in make_units(pre, secs, SPLIT_CHARS):
        verse = [s for s in u["sections"] if s["chapter"]]
        first = verse[0] if verse else u["sections"][0]
        print(f"  {u['name']:<22} [{first['heading']}] {_clean(first['body'])[:70]!r}")


def cmd_pieces(work, pre, secs):
    units = make_units(pre, secs, SPLIT_CHARS)
    joined = [s for u in units for s in u["sections"]]
    ok = joined == secs
    sizes = [sum(len(s["html"]) for s in u["sections"]) for u in units]
    print(f"{len(units)} pieces; sections reassemble in order: {ok}; largest piece "
          f"{max(sizes)} chars (cap {SPLIT_CHARS}; a single bigger section stands alone)")
    d = units_dir_for(work_key)
    if os.path.isdir(d):
        body = ""
        for u in units:
            t = open(os.path.join(d, u["name"]), encoding="utf-8").read()
            if t != unit_html(pre, u):
                print(f"  {u['name']} on disk differs from what the importer would write")
            body += t[len(pre):].replace("</article>\n", "")
        print(f"units folder present; written pieces reassemble into the source: "
              f"{body == ''.join(s['html'] for s in secs)}")


# Text between quotation marks in the notes that is the note's own prose, not a quotation
# (nested quotes make the marks pair up wrongly, so every stretch between two marks is tried).
INSTRUCTION_RE = re.compile(r"->|--|\b(?:block|piece|section|file|KJV|heading|lemma|import|"
                            r"append|filed?|skip)\b", re.I)


def cmd_notes(work, pre, secs):
    src = _norm(" ".join(_clean(s["body"]) for s in secs))
    segs = work.get("notes", "").split('"')[1:-1]
    checked = missing = 0
    for q in segs:
        if re.fullmatch(rf"{re.escape(work['book'])} \d+_\d+(?:-\d+)?(?:_\d+)?", q):
            continue  # a filename
        for part in re.split(r"\s*(?:\.\.\.|…)\s*", q):
            part = _norm(part.strip(" .,;:()"))
            if len(part) < 12 or len(part) > 400:
                continue
            if part in src:
                checked += 1
            elif not INSTRUCTION_RE.search(part):
                checked += 1
                missing += 1
                print(f"  NOT IN SOURCE: {part!r}")
    print(f"{checked} quoted fragment(s) checked, {missing} not found. (Check each miss by eye: "
          "it may be a paraphrase that shouldn't be in quotation marks, or a KJV quotation.)")


def cmd_order(work, pre, secs):
    url = source_url_for(work)
    src = _norm(" ".join(" ".join(paragraphs_of(s)) for s in secs))
    folder = os.path.join(PROJECT_DIR, FATHER)
    bad = files = 0
    for fn in sorted(os.listdir(folder)):
        if not fn.endswith(".toml"):
            continue
        t = open(os.path.join(folder, fn), encoding="utf-8").read()
        if url not in t:
            continue
        files += 1
        pos = [src.find(_norm(c["quote"])) for c in tomllib.loads(t)["commentary"]
               if c.get("source_url") == url]
        if pos != sorted(pos):
            bad += 1
            print(f"  OUT OF SOURCE ORDER: {fn[:-5]} (block offsets {pos})")
    print(f"{files} files hold this work; {bad} out of order. (Reorder by cutting the file text "
          "into [[commentary]] blocks -- only in files that are new since BASE.)")


COMMANDS = {"continuity": cmd_continuity, "boundaries": cmd_boundaries, "pieces": cmd_pieces,
            "notes": cmd_notes, "order": cmd_order}

if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in WORKS or sys.argv[2] not in COMMANDS:
        sys.exit(__doc__)
    work_key = sys.argv[1]
    work = WORKS[work_key]
    pre, secs = load_work(work)
    COMMANDS[sys.argv[2]](work, pre, secs)
