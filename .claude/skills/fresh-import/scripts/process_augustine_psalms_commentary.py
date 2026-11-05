#!/usr/bin/env python3
"""Import Augustine's Expositions on the Book of Psalms (the Oxford translation as abridged by
A. Cleveland Coxe, NPNF 1st series vol. 8, public domain) into the Commentaries-Database, one
psalm at a time, by driving a headless ``claude`` agent.

A per-work copy of process_augustine_commentary.py (see ../SKILL.md, "A homily series, one
file per sermon"): the same two-prompt flow, logs, --check and --order. Each of the 150
expositions is its own file in the Writings-Database, named by the English (KJV) psalm number,
with its own url, so each is its own WORKS entry ("PsExp001" .. "PsExp150"):

    Writings-Database/Augustine of Hippo/ON THE PSALMS/Psalm 31.html

    <article class="writing"><h1>Psalm 31<sup>..fn1..</sup></h1>   (fn1: "Lat. XXX." and the
                                                                  occasion: "A sermon to the people.")
    <i>To the end, a psalm of David himself, an ecstasy.</i><br/><br/>   (the psalm's title, if any)
    1. To the end a Psalm of David Himself, ...<br/><br/>
    2. "In Thee, O Lord, have I trusted, ..." (ver. 1). ...      (numbered paragraphs; the
                                                                  translators' "(ver. N)" marks
                                                                  give the KJV verse numbers)
    <section class="notes">...                                    (the editors' notes)

The source was rebuilt from CCEL's NPNF 1-08 text and proofread against the 1886 print just
before this import (Writings-Database 938841f3).

``load_work`` returns one section per PIECE. A psalm is one piece up to SPLIT_CHARS (html with
the notes inline); a longer one is cut into balanced pieces at the editors' headings (Psalm
119's Hebrew letters, the "Second Part" headings of Psalms 37, 49 and 59) or, failing that, at
paragraph boundaries. Each section is headed by the KJV range its "(ver. N)" marks span
("37:12-26"; the first piece starts at verse 1, the last ends at the psalm's last verse); the
heading is a hint for the audit only. The NPNF paragraph numbers are dropped (as in the
Tractates); the editors' headings are shown to the agent as ``<h2>`` and dropped from the body;
the notes are shown inline as ``<sup>[note: ...]</sup>`` and dropped from the body. The psalm's
title line (the inscription as Augustine read it) is text: it opens the first block.

    python3 process_augustine_psalms_commentary.py PsExp001 --dry-run
    python3 process_augustine_psalms_commentary.py PsExp001
    python3 process_augustine_psalms_commentary.py PsExp002-PsExp030   # a chunk: one after another
    python3 process_augustine_psalms_commentary.py PsExp001-PsExp150 --check
    python3 process_augustine_psalms_commentary.py PsExp001 --order          # all files: psalm order
    python3 process_augustine_psalms_commentary.py PsExp001 --fix-order BASE # ... and fix it
"""

import argparse
import html
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import tomllib
import unicodedata
from datetime import datetime
from urllib.parse import quote

# --- Paths --------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# These scripts live in <Commentaries-Database>/.claude/skills/fresh-import/scripts.
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
# The claude agent runs here so the Commentaries-Database CLAUDE.md conventions apply
# and its relative `<Father>/<Book Verse>.toml` writes land in the right tree.
PROJECT_DIR = os.path.abspath(os.path.join(SKILL_DIR, "..", "..", ".."))
BOOK_NAMES_PATH = os.path.join(PROJECT_DIR, "book_names.json")
# The Writings-Database checkout: $WRITINGS_DB, else a sibling of the Commentaries-Database.
WRITINGS_DIR = os.environ.get("WRITINGS_DB") or os.path.join(
    os.path.dirname(PROJECT_DIR), "Writings-Database")
# Units and run logs go here (gitignored), not next to the scripts.
WORK_DIR = os.path.join(SKILL_DIR, "work")
# KJV lookup for the agent, run from PROJECT_DIR.
KJV_LOOKUP = 'python3 .claude/skills/fresh-import/scripts/kjv_lookup.py "<Book> <C>:<V>"'
KJV_DB = os.path.join(SCRIPT_DIR, "kjv.sqlite")

FATHER = "Augustine of Hippo"

# A psalm longer than this (html chars, the inline notes included) is cut into pieces.
SPLIT_CHARS = 36000

RETRY_DELAYS = [5, 15, 45]
RATE_LIMIT_DELAYS = [60, 120, 240]

# --- Per-work configuration ---------------------------------------------------

PSALMS_DIR = "Augustine of Hippo/ON THE PSALMS"

# Psalms whose opening italic line is an editors' rubric, not the psalm's title: it is shown to
# the agent as a heading and not imported.
RUBRIC_OPENINGS = {37, 41, 49, 59}


def _last_verse(chapter):
    db = sqlite3.connect(KJV_DB)
    (n,) = db.execute("select max(txt_location) from bible_kjv where book='psalms' and "
                      "txt_location between ? and ?", (chapter * 1000000,
                                                       chapter * 1000000 + 999)).fetchone()
    return n % 1000000


# Notes for every psalm (in the prompt), then each psalm's own.
COMMON_NOTES = ""
PSALM_NOTES = {
    1: ("This is the first exposition; it begins straight with verse 1 (it has no title "
        "line)."),
    10: ("The Latin Bible joins KJV Psalms 9 and 10 into one psalm (its Psalm 9); this "
         "exposition is of KJV Psalm 10 (\"Why, O Lord, ... hast Thou withdrawn afar off?\"), "
         "and its \"(ver. N)\" marks restart at 1, as in the KJV. It has no title line."),
    37: ("This exposition is three sermons, on three parts of the psalm, under the editors' "
         "headings \"On the First Part of the Psalm.\", \"On the Second Part of the Psalm.\" "
         "and \"On the Third Part of the Psalm.\" (shown as <h2>; not imported). Each part "
         "starts its own block."),
    41: ("The italic line at the top, \"To the people, on the Feast of the Martyrs.\", is an "
         "editors' rubric (shown as <h2>), not the psalm's title: leave it out. After its opening "
         "on the martyrs' day the sermon starts from a verse sung as the antiphon (\"Mine "
         "enemies speak evil of Me\", ver. 5) before going back to verse 1: place it by what it "
         "expounds."),
    49: ("This exposition is two sermons, under the editors' headings \"The First Part.\" and "
         "\"The Second Part.\" (shown as <h2>; not imported). Each part starts its own block."),
    59: ("This exposition is two sermons, under the editors' headings \"The First Part.\" and "
         "\"The Second Part.\" (shown as <h2>; not imported). Each part starts its own block."),
    108: ("Augustine gives no full exposition of this psalm: it is made of the last part of "
          "Psalm 57 (KJV 57:7-11 = 108:1-5) and the last part of Psalm 60 (KJV 60:5-12 = "
          "108:6-13), already expounded there, and he compares the wordings. File each stretch "
          "under the Psalm 108 verse(s) it discusses; a comparison that genuinely expounds a "
          "verse of Psalm 57 or 60 may also go under that verse."),
    119: ("This long psalm is imported in five pieces, each a run of its Hebrew-letter "
          "sections; the letter headings (\"Aleph.\", \"Beth.\", ...) are the editors' (shown "
          "as <h2>; not imported), and each letter section starts its own block. Augustine's "
          "preface to his sermons on this psalm survives only in the editor's note on the title "
          "(not imported)."),
    150: ("This last exposition opens on the number and arrangement of the Psalms (\"Although "
          "the arrangement of the Psalms, which seems to me to contain the secret of a mighty "
          "mystery, hath not yet been revealed unto me\"): that opening stays at the start of "
          "the first block, in \"Psalms 150_1\"."),
}

WORKS = {
    f"PsExp{n:03d}": {
        "html": f"{PSALMS_DIR}/Psalm {n}.html",
        "book": "Psalms",
        "homily": True,
        "number": n,
        # As the url'd blocks of the old import already had it ("Exposition on Psalm 31").
        "source_title": f"Exposition on Psalm {n}",
        "passage": f"{n}:1-{_last_verse(n)}",
        "notes": PSALM_NOTES.get(n, ""),
    }
    for n in range(1, 151)
}


def source_url_for(work):
    """historicalchristian.faith url for a Writings-Database file. Every segment, the father
    folder included, is double-encoded (spaces as %2520), with %2F between segments, matching
    the existing urls ("file=Augustine%2520of%2520Hippo%2FON%2520THE%2520PSALMS%2FPsalm%252031.html")."""
    segs = work["html"].split("/")
    return ("https://historicalchristian.faith/by_father.php?file="
            + "%2F".join(quote(seg, safe="").replace("%", "%25") for seg in segs))


def units_dir_for(work_key):
    return os.path.join(WORK_DIR, f"augustine_{work_key.lower()}_units")


# --- Parsing ------------------------------------------------------------------

TAG_RE = re.compile(r"<[^>]+>")
FOOTNOTE_REF_RE = re.compile(r'<sup><a href="#fn(\d+)" id="r\d+">\d+</a></sup>')
NOTES_RE = re.compile(r'<section class="notes">(.*?)</section>\s*', re.S)
NOTE_RE = re.compile(r'<span id="fn(\d+)"><a href="#r\d+">\d+</a>(?:&nbsp;|\s)*(.*?)</span>', re.S)
H2_RE = re.compile(r"(<h2>.*?</h2>)\n?")
PARA_SPLIT_RE = re.compile(r"<br/><br/>\n?")
# A paragraph made only of italic runs and note marks: the psalm's title, or an editors' heading.
ITALIC_PARA_RE = re.compile(r"(?:\s*<i>[^<]*</i>\s*(?:<sup><a [^>]*>\d+</a></sup>)?)+\s*")
# An NPNF paragraph number opening a paragraph ("2. ", "176. ", "1. …").
PARA_NO_RE = re.compile(r"^\s*\d{1,3}\.\s*")
VER_RE = re.compile(r"\(ver\.?\s*(\d+)")
SEP = "<br/><br/>\n"


def _clean(s):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub("", s))).strip()


def _notes(text):
    m = NOTES_RE.search(text)
    return {int(k): _clean(t) for k, t in NOTE_RE.findall(m.group(1))} if m else {}


def _hinted(s, notes):
    return FOOTNOTE_REF_RE.sub(
        lambda r: (f"<sup>[note: {html.escape(notes[int(r.group(1))], quote=False)}]</sup>"
                   if int(r.group(1)) in notes else ""), s)


def _atoms(work):
    """The psalm as a list of atoms: ("heading", html) for an editors' heading (shown to the
    agent, not imported), ("para", html, body) for a paragraph of text (the psalm's title line
    included). Returns (preamble, atoms)."""
    path = os.path.join(WRITINGS_DIR, work["html"])
    with open(path, encoding="utf-8") as f:
        text = f.read()
    notes = _notes(text)
    text = NOTES_RE.sub("", text).replace("</article>", "")
    head_end = text.index("</h1>") + len("</h1>")
    preamble = _hinted(text[:head_end], notes) + "\n"
    atoms = []
    for chunk in H2_RE.split(text[head_end:]):
        if not chunk.strip():
            continue
        if H2_RE.fullmatch(chunk.strip()):
            atoms.append(("heading", chunk.strip()))
            continue
        for p in PARA_SPLIT_RE.split(chunk.strip()):
            p = p.strip()
            if not p:
                continue
            if ITALIC_PARA_RE.fullmatch(p) and (atoms or work["number"] in RUBRIC_OPENINGS):
                atoms.append(("heading", f"<h2>{_hinted(p, notes)}</h2>"))
                continue
            p = PARA_NO_RE.sub("", p)
            atoms.append(("para", _hinted(p, notes), FOOTNOTE_REF_RE.sub("", p)))
    return preamble, atoms


def _cut_points(sizes, k):
    """Indexes (into `sizes`) at which to start pieces 2..k, nearest to equal shares."""
    total, acc, cuts = sum(sizes), 0, []
    ends = []
    for s in sizes:
        acc += s
        ends.append(acc)
    for j in range(1, k):
        goal = total * j / k
        i = min(range(1, len(sizes)), key=lambda i: abs(ends[i - 1] - goal))
        if i not in cuts and (not cuts or i > cuts[-1]):
            cuts.append(i)
    return cuts


def _groups(atoms):
    """Atoms grouped at the editors' headings: each group opens with its heading(s)."""
    groups = []
    for a in atoms:
        if a[0] == "heading" and groups and groups[-1][-1][0] != "heading":
            groups.append([a])
        elif not groups:
            groups.append([a])
        else:
            groups[-1].append(a)
    return groups


def _atom_html(a):
    return a[1] + "\n" if a[0] == "heading" else a[1] + SEP


def _split(atoms, cap):
    """Cut the atoms into pieces of at most `cap` html chars: at the editors' headings if that
    can work, else at paragraph boundaries (a heading stays with the paragraph after it)."""
    size = lambda grp: sum(len(_atom_html(a)) for a in grp)
    if size(atoms) <= cap:
        return [atoms]
    groups = _groups(atoms)
    if len(groups) > 1 and all(size(g) <= cap for g in groups):
        units = groups
    else:
        units, pending = [], []     # paragraphs, each with any headings before it
        for a in atoms:
            if a[0] == "heading":
                pending.append(a)
            else:
                units.append(pending + [a])
                pending = []
        if pending:
            units[-1] += pending
    sizes = [size(u) for u in units]
    for k in range(math.ceil(sum(sizes) / cap), len(units) + 1):
        cuts = [0] + _cut_points(sizes, k) + [len(units)]
        pieces = [sum(units[a:b], []) for a, b in zip(cuts, cuts[1:])]
        if all(size(p) <= cap for p in pieces):
            return pieces
    raise SystemExit("can't cut the psalm into pieces under the cap")


def load_work(work):
    """Return (preamble_html, sections): one section per piece (see the module docstring)."""
    n = work["number"]
    preamble, atoms = _atoms(work)
    pieces = _split(atoms, SPLIT_CHARS)
    last = _last_verse(n)
    sections, prev_hi = [], 1
    for i, p in enumerate(pieces):
        html_ = "".join(_atom_html(a) for a in p)
        body = SEP.join(a[2] for a in p if a[0] == "para")
        vs = [int(v) for v in VER_RE.findall(body) if 1 <= int(v) <= last]
        lo = 1 if i == 0 else (min(vs) if vs else prev_hi)
        hi = last if i == len(pieces) - 1 else (max(vs) if vs else lo)
        hi = max(hi, lo)
        prev_hi = hi
        name = f"Ps{n:03d}" + (chr(ord("a") + i) if len(pieces) > 1 else "") + ".html"
        sections.append({
            "heading": f"{n}:{lo}" + (f"-{hi}" if hi != lo else ""),
            "chapter": n,
            "piece": name,
            "part": (i + 1, len(pieces)),
            "html": html_,
            "body": body,
        })
    return preamble, sections


def paragraphs_of(section):
    """Plain-text paragraphs of a section (for the check)."""
    out = []
    for p in re.split(r"(?:<br\s*/?>\s*){2,}", section["body"]):
        p = _clean(p)
        if p:
            out.append(p)
    return out


def make_units(preamble, sections, cap):
    """One piece per section ("Ps031.html", or "Ps119a.html" .. for a psalm cut in pieces)."""
    return [{"name": s["piece"], "chapter": s["chapter"], "sections": [s]} for s in sections]


def unit_html(preamble, unit):
    tail = "</article>\n" if "<article" in preamble else ""
    return preamble + "".join(s["html"] for s in unit["sections"]) + tail


def write_units(work_key, preamble, units):
    d = units_dir_for(work_key)
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d)
    for u in units:
        with open(os.path.join(d, u["name"]), "w", encoding="utf-8") as f:
            f.write(unit_html(preamble, u))
    return d


# --- Prompts ------------------------------------------------------------------

PROMPT1_TEMPLATE = (
    "We have Augustine's Expositions on the Book of Psalms here: 150 expositions, one per psalm, "
    "each a file of its own (most are sermons preached to the people; some were dictated). This "
    "piece is the exposition of Psalm {number}{part_label}, \"{units_dir}/{unit_name}\", cut from "
    "our PUBLIC-DOMAIN English translation (the Oxford translation as abridged in NPNF 1st "
    "series vol. 8), \"{html_path}\" (consult it if you need surrounding context; the other "
    "psalms are in the same folder). File everything under the book \"{book}\", in the "
    "\"{father}/\" folder.\n\n"
    "{part_note}"
    "Your task is to process the following file:\n"
    "{unit_name}  (Psalm {number}; the \"(ver. N)\" marks in this piece span {heading})\n\n"
    "Read the WHOLE file and import its commentary IN FULL into our commentaries db. The piece "
    "repeats the psalm's title at the top, with the editors' note on it (the Latin number, the "
    "occasion of the sermon) -- that is background for you, not commentary; don't import it.\n\n"
    "VERSE KEYS. Augustine works through his psalm, quoting each verse (or part of a verse) as "
    "he reaches it and expounding it, often with digressions (on the Donatists, the Pelagians, "
    "the martyrs, other Scripture) that arise from the verse in hand. The translators mark the "
    "verses they quote with \"(ver. N)\", using the English (KJV) verse numbers of this psalm: "
    "they are good guides, but place each stretch by what its COMMENTARY expounds, checking the "
    "wording against the KJV with `" + KJV_LOOKUP + "`. Augustine's psalter is translated from "
    "the Greek, so its wording often differs from the KJV's (\"the seat of pestilence\", \"Thou "
    "despisest in due seasons\"): find the KJV verse that corresponds. A digression goes with "
    "the verse it arises from. THE TITLE. Many expositions open with the psalm's title as "
    "Augustine read it, printed in italics (\"To the end, a psalm of David himself.\"), and "
    "then explain it: the title line is part of the text and stays at the start of the first "
    "block. Commentary on the title goes under verse 1 of the KJV psalm (\"Psalms 31_1\"; the "
    "KJV prints the title above verse 1 without a number), as a block of its own or together "
    "with the verse-1 commentary that follows it. The editors' notes are shown inline as "
    "\"[note: ...]\" in superscript after the words they refer to: Scripture references in the "
    "English numbering (\"[note: Ps. xxx. 11.]\" = Psalms 30:11), variant readings, and the "
    "editor's remarks in square brackets ending \"--C.\" (some quote sentences of Augustine that "
    "this edition leaves out of the text); they are hints, not text to import.{notes}\n\n"
    "Wherever possible, we want to use smaller verse ranges / individual verses. Do NOT simply "
    "file the exposition under its whole psalm: break it up wherever the exposition moves from "
    "one verse to the next, e.g. if a stretch comments on 31:5, insert it in \"Psalms 31_5\", "
    "not in \"Psalms 31_1-24\". It's ok to use a range if necessary to avoid breaking up a "
    "coherent thought/piece (Augustine sometimes expounds several verses as one argument, or "
    "comes back to a verse to draw out another sense), just prefer smaller ranges/individual "
    "verses -- but don't chop the exposition into tiny fragments either. The sermon's opening "
    "(a word to the hearers, a remark about the psalm just sung) stays at the start of the "
    "first block; its close (an exhortation, a prayer, \"Turning to the Lord...\") stays at the "
    "end of the last block. When you split the piece, its blocks together must still contain "
    "the WHOLE of it, every word -- and you split ONLY by cutting the text into consecutive "
    "stretches: each block must be one continuous stretch of Augustine, in his order, from a "
    "sentence boundary to a sentence boundary. Do NOT duplicate the same stretch of commentary "
    "across several verses of this psalm -- put it ONCE, at its smallest accurate "
    "verse/range.\n\n"
    "CROSS-REFERENCES ARE WELCOME (and distinct from the duplication forbidden above). "
    "Augustine constantly quotes and expounds other Scripture. Whenever a stretch genuinely "
    "QUOTES AND EXPOUNDS a specific verse from another book -- an OT verse, a Gospel passage, an "
    "Epistle passage -- or from ANOTHER psalm, you may ALSO file that portion under that verse "
    "in its own file (e.g. \"Genesis 3_17\", \"Matthew 5_3\", \"Psalms 22_1\"), in addition to "
    "its placement under this psalm. File a cross-reference only where Augustine genuinely "
    "expounds the passage, not for a passing mention or a bare one-line proof-text. Use KJV "
    "book/verse numbering for the target file. When Augustine names another psalm by number "
    "(\"in the hundred and sixth Psalm\"), the number may be the Latin one (usually one below "
    "the KJV's): check the KJV psalm and verse by the wording (the editors' notes give the "
    "English reference).\n\n"
    "THE TEXT. Copy Augustine's words VERBATIM -- nothing abridged, paraphrased, corrected, "
    "added or rearranged. Drop the html tags (italics simply become plain text; don't turn them "
    "into quotation marks; \"CXV<sup>th</sup>\" becomes \"CXVth\") and separate paragraphs with "
    "a single blank line. Keep the translation's punctuation as printed: its curly quotation "
    "marks (which don't always pair up), the dashes, the ellipses \"…\" (they mark where this "
    "edition abridged Augustine: copy them exactly where they stand, at the start, middle or "
    "end of a paragraph), the translators' words in square brackets and parentheses, and the "
    "Latin, Greek and Hebrew words as printed. Leave out the title at the top, the \"<h2>\" "
    "headings (the editors' headings: Psalm 119's Hebrew letters, the \"Second Part\" headings) "
    "and the \"[note: ...]\" hints. (The NPNF paragraph numbers have been removed from the "
    "piece; don't add them back.) Don't add headings, verse numbers or notes of your own. "
    "Don't write a python script to do this; process the file yourself manually.\n\n"
    "SOURCE FIELDS. For EVERY commentary you import from this piece, set:\n"
    "  source_url   = {source_url}\n"
    "  source_title = \"{source_title}\"\n"
    "(the same url and title for all of them -- this psalm's exposition is one page).\n\n"
    "EXISTING BLOCKS. The old imports of these expositions have ALREADY been deleted, so you "
    "are only ADDING: if a verse file exists, append your [[commentary]] after its existing "
    "blocks; otherwise create it. Many {book} files hold blocks from Augustine's other works "
    "(his sermons, letters, The City of God, the Tractates on John, ...){kept_note}: they stay "
    "first, untouched -- don't remove, merge or \"deduplicate\" them. Earlier runs of THIS "
    "import have already filed other psalms{earlier_parts}, so you will also find blocks titled "
    "\"Exposition on Psalm N\" in the files you write to (cross-references from other psalms' "
    "expositions): those are NOT old imports or duplicates either; leave them exactly as they "
    "are and append yours after them."
)

PROMPT2 = "Double check, was this fully imported properly?"

# Url-less excerpts of another translation kept in the files (set after the Phase 1 survey).
KEPT_NOTE = (", and, in a few other books' files (Wisdom, Sirach, Isaiah, ...), url-less excerpts of "
             "ANOTHER translation of these expositions, titled \"EXPOSITIONS OF THE PSALMS ...\" or "
             "\"EXPLANATIONS OF THE PSALMS ...\", kept because they hold passages this edition "
             "leaves out")


def build_prompt1(work, units_dir, units, unit):
    notes = " ".join(x for x in (COMMON_NOTES, work.get("notes", "")) if x)
    sec = unit["sections"][0]
    i, k = sec["part"]
    part_note = (f"PIECES. This psalm's exposition is long, so it is imported in {k} pieces, "
                 f"each by its own run; this is piece {i}. Import ONLY this piece; its first block "
                 "starts at the piece's first word" + (", and the earlier piece(s) are already in "
                 "the files: don't change or extend their blocks" if i > 1 else "") + ".\n\n"
                 ) if k > 1 else ""
    return PROMPT1_TEMPLATE.format(
        number=work["number"],
        part_label=f" (piece {i} of {k})" if k > 1 else "",
        part_note=part_note,
        units_dir=units_dir,
        unit_name=unit["name"],
        html_path=os.path.join(WRITINGS_DIR, work["html"]),
        book=work["book"],
        father=FATHER,
        heading=sec["heading"],
        notes=f" {notes}" if notes else "",
        source_url=source_url_for(work),
        source_title=work["source_title"],
        kept_note=KEPT_NOTE,
        earlier_parts=(" and the earlier part(s) of this one" if i > 1 else ""),
    )



# --- Deterministic post-import check ------------------------------------------

PROBE_WORDS = 8


def _norm(s):
    s = unicodedata.normalize("NFC", s)
    s = s.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'}))
    return re.sub(r"\s+", " ", s).strip()


def run_check(work, sections, quiet=False):
    """Return a list of problems (empty == all good). Prints a summary."""
    folder = os.path.join(PROJECT_DIR, FATHER)
    url = source_url_for(work)
    book = work["book"]
    with open(BOOK_NAMES_PATH, encoding="utf-8") as f:
        books = json.load(f)["canonical_names"]
    filename_re = re.compile(
        "(" + "|".join(map(re.escape, books)) + r") \d+_\d+(?:-\d+(?:_\d+)?)?\.toml"
    )
    problems, quotes, files_used, cross, contiguity = [], [], 0, [], []
    source = _norm(" ".join(" ".join(paragraphs_of(s)) for s in sections))

    for fn in sorted(os.listdir(folder)):
        if not fn.endswith(".toml"):
            continue
        path = os.path.join(folder, fn)
        with open(path, encoding="utf-8") as f:
            if url not in f.read():
                continue
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            problems.append(f"{fn}: TOML parse error: {exc}")
            continue
        mine = [c for c in data.get("commentary", []) if c.get("source_url") == url]
        if not mine:
            continue
        if not filename_re.fullmatch(fn):
            problems.append(f"{fn}: filename is not '<Book> C_V' / 'C_V-V' / 'C_V-C_V'")
        own_book = fn.startswith(book + " ")
        if own_book:
            files_used += 1
        else:
            cross.append(fn[:-5])
        for c in mine:
            q = c.get("quote", "")
            contiguity.append((fn, q))
            if own_book:
                quotes.append(q)
            if c.get("source_title") != work["source_title"]:
                problems.append(f"{fn}: wrong source_title {c.get('source_title')!r}")
            if re.search(r"</?[a-z]+>|\[note:", q):
                problems.append(f"{fn}: leftover html tag or [note: ...] in a block")

    for fn, q in contiguity:
        if _norm(q) not in source:
            problems.append(
                f"{fn}: block is not one continuous stretch of the source (text cut up, "
                f"rearranged or altered): {_norm(q)[:80]!r}"
            )

    haystack = _norm(" ".join(quotes))
    probed = 0
    for s in sections:
        for i, p in enumerate(paragraphs_of(s), 1):
            words = _norm(p).split(" ")
            for label, probe in (("start", words[:PROBE_WORDS]), ("end", words[-PROBE_WORDS:])):
                probed += 1
                if " ".join(probe) not in haystack:
                    problems.append(
                        f"paragraph {i} {label} not found: {' '.join(probe)!r}"
                    )

    tag = f"Psalm {work['number']}"
    if problems or not quiet:
        print(f"\nCHECK {tag}: {len(quotes)} block(s) in {files_used} {book} file(s); "
              f"{probed} paragraph probes; cross-book ({len(cross)}): {', '.join(cross) or 'none'}")
    if problems:
        print(f"CHECK FAILED -- {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
    elif not quiet:
        print("CHECK PASSED")
    return problems


# --- Live rendering of stream-json events -------------------------------------


def _truncate(text, limit=500):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + " …"


def render_event(event):
    """Print a human-readable line for one stream-json event, live."""
    etype = event.get("type")

    if etype == "system" and event.get("subtype") == "init":
        model = event.get("model", "?")
        print(f"    · session start (model={model})")

    elif etype == "assistant":
        for block in event.get("message", {}).get("content", []):
            btype = block.get("type")
            if btype == "text" and block.get("text", "").strip():
                print(f"    💬 {_truncate(block['text'])}")
            elif btype == "tool_use":
                name = block.get("name", "?")
                inp = block.get("input", {})
                hint = inp.get("command") or inp.get("file_path") or inp.get("pattern") or ""
                hint = f" {_truncate(str(hint), 160)}" if hint else ""
                print(f"    🔧 {name}{hint}")

    elif etype == "user":
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "tool_result":
                content = block.get("content", "")
                if isinstance(content, list):
                    content = " ".join(
                        c.get("text", "") for c in content if isinstance(c, dict)
                    )
                flag = " [error]" if block.get("is_error") else ""
                print(f"    ↳ result{flag}: {_truncate(str(content), 200)}")

    elif etype == "result":
        if event.get("subtype") != "success":
            print(f"    ⚠ result subtype={event.get('subtype')}")


# --- One claude call ----------------------------------------------------------


def is_rate_limit_error(stderr):
    lower = stderr.lower()
    return any(
        term in lower
        for term in ["rate limit", "rate_limit", "overloaded", "too many requests", "529"]
    )


def call_claude(prompt, events_log, tag, resume_session=None):
    """Run one headless claude invocation, streaming stream-json events.

    Returns (final_text, session_id). Every raw event line is persisted to
    events_log tagged with `tag` (e.g. "Part003_Ch02a/prompt1"). When resume_session
    is given, the call continues that conversation via --resume."""
    delays = RETRY_DELAYS
    for attempt in range(len(delays) + 1):
        cmd = ["claude", "-p", "--dangerously-skip-permissions"]
        if resume_session:
            cmd += ["--resume", resume_session]
        cmd += ["--output-format", "stream-json", "--verbose", prompt]

        proc = subprocess.Popen(
            cmd,
            cwd=PROJECT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        final_text = ""
        session_id = resume_session
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            events_log.write(
                json.dumps({"tag": tag, "attempt": attempt + 1, "event": event}) + "\n"
            )
            events_log.flush()
            if event.get("session_id"):
                session_id = event["session_id"]
            render_event(event)
            if event.get("type") == "result" and "result" in event:
                final_text = event["result"]

        proc.wait()
        stderr = proc.stderr.read()

        if proc.returncode == 0:
            return final_text.strip(), session_id

        if is_rate_limit_error(stderr):
            delays = RATE_LIMIT_DELAYS

        if attempt < len(delays):
            wait = delays[attempt]
            print(
                f"    Retry {attempt + 1}/{len(delays)} after {wait}s... "
                f"(rc={proc.returncode} stderr={stderr.strip()[:80]})"
            )
            time.sleep(wait)
        else:
            msg = (
                f"rc={proc.returncode} stderr={stderr.strip()[:200]} "
                f"final={final_text.strip()[:200]}"
            )
            raise RuntimeError(f"claude call failed after retries: {msg}")

    raise RuntimeError("Unreachable")


# --- Driver -------------------------------------------------------------------


def log_record(log, unit, prompt_no, started, ended, session_id, output):
    log.write(
        json.dumps(
            {
                "unit": unit["name"],
                "sections": [s["heading"] for s in unit["sections"]],
                "prompt": prompt_no,
                "timestamp": started.isoformat(),
                "duration_seconds": round((ended - started).total_seconds(), 1),
                "session_id": session_id,
                "output": output,
            }
        )
        + "\n"
    )
    log.flush()


def process_unit(work, units_dir, units, unit, log, events_log):
    """Run prompt 1 (import) then prompt 2 (self-review) in one conversation."""
    print(f"\n{'=' * 60}")
    print(f"{unit['name']}: {', '.join(s['heading'] for s in unit['sections'])}")
    print(f"{'=' * 60}")
    tag = unit["name"].removesuffix(".html")

    print("  [prompt 1] importing...")
    started = datetime.now()
    out1, session_id = call_claude(
        build_prompt1(work, units_dir, units, unit), events_log, tag=f"{tag}/prompt1"
    )
    ended = datetime.now()
    log_record(log, unit, 1, started, ended, session_id, out1)
    print(f"  [prompt 1] done ({round((ended - started).total_seconds(), 1)}s)"
          f" -- session {session_id}")
    print(f"  {_truncate(out1, 300)}")

    if not session_id:
        print("  WARNING: no session_id captured from prompt 1; prompt 2 would "
              "start a fresh conversation. Skipping prompt 2 for this piece.")
        return

    print("  [prompt 2] double-checking...")
    started = datetime.now()
    out2, _ = call_claude(
        PROMPT2, events_log, tag=f"{tag}/prompt2", resume_session=session_id
    )
    ended = datetime.now()
    log_record(log, unit, 2, started, ended, session_id, out2)
    print(f"  [prompt 2] done ({round((ended - started).total_seconds(), 1)}s)")
    print(f"  {_truncate(out2, 300)}")



def check_order(base=None):
    """Cross-psalm order: in each file, this work's blocks (all appended after the files' BASE
    content) must follow psalm number, then source position. Pieces run out of sequence (the
    pilot) break it. With `base`, reorder only those appended blocks, by cutting the file
    text, and assert the BASE content stays a byte-identical prefix. Returns the files out of
    order (before any fix)."""
    folder = os.path.join(PROJECT_DIR, FATHER)
    block_re = re.compile(r"(?m)^\[\[commentary\]\][ \t]*$")
    url_no = {source_url_for(w): w["number"] for w in WORKS.values()}
    sources = {}

    def pos(n, quote):
        if n not in sources:
            secs = load_work(WORKS[f"PsExp{n:03d}"])[1]
            sources[n] = _norm(" ".join(" ".join(paragraphs_of(s)) for s in secs))
        return sources[n].find(_norm(quote))

    bad = []
    for fn in sorted(os.listdir(folder)):
        if not fn.endswith(".toml") or fn == "metadata.toml":
            continue
        path = os.path.join(folder, fn)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if "ON%2520THE%2520PSALMS" not in text:
            continue
        starts = [m.start() for m in block_re.finditer(text)]
        blocks = [text[a:b] for a, b in zip(starts, starts[1:] + [len(text)])]
        parsed = tomllib.loads(text)["commentary"]
        assert len(parsed) == len(blocks), fn
        keys = [(url_no[c["source_url"]], pos(url_no[c["source_url"]], c["quote"]))
                if c.get("source_url") in url_no else None for c in parsed]
        mine = [i for i, k in enumerate(keys) if k]
        if not mine:
            continue
        if mine != list(range(mine[0], len(blocks))):
            print(f"  NOT APPENDED AT THE END: {fn}")
            bad.append(fn)
            continue
        order = sorted(mine, key=lambda i: keys[i])
        if order == mine:
            continue
        print(f"  OUT OF PSALM ORDER: {fn[:-5]} {[keys[i][0] for i in mine]}")
        bad.append(fn)
        if base:
            new = text[:starts[mine[0]]] + "".join(
                blocks[i].rstrip("\n") + "\n\n" for i in order)
            new = new.rstrip("\n") + "\n"
            old = subprocess.run(["git", "-C", PROJECT_DIR, "show",
                                  f"{base}:{FATHER}/{fn}"], capture_output=True, text=True).stdout
            assert new.startswith(old.rstrip("\n")), fn
            assert tomllib.loads(new)["commentary"] == (
                parsed[:mine[0]] + [parsed[i] for i in order]), fn
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)
            print("    reordered")
    print(f"{len(bad)} file(s) out of psalm order" + (" (fixed)" if base and bad else ""))
    return bad


def expand_works(specs):
    """Work keys from the arguments: keys ("PsExp005") and ranges ("PsExp005-PsExp030")."""
    keys = sorted(WORKS)
    out = []
    for spec in specs:
        a, _, b = spec.partition("-")
        if a not in WORKS or (b and b not in WORKS):
            raise SystemExit(f"unknown work {spec!r} (keys run PsExp001 .. PsExp150)")
        out += keys[keys.index(a):keys.index(b) + 1] if b else [a]
    return out


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "works", nargs="+",
        help="Psalms to import, run one after another: keys (PsExp005) and/or ranges "
             "(PsExp005-PsExp030); every piece of each psalm is run.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", action="store_true",
        help="Print the pieces and the first prompt; write and call nothing.",
    )
    mode.add_argument(
        "--split-only", action="store_true",
        help="Write the pieces to the units folders and keep them (for inspection).",
    )
    mode.add_argument("--check", action="store_true",
                      help="Run only the check (printing only failures when several works).")
    mode.add_argument("--order", action="store_true",
                      help="Check that every file holds this work's blocks in psalm order "
                           "(any works argument; all files are checked).")
    mode.add_argument("--fix-order", metavar="BASE",
                      help="As --order, and reorder the out-of-order files' appended blocks, "
                           "keeping their content at BASE (the deletion commit) unchanged.")
    args = parser.parse_args()
    if args.order or args.fix_order:
        sys.exit(1 if check_order(args.fix_order) and not args.fix_order else 0)
    keys = expand_works(args.works)

    with open(BOOK_NAMES_PATH, encoding="utf-8") as f:
        assert "Psalms" in json.load(f)["canonical_names"]

    loaded = {}
    for k in keys:
        pre, secs = load_work(WORKS[k])
        loaded[k] = (pre, secs, make_units(pre, secs, SPLIT_CHARS))

    if args.check:
        bad = [k for k in keys if run_check(WORKS[k], loaded[k][1], quiet=len(keys) > 1)]
        print(f"\n{len(keys) - len(bad)} of {len(keys)} psalm(s) pass the check"
              + (f"; failing: {', '.join(bad)}" if bad else ""))
        sys.exit(1 if bad else 0)

    print(f"Work:       {FATHER}, Expositions on the Psalms ({len(keys)} psalm(s))")
    print(f"Agent cwd:  {PROJECT_DIR}")
    for k in keys:
        pre, secs, units = loaded[k]
        for u in units:
            s = u["sections"][0]
            print(f"  {k}  {u['name']:<12} {len(s['html']):>6} chars  [{s['heading']}]")

    if args.dry_run:
        k = keys[0]
        pre, secs, units = loaded[k]
        print(f"\nSource url: {source_url_for(WORKS[k])}")
        print(f"\n--dry-run: prompt 1 for {units[0]['name']}:\n")
        print(build_prompt1(WORKS[k], units_dir_for(k), units, units[0]))
        print(f"\n[prompt 2 is always]: {PROMPT2}")
        return

    if args.split_only:
        for k in keys:
            pre, secs, units = loaded[k]
            print(f"Wrote {', '.join(u['name'] for u in units)} to {write_units(k, pre, units)}")
        return

    log_dir = os.path.join(WORK_DIR, "augustine_psalms_import_logs")
    os.makedirs(log_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = os.path.join(log_dir, f"run-{stamp}.jsonl")
    events_path = os.path.join(log_dir, f"run-{stamp}.events.jsonl")
    print(f"Summary log: {log_path}")
    print(f"Details log: {events_path}\n")

    failed = []
    with open(log_path, "a") as log, open(events_path, "a") as events_log:
        for k in keys:
            pre, secs, units = loaded[k]
            units_dir = write_units(k, pre, units)
            for unit in units:
                try:
                    process_unit(WORKS[k], units_dir, units, unit, log, events_log)
                except RuntimeError as exc:
                    print(f"  ABORTING at {k} ({unit['name']}): {exc}")
                    print(f"  (pieces kept in {units_dir})")
                    log.write(json.dumps({"unit": unit["name"], "error": str(exc)}) + "\n")
                    log.flush()
                    sys.exit(1)
            shutil.rmtree(units_dir)
            if run_check(WORKS[k], secs):
                failed.append(k)

    print(f"\nDone. {len(keys)} psalm(s) processed.")
    print(f"Summary log: {log_path}")
    print(f"Details log: {events_path}")
    if failed:
        print(f"CHECK FAILED for: {', '.join(failed)} (see above)")


if __name__ == "__main__":
    main()
